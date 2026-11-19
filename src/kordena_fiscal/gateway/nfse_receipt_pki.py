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
from cryptography.x509.oid import ExtensionOID

_CA_PATH = "NFCORE_NFSE_RECEIPT_CA_BUNDLE"
_CRL_PATH = "NFCORE_NFSE_RECEIPT_CRL_BUNDLE"
_ROOT_PIN = "NFCORE_NFSE_RECEIPT_ROOT_SHA256"
INVOICE_SIGNER_BUNDLE = "NFCORE_NFSE_RECEIPT_SIGNER_BUNDLE"
EVENT_SIGNER_BUNDLE = "NFCORE_NFSE_EVENT_SIGNER_BUNDLE"

# A partially configured live trust boundary is never synthetic/offline.
TRUST_MATERIAL_SETTINGS = (
    _CA_PATH, _CRL_PATH, _ROOT_PIN, INVOICE_SIGNER_BUNDLE, EVENT_SIGNER_BUNDLE,
)
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
            _validate_crl_scope(crl, cert_is_ca=None)
            if crl.next_update_utc is None or not (
                crl.last_update_utc <= now < crl.next_update_utc
            ):
                raise NationalReceiptPkiError("Stale national receipt CA CRL")
            _verify_signed_data(
                ca.public_key(), crl.signature, crl.tbs_certlist_bytes,
                crl.signature_hash_algorithm,
            )
        for ca in cas:
            current = ca
            seen: set[bytes] = set()
            subordinate_ca_count = 0
            for _ in range(_MAX_DEPTH):
                if current.fingerprint(hashes.SHA256()) == root.fingerprint(
                    hashes.SHA256()
                ):
                    break
                fingerprint = current.fingerprint(hashes.SHA256())
                if fingerprint in seen:
                    raise NationalReceiptPkiError("Cyclic receipt CA trust path")
                seen.add(fingerprint)
                issuers = [issuer for issuer in cas if issuer.subject == current.issuer]
                if len(issuers) != 1:
                    raise NationalReceiptPkiError("Receipt intermediate CA has no parent")
                issuer = issuers[0]
                if current.subject != current.issuer:
                    subordinate_ca_count += 1
                _check_ca_path_length(issuer, subordinate_ca_count)
                _verify_cert(current, issuer)
                _check_revocation(current, issuer, crls, now)
                current = issuer
            else:
                raise NationalReceiptPkiError("CA trust path does not reach pinned root")
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


def _require_supported_cert_extensions(cert: x509.Certificate) -> None:
    """RFC 5280: never ignore an unprocessed critical certificate constraint.

    Until name-constrained paths and any critical policy/EKU profiles are
    independently implemented and reviewed, they cannot authorize receipts.
    Noncritical informational extensions remain permitted.
    """
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        if key.key_size < 2048:
            raise NationalReceiptPkiError("Weak national receipt RSA key")
    elif isinstance(key, ec.EllipticCurvePublicKey):
        if key.key_size < 224:
            raise NationalReceiptPkiError("Weak national receipt EC key")
    else:
        raise NationalReceiptPkiError("Unsupported national receipt certificate key")
    supported = {ExtensionOID.BASIC_CONSTRAINTS, ExtensionOID.KEY_USAGE}
    # Reject policy-altering extensions even if incorrectly marked noncritical.
    # Ordinary noncritical CertificatePolicies remain informational until a
    # reviewed SEFIN policy set and complete path policy processor are available.
    unsupported_policy_controls = {
        "2.5.29.33",  # policyMappings
        "2.5.29.36",  # policyConstraints
        "2.5.29.54",  # inhibitAnyPolicy
    }
    for extension in cert.extensions:
        if extension.oid.dotted_string in unsupported_policy_controls:
            raise NationalReceiptPkiError(
                "National receipt policy controls require full path validation"
            )
        if extension.oid == ExtensionOID.NAME_CONSTRAINTS:
            raise NationalReceiptPkiError(
                "National receipt NameConstraints require full path validation"
            )
        if extension.oid == ExtensionOID.EXTENDED_KEY_USAGE:
            raise NationalReceiptPkiError(
                "National receipt EKU requires reviewed usage validation"
            )
        if extension.critical and extension.oid not in supported:
            raise NationalReceiptPkiError(
                "Unsupported critical national receipt certificate extension"
            )


def _check_ca(certificate: x509.Certificate, instant: datetime) -> None:
    _require_supported_cert_extensions(certificate)
    if not certificate.not_valid_before_utc <= instant <= certificate.not_valid_after_utc:
        raise NationalReceiptPkiError("Expired national receipt CA")
    basic = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    if not basic.ca or not usage.key_cert_sign or not usage.crl_sign:
        raise NationalReceiptPkiError("National receipt issuer not authorized as CA")


def _check_ca_path_length(
    issuer: x509.Certificate, subordinate_ca_count: int,
) -> None:
    """Enforce RFC 5280 pathLenConstraint for non-self-issued subordinate CAs."""
    constraints = issuer.extensions.get_extension_for_class(
        x509.BasicConstraints
    ).value
    if (
        constraints.path_length is not None
        and subordinate_ca_count > constraints.path_length
    ):
        raise NationalReceiptPkiError("Receipt CA path length constraint violated")


def _validate_crl_scope(
    crl: x509.CertificateRevocationList, *, cert_is_ca: bool | None,
) -> None:
    """Refuse incomplete or unsupported CRL scopes, never infer non-revocation."""
    allowed_critical = {
        ExtensionOID.ISSUING_DISTRIBUTION_POINT,
        ExtensionOID.CRL_NUMBER,
    }
    for extension in crl.extensions:
        if extension.oid == ExtensionOID.DELTA_CRL_INDICATOR:
            raise NationalReceiptPkiError("Delta receipt CRL requires complete base reconciliation")
        if extension.critical and extension.oid not in allowed_critical:
            raise NationalReceiptPkiError("Unsupported critical receipt CRL extension")
    try:
        idp = crl.extensions.get_extension_for_class(
            x509.IssuingDistributionPoint
        ).value
    except x509.ExtensionNotFound:
        return
    # Relative/name-constrained, indirect and reason-limited CRLs need
    # additional CRLDistributionPoints or delegated-signer logic. Until that
    # is independently certified, treating an unlisted serial as valid is unsafe.
    if (
        idp.indirect_crl
        or idp.only_contains_attribute_certs
        or idp.only_some_reasons is not None
        or idp.full_name is not None
        or idp.relative_name is not None
    ):
        raise NationalReceiptPkiError("Partial or indirect national receipt CRL unsupported")
    if cert_is_ca is True and idp.only_contains_user_certs:
        raise NationalReceiptPkiError("User-only receipt CRL cannot prove CA status")
    if cert_is_ca is False and idp.only_contains_ca_certs:
        raise NationalReceiptPkiError("CA-only receipt CRL cannot prove signer status")


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
    basic = child.extensions.get_extension_for_class(x509.BasicConstraints).value
    _validate_crl_scope(crl, cert_is_ca=basic.ca)
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
        _require_supported_cert_extensions(leaf)
        if not leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc:
            raise NationalReceiptPkiError("National receipt leaf expired")
        leaf_usage = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
        leaf_basic = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
        if not leaf_usage.digital_signature or leaf_basic.ca:
            raise NationalReceiptPkiError("National receipt leaf is not a signer")
        current = leaf
        seen: set[bytes] = set()
        subordinate_ca_count = 0
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
            if current is not leaf and current.subject != current.issuer:
                subordinate_ca_count += 1
            _check_ca_path_length(issuer, subordinate_ca_count)
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



def require_national_signer_pki_ready(
    pins: frozenset[str], *, bundle_env: str,
) -> None:
    """Verify every approved leaf before fiscal I/O, not only the CA chain.

    The bundle is obtained and approved independently of any fiscal response.
    A valid CA chain alone does not prove a particular signer is available,
    currently valid or non-revoked. Use independent invoice/event pin sets.
    """
    if bundle_env not in (INVOICE_SIGNER_BUNDLE, EVENT_SIGNER_BUNDLE):
        raise NationalReceiptPkiError("Unsupported national signer trust purpose")
    try:
        require_national_receipt_pki_ready()
        leaves = [
            x509.load_pem_x509_certificate(block)
            for block in _split_pem(
                _read_pem(bundle_env, _MAX_CA_BYTES),
                begin=b"-----BEGIN CERTIFICATE-----",
                end=b"-----END CERTIFICATE-----",
                maximum=8,
            )
        ]
        actual = [leaf.fingerprint(hashes.SHA256()).hex() for leaf in leaves]
        if len(actual) != len(pins) or frozenset(actual) != pins:
            raise NationalReceiptPkiError("National signer bundle differs from approved pins")
        instant = datetime.now(UTC)
        for leaf in leaves:
            verify_national_receipt_pki(leaf, instant=instant)
    except (ValueError, TypeError, OSError, InvalidSignature, x509.ExtensionNotFound):
        raise NationalReceiptPkiError("National signer ICP trust unavailable") from None
