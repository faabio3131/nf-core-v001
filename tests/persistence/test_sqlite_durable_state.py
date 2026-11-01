from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kordena_fiscal.application import FiscalApplicationService, IssuanceResumeDisposition
from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.contingency import FiscalOutboxService
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalEnvironment,
    FiscalUnitId,
    FiscalValidationError,
    HostNamespace,
    HostScope,
    SourceReference,
)
from kordena_fiscal.lifecycle import FiscalDocumentState, IdempotencyKey, IssuanceAttemptStatus
from kordena_fiscal.numbering import FiscalSequenceKey, FiscalSequencePolicy
from kordena_fiscal.persistence import PersistenceStateError, SqliteFiscalDatabase
from kordena_fiscal.reconciliation import FiscalReconciliationResult, ReconciliationStatus


def _now() -> datetime:
    return datetime(2026, 9, 11, 20, 30, tzinfo=UTC)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="kordena",
        tenant_id="fiscal-account-1",
        unit_id="fiscal-unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-v2-07",
    )


def _binding() -> FiscalAccountBinding:
    return FiscalAccountBinding(
        binding_id="binding-1",
        host_scope=HostScope(
            namespace=HostNamespace("kordena"),
            tenant_id="tenant-external",
            unit_id="unit-external",
        ),
        fiscal_account_id=FiscalAccountId("fiscal-account-1"),
        fiscal_unit_id=FiscalUnitId("fiscal-unit-1"),
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-v2.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def test_controlled_migration_is_idempotent_and_requires_durable_path(tmp_path) -> None:
    database = _database(tmp_path)

    assert database.initialize() == ()
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with pytest.raises(FiscalValidationError, match="filesystem"):
        SqliteFiscalDatabase(":memory:")


def test_restart_preserves_all_v2_07_authority_state(tmp_path) -> None:
    database = _database(tmp_path)
    scope = _scope()
    binding = _binding()
    key = IdempotencyKey("a" * 64)
    fingerprint = "b" * 64
    sequence_key = FiscalSequenceKey.from_scope(
        scope,
        model=ElectronicInvoiceModel.NFCE,
        series=1,
    )
    source = SourceReference("sale", "sale-100")

    with database.unit_of_work() as uow:
        uow.bindings.add(binding)
        idempotency = uow.idempotency.reserve(key, fingerprint, "doc-100")
        assert idempotency.replay is False
        number = uow.sequences.reserve_next(sequence_key, FiscalSequencePolicy())
        assert number.number == 1

        outbox = FiscalOutboxService(uow.outbox).enqueue(
            scope=scope,
            operation="authorize",
            deduplication_key="doc-100",
            payload=b"signed-fiscal-payload",
            created_at=_now(),
        )
        archive = FiscalArchiveEntry.build(
            scope=scope,
            document_reference="doc-100",
            kind=FiscalArchiveKind.AUTHORIZED_XML,
            content=b"<xml>authorized</xml>",
            media_type="application/xml",
            archived_at=_now(),
            retention=RetentionPolicyMetadata(policy_id="default", policy_version=1),
        )
        uow.archive.append(archive)
        reconciliation = FiscalReconciliationResult(
            status=ReconciliationStatus.MATCHED,
            scope=scope,
            source=source,
            fingerprint="f" * 64,
            selected_document_id="doc-100",
            issues=(),
        )
        uow.reconciliations.save(reconciliation)
        uow.commit()

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()

    with restarted.unit_of_work() as uow:
        assert uow.bindings.resolve(binding.host_scope) == binding
        replay = uow.idempotency.reserve(key, fingerprint, "retry-document-id")
        assert replay.replay is True
        assert replay.attempt.document_id == "doc-100"
        assert uow.sequences.last_reserved(sequence_key) == 1
        assert uow.sequences.reserve_next(sequence_key, FiscalSequencePolicy()).number == 2
        assert uow.outbox.get(outbox.entry.entry_id) == outbox.entry
        assert uow.archive.get(archive.entry_id) == archive
        assert uow.archive.list_for_document(scope, "doc-100") == (archive,)
        assert uow.reconciliations.get(scope, source) == reconciliation
        uow.commit()


def test_uncommitted_unit_of_work_rolls_back_every_repository(tmp_path) -> None:
    database = _database(tmp_path)
    binding = _binding()

    with database.unit_of_work() as uow:
        uow.bindings.add(binding)
        # no commit: __exit__ must roll back the whole local transaction

    with database.unit_of_work() as uow:
        with pytest.raises(PersistenceStateError, match="no durable fiscal binding"):
            uow.bindings.resolve(binding.host_scope)


def test_crash_retry_never_silently_duplicates_reserved_issuance(tmp_path) -> None:
    database = _database(tmp_path)
    service = FiscalApplicationService(database)
    key = IdempotencyKey("1" * 64)
    fingerprint = "2" * 64

    fresh = service.reserve_issuance(
        scope=_scope(),
        key=key,
        request_fingerprint=fingerprint,
        document_id="doc-crash-safe",
        created_at=_now(),
    )
    assert fresh.disposition is IssuanceResumeDisposition.FRESH

    for state in (
        FiscalDocumentState.VALIDATING,
        FiscalDocumentState.READY_TO_SIGN,
        FiscalDocumentState.SIGNING,
        FiscalDocumentState.READY_TO_TRANSMIT,
        FiscalDocumentState.TRANSMITTING,
    ):
        service.transition_lifecycle(
            "doc-crash-safe",
            state,
            occurred_at=_now(),
            reason=f"move to {state.value}",
            correlation_id="corr-crash",
        )

    restarted_service = FiscalApplicationService(SqliteFiscalDatabase(database.path))
    after_crash = restarted_service.reserve_issuance(
        scope=_scope(),
        key=key,
        request_fingerprint=fingerprint,
        document_id="doc-retry-metadata",
        created_at=_now(),
    )

    assert after_crash.reservation.replay is True
    assert after_crash.reservation.attempt.status is IssuanceAttemptStatus.RESERVED
    assert after_crash.disposition is IssuanceResumeDisposition.RECOVERY_REQUIRED
    assert after_crash.lifecycle.state is FiscalDocumentState.TRANSMITTING

    restarted_service.finalize_authorized(
        key=key,
        generation=after_crash.reservation.attempt.generation,
        document_id="doc-crash-safe",
        result_reference="protocol-123",
        occurred_at=_now(),
        reason="provider query confirmed prior authorization",
        correlation_id="corr-recovery",
    )

    confirmed = FiscalApplicationService(SqliteFiscalDatabase(database.path)).reserve_issuance(
        scope=_scope(),
        key=key,
        request_fingerprint=fingerprint,
        document_id="another-retry-document-id",
        created_at=_now(),
    )
    assert confirmed.disposition is IssuanceResumeDisposition.AUTHORIZED_REPLAY
    assert confirmed.reservation.attempt.result_reference == "protocol-123"
    assert confirmed.lifecycle.state is FiscalDocumentState.AUTHORIZED
