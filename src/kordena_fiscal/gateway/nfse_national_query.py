"""Read-only SEFIN Nacional DPS recovery, reusing the canonical fiscal authority.

GET /dps/{id} -> access key; GET /nfse/{key} -> authoritative XML.
This transport never POSTs DPS, cannot reassign numbers and cannot infer
authorization from a naked 50-digit key. Before field use it requires
official version-specific XSD/XMLDSig and receipt archival certification.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_national_homologation import (
    SEFIN_HOMOLOGATION_NFSE_URL,
    OfficialNfseTransportError,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

_PROVIDER_ID = "nfse-nacional-producao-restrita"
_PROVIDER = GatewayProviderMetadata(_PROVIDER_ID, "1.0")
_URL_BASE = SEFIN_HOMOLOGATION_NFSE_URL.rsplit("/nfse", 1)[0]
_MAX_RESPONSE = 4_194_304
_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


def _dps_id(request: NfseAuthorizationRequest) -> str:
    document = request.document
    cnpj = document.issuer.cnpj.value
    municipality = document.issuer.address.jurisdiction.municipality_ibge_code
    number = document.dps_number
    series = document.dps_series
    if (
        municipality is None or len(municipality) != 7
        or not municipality.isascii() or not municipality.isdecimal()
        or not cnpj.isascii() or not cnpj.isdecimal() or len(cnpj) != 14
        or number is None
        or not isinstance(number, int) or isinstance(number, bool)
        or not 1 <= number <= 999_999_999_999_999
        or not 1 <= series <= 99_999
    ):
        raise OfficialNfseTransportError(
            "Official DPS query requires a durably reserved legal issuer serial"
        )
    return f"DPS{municipality}1{cnpj}{series:05d}{number:015d}"


def _parse_key(raw: bytes, municipality: str) -> str:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise OfficialNfseTransportError("Invalid national DPS query response length")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise OfficialNfseTransportError("Invalid national DPS query JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("chaveAcesso"), str):
        raise OfficialNfseTransportError("National DPS query has no confirmed access key")
    key: str = payload["chaveAcesso"]
    if not key.isascii() or not key.isdecimal() or len(key) != 50:
        raise OfficialNfseTransportError("Invalid official NFS-e access key")
    if not key.startswith(municipality[:2]):
        raise OfficialNfseTransportError("Official NFS-e key does not match issuer UF")
    return key



def _verify_nfse_receipt_signature(
    root: etree._Element, info: etree._Element, identifier: str
) -> None:
    """Verify the official RSA-SHA256 enveloped signature over the exact NFS-e Id.

    This proves cryptographic integrity and reference binding, not independent
    ICP-Brasil chain or CRL validation. Operator trust-store certification is
    a separate release requirement; a self-signed synthetic test is not one.
    """
    signatures = root.findall(f"{{{_DS}}}Signature")
    if (
        len(signatures) != 1
        or len(root) != 2
        or root[0] is not info
        or root[1] is not signatures[0]
        or len(root.findall(f".//{{{_DS}}}Signature")) != 1
        or sum(child.get("Id") == identifier for child in root.iter()) != 1
    ):
        raise OfficialNfseTransportError("Invalid national NFS-e receipt signature placement")
    signature = signatures[0]
    signed_info = signature.find(f"{{{_DS}}}SignedInfo")
    if signed_info is None:
        raise OfficialNfseTransportError("Missing national NFS-e SignedInfo")
    references = signed_info.findall(f"{{{_DS}}}Reference")
    reference = references[0] if len(references) == 1 else None
    c14n = signed_info.find(f"{{{_DS}}}CanonicalizationMethod")
    method = signed_info.find(f"{{{_DS}}}SignatureMethod")
    if reference is None:
        raise OfficialNfseTransportError("National NFS-e requires one signature reference")
    transforms = reference.findall(f"{{{_DS}}}Transforms/{{{_DS}}}Transform")
    digest_method = reference.find(f"{{{_DS}}}DigestMethod")
    if (
        reference.get("URI") != "#" + identifier
        or c14n is None or c14n.get("Algorithm") != _C14N
        or method is None or method.get("Algorithm") != _RSA_SHA256
        or [item.get("Algorithm") for item in transforms] != [_ENVELOPED, _C14N]
        or digest_method is None or digest_method.get("Algorithm") != _SHA256
    ):
        raise OfficialNfseTransportError("Invalid national NFS-e signature profile")

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
        raise OfficialNfseTransportError("Invalid national NFS-e XMLDSig integrity") from None


def _validate_official_nfse(raw: bytes, key: str) -> bytes:
    """A bare key or unrelated XML can never produce AUTHORIZED."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise OfficialNfseTransportError("Invalid official NFS-e receipt length")
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
    except (OSError, ValueError, etree.XMLSyntaxError):
        raise OfficialNfseTransportError("Invalid signed national NFS-e receipt") from None
    if (
        root.tag != f"{{{_NS}}}NFSe"
        or root.get("versao") != "1.01"
        or getattr(root.getroottree().docinfo, "doctype", None)
    ):
        raise OfficialNfseTransportError("Non-official NFS-e XML receipt")
    infos = root.findall(f"{{{_NS}}}infNFSe")
    if len(infos) != 1 or infos[0].get("Id") != "NFS" + key:
        raise OfficialNfseTransportError("NFS-e receipt belongs to a different access key")
    _verify_nfse_receipt_signature(root, infos[0], "NFS" + key)
    # Preserve the exact receipt bytes verified against this key for atomic
    # archival with the durable authorization lifecycle. This is not an
    # authorization inference from a bare access key.
    return xml


def _read_only_get(path: str, context: ssl.SSLContext, timeout: float) -> bytes:
    if not path.startswith(_URL_BASE + "/"):
        raise OfficialNfseTransportError("National API request path invalid")
    request = Request(
        path, method="GET", headers={"Accept": "application/json"},
    )
    try:
        opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as response:
            result = response.read(_MAX_RESPONSE + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise OfficialNfseTransportError(
            "Ambiguous national NFS-e query; reconcile without retransmitting DPS"
        ) from None
    if len(result) > _MAX_RESPONSE:
        raise OfficialNfseTransportError("National query response exceeds limit")
    return bytes(result)


class NfseNationalHomologationQueryGateway:
    """Retrieve an existing DPS only; binding and A1 must match exact issuer unit."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        exchange_get: Callable[[str, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if (
            not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("SEFIN query requires canonical binding, A1 and timeout")
        self._provider_resolver = provider_resolver
        self._resolve_certificate = resolve_certificate
        self._get = exchange_get or _read_only_get
        self._timeout = timeout_seconds

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise FiscalValidationError("NFS-e query requires canonical prepared request")
        document = request.document
        scope = document.scope
        jurisdiction = document.issuer.address.jurisdiction
        if (
            scope.host_namespace is None
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or jurisdiction.municipality_ibge_code is None
        ):
            raise OfficialNfseTransportError("National NFS-e query requires trusted scope")
        dps_id = _dps_id(request)
        bound = self._provider_resolver.resolve_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=jurisdiction, operation="query",
        )
        if bound != _PROVIDER_ID:
            raise OfficialNfseTransportError("National NFS-e query provider is not bound")
        issuer_cnpj = document.issuer.cnpj.value
        material = self._resolve_certificate(scope, issuer_cnpj)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=Cnpj(issuer_cnpj), at=datetime.now(UTC),
        )
        tls = build_fiscal_tls_context(material)
        key = _parse_key(
            self._get(f"{_URL_BASE}/dps/{dps_id}", tls, self._timeout),
            jurisdiction.municipality_ibge_code,
        )
        authorized_xml = _validate_official_nfse(
            self._get(f"{_URL_BASE}/nfse/{key}", tls, self._timeout), key,
        )
        return NfseAuthorizationResult(
            status=AuthorizationStatus.AUTHORIZED,
            scope=scope, document_id=document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_PROVIDER,
            provider_request_id=dps_id,
            invoice_reference=key,
            authorized_xml=authorized_xml,
        )
