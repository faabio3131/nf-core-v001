"""Single cryptographic receipt boundary for SEFIN Nacional GET and POST.

Provider transports may vary, but an AUTHORIZED national receipt must satisfy
the same bounded payload, exact key/Id, unique reference and XMLDSig policy.
National authorization also requires pinned XSD and canonical DPS correlation.
This verifies signed bytes, not ICP-Brasil path/revocation.
Those remain separate mandatory certification gates.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_identity import national_dps_id
from kordena_fiscal.xml.nfse_nacional_schema import national_nfse_receipt_validator
from kordena_fiscal.xml.nfse_national_profiles import (
    NT009_RESTRICTED_PROFILE,
    PRODUCTION_PROFILE,
    select_national_dps_profile,
)
from kordena_fiscal.xml.schema import XmlSchemaValidationError

_MAX_RESPONSE = 4_194_304
_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
_TRUST_PINS_ENV = "NFCORE_NFSE_RECEIPT_SIGNER_SHA256"


class NfseReceiptVerificationError(FiscalValidationError):
    """Sanitized unsigned, malformed, or cryptographically invalid receipt."""


def require_national_receipt_signer_pins() -> frozenset[str]:
    """Require an explicit, bounded operator allowlist before live SEFIN traffic.

    Pins are SHA-256 fingerprints of DER end-entity signing certificates,
    not a substitute for ICP-Brasil chain/CRL/OCSP or historical validation.
    Empty, malformed or ambiguous configuration always fails closed.
    """
    value = os.environ.get(_TRUST_PINS_ENV)
    if value is None or not value or len(value) > 519:
        raise NfseReceiptVerificationError("National NFS-e signer trust pins unavailable")
    parts = value.split(",")
    allowed = frozenset("0123456789abcdefABCDEF")
    if (
        not 1 <= len(parts) <= 8
        or any(len(part) != 64 or not set(part) <= allowed for part in parts)
        or len({part.lower() for part in parts}) != len(parts)
    ):
        raise NfseReceiptVerificationError("Invalid national NFS-e signer trust pins")
    return frozenset(part.lower() for part in parts)


def _enforce_national_receipt_signer_pin(root: etree._Element) -> None:
    """Bind the verified outer XMLDSig certificate to the operator's exact pin."""
    from kordena_fiscal.gateway.nfse_receipt_pki import (
        TRUST_MATERIAL_SETTINGS,
        NationalReceiptPkiError,
        verify_national_receipt_pki,
    )

    if _TRUST_PINS_ENV not in os.environ:
        if any(name in os.environ for name in TRUST_MATERIAL_SETTINGS):
            raise NfseReceiptVerificationError("National NFS-e signer trust pins unavailable")
        # Only synthetic callers may omit operational trust entirely.
        return
    pins = require_national_receipt_signer_pins()
    node = root.find(
        f"{{{_DS}}}Signature/{{{_DS}}}KeyInfo/{{{_DS}}}X509Data/"
        f"{{{_DS}}}X509Certificate"
    )
    if node is None or not node.text:
        raise NfseReceiptVerificationError("National NFS-e signer certificate absent")
    try:
        data = base64.b64decode("".join(node.text.split()), validate=True)
        certificate = x509.load_der_x509_certificate(data)
    except (ValueError, TypeError):
        raise NfseReceiptVerificationError("Invalid national NFS-e signer certificate") from None
    if certificate.fingerprint(hashes.SHA256()).hex() not in pins:
        raise NfseReceiptVerificationError("Untrusted national NFS-e signer certificate")
    # Synthetic validation may run without operational trust files. The default
    # real HTTP transports require these files before any network dispatch.
    # If ANY PKI setting is present, partial configuration cannot silently pass.
    if any(name in os.environ for name in TRUST_MATERIAL_SETTINGS):
        try:
            verify_national_receipt_pki(certificate)
        except NationalReceiptPkiError:
            raise NfseReceiptVerificationError(
                "National NFS-e ICP path or revocation invalid"
            ) from None



def _verify_nfse_receipt_signature(
    root: etree._Element, info: etree._Element, identifier: str,
    *, allow_nested_event_signature: bool = False,
    archived_dispatch_at: datetime | None = None,
) -> x509.Certificate:
    """Verify the official RSA-SHA256 enveloped signature over the exact NFS-e Id.

    This proves cryptographic integrity and reference binding, not independent
    ICP-Brasil chain or CRL validation. Operator trust-store certification is
    a separate release requirement; a self-signed synthetic test is not one.
    """
    signatures = root.findall(f"{{{_DS}}}Signature")
    nested = [
        node for node in root.findall(f".//{{{_DS}}}Signature")
        if node not in signatures
    ]
    dps = info.find(f"{{{_NS}}}DPS") if root.tag == f"{{{_NS}}}NFSe" else None
    nested_dps = dps.find(f"{{{_DS}}}Signature") if dps is not None else None
    valid_nested = not nested or (
        len(nested) == 1 and nested[0] is nested_dps
    ) or (
        allow_nested_event_signature
        and root.tag == f"{{{_NS}}}evento"
        and len(nested) == 1
        and nested[0].getparent() is info.find(f"{{{_NS}}}pedRegEvento")
    )
    if (
        len(signatures) != 1
        or len(root) != 2
        or root[0] is not info
        or root[1] is not signatures[0]
        or not valid_nested
        or sum(child.get("Id") == identifier for child in root.iter()) != 1
        or len(ids := [node.get("Id") for node in root.iter() if node.get("Id")]) != len(set(ids))
    ):
        raise NfseReceiptVerificationError("Invalid national NFS-e receipt signature placement")
    signature = signatures[0]
    signed_info = signature.find(f"{{{_DS}}}SignedInfo")
    if signed_info is None:
        raise NfseReceiptVerificationError("Missing national NFS-e SignedInfo")
    references = signed_info.findall(f"{{{_DS}}}Reference")
    reference = references[0] if len(references) == 1 else None
    c14n = signed_info.find(f"{{{_DS}}}CanonicalizationMethod")
    method = signed_info.find(f"{{{_DS}}}SignatureMethod")
    if reference is None:
        raise NfseReceiptVerificationError("National NFS-e requires one signature reference")
    transforms = reference.findall(f"{{{_DS}}}Transforms/{{{_DS}}}Transform")
    digest_method = reference.find(f"{{{_DS}}}DigestMethod")
    if (
        reference.get("URI") != "#" + identifier
        or c14n is None or c14n.get("Algorithm") != _C14N
        or method is None or method.get("Algorithm") != _RSA_SHA256
        or [item.get("Algorithm") for item in transforms] != [_ENVELOPED, _C14N]
        or digest_method is None or digest_method.get("Algorithm") != _SHA256
    ):
        raise NfseReceiptVerificationError("Invalid national NFS-e signature profile")

    def decode(value: str | None) -> bytes:
        if not value:
            raise ValueError("missing signature field")
        return base64.b64decode("".join(value.split()), validate=True)

    try:
        cert_node = signature.find(
            f"{{{_DS}}}KeyInfo/{{{_DS}}}X509Data/{{{_DS}}}X509Certificate"
        )
        cert = x509.load_der_x509_certificate(
            decode(cert_node.text if cert_node is not None else None)
        )
        now = datetime.now(UTC)
        is_dps = root.tag == f"{{{_NS}}}DPS"
        if archived_dispatch_at is not None:
            if (
                not is_dps or archived_dispatch_at.tzinfo is None
                or archived_dispatch_at.utcoffset() is None or archived_dispatch_at > now
            ):
                raise ValueError("invalid archived dispatch instant")
            # Local observation of the submitted DPS, not a trusted timestamp
            # for an official invoice or its signer. Outer proof stays current.
            now = archived_dispatch_at
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise ValueError("certificate validity")
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not (usage.digital_signature or (is_dps and usage.content_commitment)):
            raise ValueError("certificate not allowed for digital signing")
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            raise ValueError("unexpected or weak key type")
        expected_digest = hashes.Hash(hashes.SHA256())
        expected_digest.update(
            etree.tostring(info, method="c14n", exclusive=False, with_comments=False)
        )
        if (
            decode(reference.findtext(f"{{{_DS}}}DigestValue"))
            != expected_digest.finalize()
        ):
            raise ValueError("tampered NFS-e XML")
        key.verify(
            decode(signature.findtext(f"{{{_DS}}}SignatureValue")),
            etree.tostring(
                signed_info, method="c14n", exclusive=False, with_comments=False
            ),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (
        ValueError, InvalidSignature, x509.ExtensionNotFound, etree.C14NError
    ):
        raise NfseReceiptVerificationError("Invalid national NFS-e XMLDSig integrity") from None

    if nested_dps is not None and dps is not None:
        dps_info = dps.find(f"{{{_NS}}}infDPS")
        if dps_info is None or not dps_info.get("Id"):
            raise NfseReceiptVerificationError("Missing nested DPS identity")
        _verify_nfse_receipt_signature(dps, dps_info, dps_info.get("Id", ""))
    return cert


def verify_outgoing_national_dps(
    signed_dps: bytes, *, expected_signer_sha256: str | None = None,
    archived_dispatch_at: datetime | None = None, tp_amb: str = "2",
) -> str:
    """Verify the exact signature and, before dispatch, the scoped Vault A1."""
    from kordena_fiscal.gateway.nfse_national_homologation import parse_signed_dps_info

    info = parse_signed_dps_info(signed_dps, tp_amb=tp_amb)
    certificate = _verify_nfse_receipt_signature(
        info.getroottree().getroot(), info, info.get("Id", ""),
        archived_dispatch_at=archived_dispatch_at,
    )
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    if expected_signer_sha256 is not None and fingerprint != expected_signer_sha256:
        raise NfseReceiptVerificationError("DPS signature differs from scoped Vault A1")
    return fingerprint


def validate_nfse_receipt_integrity(raw: bytes, key: str) -> bytes:
    """A bare key or unrelated XML can never produce AUTHORIZED."""
    if (
        not isinstance(key, str) or not key.isascii()
        or not key.isdecimal() or len(key) != 50
    ):
        raise NfseReceiptVerificationError("Invalid official NFS-e access key")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise NfseReceiptVerificationError("Invalid official NFS-e receipt length")
    try:
        payload = json.loads(raw)
        encoded = payload.get("nfseXmlGZipB64") if isinstance(payload, dict) else None
        if not isinstance(encoded, str):
            raise ValueError
        zipped = base64.b64decode(encoded, validate=True)
        if len(zipped) > _MAX_RESPONSE:
            raise ValueError
        with gzip.GzipFile(fileobj=io.BytesIO(zipped)) as stream:
            xml = stream.read(_MAX_RESPONSE + 1)
        if len(xml) > _MAX_RESPONSE:
            raise ValueError

    except (
        EOFError,
        OSError,
        RecursionError,
        UnicodeError,
        ValueError,
        zlib.error,
        etree.XMLSyntaxError,
    ):
        # A provider can return malformed UTF-8, a truncated GZIP stream or a
        # corrupt deflate block. None of those may escape as an HTTP 500 or
        # be treated as an authorized fiscal document.
        raise NfseReceiptVerificationError("Invalid signed national NFS-e receipt") from None
    validate_nfse_xml_integrity(xml, key)
    return xml


def validate_nfse_xml_integrity(xml: bytes, key: str) -> etree._Element:
    """Shared crypto boundary; municipal adapters apply their own XSD policy."""
    if not isinstance(xml, bytes) or not 0 < len(xml) <= _MAX_RESPONSE:
        raise NfseReceiptVerificationError("Invalid official NFS-e XML length")
    try:
        root = etree.fromstring(xml, etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
        ))
    except etree.XMLSyntaxError:
        raise NfseReceiptVerificationError("Invalid official NFS-e XML") from None
    if (
        root.tag != f"{{{_NS}}}NFSe"
        or root.get("versao") != "1.01"
        or getattr(root.getroottree().docinfo, "doctype", None)
    ):
        raise NfseReceiptVerificationError("Non-official NFS-e XML receipt")
    infos = root.findall(f"{{{_NS}}}infNFSe")
    if len(infos) != 1 or infos[0].get("Id") != "NFS" + key:
        raise NfseReceiptVerificationError("NFS-e receipt belongs to a different access key")
    _verify_nfse_receipt_signature(root, infos[0], "NFS" + key)
    # Preserve the exact receipt bytes verified against this key for atomic
    # archival with the durable authorization lifecycle. This is not an
    # authorization inference from a bare access key.
    return root


def _dps_content_digest(info: etree._Element) -> str:
    """Bind the signed infDPS, independent of its enclosing receipt namespaces."""
    if info.tag != f"{{{_NS}}}infDPS":
        raise NfseReceiptVerificationError("Invalid signed DPS content")
    return hashlib.sha256(etree.tostring(
        info, method="c14n", exclusive=True, with_comments=False,
    )).hexdigest()


@dataclass(frozen=True, slots=True)
class NationalReceiptIdentity:
    """Identity and exact fiscal content from canonical or submitted DPS."""

    municipality: str
    cnpj: str
    series: int
    number: int
    environment: str
    dps_content_sha256: str | None = None

    @property
    def dps_id(self) -> str:
        return national_dps_id(self.municipality, self.cnpj, self.series, self.number)

    @classmethod
    def from_request(
        cls, request: NfseAuthorizationRequest, *, schema_profile: str | None = None,
    ) -> NationalReceiptIdentity:
        # No A1, new serial, or fiscal I/O: reuse the canonical XML authority.
        from kordena_fiscal.issuance.nfse_dps_builder import build_unsigned_dps

        doc = request.document
        if doc.issuer.address.jurisdiction.municipality_ibge_code is None or doc.dps_number is None:
            raise NfseReceiptVerificationError("Receipt requires durably reserved DPS")
        profile = schema_profile or select_national_dps_profile(
            environment=doc.scope.environment, schema_version="1.01",
            effective_on=datetime.now(UTC).date(),
        )
        try:
            unsigned = build_unsigned_dps(request, schema_profile=profile)
            root = etree.fromstring(unsigned)
            info = root.find(f"{{{_NS}}}infDPS")
            if info is None:
                raise NfseReceiptVerificationError("Canonical DPS content unavailable")
            return cls.from_dps_info(info)
        except (FiscalValidationError, etree.LxmlError):
            raise NfseReceiptVerificationError("Canonical DPS content unavailable") from None

    @classmethod
    def from_dps_info(cls, info: etree._Element) -> NationalReceiptIdentity:
        try:
            result = cls(
                info.findtext(f"{{{_NS}}}cLocEmi", ""),
                info.findtext(f"{{{_NS}}}prest/{{{_NS}}}CNPJ", ""),
                int(info.findtext(f"{{{_NS}}}serie", "")),
                int(info.findtext(f"{{{_NS}}}nDPS", "")),
                info.findtext(f"{{{_NS}}}tpAmb", ""),
                _dps_content_digest(info),
            )
            if result.environment not in ("1", "2") or info.get("Id") != result.dps_id:
                raise ValueError
            return result
        except (ValueError, FiscalValidationError, etree.LxmlError):
            raise NfseReceiptVerificationError("Invalid canonical DPS receipt identity") from None


NATIONAL_DISPATCH_MEDIA_TYPE = "application/vnd.nfcore.national-dps-dispatch.v1+json"


@dataclass(frozen=True, slots=True)
class NationalDispatchEvidence:
    """Exact pre-HTTP signed DPS and layout, bound to one durable request."""

    schema_profile: str
    request_fingerprint: str
    signed_dps: bytes
    identity: NationalReceiptIdentity

    @classmethod
    def capture(
        cls, request: NfseAuthorizationRequest, profile: str, signed_dps: bytes,
    ) -> NationalDispatchEvidence:
        verify_outgoing_national_dps(signed_dps)
        evidence = cls._from_signed_dps(request, profile, signed_dps)
        if evidence.identity != NationalReceiptIdentity.from_request(
            request, schema_profile=profile,
        ):
            raise NfseReceiptVerificationError("Archived dispatch differs from canonical DPS")
        return evidence

    @classmethod
    def _from_signed_dps(
        cls, request: NfseAuthorizationRequest, profile: str, signed_dps: bytes,
    ) -> NationalDispatchEvidence:
        from kordena_fiscal.gateway.nfse_national_homologation import parse_signed_dps_info
        from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

        if profile not in (PRODUCTION_PROFILE, NT009_RESTRICTED_PROFILE):
            raise NfseReceiptVerificationError("Unsupported archived DPS profile")
        info = parse_signed_dps_info(signed_dps)
        national_dps_validator("1.01", profile=profile).validate_document(signed_dps)
        identity = NationalReceiptIdentity.from_dps_info(info)
        doc = request.document
        if (
            identity.municipality != doc.issuer.address.jurisdiction.municipality_ibge_code
            or identity.cnpj != doc.issuer.cnpj.value
            or identity.series != doc.dps_series or identity.number != doc.dps_number
            or identity.environment != "2"
            or doc.scope.environment is not FiscalEnvironment.HOMOLOGATION
        ):
            raise NfseReceiptVerificationError("Archived dispatch does not match fiscal identity")
        return cls(profile, request.request_fingerprint, signed_dps, identity)

    def encode(self) -> bytes:
        return json.dumps({
            "schema_profile": self.schema_profile,
            "request_fingerprint": self.request_fingerprint,
            "signed_dps": base64.b64encode(self.signed_dps).decode("ascii"),
            "signed_dps_sha256": hashlib.sha256(self.signed_dps).hexdigest(),
            "dps_content_sha256": self.identity.dps_content_sha256,
        }, sort_keys=True, separators=(",", ":")).encode("ascii")

    @classmethod
    def decode(
        cls, data: bytes, request: NfseAuthorizationRequest, *,
        archived_dispatch_at: datetime | None = None,
    ) -> NationalDispatchEvidence:
        try:
            if len(data) > 2 * _MAX_RESPONSE:
                raise ValueError("dispatch evidence size")
            payload = json.loads(data)
            if not isinstance(payload, dict) or set(payload) != {
                "schema_profile", "request_fingerprint", "signed_dps",
                "signed_dps_sha256", "dps_content_sha256",
            } or not all(isinstance(value, str) for value in payload.values()):
                raise ValueError("dispatch evidence fields")
            signed = base64.b64decode(payload["signed_dps"], validate=True)
            if (
                payload["request_fingerprint"] != request.request_fingerprint
                or hashlib.sha256(signed).hexdigest() != payload["signed_dps_sha256"]
            ):
                raise ValueError("dispatch evidence digest")
            verify_outgoing_national_dps(signed, archived_dispatch_at=archived_dispatch_at)
            evidence = cls._from_signed_dps(request, payload["schema_profile"], signed)
            if evidence.identity.dps_content_sha256 != payload["dps_content_sha256"]:
                raise ValueError("dispatch DPS digest")
            return evidence
        except (ValueError, TypeError, FiscalValidationError) as exc:
            raise NfseReceiptVerificationError("Invalid archived National DPS dispatch") from exc


def legacy_national_receipt_context(
    xml: bytes, key: str, request: NfseAuthorizationRequest,
) -> tuple[NationalReceiptIdentity, str]:
    """Pre-intent migration path: use verified provider-reported processing date.

    This date selects the historical layout only. It is never used as an
    independent timestamp or to bypass current certificate validity/CRL checks.
    Exact canonical DPS correlation and full receipt trust still apply.
    """
    root = validate_nfse_xml_integrity(xml, key)
    info = root.find(f"{{{_NS}}}infNFSe")
    assert info is not None
    try:
        raw = info.findtext(f"{{{_NS}}}dhProc")
        if not raw:
            raise ValueError("missing official processing date")
        processed = datetime.fromisoformat(raw)
        if processed.tzinfo is None or processed.utcoffset() is None:
            raise ValueError("missing processing timezone")
        if processed > datetime.now(UTC):
            raise ValueError("future processing date")
        profile = select_national_dps_profile(
            environment=request.document.scope.environment, schema_version="1.01",
            effective_on=processed.astimezone(UTC).date(),
        )
    except (ValueError, FiscalValidationError) as exc:
        raise NfseReceiptVerificationError("Historical receipt layout unavailable") from exc
    return NationalReceiptIdentity.from_request(request, schema_profile=profile), profile


def current_national_receipt_profile() -> str:
    return select_national_dps_profile(
        environment=FiscalEnvironment.HOMOLOGATION, schema_version="1.01",
        effective_on=datetime.now(UTC).date(),
    )


def validate_national_nfse_xml(
    xml: bytes, key: str, *, expected: NationalReceiptIdentity, schema_profile: str,
) -> bytes:
    """Validate archived or transported NFSe under an explicitly selected contract."""
    root = validate_nfse_xml_integrity(xml, key)
    if schema_profile not in (NT009_RESTRICTED_PROFILE, PRODUCTION_PROFILE):
        raise NfseReceiptVerificationError("National NFSe receipt schema profile unsupported")
    try:
        national_nfse_receipt_validator(profile=schema_profile).validate_document(xml)
    except XmlSchemaValidationError:
        raise NfseReceiptVerificationError("National NFSe receipt violates official XSD") from None
    info = root.find(f"{{{_NS}}}infNFSe")
    assert info is not None
    dps_info = info.find(f"{{{_NS}}}DPS/{{{_NS}}}infDPS")
    if (
        dps_info is None
        or expected.dps_content_sha256 is None
        or NationalReceiptIdentity.from_dps_info(dps_info) != expected
        or dps_info.get("Id") != expected.dps_id
        or info.findtext(f"{{{_NS}}}emit/{{{_NS}}}CNPJ") != expected.cnpj
        or info.findtext(f"{{{_NS}}}emit/{{{_NS}}}enderNac/{{{_NS}}}cMun") != expected.municipality
        # TSIdNFSe: municipality(7), ambGer(1), inscription type(1), CNPJ(14).
        # ambGer is the generating system, NOT the fiscal environment tpAmb.
        or key[:7] != expected.municipality
        or key[7:8] != info.findtext(f"{{{_NS}}}ambGer")
        or key[8:9] != "2"
        or key[9:23] != expected.cnpj
    ):
        raise NfseReceiptVerificationError("National NFSe receipt differs from canonical DPS")
    _enforce_national_receipt_signer_pin(root)
    return xml


def validate_official_nfse_receipt(
    raw: bytes, key: str, *, expected: NationalReceiptIdentity | None = None,
    schema_profile: str | None = None,
) -> bytes:
    """National POST and GET require schema, integrity and request correlation."""
    xml = validate_nfse_receipt_integrity(raw, key)
    if expected is None or schema_profile is None:
        raise NfseReceiptVerificationError("National receipt requires explicit DPS and schema")
    payload = json.loads(raw)
    if "idDps" in payload and payload["idDps"] != expected.dps_id:
        raise NfseReceiptVerificationError("National receipt envelope DPS mismatch")
    return validate_national_nfse_xml(xml, key, expected=expected, schema_profile=schema_profile)
