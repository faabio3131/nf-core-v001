from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kordena_fiscal.application import (
    FM_WEBHOOK_ATTEMPT_HEADER,
    FM_WEBHOOK_CORRELATION_HEADER,
    FM_WEBHOOK_OUTBOX_ENTRY_HEADER,
    FM_WEBHOOK_SIGNATURE_HEADER,
    DurableFiscalOutboxWorker,
    SignedWebhookOutboxHandler,
    WebhookDeliveryRequest,
    WebhookDeliveryResponse,
    WebhookDestination,
)
from kordena_fiscal.contingency import (
    FiscalOutboxEntry,
    FiscalOutboxService,
    FiscalOutboxStatus,
    FiscalRetryPolicy,
)
from kordena_fiscal.control_plane.webhook_policy import ApprovedWebhookConnection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.security import InMemoryWebhookKeyRing, WebhookSecurity, WebhookSignature


class _SyntheticEgressPolicy:
    """Unit-test policy only; in-process fake transports never open sockets."""
    def authorize(self, scope, destination_id, url, now):
        return ApprovedWebhookConnection(url, "consumer.example.test", "/fiscal/webhooks",
                                         "93.184.216.34", 1)

NOW = datetime(2026, 9, 12, 2, 0, tzinfo=UTC)
OLD_SECRET = b"previous-webhook-secret-32-bytes!!"
CURRENT_SECRET = b"current-webhook-secret--32-bytes!!"


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="kordena",
        tenant_id="fiscal-account-1",
        unit_id="fiscal-unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-webhook-v2-08",
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-v2.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _security(*, active_key_id: str = "key-current") -> WebhookSecurity:
    ring = InMemoryWebhookKeyRing(
        active_key_id=active_key_id,
        keys={
            "key-old": OLD_SECRET,
            "key-current": CURRENT_SECRET,
        },
    )
    return WebhookSecurity(
        key_resolver=ring,
        signing_key_id=ring.active_key_id,
        max_age_seconds=300,
        max_future_skew_seconds=30,
    )


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class _Resolver:
    def __init__(self, destination: WebhookDestination | None) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def resolve(self, entry: FiscalOutboxEntry) -> WebhookDestination | None:
        self.calls.append(entry.entry_id)
        return self.destination


class _VerifyingTransport:
    def __init__(
        self,
        *,
        verifier: WebhookSecurity,
        clock: _MutableClock,
        responses: list[WebhookDeliveryResponse],
    ) -> None:
        self._verifier = verifier
        self._clock = clock
        self._responses = list(responses)
        self.requests: list[WebhookDeliveryRequest] = []

    def deliver(self, request: WebhookDeliveryRequest) -> WebhookDeliveryResponse:
        self.requests.append(request)
        header = request.header(FM_WEBHOOK_SIGNATURE_HEADER)
        assert header is not None
        signature = WebhookSignature.parse(header)
        self._verifier.verify(request.body, signature, now=self._clock.now())
        if not self._responses:
            raise AssertionError("unexpected webhook delivery call")
        return self._responses.pop(0)


class _StaticTransport:
    def __init__(self, response: WebhookDeliveryResponse) -> None:
        self.response = response
        self.requests: list[WebhookDeliveryRequest] = []

    def deliver(self, request: WebhookDeliveryRequest) -> WebhookDeliveryResponse:
        self.requests.append(request)
        return self.response


def _enqueue(database: SqliteFiscalDatabase, key: str = "evt-webhook-1") -> FiscalOutboxEntry:
    with database.unit_of_work() as uow:
        result = FiscalOutboxService(uow.outbox).enqueue(
            scope=_scope(),
            operation="webhook_event",
            deduplication_key=key,
            payload=b'{"event_id":"evt-webhook-1","event_type":"fiscal.document.authorized"}',
            created_at=NOW,
        )
        uow.commit()
        return result.entry


def _destination() -> WebhookDestination:
    return WebhookDestination(
        destination_id="consumer-kordena-test",
        url="https://consumer.example.test/fiscal/webhooks",
    )


def test_durable_worker_delivers_exact_payload_with_certified_hmac_header(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    clock = _MutableClock(NOW)
    transport = _VerifyingTransport(
        verifier=_security(),
        clock=clock,
        responses=[WebhookDeliveryResponse(202, delivery_reference="delivery-accepted")],
    )
    handler = SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
        security=_security(),
        destination_resolver=_Resolver(_destination()),
        transport=transport,
        clock=clock,
    )

    outcome = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=handler,
    ).run_once(now=NOW)[0]

    assert outcome.status is FiscalOutboxStatus.SUCCEEDED
    assert outcome.completion_reference == "delivery-accepted"
    request = transport.requests[0]
    assert request.body == entry.payload
    assert request.destination == _destination()
    assert request.header(FM_WEBHOOK_CORRELATION_HEADER) == _scope().correlation_id
    assert request.header(FM_WEBHOOK_OUTBOX_ENTRY_HEADER) == entry.entry_id
    assert request.header(FM_WEBHOOK_ATTEMPT_HEADER) == "1"
    signature = WebhookSignature.parse(request.header(FM_WEBHOOK_SIGNATURE_HEADER) or "")
    assert signature.key_id == "key-current"


def test_retryable_http_response_uses_durable_backoff_and_re_signs_next_attempt(tmp_path) -> None:
    database = _database(tmp_path)
    _enqueue(database)
    clock = _MutableClock(NOW)
    transport = _VerifyingTransport(
        verifier=_security(),
        clock=clock,
        responses=[
            WebhookDeliveryResponse(429, error_detail="consumer throttled"),
            WebhookDeliveryResponse(204, delivery_reference="delivery-after-retry"),
        ],
    )
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=_security(),
            destination_resolver=_Resolver(_destination()),
            transport=transport,
            clock=clock,
        ),
        retry_policy=FiscalRetryPolicy(
            max_attempts=3,
            initial_delay_seconds=5,
            multiplier=2,
            max_delay_seconds=30,
        ),
    )

    first = worker.run_once(now=NOW)[0]
    assert first.status is FiscalOutboxStatus.RETRY_WAIT
    assert first.available_at == NOW + timedelta(seconds=5)
    assert first.last_error == "WEBHOOK_HTTP_429"

    clock.current = NOW + timedelta(seconds=5)
    second = worker.run_once(now=clock.current)[0]
    assert second.status is FiscalOutboxStatus.SUCCEEDED
    assert second.attempt_count == 2
    assert second.completion_reference == "delivery-after-retry"

    first_signature = WebhookSignature.parse(
        transport.requests[0].header(FM_WEBHOOK_SIGNATURE_HEADER) or ""
    )
    second_signature = WebhookSignature.parse(
        transport.requests[1].header(FM_WEBHOOK_SIGNATURE_HEADER) or ""
    )
    assert second_signature.timestamp == first_signature.timestamp + 5
    assert transport.requests[1].header(FM_WEBHOOK_ATTEMPT_HEADER) == "2"


def test_non_retryable_http_failure_goes_directly_to_dead_letter(tmp_path) -> None:
    database = _database(tmp_path)
    _enqueue(database)
    transport = _StaticTransport(
        WebhookDeliveryResponse(400, error_detail="invalid consumer contract")
    )
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=_security(),
            destination_resolver=_Resolver(_destination()),
            transport=transport,
            clock=_MutableClock(NOW),
        ),
    )

    outcome = worker.run_once(now=NOW)[0]

    assert outcome.status is FiscalOutboxStatus.DEAD_LETTER
    assert outcome.attempt_count == 1
    assert outcome.last_error == "WEBHOOK_HTTP_400"
    assert len(transport.requests) == 1


def test_missing_destination_fails_closed_without_transport_io(tmp_path) -> None:
    database = _database(tmp_path)
    _enqueue(database)
    resolver = _Resolver(None)
    transport = _StaticTransport(WebhookDeliveryResponse(202))
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=_security(),
            destination_resolver=resolver,
            transport=transport,
            clock=_MutableClock(NOW),
        ),
    )

    outcome = worker.run_once(now=NOW)[0]

    assert outcome.status is FiscalOutboxStatus.DEAD_LETTER
    assert outcome.last_error == "webhook destination is not configured"
    assert len(resolver.calls) == 1
    assert transport.requests == []


def test_rotation_overlap_accepts_delivery_signed_with_previous_key(tmp_path) -> None:
    database = _database(tmp_path)
    _enqueue(database, key="evt-rotation")
    clock = _MutableClock(NOW)
    receiver = _security(active_key_id="key-current")
    transport = _VerifyingTransport(
        verifier=receiver,
        clock=clock,
        responses=[WebhookDeliveryResponse(200, delivery_reference="rotation-ok")],
    )
    sender = _security(active_key_id="key-old")
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=sender,
            destination_resolver=_Resolver(_destination()),
            transport=transport,
            clock=clock,
        ),
    )

    outcome = worker.run_once(now=NOW)[0]

    assert outcome.status is FiscalOutboxStatus.SUCCEEDED
    signature = WebhookSignature.parse(
        transport.requests[0].header(FM_WEBHOOK_SIGNATURE_HEADER) or ""
    )
    assert signature.key_id == "key-old"


def test_delivery_header_matches_existing_asyncapi_v1_1_contract() -> None:
    contract_path = Path(__file__).resolve().parents[2] / "contracts" / "v1" / "asyncapi.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    webhook_headers = contract["components"]["schemas"]["WebhookHeaders"]

    assert contract["info"]["version"] == "1.1.0"
    assert contract["x-fm-webhook-signature"]["header"] == FM_WEBHOOK_SIGNATURE_HEADER
    assert FM_WEBHOOK_SIGNATURE_HEADER in webhook_headers["required"]
    assert contract["x-fm-webhook-signature"]["algorithm"] == "HMAC-SHA256"
    assert contract["x-fm-webhook-signature"]["security_stage"] == "V2-05_CERTIFIED"


@pytest.mark.parametrize(
    "url",
    [
        "http://consumer.example.test/webhook",
        "https://user:password@consumer.example.test/webhook",
        "https://consumer.example.test/webhook#fragment",
    ],
)
def test_webhook_destination_rejects_unsafe_url_shapes(url: str) -> None:
    with pytest.raises(FiscalValidationError):
        WebhookDestination(destination_id="unsafe", url=url)
