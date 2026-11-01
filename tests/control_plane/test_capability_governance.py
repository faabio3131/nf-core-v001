from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.compliance import (
    CapabilityReadinessError,
    CapabilityReadinessService,
    FiscalActionCapability,
    FiscalCapabilityLevel,
    JurisdictionCapabilityError,
    JurisdictionCapabilityMatrix,
    JurisdictionCapabilityRule,
    TechnicalValidationMode,
)
from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CapabilityControlContext,
    ControlPlaneAuthorizationError,
    ControlPlaneNotFoundError,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    GovernedCapabilityReadinessService,
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
    FiscalValidationError,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase

NOW = datetime(2026, 9, 12, 19, 0, tzinfo=UTC)


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
                ControlPlanePermission.AUDIT_READ,
            }
        ),
        tenant_ids=frozenset({tenant_id}),
    )


def _database(tmp_path, name: str = "capability.sqlite3") -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _profile(
    *,
    environment: FiscalEnvironment,
    profile_id: str,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
) -> FiscalProfile:
    return FiscalProfile(
        profile_id=profile_id,
        scope=ExecutionScope(
            host_namespace="fm.kordena",
            tenant_id=tenant_id,
            unit_id=unit_id,
            environment=environment,
            correlation_id=f"corr-{profile_id}",
        ),
        cnpj=Cnpj("11222333000181"),
        legal_name="Synthetic Capability Company",
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
        effective_from=NOW - timedelta(days=1),
    )


def _onboard(
    database: SqliteFiscalDatabase,
    *,
    environments: frozenset[FiscalEnvironment],
    tenant_id: str = "tenant-a",
    with_profiles: bool = True,
) -> None:
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
            unit_id="unit-01",
            display_name="Synthetic Unit",
            enabled_environments=environments,
        ),
        correlation_id=f"corr-unit-{tenant_id}",
    )
    if with_profiles:
        for environment in environments:
            service.add_fiscal_profile(
                actor=_tenant_admin(tenant_id),
                profile=_profile(
                    environment=environment,
                    profile_id=f"profile-{environment.value}",
                    tenant_id=tenant_id,
                ),
            )


def _readiness() -> CapabilityReadinessService:
    rules = (
        JurisdictionCapabilityRule(
            rule_id="sp-nfce-hml",
            version=1,
            state_code="SP",
            municipality_ibge_code="3550308",
            document_kind=FiscalDocumentKind.NFCE,
            environment=FiscalEnvironment.HOMOLOGATION,
            capability_level=FiscalCapabilityLevel.HOMOLOGATION_READY,
            validation_mode=TechnicalValidationMode.STRICT_REJECTION,
            effective_from=NOW - timedelta(days=10),
            source_normative="synthetic certified capability rule hml",
            capabilities=frozenset(
                {
                    FiscalActionCapability.ISSUE,
                    FiscalActionCapability.QUERY,
                }
            ),
        ),
        JurisdictionCapabilityRule(
            rule_id="sp-nfce-prod-contract-only",
            version=1,
            state_code="SP",
            municipality_ibge_code="3550308",
            document_kind=FiscalDocumentKind.NFCE,
            environment=FiscalEnvironment.PRODUCTION,
            capability_level=FiscalCapabilityLevel.CONTRACT_ONLY,
            validation_mode=TechnicalValidationMode.STRICT_REJECTION,
            effective_from=NOW - timedelta(days=10),
            source_normative="synthetic production rule intentionally not approved",
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


def test_governed_query_delegates_to_certified_readiness_authority(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    authority = _readiness()
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=authority,
    )

    snapshot = governed.query(
        actor=_tenant_admin(),
        context=_context(FiscalEnvironment.HOMOLOGATION),
    )
    direct = authority.query(
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        document_kind=FiscalDocumentKind.NFCE,
        environment=FiscalEnvironment.HOMOLOGATION,
        instant=NOW,
    )

    assert snapshot == direct
    assert snapshot.readiness is FiscalCapabilityLevel.HOMOLOGATION_READY
    assert FiscalActionCapability.ISSUE in snapshot.actions


def test_governed_require_action_preserves_authority_fail_closed_semantics(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )

    allowed = governed.require_action(
        actor=_tenant_admin(),
        context=_context(FiscalEnvironment.HOMOLOGATION),
        action=FiscalActionCapability.ISSUE,
    )
    assert allowed.readiness is FiscalCapabilityLevel.HOMOLOGATION_READY

    with pytest.raises(CapabilityReadinessError, match="not declared"):
        governed.require_action(
            actor=_tenant_admin(),
            context=_context(FiscalEnvironment.HOMOLOGATION),
            action=FiscalActionCapability.CANCEL,
        )


def test_control_plane_never_upgrades_production_readiness(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset(
            {FiscalEnvironment.HOMOLOGATION, FiscalEnvironment.PRODUCTION}
        ),
    )
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )
    context = _context(FiscalEnvironment.PRODUCTION)

    visible = governed.query(actor=_tenant_admin(), context=context)
    assert visible.readiness is FiscalCapabilityLevel.CONTRACT_ONLY

    with pytest.raises(JurisdictionCapabilityError, match="below the required"):
        governed.require_action(
            actor=_tenant_admin(),
            context=context,
            action=FiscalActionCapability.ISSUE,
        )


def test_disabled_environment_fails_before_capability_authority(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )

    with pytest.raises(ControlPlaneAuthorizationError, match="environment"):
        governed.query(
            actor=_tenant_admin(),
            context=_context(FiscalEnvironment.PRODUCTION),
        )


def test_capability_query_requires_effective_profile_and_tenant_scope(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        with_profiles=False,
    )
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )

    with pytest.raises(ControlPlaneNotFoundError, match="effective fiscal profile"):
        governed.query(
            actor=_tenant_admin(),
            context=_context(FiscalEnvironment.HOMOLOGATION),
        )

    outsider = _tenant_admin("tenant-b")
    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant"):
        governed.query(
            actor=outsider,
            context=_context(FiscalEnvironment.HOMOLOGATION),
        )


def test_capability_query_requires_explicit_read_permission(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )
    actor = AdminPrincipal(
        actor_id="profile-writer-only",
        permissions=frozenset({ControlPlanePermission.PROFILE_WRITE}),
        tenant_ids=frozenset({"tenant-a"}),
    )

    with pytest.raises(ControlPlaneAuthorizationError, match="capability.read"):
        governed.query(
            actor=actor,
            context=_context(FiscalEnvironment.HOMOLOGATION),
        )


def test_capability_reads_do_not_mutate_administrative_audit_trail(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(
        database,
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    admin = _tenant_admin()
    durable = DurableControlPlaneService(database, clock=_Clock())
    before = durable.list_audit(actor=admin, tenant_id="tenant-a")

    governed = GovernedCapabilityReadinessService(
        unit_of_work_factory=database,
        readiness=_readiness(),
    )
    governed.query(actor=admin, context=_context(FiscalEnvironment.HOMOLOGATION))

    after = durable.list_audit(actor=admin, tenant_id="tenant-a")
    assert after == before


def test_capability_context_requires_timezone_aware_instant() -> None:
    with pytest.raises(FiscalValidationError, match="timezone-aware"):
        CapabilityControlContext(
            host_namespace="fm.kordena",
            tenant_id="tenant-a",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFCE,
            instant=datetime(2026, 9, 12, 19, 0),
        )
