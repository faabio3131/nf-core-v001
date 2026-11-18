"""Real Cajamar startup opt-in, pinned inputs and same canonical fiscal UoW.

Fixture WSDL/XSD are synthetic and never enable municipal transmission.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.api import build_entrypoint_fiscal_handler_factory
from kordena_fiscal.runtime.cajamar_environment import (
    CajamarReviewedStartup,
    build_cajamar_port_builder_from_environ,
)
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.runtime.config import RuntimeConfigurationError, RuntimeSettings
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.xml.schema import (
    SchemaIntegrityError,
    SchemaResource,
    SchemaSet,
)


def _fixture(tmp_path: Path) -> Path:
    wsdl = b'<definitions name="FixtureOnly" />'
    schema = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        b'<xs:element name="EnviaLoteRps" type="xs:anyType"/>'
        b'<xs:element name="ConsultaLoteRps" type="xs:anyType"/>'
        b'<xs:element name="CancelaNfse" type="xs:anyType"/>'
        b'<xs:element name="ConsultaLoteRpsResposta" type="xs:anyType"/>'
        b'<xs:element name="CancelaNfseResposta" type="xs:anyType"/>'
        b'</xs:schema>'
    )
    (tmp_path / "test.wsdl").write_bytes(wsdl)
    (tmp_path / "test.xsd").write_bytes(schema)
    package = SchemaSet(
        version="geisweb-reviewed", root_schema="test.xsd",
        resources=(SchemaResource.from_bytes("test.xsd", schema),),
        source_uri="https://www.gerenciadecidades.com.br",
    )
    doc = {
        "mode": "reviewed-homologation",
        "endpoint": (
            "https://www.gerenciadecidades.com.br/homologacao/reforma/"
            "modelo/webservice/GeisWebServiceImpl.php"
        ),
        "namespace": "http://www.geisweb.com.br/",
        "wsdl_file": "test.wsdl",
        "wsdl_sha256": hashlib.sha256(wsdl).hexdigest(),
        "xsd_package_sha256": package.package_sha256,
        "method_actions": {
            method: "http://test.invalid/" + method
            for method in (
                "EnviaLoteRps", "ConsultaLoteRps", "ConsultaNfse", "CancelaNfse",
            )
        },
        "xsd_resources": {"test.xsd": hashlib.sha256(schema).hexdigest()},
        "xsd_roots": {
            method: "test.xsd"
            for method in (
                "EnviaLoteRps", "ConsultaLoteRps", "CancelaNfse",
                "ConsultaLoteRpsResposta", "CancelaNfseResposta",
            )
        },
        "signature_profile": "rsa-sha256-enveloped-document",
        "issuers": [{
            "tenant_id": "tenant-test", "unit_id": "unit-test",
            "issuer_cnpj": "11222333000181",
            "fiscal_profile_id": "issuer-review", "fiscal_profile_version": 1,
            "tax_regime": 1, "launch_type": "N", "geisweb_regime": "1",
            "service_city": "Cajamar",
        }],
    }
    file = tmp_path / "reviewed.json"
    file.write_text(json.dumps(doc), encoding="utf-8")
    return file


def test_cajamar_is_off_by_default_and_missing_vault_never_activates(
    tmp_path: Path,
) -> None:
    assert build_cajamar_port_builder_from_environ({}, vault=None) is None
    manifest = _fixture(tmp_path)
    with pytest.raises(RuntimeConfigurationError, match="vault"):
        build_cajamar_port_builder_from_environ(
            {"NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH": str(manifest)},
            vault=None,
        )


def test_reviewed_startup_creates_operational_ports_on_same_application(
    tmp_path: Path,
) -> None:
    manifest = _fixture(tmp_path)
    vault = EncryptedA1Vault(
        directory=tmp_path / "vault", master_key=b"a" * 32,
    )
    builder = build_cajamar_port_builder_from_environ(
        {"NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH": str(manifest)},
        vault=vault,
    )
    assert builder is not None
    db = SqliteFiscalDatabase(tmp_path / "fiscal.sqlite")
    db.initialize()
    application = FiscalApplicationService(db)
    handlers = build_runtime_fiscal_handler_factory(
        cajamar_port_builder=builder,
    )(application)
    assert {
        "issueFiscalDocument", "queryFiscalDocument",
        "cancelCajamarNfse", "reviewCajamarSubstitution",
    } <= set(handlers)
    # Nothing has been submitted and there is no issuer A1.
    assert not list((tmp_path / "vault").glob("*.a1.enc"))
    with pytest.raises(ValueError, match="Conflicting trusted Cajamar"):
        build_runtime_fiscal_handler_factory(
            cajamar_port_builder=builder, sp4_reviewed_municipalities={},
        )


def test_cajamar_refuses_unpinned_or_unsafe_config_without_network(
    tmp_path: Path,
) -> None:
    manifest = _fixture(tmp_path)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["wsdl_sha256"] = "f" * 64
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="WSDL digest"):
        CajamarReviewedStartup.load(str(manifest))
    doc["wsdl_sha256"] = hashlib.sha256(
        (tmp_path / "test.wsdl").read_bytes(),
    ).hexdigest()
    doc["xsd_resources"]["test.xsd"] = "1" * 64
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SchemaIntegrityError, match="digest mismatch"):
        CajamarReviewedStartup.load(str(manifest))
    doc["xsd_resources"]["test.xsd"] = hashlib.sha256(
        (tmp_path / "test.xsd").read_bytes(),
    ).hexdigest()
    doc["wsdl_file"] = "../outside.wsdl"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Unsafe"):
        CajamarReviewedStartup.load(str(manifest))
    doc["wsdl_file"] = "test.wsdl"
    doc["issuers"].append(dict(doc["issuers"][0]))
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Duplicate"):
        CajamarReviewedStartup.load(str(manifest))

def test_actual_uvicorn_entrypoint_factory_registers_cajamar_once(
    tmp_path: Path,
) -> None:
    manifest = _fixture(tmp_path)
    vault = EncryptedA1Vault(
        directory=tmp_path / "entrypoint-vault", master_key=b"x" * 32,
    )
    settings = RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://fake:fake@db/nfcore",
        "NFCORE_SECRET_BACKEND": "external",
    })
    env = {"NFCORE_CAJAMAR_GEISWEB_CONFIG_PATH": str(manifest)}
    factory = build_entrypoint_fiscal_handler_factory(settings, env, vault)
    assert factory is not None
    db = SqliteFiscalDatabase(tmp_path / "single-runtime.sqlite")
    db.initialize()
    same_application = FiscalApplicationService(db)
    configured = factory(same_application)
    assert "cancelCajamarNfse" in configured
    assert "reviewCajamarSubstitution" in configured
    assert "issueFiscalDocument" in configured
    assert "queryFiscalDocument" in configured

    disabled = build_entrypoint_fiscal_handler_factory(settings, {}, vault)
    assert disabled is not None
    assert "cancelCajamarNfse" not in disabled(same_application)

    dev = RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": "development",
    })
    with pytest.raises(RuntimeConfigurationError, match="staging/production"):
        build_entrypoint_fiscal_handler_factory(dev, env, vault)
    assert build_entrypoint_fiscal_handler_factory(dev, {}, vault) is None


def test_cajamar_real_cryptographic_ports_sign_verify_and_reject_tampering(
    tmp_path: Path,
) -> None:
    """Synthetic A1 only: real signature verification without fiscal network I/O."""
    manifest = _fixture(tmp_path)
    config = CajamarReviewedStartup.load(str(manifest))
    vault = EncryptedA1Vault(directory=tmp_path / "a1-vault", master_key=b"k" * 32)
    issuer = Cnpj("11222333000181")
    scope = ExecutionScope(
        "tenant-test", "unit-test", FiscalEnvironment.HOMOLOGATION,
        "crypto-fixture", "fm-nfcore",
    )
    password = b"synthetic-a1-only-no-real-client"
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Cajamar fixture"),
    ])
    encoded = issuer.value.encode("ascii")
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(identity).issuer_name(identity)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(
                ObjectIdentifier("2.16.76.1.3.3"),
                bytes([4, len(encoded)]) + encoded,
            ),
        ]), critical=False)
        .sign(private, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"synthetic-cajamar",
        key=private, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )
    vault.provision(
        scope=scope, issuer_cnpj=issuer.value,
        pkcs12_bytes=pfx, password=password,
    )
    db = SqliteFiscalDatabase(tmp_path / "signed-ports.sqlite")
    db.initialize()
    ports = config.build_ports(FiscalApplicationService(db), vault)
    unsigned = b"<CancelaNfse><CnpjCpf>11222333000181</CnpjCpf></CancelaNfse>"
    signed = ports.sign_cancel(scope, issuer, unsigned)
    assert b"SignatureValue" in signed
    ports.validate_signed_cancel(scope, issuer, signed)

    with pytest.raises(FiscalValidationError, match="modified"):
        ports.validate_signed_cancel(
            scope, issuer, signed.replace(b"11222333000181", b"11222333000182"),
        )
    with pytest.raises(FiscalValidationError, match="XMLDSig"):
        ports.validate_signed_cancel(scope, issuer, unsigned)

    # Another unit has no corresponding A1; no provider or signer fallback.
    other = ExecutionScope(
        scope.tenant_id, "another-unit", FiscalEnvironment.HOMOLOGATION,
        "scope-proof", "fm-nfcore",
    )
    with pytest.raises(FiscalValidationError):
        ports.sign_cancel(other, issuer, unsigned)

