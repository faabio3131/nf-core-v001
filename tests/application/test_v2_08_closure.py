from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.application import (
    FM_WEBHOOK_CORRELATION_HEADER,
    FM_WEBHOOK_SIGNATURE_HEADER,
    DurableFiscalOutboxWorker,
    SignedWebhookInboxReceiver,
    SignedWebhookOutboxHandler,
    WebhookDeliveryRequest,
    WebhookDeliveryResponse,
    WebhookDestination,
)
from kordena_fiscal.contingency import (
    FiscalDispatchResult,
    FiscalDispatchStatus,
    FiscalOutboxEntry,
    FiscalOutboxService,
    FiscalOutboxStatus,
    FiscalRetryPolicy,
)
from kordena_fiscal.control_plane.webhook_policy import ApprovedWebhookConnection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.events import (
    DeliveryAttemptStatus,
    FiscalInboxStatus,
    build_inbox_entry_id,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.security import (
    InMemoryWebhookKeyRing,
    WebhookSecurity,
    WebhookSignatureError,
)


class _SyntheticEgressPolicy:
    """Unit-test policy only; in-process fake transports never open sockets."""
    def authorize(self, scope, destination_id, url, now):
        return ApprovedWebhookConnection(url, "consumer.example.test", "/fiscal/webhooks",
                                         "93.184.216.34", 1)

NOW = datetime(2026, 9, 12, 3, 0, tzinfo=UTC)
SECRET = b"v2-08-final-webhook-secret-32-bytes!"


def _scope(correlation_id: str = "corr-v2-08-final") -> ExecutionScope:
    return ExecutionScope(
        host_namespace="kordena",
        tenant_id="fiscal-account-1",
        unit_id="fiscal-unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=correlation_id,
    )


def _database(tmp_path, name: str) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _security() -> WebhookSecurity:
    ring = InMemoryWebhookKeyRing(
        active_key_id="key-final",
        keys={"key-final": SECRET},
    )
    return WebhookSecurity(
        key_resolver=ring,
        signing_key_id=ring.active_key_id,
        max_age_seconds=300,
        max_future_skew_seconds=30,
    )


def _event_body(event_id: str, *, correlation_id: str = "corr-v2-08-final") -> bytes:
    return json.dumps(
        {
            "contract_version": "1.0.0",
            "event_id": event_id,
            "event_type": "fiscal.document.authorized",
            "occurred_at": NOW.isoformat(),
            "scope": {
                "host_namespace": "kordena",
                "tenant_id": "fiscal-account-1",
                "unit_id": "fiscal-unit-1",
                "environment": "homologation",
            },
            "correlation_id": correlation_id,
            "causation_id": "cause-final",
            "idempotency_key": f"idem-{event_id}",
            "subject": {"document_id": "doc-final"},
            "data": {"status": "authorized"},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _enqueue(
    database: SqliteFiscalDatabase,
    *,
    key: str,
    created_at: datetime,
    ordering_key: str | None = None,
    payload: bytes | None = None,
) -> FiscalOutboxEntry:
    with database.unit_of_work() as uow:
        result = FiscalOutboxService(uow.outbox).enqueue(
            scope=_scope(),
            operation="webhook_event",
            deduplication_key=key,
            payload=payload or _event_body(key),
            created_at=created_at,
        )
        if ordering_key is not None:
            uow.outbox_ordering.register(result.entry.entry_id, ordering_key)
        uow.commit()
        return result.entry


class _SuccessHandler:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        self.keys.append(entry.deduplication_key)
        return FiscalDispatchResult(
            FiscalDispatchStatus.SUCCEEDED,
            reference=f"ok:{entry.deduplication_key}:{entry.attempt_count}",
        )


class _SequenceHandler:
    def __init__(self, results: list[FiscalDispatchResult]) -> None:
        self._results = list(results)

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        if not self._results:
            raise AssertionError(f"unexpected delivery for {entry.entry_id}")
        return self._results.pop(0)


class _DestinationResolver:
    def resolve(self, entry: FiscalOutboxEntry) -> WebhookDestination:
        return WebhookDestination(
            destination_id="loopback-consumer",
            url="https://consumer.example.test/fiscal/webhooks",
        )


class _AtomicConsumer:
    def __init__(self) -> None:
        self.invocations = 0
        self.side_effect_entry_id: str | None = None

    def process(self, entry, uow) -> str:
        self.invocations += 1
        result = FiscalOutboxService(uow.outbox).enqueue(
            scope=entry.scope,
            operation="consumer_side_effect",
            deduplication_key=entry.event_id,
            payload=b'{"consumer_effect":"applied"}',
            created_at=NOW,
        )
        self.side_effect_entry_id = result.entry.entry_id
        return f"consumer:{entry.event_id}"


class _DuplicateLoopbackTransport:
    def __init__(self, receiver: SignedWebhookInboxReceiver) -> None:
        self._receiver = receiver
        self.results = []

    def deliver(self, request: WebhookDeliveryRequest) -> WebhookDeliveryResponse:
        signature = request.header(FM_WEBHOOK_SIGNATURE_HEADER)
        correlation = request.header(FM_WEBHOOK_CORRELATION_HEADER)
        assert signature is not None
        assert correlation is not None
        first = self._receiver.receive(
            body=request.body,
            signature_header=signature,
            correlation_id=correlation,
            received_at=NOW,
        )
        duplicate = self._receiver.receive(
            body=request.body,
            signature_header=signature,
            correlation_id=correlation,
            received_at=NOW + timedelta(seconds=1),
        )
        self.results.extend((first, duplicate))
        return WebhookDeliveryResponse(202, delivery_reference="loopback-accepted")


def test_explicit_ordering_key_blocks_only_its_own_stream(tmp_path) -> None:
    database = _database(tmp_path, "ordering.sqlite3")
    first = _enqueue(
        database,
        key="stream-a-1",
        created_at=NOW,
        ordering_key="document:doc-1",
    )
    second = _enqueue(
        database,
        key="stream-a-2",
        created_at=NOW + timedelta(seconds=1),
        ordering_key="document:doc-1",
    )
    independent = _enqueue(
        database,
        key="stream-b-1",
        created_at=NOW + timedelta(seconds=1),
        ordering_key="document:doc-2",
    )
    handler = _SuccessHandler()
    worker = DurableFiscalOutboxWorker(uow_factory=database, handler=handler)

    first_batch = worker.run_once(now=NOW + timedelta(seconds=2), limit=10)

    assert {item.entry_id for item in first_batch} == {first.entry_id, independent.entry_id}
    assert second.entry_id not in {item.entry_id for item in first_batch}
    assert set(handler.keys) == {"stream-a-1", "stream-b-1"}

    second_batch = worker.run_once(now=NOW + timedelta(seconds=2), limit=10)
    assert [item.entry_id for item in second_batch] == [second.entry_id]


def test_delivery_audit_records_success_and_crash_lease_recovery(tmp_path) -> None:
    database = _database(tmp_path, "audit.sqlite3")
    entry = _enqueue(database, key="audit-event", created_at=NOW)

    with database.unit_of_work() as uow:
        claimed = uow.outbox.claim_due(
            now=NOW,
            limit=1,
            lease_duration=timedelta(seconds=10),
        )
        assert len(claimed) == 1
        uow.delivery_audit.start(claimed[0], started_at=NOW)
        uow.commit()

    handler = _SuccessHandler()
    outcome = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=handler,
    ).run_once(now=NOW + timedelta(seconds=10))[0]

    assert outcome.status is FiscalOutboxStatus.SUCCEEDED
    assert outcome.attempt_count == 2
    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    with restarted.unit_of_work() as uow:
        audit = uow.delivery_audit.list_for_entry(entry.entry_id)
    assert [record.status for record in audit] == [
        DeliveryAttemptStatus.LEASE_EXPIRED,
        DeliveryAttemptStatus.SUCCEEDED,
    ]
    assert audit[0].last_error == "delivery lease expired before completion"
    assert audit[1].outcome_reference == "ok:audit-event:2"


def test_delivery_audit_persists_retry_then_success_across_restart(tmp_path) -> None:
    database = _database(tmp_path, "audit-retry.sqlite3")
    entry = _enqueue(
        database,
        key="audit-retry",
        created_at=NOW,
        ordering_key="document:doc-audit-retry",
    )
    policy = FiscalRetryPolicy(
        max_attempts=3,
        initial_delay_seconds=5,
        multiplier=2,
        max_delay_seconds=30,
    )
    first_worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=_SequenceHandler(
            [
                FiscalDispatchResult(
                    FiscalDispatchStatus.RETRYABLE_FAILURE,
                    error="consumer temporarily unavailable",
                )
            ]
        ),
        retry_policy=policy,
    )

    first = first_worker.run_once(now=NOW)[0]
    assert first.status is FiscalOutboxStatus.RETRY_WAIT

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    second_worker = DurableFiscalOutboxWorker(
        uow_factory=restarted,
        handler=_SequenceHandler(
            [FiscalDispatchResult(FiscalDispatchStatus.SUCCEEDED, reference="retry-ok")]
        ),
        retry_policy=policy,
    )
    second = second_worker.run_once(now=NOW + timedelta(seconds=5))[0]
    assert second.status is FiscalOutboxStatus.SUCCEEDED

    with SqliteFiscalDatabase(database.path).unit_of_work() as uow:
        audit = uow.delivery_audit.list_for_entry(entry.entry_id)
    assert [record.status for record in audit] == [
        DeliveryAttemptStatus.RETRY_SCHEDULED,
        DeliveryAttemptStatus.SUCCEEDED,
    ]
    assert audit[0].next_available_at == NOW + timedelta(seconds=5)
    assert audit[0].last_error == "consumer temporarily unavailable"
    assert audit[0].ordering_key == "document:doc-audit-retry"
    assert audit[1].outcome_reference == "retry-ok"
    assert audit[1].ordering_key == "document:doc-audit-retry"


def test_signed_outbox_to_inbox_duplicate_delivery_applies_consumer_effect_once(tmp_path) -> None:
    sender = _database(tmp_path, "sender.sqlite3")
    receiver_database = _database(tmp_path, "receiver.sqlite3")
    consumer = _AtomicConsumer()
    receiver = SignedWebhookInboxReceiver(
        security=_security(),
        uow_factory=receiver_database,
        producer="fm-fiscal-sender",
        consumer=consumer,
    )
    transport = _DuplicateLoopbackTransport(receiver)
    body = _event_body("evt-e2e-1")
    outbound = _enqueue(
        sender,
        key="evt-e2e-1",
        created_at=NOW,
        ordering_key="document:doc-final",
        payload=body,
    )
    worker = DurableFiscalOutboxWorker(
        uow_factory=sender,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=_security(),
            destination_resolver=_DestinationResolver(),
            transport=transport,
            clock=type("Clock", (), {"now": lambda self: NOW})(),
        ),
    )

    sent = worker.run_once(now=NOW)[0]

    assert sent.status is FiscalOutboxStatus.SUCCEEDED
    assert consumer.invocations == 1
    assert transport.results[0].consumer_invoked is True
    assert transport.results[0].replay is False
    assert transport.results[0].entry.status is FiscalInboxStatus.PROCESSED
    assert transport.results[1].consumer_invoked is False
    assert transport.results[1].replay is True
    assert transport.results[1].entry.entry_id == transport.results[0].entry.entry_id
    assert consumer.side_effect_entry_id is not None

    with receiver_database.unit_of_work() as uow:
        inbox_entry = uow.inbox.get(transport.results[0].entry.entry_id)
        side_effect = uow.outbox.get(consumer.side_effect_entry_id)
    assert inbox_entry is not None
    assert inbox_entry.status is FiscalInboxStatus.PROCESSED
    assert side_effect is not None
    assert side_effect.deduplication_key == "evt-e2e-1"

    with sender.unit_of_work() as uow:
        sender_audit = uow.delivery_audit.list_for_entry(outbound.entry_id)
    assert len(sender_audit) == 1
    assert sender_audit[0].status is DeliveryAttemptStatus.SUCCEEDED
    assert sender_audit[0].ordering_key == "document:doc-final"


def test_invalid_signature_is_rejected_before_durable_inbox_acceptance(tmp_path) -> None:
    database = _database(tmp_path, "invalid-signature.sqlite3")
    consumer = _AtomicConsumer()
    receiver = SignedWebhookInboxReceiver(
        security=_security(),
        uow_factory=database,
        producer="fm-fiscal-sender",
        consumer=consumer,
    )
    event_id = "evt-invalid-signature"
    body = _event_body(event_id)
    signature = _security().sign(body, now=NOW)
    tampered = signature.header_value[:-1] + (
        "0" if signature.header_value[-1] != "0" else "1"
    )

    with pytest.raises(WebhookSignatureError):
        receiver.receive(
            body=body,
            signature_header=tampered,
            correlation_id="corr-v2-08-final",
            received_at=NOW,
        )

    assert consumer.invocations == 0
    entry_id = build_inbox_entry_id(
        scope=_scope(),
        producer="fm-fiscal-sender",
        event_id=event_id,
    )
    with database.unit_of_work() as uow:
        assert uow.inbox.get(entry_id) is None
