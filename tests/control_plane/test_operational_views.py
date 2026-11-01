from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    RetentionPolicyMetadata,
)
from kordena_fiscal.contingency import FiscalOutboxService, FiscalOutboxStatus
from kordena_fiscal.control_plane import (
    AdminPrincipal,
    ArchiveReferenceView,
    ControlPlaneAuthorizationError,
    ControlPlaneNotFoundError,
    ControlPlanePermission,
    DeliveryOperationView,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    OperationalControlPlaneService,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, SourceReference
from kordena_fiscal.events import DeliveryAttemptStatus
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.reconciliation import (
    FiscalReconciliationResult,
    ReconciliationIssue,
    ReconciliationIssueCode,
    ReconciliationStatus,
)

NOW = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="global-admin",
        permissions=frozenset({ControlPlanePermission.ORGANIZATION_WRITE}),
        global_scope=True,
    )


def _operator(tenant_id: str = "tenant-a") -> AdminPrincipal:
    return AdminPrincipal(
        actor_id=f"operator-{tenant_id}",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.OPERATIONS_READ,
                ControlPlanePermission.AUDIT_READ,
            }
        ),
        tenant_ids=frozenset({tenant_id}),
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "operations.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _scope(
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    correlation_id: str = "corr-operation",
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.kordena",
        tenant_id=tenant_id,
        unit_id=unit_id,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=correlation_id,
    )


def _onboard(
    database: SqliteFiscalDatabase,
    *,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
) -> None:
    service = DurableControlPlaneService(database, clock=_Clock())
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id=tenant_id,
        legal_name=f"Synthetic {tenant_id}",
        correlation_id=f"corr-org-{tenant_id}",
    )
    service.onboard_unit(
        actor=_operator(tenant_id),
        registration=FiscalUnitRegistration(
            tenant_id=tenant_id,
            unit_id=unit_id,
            display_name=f"Synthetic {unit_id}",
        ),
        correlation_id=f"corr-unit-{tenant_id}-{unit_id}",
    )


def _seed_operational_state(database: SqliteFiscalDatabase, scope: ExecutionScope):
    source = SourceReference("sale", "sale-100")
    with database.unit_of_work() as uow:
        enqueue = FiscalOutboxService(uow.outbox).enqueue(
            scope=scope,
            operation="provider_dispatch",
            deduplication_key="doc-100",
            payload=b'{"private_payload":"must-not-escape-control-plane"}',
            created_at=NOW,
        )
        uow.outbox_ordering.register(enqueue.entry.entry_id, "document:doc-100")
        claimed = uow.outbox.claim_due(
            now=NOW,
            limit=1,
            lease_duration=timedelta(seconds=30),
        )[0]
        uow.delivery_audit.start(claimed, started_at=NOW)
        dead_letter = uow.outbox.dead_letter(
            claimed.entry_id,
            expected_attempt=claimed.attempt_count,
            error="synthetic provider rejection 999",
        )
        uow.delivery_audit.mark_dead_letter(
            claimed.entry_id,
            attempt_count=claimed.attempt_count,
            finished_at=NOW + timedelta(seconds=1),
            error="synthetic provider rejection 999",
        )

        archive = FiscalArchiveEntry.build(
            scope=scope,
            document_reference="doc-100",
            kind=FiscalArchiveKind.AUTHORIZED_XML,
            content=b"<private-xml>never-returned-by-control-plane</private-xml>",
            media_type="application/xml",
            archived_at=NOW,
            retention=RetentionPolicyMetadata(
                policy_id="fiscal-default",
                policy_version=1,
                retain_until=NOW + timedelta(days=3650),
                legal_basis_reference="synthetic-retention-policy",
            ),
        )
        uow.archive.append(archive)

        reconciliation = FiscalReconciliationResult(
            status=ReconciliationStatus.DIVERGENT,
            scope=scope,
            source=source,
            fingerprint="a" * 64,
            selected_document_id="doc-100",
            issues=(
                ReconciliationIssue(
                    code=ReconciliationIssueCode.OPERATION_FISCAL_TOTAL_MISMATCH,
                    message="synthetic fiscal total mismatch",
                    document_id="doc-100",
                ),
            ),
        )
        uow.reconciliations.save(reconciliation)
        uow.commit()
    return dead_letter, archive, reconciliation, source


def test_delivery_view_exposes_status_errors_and_attempts_without_payload(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    scope = _scope()
    dead_letter, _, _, _ = _seed_operational_state(database, scope)
    service = OperationalControlPlaneService(database)

    view = service.get_delivery_operation(
        actor=_operator(),
        scope=scope,
        entry_id=dead_letter.entry_id,
    )

    assert view.status is FiscalOutboxStatus.DEAD_LETTER
    assert view.last_error == "synthetic provider rejection 999"
    assert view.ordering_key == "document:doc-100"
    assert view.payload_sha256 == dead_letter.payload_sha256
    assert len(view.attempts) == 1
    assert view.attempts[0].status is DeliveryAttemptStatus.DEAD_LETTER
    assert view.attempts[0].last_error == "synthetic provider rejection 999"
    field_names = {item.name for item in fields(DeliveryOperationView)}
    assert "payload" not in field_names
    assert "deduplication_key" not in field_names


def test_archive_view_returns_integrity_and_retention_metadata_without_content(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    scope = _scope()
    _, archive, _, _ = _seed_operational_state(database, scope)
    service = OperationalControlPlaneService(database)

    views = service.list_archive_references(
        actor=_operator(),
        scope=scope,
        document_reference="doc-100",
    )

    assert len(views) == 1
    assert views[0].entry_id == archive.entry_id
    assert views[0].content_sha256 == archive.content_sha256
    assert views[0].retention_policy_id == "fiscal-default"
    assert views[0].legal_basis_reference == "synthetic-retention-policy"
    assert "content" not in {item.name for item in fields(ArchiveReferenceView)}


def test_reconciliation_view_reuses_certified_result_without_parallel_state(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    scope = _scope()
    _, _, reconciliation, source = _seed_operational_state(database, scope)
    service = OperationalControlPlaneService(database)

    view = service.get_reconciliation(actor=_operator(), scope=scope, source=source)

    assert view is not None
    assert view.status is reconciliation.status
    assert view.fingerprint == reconciliation.fingerprint
    assert view.selected_document_id == "doc-100"
    assert len(view.issues) == 1
    assert view.issues[0].code is ReconciliationIssueCode.OPERATION_FISCAL_TOTAL_MISMATCH


def test_operational_reads_require_permission_tenant_and_enabled_environment(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    scope = _scope()
    dead_letter, _, _, _ = _seed_operational_state(database, scope)
    service = OperationalControlPlaneService(database)

    no_permission = AdminPrincipal(
        actor_id="auditor-only",
        permissions=frozenset({ControlPlanePermission.AUDIT_READ}),
        tenant_ids=frozenset({"tenant-a"}),
    )
    with pytest.raises(ControlPlaneAuthorizationError, match="operations.read"):
        service.get_delivery_operation(
            actor=no_permission,
            scope=scope,
            entry_id=dead_letter.entry_id,
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant"):
        service.get_delivery_operation(
            actor=_operator("tenant-b"),
            scope=scope,
            entry_id=dead_letter.entry_id,
        )

    production_scope = ExecutionScope(
        host_namespace="fm.kordena",
        tenant_id="tenant-a",
        unit_id="unit-01",
        environment=FiscalEnvironment.PRODUCTION,
        correlation_id="corr-prod-read",
    )
    with pytest.raises(ControlPlaneAuthorizationError, match="environment"):
        service.list_archive_references(
            actor=_operator(),
            scope=production_scope,
            document_reference="doc-100",
        )


def test_entry_identifier_cannot_leak_another_tenant_operation(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database, tenant_id="tenant-a")
    _onboard(database, tenant_id="tenant-b")
    foreign_scope = _scope(tenant_id="tenant-b", correlation_id="corr-foreign")
    foreign_entry, _, _, _ = _seed_operational_state(database, foreign_scope)
    service = OperationalControlPlaneService(database)

    with pytest.raises(ControlPlaneNotFoundError, match="not found in scope"):
        service.get_delivery_operation(
            actor=_operator("tenant-a"),
            scope=_scope(tenant_id="tenant-a"),
            entry_id=foreign_entry.entry_id,
        )


def test_operational_views_survive_restart_and_do_not_mutate_admin_audit(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    scope = _scope()
    dead_letter, _, _, source = _seed_operational_state(database, scope)
    admin_service = DurableControlPlaneService(database, clock=_Clock())
    before = admin_service.list_audit(actor=_operator(), tenant_id="tenant-a")

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    operational = OperationalControlPlaneService(restarted)
    delivery = operational.get_delivery_operation(
        actor=_operator(),
        scope=scope,
        entry_id=dead_letter.entry_id,
    )
    archive = operational.list_archive_references(
        actor=_operator(),
        scope=scope,
        document_reference="doc-100",
    )
    reconciliation = operational.get_reconciliation(
        actor=_operator(),
        scope=scope,
        source=source,
    )

    assert delivery.status is FiscalOutboxStatus.DEAD_LETTER
    assert len(archive) == 1
    assert reconciliation is not None
    after = DurableControlPlaneService(restarted, clock=_Clock()).list_audit(
        actor=_operator(),
        tenant_id="tenant-a",
    )
    assert after == before
