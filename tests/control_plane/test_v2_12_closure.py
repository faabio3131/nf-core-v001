from __future__ import annotations

import sqlite3
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from kordena_fiscal.compliance import (
    CapabilityReadinessService,
    FiscalActionCapability,
    FiscalCapabilityLevel,
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
    ProviderCredentialsUnavailableError,
    ProviderDescriptor,
    ProviderGatewayService,
    ProviderOperation,
    ProviderRegistry,
    ProviderRequest,
    ProviderResponseStatus,
    ProviderTimeoutPolicy,
    ProviderTransportError,
    SyntheticProviderTransport,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.resilience import (
    CircuitBreakerPolicy,
    CircuitBreakerRegistry,
    ResilientProviderGateway,
    RetryPolicy,
    UnknownProviderOutcomeError,
)
from kordena_fiscal.signing import (
    CertificateUnavailableError,
    CryptographyFiscalDocumentSigner,
    FiscalSignatureRequest,
    FiscalSignatureResult,
)
from kordena_fiscal.vault import (
    EphemeralCertificateMaterial,
    EphemeralCscMaterial,
    EphemeralProviderCredentialsMaterial,
    InMemorySyntheticFiscalSecretVault,
    SecretResolutionService,
)

HOST = "fm.closure"
TENANT = "tenant-closure"
UNIT = "unit-closure"
PROVIDER = "provider-closure"
NFSE_PROVIDER = "provider-nfse-city"
NOW = datetime(2026, 9, 13, 14, 0, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
SAO_PAULO = BrazilianJurisdiction("SP", "3550308")
CERT_REF = "ref:fm-fiscal/tenant-closure/unit-closure/hml-certificate"
CREDENTIAL_REF = "ref:fm-fiscal/tenant-closure/unit-closure/hml-provider-credentials"
NFSE_CREDENTIAL_REF = (
    "ref:fm-fiscal/tenant-closure/unit-closure/hml-nfse-provider-credentials"
)
NFSE_CREDENTIAL_REF = (
    "ref:fm-fiscal/tenant-closure/unit-closure/hml-nfse-provider-credentials"
)
CSC_REF = "ref:fm-fiscal/tenant-closure/unit-closure/hml-csc"
PFX_PASSWORD = b"closure-synthetic-only"
CREDENTIAL_BYTES = b"CLOSURE-SYNTHETIC-CREDENTIAL"
NFSE_CREDENTIAL_BYTES = b"CLOSURE-SYNTHETIC-NFSE-CREDENTIAL"
CSC_BYTES = b"CLOSURE-SYNTHETIC-CSC"
TIMEOUT = ProviderTimeoutPolicy(connect_seconds=1.0, read_seconds=2.0)


class _FixedDateClock:
    def now(self) -> datetime:
        return NOW


class _MonotonicClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value


class _Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


class _Jitter:
    def value(self) -> float:
        return 0.5


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-12-closure-global",
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
        actor_id="v2-12-closure-tenant",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
            }
        ),
        tenant_ids=frozenset({TENANT}),
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-12-closure.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


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
        correlation_id="corr-v2-12-closure",
    )


def _onboard(
    database: SqliteFiscalDatabase,
) -> tuple[SecretReference, SecretReference, SecretReference, SecretReference]:
    service = DurableControlPlaneService(database)
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id=TENANT,
        legal_name="Synthetic V2-12 Closure Tenant Ltda",
        correlation_id="corr-v2-12-org",
    )
    service.onboard_unit(
        actor=_tenant_admin(),
        registration=FiscalUnitRegistration(
            tenant_id=TENANT,
            unit_id=UNIT,
            display_name="Synthetic V2-12 Closure Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-v2-12-unit",
    )
    certificate = SecretReference(
        reference_id=CERT_REF,
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    credentials = SecretReference(
        reference_id=CREDENTIAL_REF,
        kind=SecretReferenceKind.CREDENTIALS,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=PROVIDER,
    )
    nfse_credentials = SecretReference(
        reference_id=NFSE_CREDENTIAL_REF,
        kind=SecretReferenceKind.CREDENTIALS,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=NFSE_PROVIDER,
    )
    csc = SecretReference(
        reference_id=CSC_REF,
        kind=SecretReferenceKind.CSC,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=PROVIDER,
    )
    for reference in (certificate, credentials, nfse_credentials, csc):
        service.bind_secret_reference(
            actor=_tenant_admin(),
            reference=reference,
            correlation_id=f"corr-v2-12-{reference.kind.value}",
        )
    return certificate, credentials, nfse_credentials, csc


def _synthetic_pkcs12() -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "FM Fiscal V2-12 Closure Synthetic")]
    )
    naive_now = NOW.replace(tzinfo=None)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(naive_now - timedelta(minutes=1))
        .not_valid_after(naive_now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"v2-12-closure-synthetic",
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(PFX_PASSWORD),
    )


def _vault(
    certificate: SecretReference,
    credentials: SecretReference,
    nfse_credentials: SecretReference,
    csc: SecretReference,
    *,
    pkcs12_bytes: bytes,
) -> InMemorySyntheticFiscalSecretVault:
    vault = InMemorySyntheticFiscalSecretVault()
    vault.register(
        host_namespace=HOST,
        reference=certificate,
        material=EphemeralCertificateMaterial(
            reference_id=CERT_REF,
            pkcs12_bytes=pkcs12_bytes,
            password=PFX_PASSWORD,
        ),
    )
    vault.register(
        host_namespace=HOST,
        reference=credentials,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=CREDENTIAL_REF,
            credential_bytes=CREDENTIAL_BYTES,
        ),
        provider_id=PROVIDER,
    )
    vault.register(
        host_namespace=HOST,
        reference=nfse_credentials,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=NFSE_CREDENTIAL_REF,
            credential_bytes=NFSE_CREDENTIAL_BYTES,
        ),
        provider_id=NFSE_PROVIDER,
    )
    vault.register(
        host_namespace=HOST,
        reference=csc,
        material=EphemeralCscMaterial(reference_id=CSC_REF, code=CSC_BYTES),
        provider_id=PROVIDER,
    )
    return vault


def _readiness() -> CapabilityReadinessService:
    common = {
        "version": 1,
        "environment": FiscalEnvironment.HOMOLOGATION,
        "capability_level": FiscalCapabilityLevel.HOMOLOGATION_READY,
        "validation_mode": TechnicalValidationMode.STRICT_REJECTION,
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "source_normative": "synthetic V2-12 closure evidence",
    }
    rules = (
        JurisdictionCapabilityRule(
            rule_id="v2-12-closure-nfe",
            state_code="SP",
            document_kind=FiscalDocumentKind.NFE,
            capabilities=frozenset(
                {FiscalActionCapability.ISSUE, FiscalActionCapability.QUERY}
            ),
            **common,
        ),
        JurisdictionCapabilityRule(
            rule_id="v2-12-closure-nfce",
            state_code="SP",
            document_kind=FiscalDocumentKind.NFCE,
            capabilities=frozenset(
                {FiscalActionCapability.ISSUE, FiscalActionCapability.QUERY}
            ),
            **common,
        ),
        JurisdictionCapabilityRule(
            rule_id="v2-12-closure-nfse-sao-paulo",
            state_code="SP",
            municipality_ibge_code="3550308",
            document_kind=FiscalDocumentKind.NFSE,
            capabilities=frozenset({FiscalActionCapability.QUERY}),
            **common,
        ),
    )
    return CapabilityReadinessService(JurisdictionCapabilityMatrix(rules))


def _signer(
    database: SqliteFiscalDatabase,
    vault: InMemorySyntheticFiscalSecretVault,
) -> CryptographyFiscalDocumentSigner:
    return CryptographyFiscalDocumentSigner(
        secret_resolution=SecretResolutionService(
            unit_of_work_factory=database,
            vault=vault,
        ),
        clock=_FixedDateClock(),
    )


def _sign(
    signer: CryptographyFiscalDocumentSigner,
    reference: SecretReference,
    kind: FiscalDocumentKind,
) -> tuple[FiscalSignatureRequest, FiscalSignatureResult]:
    request = FiscalSignatureRequest(
        scope=_scope(),
        document_kind=kind,
        canonical_content=f"<Synthetic-{kind.value}/>".encode(),
        certificate_reference=reference,
        workload_id="v2-12-closure-signer",
    )
    result = signer.sign(request)
    signer.verify(request, result)
    return request, result


def _provider_service(
    database: SqliteFiscalDatabase,
    vault: InMemorySyntheticFiscalSecretVault,
    transport: SyntheticProviderTransport,
) -> ProviderGatewayService:
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    descriptor = ProviderDescriptor(
        provider_id=PROVIDER,
        document_kinds=frozenset({FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE}),
        jurisdictions=(SP,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset({ProviderOperation.AUTHORIZE, ProviderOperation.QUERY}),
        csc_required_for=frozenset(
            {(FiscalDocumentKind.NFCE, ProviderOperation.AUTHORIZE)}
        ),
    )
    adapter = ConfiguredProviderAdapter(
        descriptor=descriptor,
        secret_resolution=resolution,
        transport=transport,
        timeout_policy=TIMEOUT,
    )
    return ProviderGatewayService(
        registry=ProviderRegistry((adapter,)),
        readiness=_readiness(),
        clock=_FixedDateClock(),
    )


def _resilient(executor: ProviderGatewayService) -> ResilientProviderGateway:
    return ResilientProviderGateway(
        executor=executor,
        retry_policy=RetryPolicy(
            max_attempts=2,
            base_delay_seconds=0,
            max_delay_seconds=0,
            jitter_ratio=0,
        ),
        circuits=CircuitBreakerRegistry(
            policy=CircuitBreakerPolicy(
                failure_threshold=2,
                recovery_timeout_seconds=10,
            ),
            clock=_MonotonicClock(),
        ),
        sleeper=_Sleeper(),
        jitter=_Jitter(),
    )


def _authorize_request(
    kind: FiscalDocumentKind,
    signed_artifact: FiscalSignatureResult,
) -> ProviderRequest:
    return ProviderRequest(
        scope=_scope(),
        document_kind=kind,
        jurisdiction=SP,
        operation=ProviderOperation.AUTHORIZE,
        payload=signed_artifact.signed_content,
        correlation_id="corr-v2-12-authorize",
        workload_id="v2-12-provider-runtime",
        signed_artifact=signed_artifact,
    )


def test_v2_12_end_to_end_nfe_signs_routes_and_normalizes_without_secret_leak(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    pfx = _synthetic_pkcs12()
    vault = _vault(certificate, credentials, nfse_credentials, csc, pkcs12_bytes=pfx)
    signer = _signer(database, vault)
    _, signed = _sign(signer, certificate, FiscalDocumentKind.NFE)
    transport = SyntheticProviderTransport()
    gateway = _resilient(_provider_service(database, vault, transport))

    response = gateway.execute(
        _authorize_request(FiscalDocumentKind.NFE, signed),
        provider_id=PROVIDER,
    )

    assert response.status is ProviderResponseStatus.ACCEPTED
    assert response.provider_id == PROVIDER
    assert len(transport.observations) == 1
    observation = transport.observations[0]
    assert observation.credentials_reference_id == CREDENTIAL_REF
    assert observation.csc_reference_id is None
    assert observation.connect_timeout_seconds == 1.0
    assert observation.read_timeout_seconds == 2.0
    rendered = repr(observation)
    assert CREDENTIAL_BYTES.decode() not in rendered
    assert PFX_PASSWORD.decode() not in rendered


def test_v2_12_end_to_end_nfce_requires_provider_scoped_csc(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    vault = _vault(
        certificate,
        credentials,
        nfse_credentials,
        csc,
        pkcs12_bytes=_synthetic_pkcs12(),
    )
    _, signed = _sign(_signer(database, vault), certificate, FiscalDocumentKind.NFCE)
    transport = SyntheticProviderTransport()
    gateway = _resilient(_provider_service(database, vault, transport))

    response = gateway.execute(
        _authorize_request(FiscalDocumentKind.NFCE, signed),
        provider_id=PROVIDER,
    )

    assert response.status is ProviderResponseStatus.ACCEPTED
    assert transport.observations[0].credentials_reference_id == CREDENTIAL_REF
    assert transport.observations[0].csc_reference_id == CSC_REF


def test_v2_12_unknown_authorization_outcome_requires_reconciliation_not_retry(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    vault = _vault(
        certificate,
        credentials,
        nfse_credentials,
        csc,
        pkcs12_bytes=_synthetic_pkcs12(),
    )
    _, signed = _sign(_signer(database, vault), certificate, FiscalDocumentKind.NFE)
    transport = SyntheticProviderTransport()
    transport.queue_error(ProviderTransportError("ambiguous delivery", delivery_unknown=True))
    gateway = _resilient(_provider_service(database, vault, transport))

    with pytest.raises(UnknownProviderOutcomeError, match="reconciliation"):
        gateway.execute(
            _authorize_request(FiscalDocumentKind.NFE, signed),
            provider_id=PROVIDER,
        )

    assert len(transport.observations) == 1


def test_v2_12_provider_credentials_are_partitioned_and_never_fall_back(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    vault = _vault(
        certificate,
        credentials,
        nfse_credentials,
        csc,
        pkcs12_bytes=_synthetic_pkcs12(),
    )
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    transport = SyntheticProviderTransport()
    adapter = ConfiguredProviderAdapter(
        descriptor=ProviderDescriptor(
            provider_id="provider-without-slot",
            document_kinds=frozenset({FiscalDocumentKind.NFE}),
            jurisdictions=(SP,),
            environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
            operations=frozenset({ProviderOperation.QUERY}),
        ),
        secret_resolution=resolution,
        transport=transport,
        timeout_policy=TIMEOUT,
    )
    service = ProviderGatewayService(
        registry=ProviderRegistry((adapter,)),
        readiness=_readiness(),
        clock=_FixedDateClock(),
    )
    request = ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        operation=ProviderOperation.QUERY,
        payload=b"query",
        correlation_id="corr-provider-isolation",
        workload_id="v2-12-provider-isolation",
    )

    with pytest.raises(ProviderCredentialsUnavailableError, match="unavailable"):
        service.execute(request, provider_id="provider-without-slot")
    assert transport.observations == []


def test_v2_12_nfse_remains_municipality_and_provider_specific(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    vault = _vault(
        certificate,
        credentials,
        nfse_credentials,
        csc,
        pkcs12_bytes=_synthetic_pkcs12(),
    )
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    transport = SyntheticProviderTransport()
    adapter = ConfiguredProviderAdapter(
        descriptor=ProviderDescriptor(
            provider_id=NFSE_PROVIDER,
            document_kinds=frozenset({FiscalDocumentKind.NFSE}),
            jurisdictions=(SAO_PAULO,),
            environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
            operations=frozenset({ProviderOperation.QUERY}),
        ),
        secret_resolution=resolution,
        transport=transport,
        timeout_policy=TIMEOUT,
    )
    service = ProviderGatewayService(
        registry=ProviderRegistry((adapter,)),
        readiness=_readiness(),
        clock=_FixedDateClock(),
    )
    request = ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=SAO_PAULO,
        operation=ProviderOperation.QUERY,
        payload=b"nfse-query",
        correlation_id="corr-nfse-city",
        workload_id="v2-12-nfse-runtime",
    )

    response = _resilient(service).execute(request, provider_id=NFSE_PROVIDER)

    assert response.status is ProviderResponseStatus.ACCEPTED
    assert transport.observations[0].credentials_reference_id == NFSE_CREDENTIAL_REF
    assert transport.observations[0].csc_reference_id is None


def test_v2_12_restart_preserves_references_but_not_runtime_secret_material(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    pfx = _synthetic_pkcs12()
    vault = _vault(certificate, credentials, nfse_credentials, csc, pkcs12_bytes=pfx)
    signer = _signer(database, vault)
    _sign(signer, certificate, FiscalDocumentKind.NFE)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    empty_vault = InMemorySyntheticFiscalSecretVault()
    restarted_signer = _signer(restarted, empty_vault)
    request = FiscalSignatureRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        canonical_content=b"<RestartSynthetic/>",
        certificate_reference=certificate,
        workload_id="v2-12-restart",
    )

    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        restarted_signer.sign(request)

    with restarted.unit_of_work() as uow:
        persisted = uow.control_plane.get_secret_reference(
            TENANT,
            UNIT,
            FiscalEnvironment.HOMOLOGATION,
            SecretReferenceKind.CERTIFICATE,
        )
    assert persisted == certificate


def test_v2_12_sqlite_contains_references_but_no_runtime_secret_material(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, credentials, nfse_credentials, csc = _onboard(database)
    pfx = _synthetic_pkcs12()
    vault = _vault(certificate, credentials, nfse_credentials, csc, pkcs12_bytes=pfx)
    _, signed = _sign(_signer(database, vault), certificate, FiscalDocumentKind.NFE)
    transport = SyntheticProviderTransport()
    _resilient(_provider_service(database, vault, transport)).execute(
        _authorize_request(FiscalDocumentKind.NFE, signed),
        provider_id=PROVIDER,
    )

    with sqlite3.connect(database.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(fm_control_plane_secret_references)"
            ).fetchall()
        }
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
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
    assert not any(
        token in name.lower()
        for name in tables
        for token in ("vault", "private_key", "provider_secret", "circuit_breaker")
    )

    database_bytes = database.path.read_bytes()
    assert PFX_PASSWORD not in database_bytes
    assert CREDENTIAL_BYTES not in database_bytes
    assert NFSE_CREDENTIAL_BYTES not in database_bytes
    assert CSC_BYTES not in database_bytes
    assert pfx[:32] not in database_bytes


def test_v2_12_structural_secret_dependency_architecture_and_product_neutrality() -> None:
    root = Path(__file__).resolve().parents[2]
    src = root / "src" / "kordena_fiscal"

    secret_files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pfx", ".p12", ".pem", ".key"}
    ]
    assert secret_files == []

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in src.rglob("*.py")
    )
    assert "BEGIN " + "PRIVATE KEY" not in source_text
    assert "BEGIN " + "CERTIFICATE" not in source_text

    domain_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (src / "domain").rglob("*.py")
    )
    for forbidden_import in (
        "kordena_fiscal.vault",
        "kordena_fiscal.gateway",
        "kordena_fiscal.signing",
        "kordena_fiscal.resilience",
        "kordena_fiscal.homologation",
        "cryptography",
    ):
        assert forbidden_import not in domain_text

    adapter_text = "\n".join(
        path.read_text(encoding="utf-8")
        for package in ("vault", "signing", "gateway", "resilience", "homologation")
        for path in (src / package).rglob("*.py")
    ).lower()
    for product_marker in ("fm.iron", "iron fit", "vendedor ia", "campaia"):
        assert product_marker not in adapter_text

    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    assert set(project["dependencies"]) == {
        "cryptography>=50,<51",
        "lxml>=5.3,<7",
        "google-cloud-secret-manager>=2.31,<3",
        "google-crc32c>=1.8,<2",
    }
