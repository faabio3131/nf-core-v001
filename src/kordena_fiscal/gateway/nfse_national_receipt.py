"""Single cryptographic receipt boundary for SEFIN Nacional GET and POST.

Provider transports may vary, but an AUTHORIZED national receipt must satisfy
the same bounded payload, exact key/Id, unique reference and XMLDSig policy.
This verifies signed bytes, not ICP-Brasil path/revocation or official XSD.
Those remain separate mandatory certification gates.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import zlib
from datetime import UTC, datetime

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree

from kordena_fiscal.domain import FiscalValidationError

_MAX_RESPONSE = 4_194_304
_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


class NfseReceiptVerificationError(FiscalValidationError):
    """Sanitized unsigned, malformed, or cryptographically invalid receipt."""


def _verify_nfse_receipt_signature(
    root: etree._Element, info: etree._Element, identifier: str,
    *, allow_nested_event_signature: bool = False,
) -> None:
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
    valid_nested = (
        allow_nested_event_signature
        and root.tag == "{http://www.sped.fazenda.gov.br/nfse}evento"
        and len(nested) <= 1
        and all(
            node.getparent() is not None
            and (parent := node.getparent()) is not None
            and parent.tag == "{http://www.sped.fazenda.gov.br/nfse}pedRegEvento"
            for node in nested
        )
    )
    if (
        len(signatures) != 1
        or len(root) != 2
        or root[0] is not info
        or root[1] is not signatures[0]
        or (
            bool(nested)
            if not allow_nested_event_signature else not valid_nested
        )
        or sum(child.get("Id") == identifier for child in root.iter()) != 1
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
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise ValueError("certificate validity")
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        if not usage.digital_signature:
            raise ValueError("certificate not allowed for digital signing")
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            raise ValueError("unexpected key type")
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


def validate_official_nfse_receipt(raw: bytes, key: str) -> bytes:
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
        root: etree._Element = etree.fromstring(
            xml, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False,
                no_network=True, huge_tree=False,
            )
        )
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
    return xml


