from __future__ import annotations

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
from kordena_fiscal.homologation import TechnicalGateState
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.homologation_readiness import (
    DurableHomologationEnvironmentReadinessService,
)

NOW = datetime(2026, 9, 13, 19, 0, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
SP_SAO_PAULO = BrazilianJurisdiction("SP", "3550308")


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-b1-admin",
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


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-b1.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    service = DurableControlPlaneService(database)
    service.onboard_organization(
        actor=_admin(),
        tenant_id="tenant-b1",
        legal_name="Synthetic B1 Tenant",
        correlation_id="corr-b1-org",
    )
    service.onboard_unit(
        actor=_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-b1",
            unit_id="unit-b1",
            display_name="Synthetic B1 Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-b1-unit",
    )
    return database


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.synthetic-b1",
        tenant_id="tenant-b1",
        unit_id="unit-b1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-b1-runtime",
    )


def _nfe_descriptor(provider_id: str = "provider-a") -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        document_kinds=frozenset({FiscalDocumentKind.NFE}),
        jurisdictions=(SP,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset(
            {
                ProviderOperation.AUTHORIZE,
                ProviderOperation.QUERY,
                ProviderOperation.CANCEL,
            }
        ),
    )


def _runtime_policy(provider_id: str = "provider-a") -> ProviderRuntimePolicyConfig:
    return ProviderRuntimePolicyConfig(
        policy_id=f"policy-{provider_id}-b1",
        tenant_id="tenant-b1",
        unit_id="unit-b1",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=provider_id,
        connect_timeout_seconds=5,
        read_timeout_seconds=15,
        max_attempts=2,
        base_delay_seconds=0.25,
        max_delay_seconds=1,
        jitter_ratio=0,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=10,
    )


def _bind_nfe_authorize(database: SqliteFiscalDatabase) -> None:
    CommercialConfigurationService(database).set_provider_binding(
        actor=_admin(),
        binding=ProviderBinding(
            binding_id="binding-nfe-auth-b1",
            tenant_id="tenant-b1",
            unit_id="unit-b1",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id="provider-a",
        ),
    )
    CommercialConfigurationService(database).set_runtime_policy(
        actor=_admin(),
        policy=_runtime_policy(),
    )


def _bind_reference(
    database: SqliteFiscalDatabase,
    *,
    kind: SecretReferenceKind,
    reference_id: str,
    provider_id: str | None = None,
) -> None:
    DurableControlPlaneService(database).bind_secret_reference(
        actor=_admin(),
        reference=SecretReference(
            reference_id=reference_id,
            kind=kind,
            tenant_id="tenant-b1",
            unit_id="unit-b1",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=provider_id,
        ),
        correlation_id=f"corr-{kind.value}-{provider_id or 'unit'}",
    )


def _technical_evidence(
    *,
    provider_id: str = "provider-a",
    document_kind: FiscalDocumentKind = FiscalDocumentKind.NFE,
    jurisdiction: BrazilianJurisdiction = SP,
    operation: str = "authorize",
    requires_signer: bool = True,
    requires_csc: bool = False,
) -> HomologationEvidenceRecord:
    return HomologationEvidenceRecord(
        tenant_id="tenant-b1",
        unit_id="unit-b1",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=provider_id,
        document_kind=document_kind,
        jurisdiction=jurisdiction,
        operation=operation,
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
    )


def test_b1_homologation_readiness_is_durable_exact_and_internal_only(tmp_path) -> None:
    database = _database(tmp_path)
    _bind_nfe_authorize(database)
    _bind_reference(
        database,
        kind=SecretReferenceKind.CERTIFICATE,
        reference_id="ref:synthetic/tenant-b1/unit-b1/hml-certificate",
    )
    _bind_reference(
        database,
        kind=SecretReferenceKind.CREDENTIALS,
        reference_id="ref:synthetic/tenant-b1/unit-b1/provider-a-credentials",
        provider_id="provider-a",
    )
    CommercialRuntimeConfigurationService(database).set_homologation_evidence(
        actor=_admin(),
        record=_technical_evidence(),
    )

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    result = DurableHomologationEnvironmentReadinessService(
        restarted,
        provider_catalog=(_nfe_descriptor(),),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id == "provider-a"
    assert result.missing_configuration == ()
    assert result.technical_state is TechnicalGateState.TECHNICALLY_CERTIFIED
    assert result.internally_ready is True
    assert result.external_official is False
    assert result.external_evidence_id is None
    assert result.officially_homologated is False


def test_b1_provider_scoped_credentials_fail_closed_without_cross_provider_fallback(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    _bind_nfe_authorize(database)
    _bind_reference(
        database,
        kind=SecretReferenceKind.CERTIFICATE,
        reference_id="ref:synthetic/tenant-b1/unit-b1/hml-certificate",
    )
    _bind_reference(
        database,
        kind=SecretReferenceKind.CREDENTIALS,
        reference_id="ref:synthetic/tenant-b1/unit-b1/provider-b-credentials",
        provider_id="provider-b",
    )
    CommercialRuntimeConfigurationService(database).set_homologation_evidence(
        actor=_admin(),
        record=_technical_evidence(),
    )

    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_nfe_descriptor("provider-a"), _nfe_descriptor("provider-b")),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id == "provider-a"
    assert "provider_credentials_reference" in result.missing_configuration
    assert result.internally_ready is False


def test_b1_missing_exact_binding_does_not_fall_back_to_other_jurisdiction(tmp_path) -> None:
    database = _database(tmp_path)
    CommercialConfigurationService(database).set_provider_binding(
        actor=_admin(),
        binding=ProviderBinding(
            binding_id="binding-nfse-sp-b1",
            tenant_id="tenant-b1",
            unit_id="unit-b1",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=SP_SAO_PAULO,
            operation=ConfiguredFiscalOperation.QUERY,
            provider_id="provider-nfse",
        ),
    )
    descriptor = ProviderDescriptor(
        provider_id="provider-nfse",
        document_kinds=frozenset({FiscalDocumentKind.NFSE}),
        jurisdictions=(SP_SAO_PAULO,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset({ProviderOperation.QUERY}),
    )
    other_municipality = BrazilianJurisdiction("SP", "3509502")

    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(descriptor,),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=other_municipality,
        operation=ProviderOperation.QUERY,
    )

    assert result.provider_id is None
    assert "provider_binding" in result.missing_configuration
    assert result.internally_ready is False


def test_b1_production_scope_is_rejected_before_configuration_resolution(tmp_path) -> None:
    database = _database(tmp_path)
    production_scope = ExecutionScope(
        host_namespace="fm.synthetic-b1",
        tenant_id="tenant-b1",
        unit_id="unit-b1",
        environment=FiscalEnvironment.PRODUCTION,
        correlation_id="corr-b1-production",
    )

    with pytest.raises(FiscalValidationError, match="only accepts HOMOLOGATION"):
        DurableHomologationEnvironmentReadinessService(
            database,
            provider_catalog=(_nfe_descriptor(),),
        ).assess(
            scope=production_scope,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=ProviderOperation.AUTHORIZE,
        )


def test_b1_recorded_evidence_cannot_hide_missing_runtime_policy(tmp_path) -> None:
    database = _database(tmp_path)
    CommercialConfigurationService(database).set_provider_binding(
        actor=_admin(),
        binding=ProviderBinding(
            binding_id="binding-nfe-auth-b1-no-policy",
            tenant_id="tenant-b1",
            unit_id="unit-b1",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id="provider-a",
        ),
    )
    _bind_reference(
        database,
        kind=SecretReferenceKind.CERTIFICATE,
        reference_id="ref:synthetic/tenant-b1/unit-b1/hml-certificate",
    )
    _bind_reference(
        database,
        kind=SecretReferenceKind.CREDENTIALS,
        reference_id="ref:synthetic/tenant-b1/unit-b1/provider-a-credentials",
        provider_id="provider-a",
    )
    CommercialRuntimeConfigurationService(database).set_homologation_evidence(
        actor=_admin(),
        record=_technical_evidence(),
    )

    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_nfe_descriptor(),),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.technical_state is TechnicalGateState.TECHNICALLY_CERTIFIED
    assert "provider_runtime_policy" in result.missing_configuration
    assert result.internally_ready is False
