"""FIS-03: current-time pinned chain and independently signed CRLs, synthetic only."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from kordena_fiscal.gateway.nfse_receipt_pki import (
    NationalReceiptPkiError,
    require_national_receipt_pki_ready,
    verify_national_receipt_pki,
)

_CA = "NFCORE_NFSE_RECEIPT_CA_BUNDLE"
_CRL = "NFCORE_NFSE_RECEIPT_CRL_BUNDLE"
_ROOT = "NFCORE_NFSE_RECEIPT_ROOT_SHA256"


def _name(label: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _certificate(
    name: x509.Name, issuer: x509.Name, public_key: rsa.RSAPublicKey,
    signing_key: rsa.RSAPrivateKey, *, ca: bool,
) -> x509.Certificate:
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(issuer).public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=2 if ca else None),
                       critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(signing_key, hashes.SHA256())
    )


def _crl(
    certificate: x509.Certificate, key: rsa.RSAPrivateKey,
    *, revoke: int | None = None, stale: bool = False,
) -> x509.CertificateRevocationList:
    now = datetime.now(UTC)
    before = now - timedelta(days=3) if stale else now - timedelta(hours=1)
    after = now - timedelta(days=2) if stale else now + timedelta(hours=6)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(certificate.subject)
        .last_update(before).next_update(after)
    )
    if revoke is not None:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(revoke).revocation_date(now - timedelta(minutes=1))
            .build()
        )
    return builder.sign(key, hashes.SHA256())


def _write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    certificates: list[x509.Certificate],
    crls: list[x509.CertificateRevocationList],
    root: x509.Certificate,
) -> None:
    ca_path = tmp_path / "trusted-cas.pem"
    crl_path = tmp_path / "signed-crls.pem"
    ca_path.write_bytes(b"".join(
        item.public_bytes(serialization.Encoding.PEM) for item in certificates
    ))
    crl_path.write_bytes(b"".join(
        item.public_bytes(serialization.Encoding.PEM) for item in crls
    ))
    monkeypatch.setenv(_CA, str(ca_path))
    monkeypatch.setenv(_CRL, str(crl_path))
    monkeypatch.setenv(_ROOT, root.fingerprint(hashes.SHA256()).hex())


@pytest.fixture
def chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root_key, intermediate_key, leaf_key = _key(), _key(), _key()
    root_name, intermediate_name, leaf_name = _name("Synthetic ICP Root"), (
        _name("Synthetic Intermediate")), _name("Synthetic SEFIN Signer")
    root = _certificate(root_name, root_name, root_key.public_key(), root_key, ca=True)
    intermediate = _certificate(
        intermediate_name, root_name, intermediate_key.public_key(), root_key, ca=True,
    )
    leaf = _certificate(
        leaf_name, intermediate_name, leaf_key.public_key(), intermediate_key, ca=False,
    )
    return tmp_path, monkeypatch, root, intermediate, leaf, root_key, intermediate_key


def test_synthetic_chain_and_fresh_signed_crls_pass(chain) -> None:
    path, monkeypatch, root, intermediate, leaf, root_key, intermediate_key = chain
    _write(path, monkeypatch, [intermediate, root], [
        _crl(intermediate, intermediate_key), _crl(root, root_key),
    ], root)
    require_national_receipt_pki_ready()
    verify_national_receipt_pki(leaf)


@pytest.mark.parametrize("fault", [
    "no_crl", "revoked_leaf", "revoked_intermediate", "stale",
    "wrong_root", "spoofed_crl", "missing_issuer", "malformed_root",
])
def test_absent_or_broken_trust_never_validates_synthetic_leaf(chain, fault) -> None:
    path, monkeypatch, root, intermediate, leaf, root_key, intermediate_key = chain
    leaves = [_crl(intermediate, intermediate_key), _crl(root, root_key)]
    certificates = [intermediate, root]
    if fault == "no_crl":
        leaves = [leaves[1]]
    elif fault == "revoked_leaf":
        leaves[0] = _crl(intermediate, intermediate_key, revoke=leaf.serial_number)
    elif fault == "revoked_intermediate":
        leaves[1] = _crl(root, root_key, revoke=intermediate.serial_number)
    elif fault == "stale":
        leaves[0] = _crl(intermediate, intermediate_key, stale=True)
    elif fault == "spoofed_crl":
        leaves[0] = _crl(intermediate, root_key)
    elif fault == "missing_issuer":
        certificates = [root]
    _write(path, monkeypatch, certificates, leaves, root)
    if fault == "wrong_root":
        monkeypatch.setenv(_ROOT, "0" * 64)
    elif fault == "malformed_root":
        monkeypatch.setenv(_ROOT, "not-a-sha")
    with pytest.raises(NationalReceiptPkiError):
        verify_national_receipt_pki(leaf)


def test_missing_operational_pki_is_fail_closed_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for setting in (_CA, _CRL, _ROOT):
        monkeypatch.delenv(setting, raising=False)
    with pytest.raises(NationalReceiptPkiError, match="unavailable"):
        require_national_receipt_pki_ready()


def test_malformed_pem_and_symlink_are_rejected(chain) -> None:
    path, monkeypatch, root, intermediate, leaf, root_key, intermediate_key = chain
    _write(path, monkeypatch, [intermediate, root], [
        _crl(intermediate, intermediate_key), _crl(root, root_key),
    ], root)
    pem_path = path / "trusted-cas.pem"
    pem_path.write_bytes(pem_path.read_bytes() + b"attacker")
    with pytest.raises(NationalReceiptPkiError):
        verify_national_receipt_pki(leaf)
    pem_path.unlink()
    pem_path.symlink_to(path / "signed-crls.pem")
    with pytest.raises(NationalReceiptPkiError):
        require_national_receipt_pki_ready()


def test_preflight_rejects_wrong_root_and_stale_or_forged_crls(chain) -> None:
    path, monkeypatch, root, intermediate, _, root_key, intermediate_key = chain
    _write(path, monkeypatch, [root, intermediate], [
        _crl(root, root_key), _crl(intermediate, intermediate_key),
    ], root)
    require_national_receipt_pki_ready()
    monkeypatch.setenv(_ROOT, "f" * 64)
    with pytest.raises(NationalReceiptPkiError):
        require_national_receipt_pki_ready()
    monkeypatch.setenv(_ROOT, root.fingerprint(hashes.SHA256()).hex())
    _write(path, monkeypatch, [root, intermediate], [
        _crl(root, root_key), _crl(intermediate, intermediate_key, stale=True),
    ], root)
    with pytest.raises(NationalReceiptPkiError):
        require_national_receipt_pki_ready()
    _write(path, monkeypatch, [root, intermediate], [
        _crl(root, root_key), _crl(intermediate, root_key),
    ], root)
    with pytest.raises(NationalReceiptPkiError):
        require_national_receipt_pki_ready()
