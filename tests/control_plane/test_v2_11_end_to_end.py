from __future__ import annotations

import ast
import sqlite3
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    RetentionPolicyMetadata,
)
from kordena_fiscal.compliance import (
    CapabilityReadinessService,
    FiscalActionCapability,
    FiscalCapabilityLevel,
    JurisdictionCapabilityError,
    JurisdictionCapabilityMatrix,
    JurisdictionCapabilityRule,
    TechnicalValidationMode,
)
from kordena_fiscal.contingency import FiscalOutboxService, FiscalOutboxStatus
from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CapabilityControlContext,
    ControlPlaneAuthorizationError,
    ControlPlaneConflictError,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    GovernedCapabilityReadinessService,
    OperationalControlPlaneService,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalProfile,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.reconciliation import (
    FiscalReconciliationResult,
    ReconciliationIssue,
    ReconciliationIssueCode,
    ReconciliationStatus,
)

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="global-admin",
        permissions=frozenset({ControlPlanePermission.ORGANIZATION_WRITE}),
        global_scope=True,
    )


def _tenant_admin(tenant_id: str = "tenant-a") -> AdminPrincipal:
    return AdminPrincipal(
        actor_id=f"admin-{tenant_id}",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.PROFILE_WRITE,
                ControlPlanePermission.CAPABILITY_READ,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.AUDIT_READ,
                ControlPlanePermission.OPERATIONS_READ,
            }
        ),
        tenant_ids=frozenset({tenant_id}),
    )


def _no_permissions(
    tenant_id: str = "tenant-a",
    *,
    global_scope: bool = False,
) -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="no-permissions-global" if global_scope else f"no-permissions-{tenant_id}",
        permissions=frozenset(),
        tenant_ids=frozenset() if global_scope else frozenset({tenant_id}),
        global_scope=global_scope,
    )


def _database(tmp_path, name: str = "v2-11-e2e.sqlite3") -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _scope(
    *,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    correlation_id: str = "corr-e2e",
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.kordena",
        tenant_id=tenant_id,
        unit_id=unit_id,
        environment=environment,
        correlation_id=correlation_id,
    )


def _profile(
    *,
    profile_id: str,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    effective_from: datetime = NOW - timedelta(days=1),
    effective_to: datetime | None = None,
    version: int = 1,
) -> FiscalProfile:
    return FiscalProfile(
        profile_id=profile_id,
        version=version,
        scope=_scope(
            tenant_id=tenant_id,
            unit_id=unit_id,
            environment=environment,
            correlation_id=f"corr-{profile_id}-v{version}",
        ),
        cnpj=Cnpj("11222333000181"),
        legal_name="Synthetic V2-11 Certification Company",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration(
            state_code="SP",
            number="110042490114",
        ),
        primary_cnae=CnaeCode("6202300"),
        address=FiscalAddress(
            street="Praca da Se",
            number="100",
            district="Se",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction(
                state_code="SP",
                municipality_ibge_code="3550308",
            ),
            postal_code="01001000",
        ),
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _onboard(
    database: SqliteFiscalDatabase,
    *,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    environments: frozenset[FiscalEnvironment] = frozenset(
        {FiscalEnvironment.HOMOLOGATION}
    ),
) -> DurableControlPlaneService:
    service = DurableControlPlaneService(database, clock=_Clock())
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id=tenant_id,
        legal_name=f"Synthetic {tenant_id}",
        correlation_id=f"corr-org-{tenant_id}",
    )
    service.onboard_unit(
        actor=_tenant_admin(tenant_id),
        registration=FiscalUnitRegistration(
            tenant_id=tenant_id,
            unit_id=unit_id,
            display_name=f"Synthetic {unit_id}",
            enabled_environments=environments,
        ),
        correlation_id=f"corr-unit-{tenant_id}-{unit_id}",
    )
    return service


def _readiness() -> CapabilityReadinessService:
    rules = (
        JurisdictionCapabilityRule(
            rule_id="sp-nfce-hml-e2e",
            version=1,
            state_code="SP",
            municipality_ibge_code="3550308",
            document_kind=FiscalDocumentKind.NFCE,
            environment=FiscalEnvironment.HOMOLOGATION,
            capability_level=FiscalCapabilityLevel.HOMOLOGATION_READY,
            validation_mode=TechnicalValidationMode.STRICT_REJECTION,
            effective_from=NOW - timedelta(days=10),
            source_normative="synthetic V2-11 homologation certification rule",
            capabilities=frozenset(
                {FiscalActionCapability.ISSUE, FiscalActionCapability.QUERY}
            ),
        ),
        JurisdictionCapabilityRule(
            rule_id="sp-nfce-prod-contract-only-e2e",
            version=1,
            state_code="SP",
            municipality_ibge_code="3550308",
            document_kind=FiscalDocumentKind.NFCE,
            environment=FiscalEnvironment.PRODUCTION,
            capability_level=FiscalCapabilityLevel.CONTRACT_ONLY,
            validation_mode=TechnicalValidationMode.STRICT_REJECTION,
            effective_from=NOW - timedelta(days=10),
            source_normative="synthetic V2-11 production rule without approval",
            capabilities=frozenset({FiscalActionCapability.ISSUE}),
        ),
    )
    return CapabilityReadinessService(JurisdictionCapabilityMatrix(rules))


def _context(environment: FiscalEnvironment) -> CapabilityControlContext:
    return CapabilityControlContext(
        host_namespace="fm.kordena",
        tenant_id="tenant-a",
        unit_id="unit-01",
        environment=environment,
        document_kind=FiscalDocumentKind.NFCE,
        instant=NOW,
    )


def _seed_operational_state(
    database: SqliteFiscalDatabase,
    scope: ExecutionScope,
) -> tuple[str, SourceReference]:
    source = SourceReference("sale", f"sale-{scope.unit_id}")
    with database.unit_of_work() as uow:
        enqueue = FiscalOutboxService(uow.outbox).enqueue(
            scope=scope,
            operation="provider_dispatch",
            deduplication_key=f"doc-{scope.unit_id}",
            payload=b'{"synthetic":"private-operational-payload"}',
            created_at=NOW,
        )
        uow.outbox_ordering.register(
            enqueue.entry.entry_id,
            f"document:doc-{scope.unit_id}",
        )
        claimed = uow.outbox.claim_due(
            now=NOW,
            limit=1,
            lease_duration=timedelta(seconds=30),
        )[0]
        uow.delivery_audit.start(claimed, started_at=NOW)
        dead_letter = uow.outbox.dead_letter(
            claimed.entry_id,
            expected_attempt=claimed.attempt_count,
            error="synthetic provider rejection",
        )
        uow.delivery_audit.mark_dead_letter(
            claimed.entry_id,
            attempt_count=claimed.attempt_count,
            finished_at=NOW + timedelta(seconds=1),
            error="synthetic provider rejection",
        )
        archive = FiscalArchiveEntry.build(
            scope=scope,
            document_reference=f"doc-{scope.unit_id}",
            kind=FiscalArchiveKind.AUTHORIZED_XML,
            content=b"<synthetic-private-content />",
            media_type="application/xml",
            archived_at=NOW,
            retention=RetentionPolicyMetadata(
                policy_id="fiscal-default",
                policy_version=1,
                retain_until=NOW + timedelta(days=3650),
            ),
        )
        uow.archive.append(archive)
        uow.reconciliations.save(
            FiscalReconciliationResult(
                status=ReconciliationStatus.DIVERGENT,
                scope=scope,
                source=source,
                fingerprint="a" * 64,
                selected_document_id=f"doc-{scope.unit_id}",
                issues=(
                    ReconciliationIssue(
                        code=ReconciliationIssueCode.OPERATION_FISCAL_TOTAL_MISMATCH,
                        message="synthetic reconciliation divergence",
                        document_id=f"doc-{scope.unit_id}",
                    ),
                ),
            )
        )
        uow.commit()
    assert dead_letter.status is FiscalOutboxStatus.DEAD_LETTER
    return dead_letter.entry_id, source


def test_full_control_plane_survives_restart_without_promoting_production(tmp_path) -> None:
    database = _database(tmp_path)
    service = _onboard(
        database,
        environments=frozenset(
            {FiscalEnvironment.HOMOLOGATION, FiscalEnvironment.PRODUCTION}
        ),
    )
    admin = _tenant_admin()
    reference = SecretReference(
        reference_id="ref:fm-fiscal/tenant-a/unit-01/hml-certificate",
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id="tenant-a",
        unit_id="unit-01",
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    service.bind_secret_reference(
        actor=admin,
        reference=reference,
        correlation_id="corr-secret-e2e",
    )
    hml_profile = _profile(profile_id="profile-hml")
    prod_profile = _profile(
        profile_id="profile-prod",
        environment=FiscalEnvironment.PRODUCTION,
    )
    service.add_fiscal_profile(actor=admin, profile=hml_profile)
    service.add_fiscal_profile(actor=admin, profile=prod_profile)

    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )
    assert governed.query(
        actor=admin,
        context=_context(FiscalEnvironment.HOMOLOGATION),
    ).readiness is FiscalCapabilityLevel.HOMOLOGATION_READY
    assert governed.query(
        actor=admin,
        context=_context(FiscalEnvironment.PRODUCTION),
    ).readiness is FiscalCapabilityLevel.CONTRACT_ONLY
    with pytest.raises(JurisdictionCapabilityError, match="below the required"):
        governed.require_action(
            actor=admin,
            context=_context(FiscalEnvironment.PRODUCTION),
            action=FiscalActionCapability.ISSUE,
        )

    scope = _scope()
    entry_id, source = _seed_operational_state(database, scope)
    audit_before = service.list_audit(actor=admin, tenant_id="tenant-a")

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    operational = OperationalControlPlaneService(restarted)
    delivery = operational.get_delivery_operation(
        actor=admin,
        scope=scope,
        entry_id=entry_id,
    )
    archive = operational.list_archive_references(
        actor=admin,
        scope=scope,
        document_reference="doc-unit-01",
    )
    reconciliation = operational.get_reconciliation(
        actor=admin,
        scope=scope,
        source=source,
    )

    assert delivery.status is FiscalOutboxStatus.DEAD_LETTER
    assert len(delivery.attempts) == 1
    assert len(archive) == 1
    assert reconciliation is not None
    assert reconciliation.status is ReconciliationStatus.DIVERGENT

    with restarted.unit_of_work() as uow:
        assert uow.control_plane.get_secret_reference(
            "tenant-a",
            "unit-01",
            FiscalEnvironment.HOMOLOGATION,
            SecretReferenceKind.CERTIFICATE,
        ) == reference
        assert uow.control_plane.resolve_profile(
            host_namespace="fm.kordena",
            tenant_id="tenant-a",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            instant=NOW,
        ) == hml_profile

    audit_after = DurableControlPlaneService(
        restarted,
        clock=_Clock(),
    ).list_audit(actor=admin, tenant_id="tenant-a")
    assert audit_after == audit_before
    assert all(event.occurred_at.tzinfo is not None for event in audit_after)
    assert all(event.actor_id and event.correlation_id for event in audit_after)


def test_every_administrative_permission_fails_closed_when_missing(tmp_path) -> None:
    database = _database(tmp_path)
    service = _onboard(database)
    no_tenant_permissions = _no_permissions()

    with pytest.raises(ControlPlaneAuthorizationError, match="organization.write"):
        service.onboard_organization(
            actor=_no_permissions(global_scope=True),
            tenant_id="tenant-denied",
            legal_name="Denied",
            correlation_id="corr-denied-org",
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="unit.write"):
        service.onboard_unit(
            actor=no_tenant_permissions,
            registration=FiscalUnitRegistration(
                tenant_id="tenant-a",
                unit_id="unit-denied",
                display_name="Denied",
            ),
            correlation_id="corr-denied-unit",
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="profile.write"):
        service.add_fiscal_profile(
            actor=no_tenant_permissions,
            profile=_profile(profile_id="profile-denied"),
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="secret_reference.write"):
        service.bind_secret_reference(
            actor=no_tenant_permissions,
            reference=SecretReference(
                reference_id="ref:fm-fiscal/tenant-a/unit-01/denied",
                kind=SecretReferenceKind.CREDENTIALS,
                tenant_id="tenant-a",
                unit_id="unit-01",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id="provider-denied",
            ),
            correlation_id="corr-denied-reference",
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="audit.read"):
        service.list_audit(actor=no_tenant_permissions, tenant_id="tenant-a")

    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )
    with pytest.raises(ControlPlaneAuthorizationError, match="capability.read"):
        governed.query(
            actor=no_tenant_permissions,
            context=_context(FiscalEnvironment.HOMOLOGATION),
        )

    operational = OperationalControlPlaneService(database)
    with pytest.raises(ControlPlaneAuthorizationError, match="operations.read"):
        operational.get_delivery_operation(
            actor=no_tenant_permissions,
            scope=_scope(),
            entry_id="0" * 64,
        )


def test_profile_boundaries_and_cross_scope_operational_isolation(tmp_path) -> None:
    database = _database(tmp_path)
    service_a = _onboard(database, tenant_id="tenant-a", unit_id="unit-01")
    _onboard(database, tenant_id="tenant-b", unit_id="unit-01")
    _onboard(database, tenant_id="tenant-c", unit_id="unit-02")
    admin_a = _tenant_admin("tenant-a")
    boundary = NOW + timedelta(days=30)

    first = _profile(
        profile_id="profile-a-1",
        effective_from=NOW - timedelta(days=1),
        effective_to=boundary,
    )
    second = _profile(
        profile_id="profile-a-2",
        effective_from=boundary,
        effective_to=None,
    )
    service_a.add_fiscal_profile(actor=admin_a, profile=first)
    service_a.add_fiscal_profile(actor=admin_a, profile=second)

    overlap = _profile(
        profile_id="profile-overlap",
        effective_from=NOW,
        effective_to=NOW + timedelta(days=1),
    )
    with pytest.raises(ControlPlaneConflictError, match="overlaps"):
        service_a.add_fiscal_profile(actor=admin_a, profile=overlap)

    with database.unit_of_work() as uow:
        assert uow.control_plane.resolve_profile(
            host_namespace="fm.kordena",
            tenant_id="tenant-a",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            instant=boundary - timedelta(seconds=1),
        ) == first
        assert uow.control_plane.resolve_profile(
            host_namespace="fm.kordena",
            tenant_id="tenant-a",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            instant=boundary,
        ) == second
        assert uow.control_plane.resolve_profile(
            host_namespace="fm.kordena",
            tenant_id="tenant-b",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            instant=NOW,
        ) is None

    foreign_tenant_scope = _scope(
        tenant_id="tenant-b",
        correlation_id="corr-foreign-tenant",
    )
    foreign_tenant_entry, _ = _seed_operational_state(database, foreign_tenant_scope)
    foreign_unit_scope = _scope(
        tenant_id="tenant-c",
        unit_id="unit-02",
        correlation_id="corr-foreign-unit",
    )
    foreign_unit_entry, _ = _seed_operational_state(database, foreign_unit_scope)
    operational = OperationalControlPlaneService(database)

    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant"):
        operational.get_delivery_operation(
            actor=admin_a,
            scope=foreign_tenant_scope,
            entry_id=foreign_tenant_entry,
        )
    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant"):
        operational.get_delivery_operation(
            actor=admin_a,
            scope=foreign_unit_scope,
            entry_id=foreign_unit_entry,
        )


def test_production_is_never_implicit_and_disabled_environment_is_blocked(tmp_path) -> None:
    database = _database(tmp_path)
    service = _onboard(database)
    admin = _tenant_admin()

    with database.unit_of_work() as uow:
        unit = uow.control_plane.get_unit("tenant-a", "unit-01")
    assert unit is not None
    assert unit.enabled_environments == frozenset({FiscalEnvironment.HOMOLOGATION})

    with pytest.raises(ControlPlaneAuthorizationError, match="environment"):
        service.add_fiscal_profile(
            actor=admin,
            profile=_profile(
                profile_id="profile-prod-denied",
                environment=FiscalEnvironment.PRODUCTION,
            ),
        )

    production_scope = _scope(environment=FiscalEnvironment.PRODUCTION)
    with pytest.raises(ControlPlaneAuthorizationError, match="environment"):
        OperationalControlPlaneService(database).list_archive_references(
            actor=admin,
            scope=production_scope,
            document_reference="doc-never-created",
        )


def test_secret_reference_schema_and_views_exclude_raw_material(tmp_path) -> None:
    database = _database(tmp_path)
    service = _onboard(database)
    reference = SecretReference(
        reference_id="ref:fm-fiscal/tenant-a/unit-01/certificate",
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id="tenant-a",
        unit_id="unit-01",
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    service.bind_secret_reference(
        actor=_tenant_admin(),
        reference=reference,
        correlation_id="corr-reference-schema",
    )

    with sqlite3.connect(database.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(fm_control_plane_secret_references)"
            ).fetchall()
        }
    assert columns == {
        "reference_id",
        "kind",
        "tenant_id",
        "unit_id",
        "environment",
        "provider_id",
    }
    assert not {
        "secret",
        "value",
        "material",
        "password",
        "token",
        "pfx",
        "csc",
    } & columns
    assert {item.name for item in fields(SecretReference)} == columns

    from kordena_fiscal.control_plane import ArchiveReferenceView, DeliveryOperationView

    delivery_fields = {item.name for item in fields(DeliveryOperationView)}
    archive_fields = {item.name for item in fields(ArchiveReferenceView)}
    assert "payload" not in delivery_fields
    assert "deduplication_key" not in delivery_fields
    assert "content" not in archive_fields


def test_migration_v4_is_idempotent_and_preserves_certified_history(tmp_path) -> None:
    database = _database(tmp_path, "migration-certification.sqlite3")
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    assert database.initialize() == ()

    with sqlite3.connect(database.path) as connection:
        migrations = connection.execute(
            "SELECT version, name FROM fm_schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert migrations == [
        (1, "v2_07_durable_fiscal_state"),
        (2, "v2_08_durable_inbox"),
        (3, "v2_08_delivery_audit_and_ordering"),
        (4, "v2_11_control_plane_durable_state"),
        (5, "v2_15_zero_code_commercial_configuration"),
        (13, "p02_t02_scoped_fiscal_projections"),
        (14, "customer_configuration_commands_and_egress"),
        (17, "external_secret_bindings"),
        (18, "public_trial_rate_windows"),
    ]
    assert {
        "fm_control_plane_organizations",
        "fm_control_plane_units",
        "fm_control_plane_secret_references",
        "fm_control_plane_fiscal_profiles",
        "fm_control_plane_audit",
    } <= tables


def test_control_plane_is_product_neutral_and_does_not_implement_v2_12_adapters() -> None:
    root = Path(__file__).resolve().parents[2]
    control_plane_dir = root / "src" / "kordena_fiscal" / "control_plane"
    imported_modules: set[str] = set()

    for path in control_plane_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    forbidden_import_fragments = {
        "contract_packs.kordena",
        "contract_packs.iron",
        "contract_packs.sales",
        "contract_packs.campaia",
        "provider",
        "signer",
        "vault",
        "kms",
    }
    assert not {
        module
        for module in imported_modules
        if any(fragment in module.lower() for fragment in forbidden_import_fragments)
    }

    filenames = {path.name.lower() for path in control_plane_dir.glob("*.py")}
    assert not {
        name
        for name in filenames
        if any(fragment in name for fragment in {"provider", "signer", "vault", "gateway"})
    }
