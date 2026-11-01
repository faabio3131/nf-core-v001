from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CommercialConfigurationService,
    ConfiguredFiscalOperation,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    ProviderBinding,
    ProviderRuntimePolicyConfig,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.control_plane.commercial_admin import (
    CommercialRuntimeConfigurationService,
)
from kordena_fiscal.control_plane.commercial_models import HomologationEvidenceRecord
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway import ProviderDescriptor, ProviderOperation
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.homologation_readiness import (
    DurableHomologationEnvironmentReadinessService,
)

NOW = datetime(2026, 9, 13, 19, 40, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
PROVIDER_A = "provider-nfce-a"
PROVIDER_B = "provider-nfce-b"


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-b3-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.COMMERCIAL_CONFIG_WRITE,
            }
        ),
        global_scope=True,
    )


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.synthetic-b3",
        tenant_id="tenant-b3",
        unit_id="unit-b3",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-b3",
    )


def _descriptor(provider_id: str = PROVIDER_A) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        document_kinds=frozenset({FiscalDocumentKind.NFCE}),
        jurisdictions=(SP,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset(
            {
                ProviderOperation.AUTHORIZE,
                ProviderOperation.QUERY,
                ProviderOperation.CANCEL,
            }
        ),
        csc_required_for=frozenset(
            {(FiscalDocumentKind.NFCE, ProviderOperation.AUTHORIZE)}
        ),
    )


def _database(tmp_path, *, bind_provider_a_csc: bool = True) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-b3-nfce.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    control = DurableControlPlaneService(database)
    control.onboard_organization(
        actor=_admin(),
        tenant_id="tenant-b3",
        legal_name="Synthetic B3 NFC-e Tenant",
        correlation_id="corr-b3-org",
    )
    control.onboard_unit(
        actor=_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-b3",
            unit_id="unit-b3",
            display_name="Synthetic B3 NFC-e Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-b3-unit",
    )
    references = [
        SecretReference(
            reference_id="ref:synthetic/b3/certificate",
            kind=SecretReferenceKind.CERTIFICATE,
            tenant_id="tenant-b3",
            unit_id="unit-b3",
            environment=FiscalEnvironment.HOMOLOGATION,
        ),
        SecretReference(
            reference_id="ref:synthetic/b3/provider-a-credentials",
            kind=SecretReferenceKind.CREDENTIALS,
            tenant_id="tenant-b3",
            unit_id="unit-b3",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_A,
        ),
    ]
    if bind_provider_a_csc:
        references.append(
            SecretReference(
                reference_id="ref:synthetic/b3/provider-a-csc",
                kind=SecretReferenceKind.CSC,
                tenant_id="tenant-b3",
                unit_id="unit-b3",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=PROVIDER_A,
            )
        )
    for index, reference in enumerate(references):
        control.bind_secret_reference(
            actor=_admin(),
            reference=reference,
            correlation_id=f"corr-b3-secret-{index}",
        )

    commercial = CommercialConfigurationService(database)
    commercial.set_runtime_policy(
        actor=_admin(),
        policy=ProviderRuntimePolicyConfig(
            policy_id="policy-nfce-b3",
            tenant_id="tenant-b3",
            unit_id="unit-b3",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_A,
            connect_timeout_seconds=5,
            read_timeout_seconds=15,
            max_attempts=2,
            base_delay_seconds=0.1,
            max_delay_seconds=0.5,
            jitter_ratio=0,
            circuit_failure_threshold=2,
            circuit_recovery_seconds=10,
        ),
    )
    runtime_admin = CommercialRuntimeConfigurationService(database)
    for operation in (
        ProviderOperation.AUTHORIZE,
        ProviderOperation.QUERY,
        ProviderOperation.CANCEL,
    ):
        commercial.set_provider_binding(
            actor=_admin(),
            binding=ProviderBinding(
                binding_id=f"binding-nfce-{operation.value}-b3",
                tenant_id="tenant-b3",
                unit_id="unit-b3",
                environment=FiscalEnvironment.HOMOLOGATION,
                document_kind=FiscalDocumentKind.NFCE,
                jurisdiction=SP,
                operation=ConfiguredFiscalOperation(operation.value),
                provider_id=PROVIDER_A,
            ),
        )
        requires_signer = operation is ProviderOperation.AUTHORIZE
        requires_csc = operation is ProviderOperation.AUTHORIZE
        runtime_admin.set_homologation_evidence(
            actor=_admin(),
            record=HomologationEvidenceRecord(
                tenant_id="tenant-b3",
                unit_id="unit-b3",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=PROVIDER_A,
                document_kind=FiscalDocumentKind.NFCE,
                jurisdiction=SP,
                operation=operation.value,
                provider_adapter_available=True,
                credentials_reference_configured=True,
                signer_capability=requires_signer,
                csc_reference_configured=requires_csc,
                transport_configured=True,
                resilience_certified=True,
                contract_tests_certified=True,
                jurisdiction_mapping=True,
                operation_supported=True,
                requires_signer=requires_signer,
                requires_csc=requires_csc,
                external_official=False,
                recorded_at=NOW,
            ),
        )
    return database


def test_b3_nfce_authorize_query_cancel_matrix_is_internally_certified(tmp_path) -> None:
    database = _database(tmp_path)
    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    service = DurableHomologationEnvironmentReadinessService(
        restarted,
        provider_catalog=(_descriptor(),),
    )

    results = tuple(
        service.assess(
            scope=_scope(),
            document_kind=FiscalDocumentKind.NFCE,
            jurisdiction=SP,
            operation=operation,
        )
        for operation in (
            ProviderOperation.AUTHORIZE,
            ProviderOperation.QUERY,
            ProviderOperation.CANCEL,
        )
    )

    assert all(item.internally_ready for item in results)
    assert all(item.provider_id == PROVIDER_A for item in results)
    assert all(not item.officially_homologated for item in results)


def test_b3_nfce_csc_is_provider_scoped_and_never_falls_back(tmp_path) -> None:
    database = _database(tmp_path, bind_provider_a_csc=False)
    DurableControlPlaneService(database).bind_secret_reference(
        actor=_admin(),
        reference=SecretReference(
            reference_id="ref:synthetic/b3/provider-b-csc",
            kind=SecretReferenceKind.CSC,
            tenant_id="tenant-b3",
            unit_id="unit-b3",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_B,
        ),
        correlation_id="corr-b3-provider-b-csc",
    )

    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_descriptor(PROVIDER_A), _descriptor(PROVIDER_B)),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFCE,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id == PROVIDER_A
    assert "csc_reference" in result.missing_configuration
    assert result.internally_ready is False


def test_b3_nfce_homologation_never_falls_back_to_production(tmp_path) -> None:
    database = _database(tmp_path)
    production_scope = ExecutionScope(
        host_namespace="fm.synthetic-b3",
        tenant_id="tenant-b3",
        unit_id="unit-b3",
        environment=FiscalEnvironment.PRODUCTION,
        correlation_id="corr-b3-production",
    )

    with pytest.raises(FiscalValidationError, match="only accepts HOMOLOGATION"):
        DurableHomologationEnvironmentReadinessService(
            database,
            provider_catalog=(_descriptor(),),
        ).assess(
            scope=production_scope,
            document_kind=FiscalDocumentKind.NFCE,
            jurisdiction=SP,
            operation=ProviderOperation.AUTHORIZE,
        )


def test_b3_persistence_contains_only_opaque_secret_references(tmp_path) -> None:
    database = _database(tmp_path)
    with sqlite3.connect(database.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(fm_control_plane_secret_references)"
            ).fetchall()
        }
        rows = connection.execute(
            "SELECT reference_id, kind, provider_id "
            "FROM fm_control_plane_secret_references "
            "WHERE tenant_id = ? AND unit_id = ?",
            ("tenant-b3", "unit-b3"),
        ).fetchall()

    assert "secret" not in columns
    assert "password" not in columns
    assert "private_key" not in columns
    assert rows
    assert all(str(row[0]).startswith("ref:") for row in rows)
    csc_rows = [row for row in rows if row[1] == SecretReferenceKind.CSC.value]
    assert csc_rows == [("ref:synthetic/b3/provider-a-csc", "csc", PROVIDER_A)]
