from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kordena_fiscal.compliance import (
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
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
)
from kordena_fiscal.gateway import (
    ConfiguredProviderAdapter,
    CscUnavailableError,
    ProviderCredentialsUnavailableError,
    ProviderDescriptor,
    ProviderGatewayService,
    ProviderOperation,
    ProviderRegistry,
    ProviderRequest,
    ProviderResponseStatus,
    ProviderTimeoutPolicy,
    ProviderTransportResponse,
    SyntheticProviderTransport,
    UnsupportedProviderError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.signing import FiscalSignatureResult, SignatureAlgorithm
from kordena_fiscal.vault import (
    EphemeralCscMaterial,
    EphemeralProviderCredentialsMaterial,
    InMemorySyntheticFiscalSecretVault,
    SecretResolutionService,
)

HOST = "fm.kordena"
TENANT = "tenant-provider"
UNIT = "unit-provider"
JURISDICTION = BrazilianJurisdiction("SP")
NOW = datetime(2026, 9, 13, 13, 0, tzinfo=UTC)
TIMEOUT = ProviderTimeoutPolicy(connect_seconds=1.0, read_seconds=2.0)
CREDENTIAL_REF = "ref:fm-fiscal/tenant-provider/unit-provider/hml-provider-credentials"
CSC_REF = "ref:fm-fiscal/tenant-provider/unit-provider/hml-csc"


class _Clock:
    def now(self) -> datetime:
        return NOW


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="provider-global-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
            }
        ),
        global_scope=True,
    )


def _tenant_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="provider-tenant-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
            }
        ),
        tenant_ids=frozenset({TENANT}),
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "provider-runtime.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _onboard(
    database: SqliteFiscalDatabase,
    *,
    provider_id: str = "synthetic-sp",
) -> tuple[SecretReference, SecretReference]:
    control = DurableControlPlaneService(database)
    control.onboard_organization(
        actor=_global_admin(),
        tenant_id=TENANT,
        legal_name="Synthetic Provider Tenant Ltda",
        correlation_id="corr-provider-org",
    )
    control.onboard_unit(
        actor=_tenant_admin(),
        registration=FiscalUnitRegistration(
            tenant_id=TENANT,
            unit_id=UNIT,
            display_name="Synthetic Provider Unit",
            enabled_environments=frozenset(
                {FiscalEnvironment.HOMOLOGATION, FiscalEnvironment.PRODUCTION}
            ),
        ),
        correlation_id="corr-provider-unit",
    )
    credentials = SecretReference(
        reference_id=CREDENTIAL_REF,
        kind=SecretReferenceKind.CREDENTIALS,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=provider_id,
    )
    csc = SecretReference(
        reference_id=CSC_REF,
        kind=SecretReferenceKind.CSC,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=provider_id,
    )
    for reference in (credentials, csc):
        control.bind_secret_reference(
            actor=_tenant_admin(),
            reference=reference,
            correlation_id=f"corr-provider-{reference.kind.value}",
        )
    return credentials, csc


def _vault(
    credentials: SecretReference,
    csc: SecretReference,
    *,
    provider_id: str,
) -> InMemorySyntheticFiscalSecretVault:
    vault = InMemorySyntheticFiscalSecretVault()
    vault.register(
        host_namespace=HOST,
        reference=credentials,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=CREDENTIAL_REF,
            credential_bytes=b"SYNTHETIC-PROVIDER-CREDENTIAL-NOT-REAL",
        ),
        provider_id=provider_id,
    )
    vault.register(
        host_namespace=HOST,
        reference=csc,
        material=EphemeralCscMaterial(
            reference_id=CSC_REF,
            code=b"SYNTHETIC-CSC-NOT-REAL",
        ),
        provider_id=provider_id,
    )
    return vault


def _readiness() -> CapabilityReadinessService:
    rules = tuple(
        JurisdictionCapabilityRule(
            rule_id=f"sp-{kind.value}-hml-provider-tests",
            version=1,
            state_code="SP",
            document_kind=kind,
            environment=FiscalEnvironment.HOMOLOGATION,
            capability_level=FiscalCapabilityLevel.HOMOLOGATION_READY,
            validation_mode=TechnicalValidationMode.STRICT_REJECTION,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            source_normative="synthetic contract evidence",
            capabilities=frozenset(
                {
                    FiscalActionCapability.ISSUE,
                    FiscalActionCapability.QUERY,
                    FiscalActionCapability.CANCEL,
                    FiscalActionCapability.INUTILIZE,
                }
            ),
        )
        for kind in (FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE)
    )
    return CapabilityReadinessService(JurisdictionCapabilityMatrix(rules))


def _scope(
    *,
    tenant: str = TENANT,
    unit: str = UNIT,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace=HOST,
        tenant_id=tenant,
        unit_id=unit,
        environment=environment,
        correlation_id="corr-provider-request",
    )


def _signature(kind: FiscalDocumentKind) -> FiscalSignatureResult:
    return FiscalSignatureResult(
        signed_content=b"<synthetic-signed/>",
        signature=b"synthetic-signature",
        algorithm=SignatureAlgorithm.RSA_SHA256,
        certificate_reference_id="ref:fm-fiscal/synthetic/certificate",
        certificate_fingerprint_sha256="a" * 64,
        signed_at=NOW,
        document_kind=kind,
    )


def _request(
    *,
    kind: FiscalDocumentKind = FiscalDocumentKind.NFE,
    scope: ExecutionScope | None = None,
    operation: ProviderOperation = ProviderOperation.AUTHORIZE,
    jurisdiction: BrazilianJurisdiction = JURISDICTION,
) -> ProviderRequest:
    return ProviderRequest(
        scope=scope or _scope(),
        document_kind=kind,
        jurisdiction=jurisdiction,
        operation=operation,
        payload=b"<synthetic-provider-payload/>",
        correlation_id="corr-provider-request",
        workload_id="provider-runtime",
        signed_artifact=_signature(kind) if operation is ProviderOperation.AUTHORIZE else None,
    )


def _descriptor(provider_id: str = "synthetic-sp") -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        document_kinds=frozenset({FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE}),
        jurisdictions=(JURISDICTION,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset(
            {
                ProviderOperation.AUTHORIZE,
                ProviderOperation.QUERY,
                ProviderOperation.CANCEL,
                ProviderOperation.INUTILIZE,
            }
        ),
        csc_required_for=frozenset(
            {(FiscalDocumentKind.NFCE, ProviderOperation.AUTHORIZE)}
        ),
    )


def _adapter(
    *,
    descriptor: ProviderDescriptor,
    resolution: SecretResolutionService,
    transport: SyntheticProviderTransport,
) -> ConfiguredProviderAdapter:
    return ConfiguredProviderAdapter(
        descriptor=descriptor,
        secret_resolution=resolution,
        transport=transport,
        timeout_policy=TIMEOUT,
    )


def _runtime(tmp_path, *, provider_id: str = "synthetic-sp"):
    database = _database(tmp_path)
    credentials, csc = _onboard(database, provider_id=provider_id)
    vault = _vault(credentials, csc, provider_id=provider_id)
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    transport = SyntheticProviderTransport()
    adapter = _adapter(
        descriptor=_descriptor(provider_id),
        resolution=resolution,
        transport=transport,
    )
    service = ProviderGatewayService(
        registry=ProviderRegistry((adapter,)),
        readiness=_readiness(),
        clock=_Clock(),
    )
    return database, vault, transport, service, adapter


def test_routes_supported_nfe_and_normalizes_response(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    transport.queue_response(
        ProviderTransportResponse(
            status=ProviderResponseStatus.ACCEPTED,
            provider_request_id="req-1",
            external_reference="protocol-1",
        )
    )

    response = service.execute(_request(), provider_id="synthetic-sp")

    assert response.provider_id == "synthetic-sp"
    assert response.status is ProviderResponseStatus.ACCEPTED
    assert response.external_reference == "protocol-1"
    observation = transport.observations[0]
    assert observation.credentials_reference_id == CREDENTIAL_REF
    assert observation.csc_reference_id is None
    assert observation.connect_timeout_seconds == 1.0
    assert observation.read_timeout_seconds == 2.0


def test_nfce_resolves_csc_only_when_descriptor_requires_it(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    response = service.execute(
        _request(kind=FiscalDocumentKind.NFCE),
        provider_id="synthetic-sp",
    )
    assert response.status is ProviderResponseStatus.ACCEPTED
    assert transport.observations[0].credentials_reference_id == CREDENTIAL_REF
    assert transport.observations[0].csc_reference_id == CSC_REF


def test_unknown_provider_fails_closed(tmp_path) -> None:
    _, _, _, service, _ = _runtime(tmp_path)
    with pytest.raises(UnsupportedProviderError, match="exactly one"):
        service.execute(_request(), provider_id="missing-provider")


def test_ambiguous_provider_resolution_never_selects_default(tmp_path) -> None:
    database = _database(tmp_path)
    credentials, csc = _onboard(database, provider_id="provider-a")
    resolution = SecretResolutionService(
        unit_of_work_factory=database,
        vault=_vault(credentials, csc, provider_id="provider-a"),
    )
    first = _adapter(
        descriptor=_descriptor("provider-a"),
        resolution=resolution,
        transport=SyntheticProviderTransport(),
    )
    second = _adapter(
        descriptor=_descriptor("provider-b"),
        resolution=resolution,
        transport=SyntheticProviderTransport(),
    )
    service = ProviderGatewayService(
        registry=ProviderRegistry((first, second)),
        readiness=_readiness(),
        clock=_Clock(),
    )
    with pytest.raises(UnsupportedProviderError, match="exactly one"):
        service.execute(_request())


def test_provider_a_credentials_never_fall_back_to_provider_b(tmp_path) -> None:
    database = _database(tmp_path)
    credentials, csc = _onboard(database, provider_id="provider-a")
    vault = _vault(credentials, csc, provider_id="provider-a")
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    transport_a = SyntheticProviderTransport()
    transport_b = SyntheticProviderTransport()
    first = _adapter(
        descriptor=_descriptor("provider-a"),
        resolution=resolution,
        transport=transport_a,
    )
    second = _adapter(
        descriptor=_descriptor("provider-b"),
        resolution=resolution,
        transport=transport_b,
    )
    service = ProviderGatewayService(
        registry=ProviderRegistry((first, second)),
        readiness=_readiness(),
        clock=_Clock(),
    )

    response = service.execute(_request(), provider_id="provider-a")
    assert response.status is ProviderResponseStatus.ACCEPTED
    with pytest.raises(ProviderCredentialsUnavailableError, match="unavailable"):
        service.execute(_request(), provider_id="provider-b")
    assert len(transport_a.observations) == 1
    assert transport_b.observations == []


def test_unsupported_jurisdiction_fails_before_transport(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    with pytest.raises(JurisdictionCapabilityError, match="no explicit"):
        service.execute(
            _request(jurisdiction=BrazilianJurisdiction("RJ")),
            provider_id="synthetic-sp",
        )
    assert transport.observations == []


def test_cross_tenant_and_cross_unit_credentials_fail_closed(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    with pytest.raises(ProviderCredentialsUnavailableError, match="unavailable"):
        service.execute(
            _request(scope=_scope(tenant="tenant-other")),
            provider_id="synthetic-sp",
        )
    with pytest.raises(ProviderCredentialsUnavailableError, match="unavailable"):
        service.execute(
            _request(scope=_scope(unit="unit-other")),
            provider_id="synthetic-sp",
        )
    assert transport.observations == []


def test_cross_environment_never_reuses_homologation_credentials(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    with pytest.raises(JurisdictionCapabilityError, match="no explicit"):
        service.execute(
            _request(scope=_scope(environment=FiscalEnvironment.PRODUCTION)),
            provider_id="synthetic-sp",
        )
    assert transport.observations == []


def test_missing_credentials_cannot_be_replaced_by_csc(tmp_path) -> None:
    database = _database(tmp_path)
    _, csc = _onboard(database)
    empty = InMemorySyntheticFiscalSecretVault()
    empty.register(
        host_namespace=HOST,
        reference=csc,
        material=EphemeralCscMaterial(reference_id=CSC_REF, code=b"SYNTHETIC-CSC"),
        provider_id="synthetic-sp",
    )
    adapter = _adapter(
        descriptor=_descriptor(),
        resolution=SecretResolutionService(unit_of_work_factory=database, vault=empty),
        transport=SyntheticProviderTransport(),
    )
    with pytest.raises(ProviderCredentialsUnavailableError, match="unavailable"):
        adapter.execute(_request())


def test_missing_csc_fails_closed_for_nfce(tmp_path) -> None:
    database = _database(tmp_path)
    credentials, _ = _onboard(database)
    vault = InMemorySyntheticFiscalSecretVault()
    vault.register(
        host_namespace=HOST,
        reference=credentials,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=CREDENTIAL_REF,
            credential_bytes=b"SYNTHETIC-CREDENTIAL",
        ),
        provider_id="synthetic-sp",
    )
    adapter = _adapter(
        descriptor=_descriptor(),
        resolution=SecretResolutionService(unit_of_work_factory=database, vault=vault),
        transport=SyntheticProviderTransport(),
    )
    with pytest.raises(CscUnavailableError, match="unavailable"):
        adapter.execute(_request(kind=FiscalDocumentKind.NFCE))


def test_request_and_transport_observation_never_expose_secret_material(tmp_path) -> None:
    _, _, transport, service, _ = _runtime(tmp_path)
    request = _request(kind=FiscalDocumentKind.NFCE)
    service.execute(request, provider_id="synthetic-sp")
    assert "SYNTHETIC" not in repr(request)
    observation = transport.observations[0]
    assert "CREDENTIAL-NOT-REAL" not in repr(observation)
    assert "CSC-NOT-REAL" not in repr(observation)
    assert observation.credentials_reference_id.startswith("ref:")
    assert observation.csc_reference_id == CSC_REF


def test_registry_uses_jurisdiction_and_capability_not_host_product_name(tmp_path) -> None:
    _, _, _, _, adapter = _runtime(tmp_path)
    registry = ProviderRegistry((adapter,))
    selected = registry.resolve(
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=JURISDICTION,
        environment=FiscalEnvironment.HOMOLOGATION,
        operation=ProviderOperation.QUERY,
        provider_id="synthetic-sp",
    )
    assert selected.descriptor.provider_id == "synthetic-sp"
    assert not hasattr(selected.descriptor, "product_name")
    assert not hasattr(selected.descriptor, "host_namespace")


def test_synthetic_transport_performs_no_network_and_persists_no_secret(tmp_path) -> None:
    database, _, transport, service, _ = _runtime(tmp_path)
    service.execute(
        _request(kind=FiscalDocumentKind.NFCE),
        provider_id="synthetic-sp",
    )
    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    assert len(transport.observations) == 1
    assert all(
        token not in repr(transport.observations[0])
        for token in (
            "SYNTHETIC-PROVIDER-CREDENTIAL-NOT-REAL",
            "SYNTHETIC-CSC-NOT-REAL",
        )
    )
