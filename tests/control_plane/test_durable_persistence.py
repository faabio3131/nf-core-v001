from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    ControlPlaneAuthorizationError,
    ControlPlaneConflictError,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    MunicipalRegistration,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="fm-platform-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.PROFILE_WRITE,
                ControlPlanePermission.CAPABILITY_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.AUDIT_READ,
                ControlPlanePermission.OPERATIONS_READ,
            }
        ),
        global_scope=True,
    )


def _tenant_admin(tenant_id: str = "tenant-a") -> AdminPrincipal:
    return AdminPrincipal(
        actor_id=f"admin-{tenant_id}",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.PROFILE_WRITE,
                ControlPlanePermission.CAPABILITY_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.AUDIT_READ,
                ControlPlanePermission.OPERATIONS_READ,
            }
        ),
        tenant_ids=frozenset({tenant_id}),
    )


def _database(tmp_path, name: str = "control-plane.sqlite3") -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _service(database: SqliteFiscalDatabase) -> DurableControlPlaneService:
    return DurableControlPlaneService(database, clock=_FixedClock())


def _onboard(
    service: DurableControlPlaneService,
    *,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    environments: frozenset[FiscalEnvironment] = frozenset(
        {FiscalEnvironment.HOMOLOGATION}
    ),
) -> None:
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


def _profile(
    *,
    profile_id: str = "profile-a",
    version: int = 1,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-01",
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    effective_from: datetime = NOW,
    effective_to: datetime | None = None,
    correlation_id: str = "corr-profile-a",
) -> FiscalProfile:
    return FiscalProfile(
        profile_id=profile_id,
        version=version,
        scope=ExecutionScope(
            host_namespace="fm.kordena",
            tenant_id=tenant_id,
            unit_id=unit_id,
            environment=environment,
            correlation_id=correlation_id,
        ),
        cnpj=Cnpj("11222333000181"),
        legal_name="Synthetic Fiscal Company A Ltda",
        trade_name="Synthetic A",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration(
            state_code="SP",
            number="110042490114",
        ),
        municipal_registration=MunicipalRegistration("12345678"),
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
            complement="Suite 10",
        ),
        effective_from=effective_from,
        effective_to=effective_to,
    )



def _remove_v5(connection: sqlite3.Connection) -> None:
    # Reconstruct the earlier schema, not just its migration ledger.
    connection.execute("DROP TABLE fm_public_trial_rate_windows")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 18")
    connection.execute("DROP TABLE fm_secret_bindings")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 17")
    connection.execute("DROP TABLE fm_configuration_commands")
    connection.execute("DROP TABLE fm_configuration_revisions")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 14")
    connection.execute("DROP INDEX fm_idempotency_document_idx")
    connection.execute("DROP INDEX fm_fiscal_lifecycle_scope_idx")
    connection.execute("DROP INDEX fm_fiscal_outbox_scope_idx")
    connection.execute("DROP INDEX fm_fiscal_archive_scope_idx")
    for column in ("host_namespace", "tenant_id", "unit_id", "environment"):
        connection.execute(f"ALTER TABLE fm_fiscal_lifecycle DROP COLUMN {column}")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 13")

    for table in (
        "fm_commercial_homologation_evidence",
        "fm_commercial_workload_credentials",
        "fm_commercial_numbering_configurations",
        "fm_commercial_provider_runtime_policies",
        "fm_commercial_webhook_destinations",
        "fm_commercial_unit_modules",
        "fm_commercial_product_profiles",
        "fm_commercial_provider_bindings",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 5")

def _remove_v4(connection: sqlite3.Connection) -> None:
    connection.execute("DROP INDEX fm_control_plane_audit_tenant_idx")
    connection.execute("DROP TABLE fm_control_plane_audit")
    connection.execute("DROP INDEX fm_control_plane_fiscal_profiles_effective_idx")
    connection.execute("DROP TABLE fm_control_plane_fiscal_profiles")
    connection.execute("DROP TABLE fm_control_plane_secret_references")
    connection.execute("DROP TABLE fm_control_plane_units")
    connection.execute("DROP TABLE fm_control_plane_organizations")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 4")


def test_v2_11_migration_v4_is_explicit_and_upgrades_v2_08_checkpoint(tmp_path) -> None:
    database = _database(tmp_path, "migration-v4.sqlite3")
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        _remove_v5(connection)
        _remove_v4(connection)
        connection.commit()

    assert database.applied_migrations() == (1, 2, 3)
    assert database.initialize() == (4, 5, 13, 14, 17, 18, 19)
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "fm_control_plane_organizations",
        "fm_control_plane_units",
        "fm_control_plane_secret_references",
        "fm_control_plane_fiscal_profiles",
        "fm_control_plane_audit",
    } <= tables


def test_onboarding_and_audit_survive_restart(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    with restarted.unit_of_work() as uow:
        organization = uow.control_plane.get_organization("tenant-a")
        unit = uow.control_plane.get_unit("tenant-a", "unit-01")
        audit = uow.control_plane.list_audit("tenant-a")

    assert organization == FiscalOrganization(
        tenant_id="tenant-a",
        legal_name="Synthetic tenant-a",
    )
    assert unit is not None
    assert unit.enabled_environments == frozenset({FiscalEnvironment.HOMOLOGATION})
    assert {event.action.value for event in audit} == {
        "organization.onboarded",
        "unit.onboarded",
    }


def test_secret_reference_round_trip_persists_only_opaque_reference_metadata(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)
    reference = SecretReference(
        reference_id="ref:fm-fiscal/tenant-a/unit-01/hml-certificate",
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id="tenant-a",
        unit_id="unit-01",
        environment=FiscalEnvironment.HOMOLOGATION,
    )

    service.bind_secret_reference(
        actor=_tenant_admin(),
        reference=reference,
        correlation_id="corr-secret-1",
    )

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    with restarted.unit_of_work() as uow:
        persisted = uow.control_plane.get_secret_reference(
            "tenant-a",
            "unit-01",
            FiscalEnvironment.HOMOLOGATION,
            SecretReferenceKind.CERTIFICATE,
        )
    assert persisted == reference

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
    assert not ({"secret", "value", "material", "password", "token", "pfx", "csc"} & columns)


def test_fiscal_profile_round_trip_and_effective_resolution_survive_restart(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)
    profile = _profile(effective_from=NOW, effective_to=NOW + timedelta(days=30))

    assert service.add_fiscal_profile(actor=_tenant_admin(), profile=profile) == profile

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    with restarted.unit_of_work() as uow:
        exact = uow.control_plane.get_profile("profile-a", 1)
        effective = uow.control_plane.resolve_profile(
            host_namespace="fm.kordena",
            tenant_id="tenant-a",
            unit_id="unit-01",
            environment=FiscalEnvironment.HOMOLOGATION,
            instant=NOW + timedelta(days=1),
        )
        audit = uow.control_plane.list_audit("tenant-a")

    assert exact == profile
    assert effective == profile
    profile_events = [
        event for event in audit if event.action.value == "fiscal_profile.added"
    ]
    assert len(profile_events) == 1
    assert profile_events[0].target_id == "profile-a:v1"


def test_overlapping_profile_is_rejected_without_extra_audit_fact(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)
    first = _profile(
        profile_id="profile-a",
        effective_from=NOW,
        effective_to=NOW + timedelta(days=30),
    )
    service.add_fiscal_profile(actor=_tenant_admin(), profile=first)
    before = service.list_audit(actor=_tenant_admin(), tenant_id="tenant-a")

    overlapping = _profile(
        profile_id="profile-b",
        effective_from=NOW + timedelta(days=10),
        effective_to=NOW + timedelta(days=40),
        correlation_id="corr-profile-b",
    )
    with pytest.raises(ControlPlaneConflictError, match="overlaps"):
        service.add_fiscal_profile(actor=_tenant_admin(), profile=overlapping)

    after = service.list_audit(actor=_tenant_admin(), tenant_id="tenant-a")
    assert after == before
    with database.unit_of_work() as uow:
        assert uow.control_plane.get_profile("profile-b", 1) is None


def test_adjacent_profile_periods_are_allowed_and_resolve_deterministically(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)
    boundary = NOW + timedelta(days=30)
    first = _profile(
        profile_id="profile-a",
        effective_from=NOW,
        effective_to=boundary,
    )
    second = _profile(
        profile_id="profile-b",
        effective_from=boundary,
        effective_to=None,
        correlation_id="corr-profile-b",
    )
    service.add_fiscal_profile(actor=_tenant_admin(), profile=first)
    service.add_fiscal_profile(actor=_tenant_admin(), profile=second)

    with database.unit_of_work() as uow:
        assert (
            uow.control_plane.resolve_profile(
                host_namespace="fm.kordena",
                tenant_id="tenant-a",
                unit_id="unit-01",
                environment=FiscalEnvironment.HOMOLOGATION,
                instant=boundary - timedelta(seconds=1),
            )
            == first
        )
        assert (
            uow.control_plane.resolve_profile(
                host_namespace="fm.kordena",
                tenant_id="tenant-a",
                unit_id="unit-01",
                environment=FiscalEnvironment.HOMOLOGATION,
                instant=boundary,
            )
            == second
        )


def test_profile_environment_must_be_explicitly_enabled(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service)
    production = _profile(environment=FiscalEnvironment.PRODUCTION)

    with pytest.raises(ControlPlaneAuthorizationError, match="environment"):
        service.add_fiscal_profile(actor=_tenant_admin(), profile=production)


def test_durable_rbac_rejects_cross_tenant_writes_and_reads(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    _onboard(service, tenant_id="tenant-a")
    _onboard(service, tenant_id="tenant-b")

    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant"):
        service.onboard_unit(
            actor=_tenant_admin("tenant-a"),
            registration=FiscalUnitRegistration(
                tenant_id="tenant-b",
                unit_id="unit-02",
                display_name="Forbidden Unit",
            ),
            correlation_id="corr-forbidden-unit",
        )

    with pytest.raises(ControlPlaneAuthorizationError, match="cannot access tenant audit"):
        service.list_audit(actor=_tenant_admin("tenant-a"), tenant_id="tenant-b")


def test_uncommitted_control_plane_transaction_rolls_back_atomically(tmp_path) -> None:
    database = _database(tmp_path)
    organization = FiscalOrganization(tenant_id="tenant-rollback", legal_name="Rollback Co")

    with database.unit_of_work() as uow:
        uow.control_plane.add_organization(organization)
        assert uow.control_plane.get_organization("tenant-rollback") == organization
        # Deliberately do not commit.

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    with restarted.unit_of_work() as uow:
        assert uow.control_plane.get_organization("tenant-rollback") is None
