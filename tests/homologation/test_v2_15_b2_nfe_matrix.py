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
)
from kordena_fiscal.gateway import (
    ProviderDescriptor,
    ProviderOperation,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseStatus,
    ProviderTransportError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.resilience import (
    CircuitBreakerPolicy,
    CircuitBreakerRegistry,
    ResilientProviderGateway,
    RetryMode,
    RetryPolicy,
    UnknownProviderOutcomeError,
    retry_mode,
)
from kordena_fiscal.runtime.homologation_readiness import (
    DurableHomologationEnvironmentReadinessService,
)
from kordena_fiscal.signing import FiscalSignatureResult, SignatureAlgorithm

NOW = datetime(2026, 9, 13, 19, 20, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
MG = BrazilianJurisdiction("MG")
PROVIDER = "provider-nfe-synthetic"


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-b2-admin",
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
        host_namespace="fm.synthetic-b2",
        tenant_id="tenant-b2",
        unit_id="unit-b2",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-b2",
    )


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=PROVIDER,
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


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-b2-nfe.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    control = DurableControlPlaneService(database)
    control.onboard_organization(
        actor=_admin(),
        tenant_id="tenant-b2",
        legal_name="Synthetic B2 NF-e Tenant",
        correlation_id="corr-b2-org",
    )
    control.onboard_unit(
        actor=_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-b2",
            unit_id="unit-b2",
            display_name="Synthetic B2 NF-e Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-b2-unit",
    )
    for kind, provider_id, suffix in (
        (SecretReferenceKind.CERTIFICATE, None, "certificate"),
        (SecretReferenceKind.CREDENTIALS, PROVIDER, "credentials"),
    ):
        control.bind_secret_reference(
            actor=_admin(),
            reference=SecretReference(
                reference_id=f"ref:synthetic/b2/{suffix}",
                kind=kind,
                tenant_id="tenant-b2",
                unit_id="unit-b2",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=provider_id,
            ),
            correlation_id=f"corr-b2-{suffix}",
        )

    commercial = CommercialConfigurationService(database)
    commercial.set_runtime_policy(
        actor=_admin(),
        policy=ProviderRuntimePolicyConfig(
            policy_id="policy-nfe-b2",
            tenant_id="tenant-b2",
            unit_id="unit-b2",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER,
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
                binding_id=f"binding-nfe-{operation.value}-b2",
                tenant_id="tenant-b2",
                unit_id="unit-b2",
                environment=FiscalEnvironment.HOMOLOGATION,
                document_kind=FiscalDocumentKind.NFE,
                jurisdiction=SP,
                operation=ConfiguredFiscalOperation(operation.value),
                provider_id=PROVIDER,
            ),
        )
        requires_signer = operation is ProviderOperation.AUTHORIZE
        runtime_admin.set_homologation_evidence(
            actor=_admin(),
            record=HomologationEvidenceRecord(
                tenant_id="tenant-b2",
                unit_id="unit-b2",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=PROVIDER,
                document_kind=FiscalDocumentKind.NFE,
                jurisdiction=SP,
                operation=operation.value,
                provider_adapter_available=True,
                credentials_reference_configured=True,
                signer_capability=requires_signer,
                csc_reference_configured=False,
                transport_configured=True,
                resilience_certified=True,
                contract_tests_certified=True,
                jurisdiction_mapping=True,
                operation_supported=True,
                requires_signer=requires_signer,
                external_official=False,
                recorded_at=NOW,
            ),
        )
    return database


def test_b2_nfe_matrix_authorize_query_cancel_is_internally_certified_after_restart(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    service = DurableHomologationEnvironmentReadinessService(
        restarted,
        provider_catalog=(_descriptor(),),
    )

    assessments = {
        operation: service.assess(
            scope=_scope(),
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=operation,
        )
        for operation in (
            ProviderOperation.AUTHORIZE,
            ProviderOperation.QUERY,
            ProviderOperation.CANCEL,
        )
    }

    assert all(item.internally_ready for item in assessments.values())
    assert all(not item.officially_homologated for item in assessments.values())
    assert all(item.provider_id == PROVIDER for item in assessments.values())


def test_b2_nfe_matrix_never_falls_back_across_jurisdiction(tmp_path) -> None:
    database = _database(tmp_path)
    result = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_descriptor(),),
    ).assess(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=MG,
        operation=ProviderOperation.AUTHORIZE,
    )

    assert result.provider_id is None
    assert "provider_binding" in result.missing_configuration
    assert result.internally_ready is False


def _signed_artifact() -> FiscalSignatureResult:
    return FiscalSignatureResult(
        signed_content=b"<NFe Id='NFeSynthetic'>signed</NFe>",
        signature=b"synthetic-detached-signature",
        algorithm=SignatureAlgorithm.RSA_SHA256,
        certificate_reference_id="ref:synthetic/b2/certificate",
        certificate_fingerprint_sha256="a" * 64,
        signed_at=NOW,
        document_kind=FiscalDocumentKind.NFE,
    )


def _authorize_request() -> ProviderRequest:
    return ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
        payload=b"<NFe Id='NFeSynthetic'>signed</NFe>",
        correlation_id="corr-b2-authorize",
        workload_id="workload-b2",
        signed_artifact=_signed_artifact(),
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
        raise ProviderTransportError(
            "synthetic unknown delivery",
            delivery_unknown=True,
        )


class _RejectingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        assert provider_id == PROVIDER
        return ProviderResponse(
            provider_id=PROVIDER,
            operation=request.operation,
            status=ProviderResponseStatus.REJECTED,
            correlation_id=request.correlation_id,
            code="synthetic-rejection",
            message="synthetic fiscal rejection",
        )


def _resilient(executor) -> ResilientProviderGateway:
    return ResilientProviderGateway(
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


def test_b2_nfe_unknown_authorization_outcome_is_not_blindly_retried() -> None:
    executor = _UnknownDeliveryExecutor()
    with pytest.raises(UnknownProviderOutcomeError) as exc_info:
        _resilient(executor).execute(_authorize_request(), provider_id=PROVIDER)

    assert executor.calls == 1
    assert exc_info.value.requires_reconciliation is True
    assert retry_mode(ProviderOperation.AUTHORIZE) is RetryMode.CONDITIONAL_RETRY
    assert retry_mode(ProviderOperation.QUERY) is RetryMode.SAFE_RETRY


def test_b2_nfe_fiscal_rejection_is_normalized_without_retry() -> None:
    executor = _RejectingExecutor()
    response = _resilient(executor).execute(_authorize_request(), provider_id=PROVIDER)

    assert executor.calls == 1
    assert response.status is ProviderResponseStatus.REJECTED
    assert response.code == "synthetic-rejection"
    assert response.provider_id == PROVIDER
