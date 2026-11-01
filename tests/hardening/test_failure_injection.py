from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from kordena_fiscal.application import (
    DurableFiscalOutboxWorker,
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
from kordena_fiscal.control_plane import SecretReference, SecretReferenceKind
from kordena_fiscal.control_plane.webhook_policy import ApprovedWebhookConnection
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
)
from kordena_fiscal.gateway import (
    ProviderOperation,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseStatus,
    ProviderTransportError,
)
from kordena_fiscal.observability import (
    ObservabilityCategory,
    ObservabilityContext,
    ObservabilitySeverity,
    StructuredObservabilityEvent,
    StructuredObservabilityService,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.resilience import (
    CircuitBreakerPolicy,
    CircuitBreakerRegistry,
    CircuitKey,
    CircuitState,
    ResilientProviderGateway,
    RetryPolicy,
    UnknownProviderOutcomeError,
)
from kordena_fiscal.security import InMemoryWebhookKeyRing, WebhookSecurity
from kordena_fiscal.signing import (
    CryptographyFiscalDocumentSigner,
    FiscalSignatureRequest,
    FiscalSignatureResult,
    SignatureAlgorithm,
    SignerUnavailableError,
)
from kordena_fiscal.vault import (
    InMemorySyntheticFiscalSecretVault,
    SecretResolutionContext,
    SecretResolutionService,
    SecretUnavailableError,
    SecretUsagePurpose,
)


class _SyntheticEgressPolicy:
    """Unit-test policy only; in-process fake transports never open sockets."""
    def authorize(self, scope, destination_id, url, now):
        return ApprovedWebhookConnection(url, "consumer.example.test", "/fiscal/webhooks",
                                         "93.184.216.34", 1)

NOW = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")


class _MonoClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


class _Jitter:
    def value(self) -> float:
        return 0.5


class _ScriptedExecutor:
    def __init__(self, scripted: list[ProviderResponse | Exception]) -> None:
        self.scripted = list(scripted)
        self.calls = 0

    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        if not self.scripted:
            raise AssertionError("unexpected provider call")
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FailingEventSink:
    def publish(self, event: StructuredObservabilityEvent) -> None:
        raise RuntimeError("synthetic telemetry outage")


class _Clock:
    def now(self) -> datetime:
        return NOW


class _WebhookResolver:
    def resolve(self, entry: FiscalOutboxEntry) -> WebhookDestination | None:
        return WebhookDestination(
            destination_id="synthetic-hardening-consumer",
            url="https://consumer.example.test/fiscal/webhooks",
        )


class _FailingWebhookTransport:
    def __init__(self) -> None:
        self.calls = 0

    def deliver(self, request: WebhookDeliveryRequest) -> WebhookDeliveryResponse:
        self.calls += 1
        raise TimeoutError("synthetic webhook timeout")


class _CountingHandler:
    def __init__(self) -> None:
        self.calls = 0

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        self.calls += 1
        return FiscalDispatchResult(FiscalDispatchStatus.SUCCEEDED, reference="ok")


class _FailingUowFactory:
    def __call__(self):
        raise sqlite3.OperationalError("synthetic storage outage")


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.hardening",
        tenant_id="tenant-hardening",
        unit_id="unit-hardening",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-hardening",
    )


def _signature() -> FiscalSignatureResult:
    return FiscalSignatureResult(
        signed_content=b"synthetic-hardening-payload",
        signature=b"synthetic-hardening-signature",
        algorithm=SignatureAlgorithm.RSA_SHA256,
        certificate_reference_id="ref:hardening/certificate",
        certificate_fingerprint_sha256="a" * 64,
        signed_at=NOW,
        document_kind=FiscalDocumentKind.NFE,
    )


def _request(operation: ProviderOperation = ProviderOperation.QUERY) -> ProviderRequest:
    return ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=operation,
        payload=b"synthetic-hardening-payload",
        correlation_id="corr-hardening",
        workload_id="hardening-worker",
        signed_artifact=(
            _signature() if operation is ProviderOperation.AUTHORIZE else None
        ),
    )


def _response() -> ProviderResponse:
    return ProviderResponse(
        provider_id="provider-hardening",
        operation=ProviderOperation.QUERY,
        status=ProviderResponseStatus.FOUND,
        correlation_id="corr-hardening",
    )


def _resilient(
    executor: _ScriptedExecutor,
    *,
    clock: _MonoClock | None = None,
    failure_threshold: int = 5,
    max_attempts: int = 3,
) -> tuple[ResilientProviderGateway, CircuitBreakerRegistry, _Sleeper, _MonoClock]:
    actual_clock = clock or _MonoClock()
    sleeper = _Sleeper()
    circuits = CircuitBreakerRegistry(
        policy=CircuitBreakerPolicy(
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=10,
        ),
        clock=actual_clock,
    )
    gateway = ResilientProviderGateway(
        executor=executor,
        retry_policy=RetryPolicy(
            max_attempts=max_attempts,
            base_delay_seconds=1,
            max_delay_seconds=4,
        ),
        circuits=circuits,
        sleeper=sleeper,
        jitter=_Jitter(),
    )
    return gateway, circuits, sleeper, actual_clock


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "hardening.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _enqueue(
    database: SqliteFiscalDatabase,
    key: str = "hardening-event",
) -> FiscalOutboxEntry:
    with database.unit_of_work() as uow:
        result = FiscalOutboxService(uow.outbox).enqueue(
            scope=_scope(),
            operation="webhook_event",
            deduplication_key=key,
            payload=b'{"event":"synthetic-hardening"}',
            created_at=NOW,
        )
        uow.commit()
        return result.entry


def _webhook_security() -> WebhookSecurity:
    ring = InMemoryWebhookKeyRing(
        active_key_id="hardening-key",
        keys={"hardening-key": b"hardening-webhook-secret-32-bytes!!"},
    )
    return WebhookSecurity(
        key_resolver=ring,
        signing_key_id=ring.active_key_id,
        max_age_seconds=300,
        max_future_skew_seconds=30,
    )


def test_provider_timeout_is_bounded_and_exhausts_retry_budget() -> None:
    executor = _ScriptedExecutor(
        [
            ProviderTransportError("timeout-1"),
            ProviderTransportError("timeout-2"),
            ProviderTransportError("timeout-3"),
        ]
    )
    gateway, _, sleeper, _ = _resilient(executor)

    with pytest.raises(ProviderTransportError, match="timeout-3"):
        gateway.execute(_request(), provider_id="provider-hardening")

    assert executor.calls == 3
    assert sleeper.delays == [1.0, 2.0]


def test_intermittent_provider_recovers_without_duplicate_extra_call() -> None:
    executor = _ScriptedExecutor([ProviderTransportError("temporary"), _response()])
    gateway, _, sleeper, _ = _resilient(executor)

    result = gateway.execute(_request(), provider_id="provider-hardening")

    assert result.status is ProviderResponseStatus.FOUND
    assert executor.calls == 2
    assert sleeper.delays == [1.0]


def test_circuit_opens_then_half_open_probe_recovers() -> None:
    clock = _MonoClock()
    executor = _ScriptedExecutor([ProviderTransportError("down"), _response()])
    gateway, circuits, _, _ = _resilient(
        executor,
        clock=clock,
        failure_threshold=1,
        max_attempts=1,
    )
    key = CircuitKey(
        provider_id="provider-hardening",
        environment="homologation",
        state_code="SP",
    )

    with pytest.raises(ProviderTransportError):
        gateway.execute(_request(), provider_id="provider-hardening")
    assert circuits.state(key) is CircuitState.OPEN

    clock.advance(10)
    recovered = gateway.execute(_request(), provider_id="provider-hardening")
    assert recovered.status is ProviderResponseStatus.FOUND
    assert circuits.state(key) is CircuitState.CLOSED


def test_unknown_authorization_outcome_is_never_retried() -> None:
    executor = _ScriptedExecutor(
        [ProviderTransportError("socket closed", delivery_unknown=True), _response()]
    )
    gateway, _, sleeper, _ = _resilient(executor)

    with pytest.raises(UnknownProviderOutcomeError, match="reconciliation"):
        gateway.execute(
            _request(ProviderOperation.AUTHORIZE),
            provider_id="provider-hardening",
        )

    assert executor.calls == 1
    assert sleeper.delays == []


def test_vault_outage_fails_closed_before_material_is_returned() -> None:
    reference = SecretReference(
        reference_id="ref:hardening/certificate",
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id=_scope().tenant_id,
        unit_id=_scope().unit_id,
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    context = SecretResolutionContext(
        scope=_scope(),
        purpose=SecretUsagePurpose.DOCUMENT_SIGNING,
        kind=SecretReferenceKind.CERTIFICATE,
        workload_id="hardening-signer",
    )
    vault = InMemorySyntheticFiscalSecretVault(available=False)

    with pytest.raises(SecretUnavailableError, match="unavailable"):
        vault.resolve(reference, context)


def test_signer_outage_fails_closed_without_touching_secret_resolver() -> None:
    reference = SecretReference(
        reference_id="ref:hardening/certificate",
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id=_scope().tenant_id,
        unit_id=_scope().unit_id,
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    request = FiscalSignatureRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        canonical_content=b"<SyntheticHardening/>",
        certificate_reference=reference,
        workload_id="hardening-signer",
    )
    signer = CryptographyFiscalDocumentSigner(
        secret_resolution=cast(SecretResolutionService, object()),
        available=False,
    )

    with pytest.raises(SignerUnavailableError, match="unavailable"):
        signer.sign(request)


def test_telemetry_sink_outage_is_explicitly_fail_open() -> None:
    service = StructuredObservabilityService(sink=_FailingEventSink(), clock=_Clock())
    context = ObservabilityContext(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        provider_id="provider-hardening",
        operation="authorize",
    )

    emitted = service.emit(
        event_name="hardening.telemetry.synthetic",
        severity=ObservabilitySeverity.ERROR,
        category=ObservabilityCategory.APPLICATION,
        context=context,
        attributes={"status": "synthetic"},
    )

    assert emitted is False


def test_webhook_transport_timeout_is_retried_then_dead_lettered(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    transport = _FailingWebhookTransport()
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=SignedWebhookOutboxHandler(
            policy=_SyntheticEgressPolicy(),
            security=_webhook_security(),
            destination_resolver=_WebhookResolver(),
            transport=transport,
            clock=_Clock(),
        ),
        retry_policy=FiscalRetryPolicy(
            max_attempts=2,
            initial_delay_seconds=1,
            multiplier=2,
            max_delay_seconds=10,
        ),
    )

    first = worker.run_once(now=NOW)[0]
    second = worker.run_once(now=NOW + timedelta(seconds=1))[0]

    assert first.status is FiscalOutboxStatus.RETRY_WAIT
    assert second.entry_id == entry.entry_id
    assert second.status is FiscalOutboxStatus.DEAD_LETTER
    assert transport.calls == 2


def test_storage_outage_fails_closed_before_dispatch() -> None:
    handler = _CountingHandler()
    worker = DurableFiscalOutboxWorker(
        uow_factory=cast(FiscalUnitOfWorkFactory, _FailingUowFactory()),
        handler=handler,
    )

    with pytest.raises(sqlite3.OperationalError, match="storage outage"):
        worker.run_once(now=NOW)

    assert handler.calls == 0


def test_expired_claim_replays_after_restart_without_parallel_dispatch(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database, key="restart-replay")
    with database.unit_of_work() as uow:
        claimed = uow.outbox.claim_due(
            now=NOW,
            limit=1,
            lease_duration=timedelta(seconds=5),
        )[0]
        uow.commit()
    assert claimed.attempt_count == 1

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    handler = _CountingHandler()
    worker = DurableFiscalOutboxWorker(uow_factory=restarted, handler=handler)

    assert worker.run_once(now=NOW + timedelta(seconds=4)) == ()
    recovered = worker.run_once(now=NOW + timedelta(seconds=5))[0]

    assert recovered.entry_id == entry.entry_id
    assert recovered.status is FiscalOutboxStatus.SUCCEEDED
    assert recovered.attempt_count == 2
    assert handler.calls == 1


def test_unexpected_adapter_exception_is_permanent_and_not_retried() -> None:
    executor = _ScriptedExecutor([RuntimeError("synthetic adapter crash"), _response()])
    gateway, _, sleeper, _ = _resilient(executor)

    with pytest.raises(RuntimeError, match="adapter crash"):
        gateway.execute(_request(), provider_id="provider-hardening")

    assert executor.calls == 1
    assert sleeper.delays == []
