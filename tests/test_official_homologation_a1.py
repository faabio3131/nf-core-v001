"""Certificate Vault, XMLDSig and homologation SOAP smoke tests without fiscal credentials."""
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from lxml import etree

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.nfe_sp_homologation import (
    NFE_NAMESPACE,
    SOAP12_NAMESPACE,
    _parse_xml,
    _soap_envelope,
)
from kordena_fiscal.signing.nfe_xmldsig import sign_nfe_envi_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.encrypted_a1 import A1VaultUnavailable, EncryptedA1Vault


@pytest.fixture
def test_a1():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NFCore Test")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(issuer)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(
                ObjectIdentifier("2.16.76.1.3.3"),
                bytes.fromhex("0c0e") + b"11222333000181",
            ),
        ]), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(key, hashes.SHA256())
    )
    data = pkcs12.serialize_key_and_certificates(
        name=b"nfcore-test", key=key, cert=certificate, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"test-pass"),
    )
    return data, b"test-pass", certificate


def _scope(tenant: str = "tenant-a") -> ExecutionScope:
    return ExecutionScope(
        tenant_id=tenant, unit_id="unit-1", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="homologation-smoke", host_namespace="fm-nfcore",
    )


def test_a1_vault_roundtrip_is_encrypted_and_tenant_isolated(tmp_path, test_a1):
    pfx, password, _ = test_a1
    vault = EncryptedA1Vault(directory=tmp_path, master_key=b"2" * 32)
    evidence = vault.provision(
        scope=_scope(), issuer_cnpj="11222333000181",
        pkcs12_bytes=pfx, password=password,
    )
    assert evidence.issuer_cnpj == "11222333000181"
    sealed = list(tmp_path.glob("*.a1.enc"))
    assert len(sealed) == 1
    assert pfx not in sealed[0].read_bytes()
    resolved = vault.resolve(scope=_scope(), issuer_cnpj="11222333000181")
    assert resolved.pkcs12_bytes == pfx
    assert resolved.password == password
    with pytest.raises(A1VaultUnavailable):
        vault.resolve(scope=_scope("tenant-b"), issuer_cnpj="11222333000181")


def test_signed_nfe_rsa_sha256_and_homologation_soap(test_a1):
    pfx, password, cert = test_a1
    key = "1" * 44
    unsigned = (
        '<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        '<idLote>1</idLote><indSinc>1</indSinc><NFe><infNFe Id="NFe' + key +
        '" versao="4.00"><ide><tpAmb>2</tpAmb></ide></infNFe></NFe></enviNFe>'
    ).encode()
    material = EphemeralCertificateMaterial(
        reference_id="ref:nfcore-smoke", pkcs12_bytes=pfx, password=password
    )
    signed = sign_nfe_envi_xml(unsigned, material)
    root = _parse_xml(signed)
    ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
    signed_info = root.find(".//ds:SignedInfo", ns)
    signature = root.find(".//ds:SignatureValue", ns)
    assert signed_info is not None and signature is not None
    import base64
    cert.public_key().verify(
        base64.b64decode(signature.text),
        etree.tostring(signed_info, method="c14n"),
        padding.PKCS1v15(), hashes.SHA256(),
    )
    soap = _soap_envelope(root)
    envelope = _parse_xml(soap)
    assert envelope.tag == f"{{{SOAP12_NAMESPACE}}}Envelope"
    assert envelope.find(f".//{{{NFE_NAMESPACE}}}enviNFe") is not None


def test_a1_offline_export_restores_real_synthetic_aesgcm_vault(
    tmp_path, test_a1, monkeypatch,
):
    """No Contabo credential: encrypt a valid synthetic PFX, back it up and read it back."""
    import importlib.util
    import os
    import shutil
    import zipfile
    from pathlib import Path

    from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

    script = Path(__file__).resolve().parents[1] / "deploy/contabo/a1-vault-ops.py"
    spec = importlib.util.spec_from_file_location("a1_ops_offline", script)
    assert spec is not None and spec.loader is not None
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)

    vault_dir = tmp_path / "live"
    vault = EncryptedA1Vault(directory=vault_dir, master_key=b"2" * 32)
    pfx, password, _ = test_a1
    vault.provision(
        scope=_scope(), issuer_cnpj="11222333000181",
        pkcs12_bytes=pfx, password=password,
    )
    original = {p.name: p.read_bytes() for p in vault_dir.glob("*.a1.enc")}
    assert len(original) == 1
    assert pfx not in next(iter(original.values()))
    monkeypatch.setenv("NFCORE_A1_VAULT_HOST_DIR", str(vault_dir))
    monkeypatch.setattr(ops, "_VAULT_UID", os.getuid())

    recovery_dir = tmp_path / "offline"
    recovery_dir.mkdir(mode=0o700)
    recovery_dir.chmod(0o700)
    archive = recovery_dir / "a1-ciphertexts.zip"
    assert ops.offline_export(str(archive)) == 0
    assert (archive.stat().st_mode & 0o777) == 0o600
    assert ops.offline_restore_test(str(archive)) == 0

    isolated = tmp_path / "isolated-restored"
    isolated.mkdir(mode=0o700)
    assert ops._extract_offline(archive, isolated) == 1
    restored_vault = EncryptedA1Vault(directory=isolated, master_key=b"2" * 32)
    material = restored_vault.resolve(
        scope=_scope(), issuer_cnpj="11222333000181",
    )
    assert material.pkcs12_bytes == pfx
    assert material.password == password
    with pytest.raises(A1VaultUnavailable):
        restored_vault.resolve(
            scope=_scope("tenant-b"), issuer_cnpj="11222333000181",
        )
    assert {p.name: p.read_bytes() for p in vault_dir.glob("*.a1.enc")} == original

    with pytest.raises(ops.VaultOpsError):
        ops.offline_export(str(archive))  # no clobber
    corrupted = recovery_dir / "tampered.zip"
    shutil.copyfile(archive, corrupted)
    with zipfile.ZipFile(corrupted, "a") as zf:
        zf.writestr("unexpected-file", b"evil")
    with pytest.raises(ops.VaultOpsError):
        ops.offline_restore_test(str(corrupted))

    (vault_dir / next(iter(original))).unlink()
    with pytest.raises(ops.VaultOpsError):
        ops.offline_export(str(recovery_dir / "empty.zip"))
