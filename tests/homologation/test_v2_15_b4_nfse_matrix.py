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
from kordena_fiscal.gateway import (
    ProviderDescriptor,
    ProviderOperation,
    ProviderRequest,
    ProviderResponse,
    ProviderTransportError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.resilience import (
    CircuitBreakerPolicy,
    CircuitBreakerRegistry,
    ResilientProviderGateway,
    RetryPolicy,
    UnknownProviderOutcomeError,
)
from kordena_fiscal.runtime.homologation_readiness import (
    DurableHomologationEnvironmentReadinessService,
)
from kordena_fiscal.signing import FiscalSignatureResult, SignatureAlgorithm

NOW = datetime(2026, 9, 13, 20, 0, tzinfo=UTC)
SAO_PAULO = BrazilianJurisdiction("SP", "3550308")
CAMPINAS = BrazilianJurisdiction("SP", "3509502")
PROVIDER_A = "provider-nfse-a"
PROVIDER_B = "provider-nfse-b"


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-b4-admin",
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
        host_namespace="fm.synthetic-b4",
        tenant_id="tenant-b4",
        unit_id="unit-b4",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-b4",
    )


def _descriptor(provider_id: str = PROVIDER_A) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        document_kinds=frozenset({FiscalDocumentKind.NFSE}),
        jurisdictions=(SAO_PAULO,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset(
            {
                ProviderOperation.AUTHORIZE,
                ProviderOperation.QUERY,
                ProviderOperation.CANCEL,
            }
        ),
    )


def _database(
    tmp_path,
    *,
    provider_a_credentials: bool = True,
) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-b4-nfse.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    control = DurableControlPlaneService(database)
    control.onboard_organization(
        actor=_admin(),
        tenant_id="tenant-b4",
        legal_name="Synthetic B4 NFS-e Tenant",
        correlation_id="corr-b4-org",
    )
    control.onboard_unit(
        actor=_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-b4",
            unit_id="unit-b4",
            display_name="Synthetic B4 NFS-e Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-b4-unit",
    )
    if provider_a_credentials:
        control.bind_secret_reference(
            actor=_admin(),
            reference=SecretReference(
                reference_id="ref:synthetic/b4/provider-a-credentials",
                kind=SecretReferenceKind.CREDENTIALS,
                tenant_id="tenant-b4",
                unit_id="unit-b4",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=PROVIDER_A,
            ),
            correlation_id="corr-b4-credentials-a",
        )

    commercial = CommercialConfigurationService(database)
    commercial.set_runtime_policy(
        actor=_admin(),
        policy=ProviderRuntimePolicyConfig(
            policy_id="policy-nfse-b4",
            tenant_id="tenant-b4",
            unit_id="unit-b4",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_A,
            connect_timeout_seconds=5,
            read_timeout_seconds=20,
            max_attempts=3,
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
                binding_id=f"binding-nfse-{operation.value}-b4",
                tenant_id="tenant-b4",
                unit_id="unit-b4",
                environment=FiscalEnvironment.HOMOLOGATION,
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=SAO_PAULO,
                operation=ConfiguredFiscalOperation(operation.value),
                provider_id=PROVIDER_A,
            ),
        )
        runtime_admin.set_homologation_evidence(
            actor=_admin(),
            record=HomologationEvidenceRecord(
                tenant_id="tenant-b4",
                unit_id="unit-b4",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=PROVIDER_A,
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=SAO_PAULO,
                operation=operation.value,
                provider_adapter_available=True,
                credentials_reference_configured=True,
                signer_capability=False,
                csc_reference_configured=False,
                transport_configured=True,
                resilience_certified=True,
                contract_tests_certified=True,
                jurisdiction_mapping=True,
                operation_supported=True,
                requires_signer=False,
                requires_csc=False,
                external_official=False,
                recorded_at=NOW,
            ),
        )
    return database


def test_b4_nfse_matrix_is_exactly_municipal_and_internally_ready_after_restart(
    tmp_path,
) -> None:
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
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=SAO_PAULO,
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
    assert all(not item.external_official for item in results)


def test_b4_nfse_never_falls_back_from_wrong_municipality_to_state(tmp_path) -> None:
    database = _database(tmp_path)
    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_descriptor(),),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=CAMPINAS,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id is None
    assert "provider_binding" in result.missing_configuration
    assert result.internally_ready is False


def test_b4_nfse_binding_and_evidence_require_municipality_ibge() -> None:
    state_only = BrazilianJurisdiction("SP")
    with pytest.raises(FiscalValidationError, match="municipality IBGE"):
        ProviderBinding(
            binding_id="invalid-nfse-state-only",
            tenant_id="tenant-b4",
            unit_id="unit-b4",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=state_only,
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id=PROVIDER_A,
        )
    with pytest.raises(FiscalValidationError, match="municipality IBGE"):
        HomologationEvidenceRecord(
            tenant_id="tenant-b4",
            unit_id="unit-b4",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_A,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=state_only,
            operation="authorize",
            provider_adapter_available=True,
            credentials_reference_configured=True,
            signer_capability=False,
            csc_reference_configured=False,
            transport_configured=True,
            resilience_certified=True,
            contract_tests_certified=True,
            jurisdiction_mapping=True,
            operation_supported=True,
        )


def test_b4_nfse_provider_credentials_never_fall_back_cross_provider(tmp_path) -> None:
    database = _database(tmp_path, provider_a_credentials=False)
    DurableControlPlaneService(database).bind_secret_reference(
        actor=_admin(),
        reference=SecretReference(
            reference_id="ref:synthetic/b4/provider-b-credentials",
            kind=SecretReferenceKind.CREDENTIALS,
            tenant_id="tenant-b4",
            unit_id="unit-b4",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER_B,
        ),
        correlation_id="corr-b4-credentials-b",
    )
    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_descriptor(PROVIDER_A), _descriptor(PROVIDER_B)),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=SAO_PAULO,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id == PROVIDER_A
    assert "provider_credentials_reference" in result.missing_configuration
    assert result.internally_ready is False


def test_b4_nfse_homologation_rejects_production_scope(tmp_path) -> None:
    database = _database(tmp_path)
    production = ExecutionScope(
        host_namespace="fm.synthetic-b4",
        tenant_id="tenant-b4",
        unit_id="unit-b4",
        environment=FiscalEnvironment.PRODUCTION,
        correlation_id="corr-b4-production",
    )
    with pytest.raises(FiscalValidationError, match="only accepts HOMOLOGATION"):
        DurableHomologationEnvironmentReadinessService(
            database,
            provider_catalog=(_descriptor(),),
        ).assess(
            scope=production,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=SAO_PAULO,
            operation=ProviderOperation.AUTHORIZE,
        )


def _nfse_signed_artifact() -> FiscalSignatureResult:
    return FiscalSignatureResult(
        signed_content=b"<NFSe>synthetic</NFSe>",
        signature=b"synthetic-signature",
        algorithm=SignatureAlgorithm.RSA_SHA256,
        certificate_reference_id="ref:synthetic/b4/certificate",
        certificate_fingerprint_sha256="b" * 64,
        signed_at=NOW,
        document_kind=FiscalDocumentKind.NFSE,
    )


def _nfse_authorize_request() -> ProviderRequest:
    return ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=SAO_PAULO,
        operation=ProviderOperation.AUTHORIZE,
        payload=b"<NFSe>synthetic</NFSe>",
        correlation_id="corr-b4-authorize",
        workload_id="workload-b4",
        signed_artifact=_nfse_signed_artifact(),
    )


class _UnknownDeliveryExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        raise ProviderTransportError("synthetic unknown outcome", delivery_unknown=True)


def test_b4_nfse_unknown_authorize_outcome_requires_reconciliation_without_blind_retry() -> None:
    executor = _UnknownDeliveryExecutor()
    gateway = ResilientProviderGateway(
        executor=executor,
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0,
            max_delay_seconds=0,
            jitter_ratio=0,
        ),
        circuits=CircuitBreakerRegistry(
            policy=CircuitBreakerPolicy(
                failure_threshold=3,
                recovery_timeout_seconds=10,
            )
        ),
    )

    with pytest.raises(UnknownProviderOutcomeError) as exc_info:
        gateway.execute(_nfse_authorize_request(), provider_id=PROVIDER_A)

    assert executor.calls == 1
    assert exc_info.value.requires_reconciliation is True
