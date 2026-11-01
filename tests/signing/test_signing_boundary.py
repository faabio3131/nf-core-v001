from __future__ import annotations

import inspect
import sqlite3
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.signing import (
    CertificateUnavailableError,
    CryptographyFiscalDocumentSigner,
    FiscalSignatureRequest,
    FiscalSignatureResult,
    InvalidCertificateMaterialError,
    SignatureAlgorithm,
    SignatureVerificationError,
    SignerUnavailableError,
    UnsupportedSignatureCapabilityError,
)
from kordena_fiscal.vault import (
    EphemeralCertificateMaterial,
    InMemorySyntheticFiscalSecretVault,
    SecretResolutionService,
)

HOST = "fm.kordena"
TENANT = "tenant-signer"
UNIT = "unit-signer"
CERT_REF = "ref:fm-fiscal/tenant-signer/unit-signer/hml-certificate"
NOW = datetime(2026, 9, 13, 13, 0, tzinfo=UTC)
CANONICAL_CONTENT = b"<SyntheticFiscalDocument Id='NFeSynthetic'>payload</SyntheticFiscalDocument>"
PFX_PASSWORD = b"synthetic-test-only"


class _FixedClock:
    def now(self) -> datetime:
        return NOW


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="signer-global-admin",
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
        actor_id="signer-tenant-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
            }
        ),
        tenant_ids=frozenset({TENANT}),
    )


def _database(tmp_path, name: str = "signer.sqlite3") -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _certificate_reference(
    *,
    tenant: str = TENANT,
    unit: str = UNIT,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    reference_id: str = CERT_REF,
) -> SecretReference:
    return SecretReference(
        reference_id=reference_id,
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id=tenant,
        unit_id=unit,
        environment=environment,
    )


def _onboard_and_bind(database: SqliteFiscalDatabase) -> SecretReference:
    service = DurableControlPlaneService(database)
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id=TENANT,
        legal_name="Synthetic Signer Tenant Ltda",
        correlation_id="corr-signer-org",
    )
    service.onboard_unit(
        actor=_tenant_admin(),
        registration=FiscalUnitRegistration(
            tenant_id=TENANT,
            unit_id=UNIT,
            display_name="Synthetic Signer Unit",
        ),
        correlation_id="corr-signer-unit",
    )
    reference = _certificate_reference()
    service.bind_secret_reference(
        actor=_tenant_admin(),
        reference=reference,
        correlation_id="corr-signer-certificate",
    )
    return reference


def _synthetic_pkcs12() -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "FM Fiscal Synthetic Signer Test")]
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
        name=b"fm-fiscal-synthetic",
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(PFX_PASSWORD),
    )


def _request(
    reference: SecretReference,
    *,
    host: str = HOST,
    tenant: str = TENANT,
    unit: str = UNIT,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    document_kind: FiscalDocumentKind = FiscalDocumentKind.NFE,
    content: bytes = CANONICAL_CONTENT,
) -> FiscalSignatureRequest:
    return FiscalSignatureRequest(
        scope=ExecutionScope(
            host_namespace=host,
            tenant_id=tenant,
            unit_id=unit,
            environment=environment,
            correlation_id="corr-sign-request",
        ),
        document_kind=document_kind,
        canonical_content=content,
        certificate_reference=reference,
        workload_id="fiscal-signer-runtime",
    )


def _signer(
    database: SqliteFiscalDatabase,
    reference: SecretReference,
    *,
    pkcs12_bytes: bytes | None = None,
    vault_available: bool = True,
    signer_available: bool = True,
) -> CryptographyFiscalDocumentSigner:
    vault = InMemorySyntheticFiscalSecretVault(available=vault_available)
    vault.register(
        host_namespace=HOST,
        reference=reference,
        material=EphemeralCertificateMaterial(
            reference_id=reference.reference_id,
            pkcs12_bytes=pkcs12_bytes if pkcs12_bytes is not None else _synthetic_pkcs12(),
            password=PFX_PASSWORD,
        ),
    )
    resolution = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    return CryptographyFiscalDocumentSigner(
        secret_resolution=resolution,
        clock=_FixedClock(),
        available=signer_available,
    )


def test_signs_and_verifies_canonical_nfe_content(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)
    request = _request(reference)

    result = signer.sign(request)
    signer.verify(request, result)

    assert result.signed_content == CANONICAL_CONTENT
    assert result.signature
    assert result.algorithm is SignatureAlgorithm.RSA_SHA256
    assert result.certificate_reference_id == CERT_REF
    assert len(result.certificate_fingerprint_sha256) == 64
    assert result.signed_at == NOW


def test_tampered_content_and_signature_are_detected(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)
    request = _request(reference)
    result = signer.sign(request)

    tampered_request = _request(reference, content=CANONICAL_CONTENT + b"tampered")
    with pytest.raises(SignatureVerificationError, match="signed content"):
        signer.verify(tampered_request, result)

    tampered_signature = FiscalSignatureResult(
        signed_content=result.signed_content,
        signature=result.signature[:-1] + bytes([result.signature[-1] ^ 1]),
        algorithm=result.algorithm,
        certificate_reference_id=result.certificate_reference_id,
        certificate_fingerprint_sha256=result.certificate_fingerprint_sha256,
        signed_at=result.signed_at,
        document_kind=result.document_kind,
    )
    with pytest.raises(SignatureVerificationError, match="verification failed"):
        signer.verify(request, tampered_signature)


def test_cross_tenant_and_cross_unit_certificate_use_is_blocked(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)

    other_tenant_reference = _certificate_reference(
        tenant="tenant-other",
        reference_id="ref:fm-fiscal/tenant-other/unit-signer/hml-certificate",
    )
    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        signer.sign(
            _request(
                other_tenant_reference,
                tenant="tenant-other",
            )
        )

    other_unit_reference = _certificate_reference(
        unit="unit-other",
        reference_id="ref:fm-fiscal/tenant-signer/unit-other/hml-certificate",
    )
    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        signer.sign(_request(other_unit_reference, unit="unit-other"))


def test_cross_environment_certificate_use_is_blocked(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)
    production_reference = _certificate_reference(
        environment=FiscalEnvironment.PRODUCTION,
        reference_id="ref:fm-fiscal/tenant-signer/unit-signer/prod-certificate",
    )

    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        signer.sign(
            _request(
                production_reference,
                environment=FiscalEnvironment.PRODUCTION,
            )
        )


def test_non_certificate_reference_cannot_enter_signer_boundary() -> None:
    csc_reference = SecretReference(
        reference_id="ref:fm-fiscal/tenant-signer/unit-signer/hml-csc",
        kind=SecretReferenceKind.CSC,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="synthetic-signing-provider",
    )

    with pytest.raises(FiscalValidationError, match="certificate"):
        _request(csc_reference)


def test_vault_and_signer_unavailability_fail_closed(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)

    vault_down = _signer(database, reference, vault_available=False)
    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        vault_down.sign(_request(reference))

    signer_down = _signer(database, reference, signer_available=False)
    with pytest.raises(SignerUnavailableError, match="unavailable"):
        signer_down.sign(_request(reference))


def test_invalid_pkcs12_material_is_rejected_without_secret_leak(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    invalid_marker = b"SUPERSECRET-INVALID-PKCS12"
    signer = _signer(database, reference, pkcs12_bytes=invalid_marker)

    with pytest.raises(InvalidCertificateMaterialError) as exc_info:
        signer.sign(_request(reference))

    assert "SUPERSECRET" not in str(exc_info.value)
    assert PFX_PASSWORD.decode() not in str(exc_info.value)


def test_nfse_is_not_falsely_treated_as_nfe_signature_profile(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)

    with pytest.raises(UnsupportedSignatureCapabilityError, match="nfse"):
        signer.sign(_request(reference, document_kind=FiscalDocumentKind.NFSE))


def test_signing_objects_do_not_render_canonical_or_secret_material(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)
    request = _request(reference)
    result = signer.sign(request)

    assert "SyntheticFiscalDocument" not in repr(request)
    assert "SyntheticFiscalDocument" not in repr(result)
    assert PFX_PASSWORD.decode() not in repr(request)
    assert PFX_PASSWORD.decode() not in repr(result)


def test_signing_adds_no_secret_columns_or_pfx_fixtures(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard_and_bind(database)

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
    assert not ({"secret", "password", "private_key", "pfx", "token", "material"} & columns)

    test_root = Path(__file__).resolve().parents[1]
    persisted_secret_files = [
        path
        for path in test_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pfx", ".p12", ".pem", ".key"}
    ]
    assert persisted_secret_files == []


def test_restart_preserves_reference_but_not_signing_material(tmp_path) -> None:
    database = _database(tmp_path)
    reference = _onboard_and_bind(database)
    signer = _signer(database, reference)
    signer.sign(_request(reference))

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    empty_vault = InMemorySyntheticFiscalSecretVault()
    restarted_signer = CryptographyFiscalDocumentSigner(
        secret_resolution=SecretResolutionService(
            unit_of_work_factory=restarted,
            vault=empty_vault,
        ),
        clock=_FixedClock(),
    )

    with pytest.raises(CertificateUnavailableError, match="unavailable"):
        restarted_signer.sign(_request(reference))


def test_signer_has_no_readiness_authority_or_persistence_port() -> None:
    constructor_parameters = set(
        inspect.signature(CryptographyFiscalDocumentSigner.__init__).parameters
    )
    result_fields = {item.name for item in fields(FiscalSignatureResult)}

    assert "readiness" not in constructor_parameters
    assert "unit_of_work_factory" not in constructor_parameters
    assert "readiness" not in result_fields
    assert "production_approved" not in result_fields
