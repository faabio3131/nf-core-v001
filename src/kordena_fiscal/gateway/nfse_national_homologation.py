"""NFS-e Nacional: deterministic, homologation-only DPS HTTP/mTLS boundary.

This transport accepts already prepared, signed DPS XML; it is NOT the authority
that builds a fiscal document or selects a municipality. ADN is a separate
distribution interface and is deliberately not used for issuance.
"""
from __future__ import annotations

import base64
import gzip
import json
import ssl
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

SEFIN_HOMOLOGATION_NFSE_URL = (
    "https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional/nfse"
)
_MAX_DPS_BYTES = 2_097_152
_MAX_RESPONSE_BYTES = 4_194_304


class OfficialNfseTransportError(FiscalValidationError):
    """Safe, non-secret NFS-e transport failure."""


_NFSE = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def parse_signed_dps_info(signed_dps_xml: bytes) -> etree._Element:
    if not isinstance(signed_dps_xml, bytes) or not 0 < len(signed_dps_xml) <= _MAX_DPS_BYTES:
        raise OfficialNfseTransportError("Invalid DPS size")
    try:
        root: etree._Element = etree.fromstring(
            signed_dps_xml, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise OfficialNfseTransportError("Invalid DPS XML") from None
    ns = {"nfse": _NFSE, "ds": _DS}
    if root.tag != f"{{{_NFSE}}}DPS" or getattr(root.getroottree().docinfo, "doctype", None):
        raise OfficialNfseTransportError("National NFS-e requires the official DPS root")
    infos = root.findall("nfse:infDPS", ns)
    signatures = root.findall(".//ds:Signature", ns)
    if len(infos) != 1 or len(signatures) != 1 or signatures[0].getparent() is not root:
        raise OfficialNfseTransportError("DPS requires one infDPS and one direct XMLDSig")
    info = infos[0]
    identifier = info.get("Id")
    if not identifier or sum(node.get("Id") == identifier for node in root.iter()) != 1:
        raise OfficialNfseTransportError("DPS signature Id is missing or ambiguous")
    envs = root.findall(".//nfse:tpAmb", ns)
    if len(envs) != 1 or envs[0].getparent() is not info or envs[0].text != "2":
        raise OfficialNfseTransportError("DPS requires tpAmb=2")
    references = signatures[0].findall("ds:SignedInfo/ds:Reference", ns)
    if len(references) != 1 or references[0].get("URI") != "#" + identifier:
        raise OfficialNfseTransportError("DPS signature reference does not match infDPS")
    return info


def build_nfse_dps_request(
    signed_dps_xml: bytes, *, issuer_cnpj: str | None = None,
    issuer_municipality_ibge: str | None = None,
) -> bytes:
    """Build the public Emissor Nacional API JSON envelope from signed DPS XML."""
    info = parse_signed_dps_info(signed_dps_xml)
    if (
        issuer_municipality_ibge is not None
        and info.findtext(f"{{{_NFSE}}}cLocEmi") != issuer_municipality_ibge
    ):
        raise OfficialNfseTransportError("DPS issuer municipality differs from the fiscal profile")
    if issuer_cnpj is not None:
        if info.findtext(f"{{{_NFSE}}}prest/{{{_NFSE}}}CNPJ") != issuer_cnpj:
            raise OfficialNfseTransportError("DPS issuer disagrees with the scoped A1")
        version = info.getroottree().getroot().get("versao", "")
        national_dps_validator(version).validate_document(signed_dps_xml)
    return json.dumps(
        {"dpsXmlGZipB64": base64.b64encode(gzip.compress(signed_dps_xml, mtime=0)).decode("ascii")},
        separators=(",", ":"),
    ).encode("ascii")


def parse_nfse_homologation_response(raw: bytes) -> dict[str, str]:
    """Expose only references and canonical XML; never reflect provider internals."""
    if not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise OfficialNfseTransportError("Resposta da NFS-e Nacional ausente ou excede limite")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise OfficialNfseTransportError("Resposta inválida da NFS-e Nacional") from None
    if not isinstance(payload, dict):
        raise OfficialNfseTransportError("Resposta inválida da NFS-e Nacional")
    access_key = payload.get("chaveAcesso")
    encoded = payload.get("nfseXmlGZipB64")
    if isinstance(access_key, str) and access_key and isinstance(encoded, str) and encoded:
        try:
            zipped = base64.b64decode(encoded, validate=True)
            if len(zipped) > _MAX_RESPONSE_BYTES:
                raise ValueError
            # Bound the uncompressed payload to prevent compression bombs.
            with gzip.GzipFile(fileobj=__import__("io").BytesIO(zipped)) as stream:
                document = stream.read(_MAX_RESPONSE_BYTES + 1)
            if len(document) > _MAX_RESPONSE_BYTES:
                raise ValueError
            root = etree.fromstring(
                document, parser=etree.XMLParser(resolve_entities=False, no_network=True)
            )
            ns = "http://www.sped.fazenda.gov.br/nfse"
            if (
                root.tag != f"{{{ns}}}NFSe"
                or bool(getattr(root.getroottree().docinfo, "doctype", ""))
                or not access_key.isascii()
                or not access_key.isdecimal()
                or len(access_key) != 50
            ):
                raise ValueError("Non-NFSe document or invalid national access key")
            # A random valid-looking NFSe root is not fiscal proof. Bind the
            # official 50-digit response key to infNFSe/Id ("NFS" + key).
            # Source: NFS-e national DANFSe NT 008/2026, sec. 2.1.1,
            # and official NFS-e XSD identifier contract.
            infos = root.findall(f"{{{ns}}}infNFSe")
            if len(infos) != 1 or infos[0].get("Id") != "NFS" + access_key:
                raise ValueError("NFS-e XML does not belong to response access key")
        except (ValueError, OSError, etree.XMLSyntaxError):
            raise OfficialNfseTransportError(
                "XML retornado pela NFS-e Nacional é inválido"
            ) from None
        return {"status": "authorized", "chaveAcesso": access_key, "xml": document.decode("utf-8")}
    raise OfficialNfseTransportError(
        "NFS-e Nacional não autorizou a DPS; consulte as rejeições no retorno oficial"
    )


class NfseNationalHomologationTransport:
    """Bound, non-retrying HTTPS POST; ambiguous fiscal submissions need reconciliation."""

    def __init__(
        self,
        *,
        certificate: EphemeralCertificateMaterial,
        timeout_seconds: float = 15.0,
        exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
    ) -> None:
        if not isinstance(certificate, EphemeralCertificateMaterial):
            raise OfficialNfseTransportError("Certificado A1 não localizado para o CNPJ")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Timeout fiscal inválido")
        self._certificate = certificate
        self._timeout = timeout_seconds
        self._exchange = exchange or self._https_exchange

    @staticmethod
    def _https_exchange(body: bytes, context: ssl.SSLContext, timeout: float) -> bytes:
        request = Request(
            SEFIN_HOMOLOGATION_NFSE_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
            raise OfficialNfseTransportError(
                "Falha de comunicação com a NFS-e Nacional; consulte antes de reenviar"
            ) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise OfficialNfseTransportError("Resposta da NFS-e Nacional excede limite")
        return bytes(raw)

    def submit_signed_dps(self, signed_dps_xml: bytes) -> dict[str, str]:
        """Send only homologation DPS, without changing business authorization."""
        body = build_nfse_dps_request(signed_dps_xml)
        return parse_nfse_homologation_response(
            self._exchange(body, build_fiscal_tls_context(self._certificate), self._timeout)
        )

    def sign_and_submit_dps(self, unsigned_dps_xml: bytes) -> dict[str, str]:
        """Use the same scoped A1 identity for XMLDSig and the mTLS handshake."""
        return self.submit_signed_dps(
            sign_nfse_dps_xml(unsigned_dps_xml, self._certificate)
        )
