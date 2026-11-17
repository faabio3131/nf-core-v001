"""Offline, fail-closed ICP trust-path and CRL proof for national NFS-e receipts.

The live transport requires all three operator-controlled artifacts BEFORE HTTP.
The XMLDSig leaf must independently match the exact SEFIN leaf pin. Trust
anchors and CRLs are signed public material, not certificates from the payload.

This is current-time validation only. It does not assert historic LTV or an
official SEFIN signer identity until real operator pins have been verified.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

_CA_PATH = "NFCORE_NFSE_RECEIPT_CA_BUNDLE"
_CRL_PATH = "NFCORE_NFSE_RECEIPT_CRL_BUNDLE"
_ROOT_PIN = "NFCORE_NFSE_RECEIPT_ROOT_SHA256"
_MAX_CA_BYTES = 131072
_MAX_CRL_BYTES = 1048576
_MAX_DEPTH = 5


class NationalReceiptPkiError(ValueError):
    """No trust material, invalid chain, stale/revoked signer, or bad CRL."""


def _read_pem(path_env: str, limit: int) -> bytes:
    path_text = os.environ.get(path_env, "")
    if not path_text or len(path_text) > 512:
        raise NationalReceiptPkiError("National receipt PKI trust material unavailable")
    path = Path(path_text)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise NationalReceiptPkiError("National receipt PKI trust material unavailable")
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        raise NationalReceiptPkiError("National receipt PKI trust material unavailable") from None
    if not data or len(data) > limit:
        raise NationalReceiptPkiError("National receipt PKI trust material invalid")
    return data


def _split_pem(data: bytes, *, begin: bytes, end: bytes, maximum: int) -> list[bytes]:
    parts = data.split(end)
    if len(parts) < 2 or parts[-1].strip():
        raise NationalReceiptPkiError("Malformed national receipt trust bundle")
    blocks = []
    for part in parts[:-1]:
        part = part.strip()
        if not part.startswith(begin) or part.count(begin) != 1:
            raise NationalReceiptPkiError("Malformed national receipt trust bundle")
        blocks.append(part + b"\n" + end + b"\n")
    if not 1 <= len(blocks) <= maximum:
        raise NationalReceiptPkiError("National receipt trust bundle count invalid")
    return blocks


def _load() -> tuple[list[x509.Certificate], list[x509.CertificateRevocationList], str]:
    root_pin = os.environ.get(_ROOT_PIN, "").lower()
    if len(root_pin) != 64 or any(ch not in "0123456789abcdef" for ch in root_pin):
        raise NationalReceiptPkiError("Trusted ICP root fingerprint unavailable")
    cas = [
        x509.load_pem_x509_certificate(block)
        for block in _split_pem(
            _read_pem(_CA_PATH, _MAX_CA_BYTES),
            begin=b"-----BEGIN CERTIFICATE-----",
            end=b"-----END CERTIFICATE-----",
            maximum=6,
        )
    ]
    crls = [
        x509.load_pem_x509_crl(block)
        for block in _split_pem(
            _read_pem(_CRL_PATH, _MAX_CRL_BYTES),
            begin=b"-----BEGIN X509 CRL-----",
            end=b"-----END X509 CRL-----",
            maximum=8,
        )
    ]
    fingerprints = [ca.fingerprint(hashes.SHA256()).hex() for ca in cas]
    if len(set(fingerprints)) != len(fingerprints):
        raise NationalReceiptPkiError("Duplicated certificate in receipt trust bundle")
    return cas, crls, root_pin


def require_national_receipt_pki_ready() -> None:
    """Deny real SEFIN HTTP until every bundled CA and signed CRL is valid."""
    try:
        cas, crls, root_pin = _load()
        now = datetime.now(UTC)
        roots = [ca for ca in cas if ca.fingerprint(hashes.SHA256()).hex() == root_pin]
        if len(roots) != 1 or roots[0].issuer != roots[0].subject:
            raise NationalReceiptPkiError("Pinned receipt ICP root missing")
        root = roots[0]
        _verify_cert(root, root)
        for ca in cas:
            _check_ca(ca, now)
            candidates = [item for item in crls if item.issuer == ca.subject]
            if len(candidates) != 1:
                raise NationalReceiptPkiError("Missing or ambiguous signed CA CRL")
            crl = candidates[0]
            if crl.next_update_utc is None or not (
                crl.last_update_utc <= now < crl.next_update_utc
            ):
                raise NationalReceiptPkiError("Stale national receipt CA CRL")
            _verify_signed_data(
                ca.public_key(), crl.signature, crl.tbs_certlist_bytes,
                crl.signature_hash_algorithm,
            )
        for ca in cas:
            if ca is root:
                continue
            issuers = [issuer for issuer in cas if issuer.subject == ca.issuer]
            if len(issuers) != 1:
                raise NationalReceiptPkiError("Receipt intermediate CA has no parent")
            issuer = issuers[0]
            _verify_cert(ca, issuer)
            _check_revocation(ca, issuer, crls, now)
    except (
        ValueError, TypeError, OSError, InvalidSignature, x509.ExtensionNotFound,
    ):
        raise NationalReceiptPkiError("National receipt ICP/CRL trust unavailable") from None


def _verify_signed_data(
    public_key: object, signature: bytes, signed_bytes: bytes,
    algorithm: hashes.HashAlgorithm | None,
) -> None:
    if algorithm is None or algorithm.name not in {"sha256", "sha384", "sha512"}:
        raise NationalReceiptPkiError("Weak national receipt certificate signature")
    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, signed_bytes, padding.PKCS1v15(), algorithm)
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, signed_bytes, ec.ECDSA(algorithm))
    else:
        raise NationalReceiptPkiError("Unsupported national receipt CA key")


def _verify_cert(child: x509.Certificate, issuer: x509.Certificate) -> None:
    if child.issuer != issuer.subject:
        raise NationalReceiptPkiError("National receipt certificate issuer mismatch")
    _verify_signed_data(
        issuer.public_key(), child.signature, child.tbs_certificate_bytes,
        child.signature_hash_algorithm,
    )


def _check_ca(certificate: x509.Certificate, instant: datetime) -> None:
    if not certificate.not_valid_before_utc <= instant <= certificate.not_valid_after_utc:
        raise NationalReceiptPkiError("Expired national receipt CA")
    basic = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    if not basic.ca or not usage.key_cert_sign or not usage.crl_sign:
        raise NationalReceiptPkiError("National receipt issuer not authorized as CA")


def _check_revocation(
    child: x509.Certificate, issuer: x509.Certificate,
    crls: list[x509.CertificateRevocationList], instant: datetime,
) -> None:
    matching = [
        item for item in crls
        if item.issuer == issuer.subject
        and item.last_update_utc <= instant
        and item.next_update_utc is not None
        and instant < item.next_update_utc
    ]
    if len(matching) != 1:
        raise NationalReceiptPkiError("Missing or stale signed receipt CA CRL")
    crl = matching[0]
    _verify_signed_data(
        issuer.public_key(), crl.signature, crl.tbs_certlist_bytes,
        crl.signature_hash_algorithm,
    )
    if crl.get_revoked_certificate_by_serial_number(child.serial_number) is not None:
        raise NationalReceiptPkiError("National receipt certificate revoked")


def verify_national_receipt_pki(
    leaf: x509.Certificate, *, instant: datetime | None = None,
) -> None:
    """Require current trusted CA path and signed fresh revocation proof for each link."""
    try:
        cas, crls, root_pin = _load()
        now = instant or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise NationalReceiptPkiError("PKI instant must have timezone")
        if not leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc:
            raise NationalReceiptPkiError("National receipt leaf expired")
        leaf_usage = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
        leaf_basic = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
        if not leaf_usage.digital_signature or leaf_basic.ca:
            raise NationalReceiptPkiError("National receipt leaf is not a signer")
        current = leaf
        seen: set[bytes] = set()
        for _ in range(_MAX_DEPTH):
            fingerprint = current.fingerprint(hashes.SHA256())
            if fingerprint in seen:
                raise NationalReceiptPkiError("Cyclic national receipt trust path")
            seen.add(fingerprint)
            candidates = [ca for ca in cas if ca.subject == current.issuer]
            if len(candidates) != 1:
                raise NationalReceiptPkiError("Ambiguous or missing receipt issuer CA")
            issuer = candidates[0]
            _check_ca(issuer, now)
            _verify_cert(current, issuer)
            _check_revocation(current, issuer, crls, now)
            if issuer.fingerprint(hashes.SHA256()).hex() == root_pin:
                if issuer.subject != issuer.issuer:
                    raise NationalReceiptPkiError("Trust anchor must be self-issued")
                _verify_cert(issuer, issuer)
                return
            current = issuer
        raise NationalReceiptPkiError("National receipt trust path too deep")
    except (
        ValueError, TypeError, OSError, InvalidSignature,
        x509.ExtensionNotFound,
    ):
        raise NationalReceiptPkiError("National receipt ICP path or CRL rejected") from None
