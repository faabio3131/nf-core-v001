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
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_national_receipt import (
    NationalReceiptIdentity,
    NfseReceiptVerificationError,
    require_national_receipt_signer_pins,
    validate_official_nfse_receipt,
)
from kordena_fiscal.issuance.nfe_nfse import NfseRejectionDetail
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator
from kordena_fiscal.xml.nfse_national_profiles import (
    PRODUCTION_PROFILE,
    select_national_dps_profile,
)

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
    schema_profile: str = PRODUCTION_PROFILE,
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
        national_dps_validator(version, profile=schema_profile).validate_document(signed_dps_xml)
    return json.dumps(
        {"dpsXmlGZipB64": base64.b64encode(gzip.compress(signed_dps_xml, mtime=0)).decode("ascii")},
        separators=(",", ":"),
    ).encode("ascii")


def parse_national_nfse_rejections(payload: object) -> tuple[NfseRejectionDetail, ...]:
    """Normalize all SEFIN error entries without truncation or secret echo.

    Preserves raw provider descriptions in the private fiscal result; callers
    must never return that text directly through HTTP or log it. The caller
    stores details under the scoped fiscal archive's retention policy.
    """
    if not isinstance(payload, dict):
        raise OfficialNfseTransportError("Resposta NFS-e Nacional inválida")
    errors = payload.get("erros")
    if errors is None:
        return ()
    if not isinstance(errors, list) or not 1 <= len(errors) <= 32:
        raise OfficialNfseTransportError("Lista de rejeições SEFIN inválida")
    details: list[NfseRejectionDetail] = []
    for entry in errors:
        if not isinstance(entry, dict):
            raise OfficialNfseTransportError("Rejeição SEFIN inválida")
        code = entry.get("Codigo", entry.get("codigo"))
        message = entry.get("Descricao", entry.get("descricao"))
        if (not isinstance(code, (str, int)) or isinstance(code, bool)
                or not isinstance(message, str)):
            raise OfficialNfseTransportError("Rejeição SEFIN sem código e motivo")
        details.append(NfseRejectionDetail(
            code=str(code), origin="SEFIN_NACIONAL", raw_message=message,
        ))
    return tuple(details)


def parse_nfse_homologation_response(
    raw: bytes, *, expected: NationalReceiptIdentity | None = None,
    schema_profile: str | None = None,
) -> dict[str, str]:
    """Expose only references and canonical XML; never reflect provider internals."""
    if not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise OfficialNfseTransportError("Resposta da NFS-e Nacional ausente ou excede limite")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise OfficialNfseTransportError("Resposta inválida da NFS-e Nacional") from None
    if not isinstance(payload, dict):
        raise OfficialNfseTransportError("Resposta inválida da NFS-e Nacional")
    access_key = payload.get("chaveAcesso")
    encoded = payload.get("nfseXmlGZipB64")
    if isinstance(access_key, str) and access_key and isinstance(encoded, str) and encoded:
        try:
            # A direct POST acknowledgement and a later GET recovery share
            # exactly one verification contract before AUTHORIZED is returned.
            document = validate_official_nfse_receipt(
                raw, access_key, expected=expected, schema_profile=schema_profile,
            )
            rendered = document.decode("utf-8")
        except (NfseReceiptVerificationError, UnicodeDecodeError):
            raise OfficialNfseTransportError(
                "XML retornado pela NFS-e Nacional é inválido"
            ) from None
        return {"status": "authorized", "chaveAcesso": access_key, "xml": rendered}
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
        self._requires_receipt_trust = exchange is None

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
        info = parse_signed_dps_info(signed_dps_xml)
        version = info.getroottree().getroot().get("versao", "")
        profile = select_national_dps_profile(
            environment=FiscalEnvironment.HOMOLOGATION, schema_version=version,
            effective_on=datetime.now(UTC).date(),
        )
        # This public HTTP boundary must validate even without optional issuer
        # correlation. The envelope helper alone is not permission to transmit.
        national_dps_validator(version, profile=profile).validate_document(signed_dps_xml)
        expected = NationalReceiptIdentity.from_dps_info(info)
        body = build_nfse_dps_request(signed_dps_xml, schema_profile=profile)
        if self._requires_receipt_trust:
            require_national_receipt_signer_pins()
        return parse_nfse_homologation_response(
            self._exchange(body, build_fiscal_tls_context(self._certificate), self._timeout),
            expected=expected, schema_profile=profile,
        )

    def sign_and_submit_dps(self, unsigned_dps_xml: bytes) -> dict[str, str]:
        """Use the same scoped A1 identity for XMLDSig and the mTLS handshake."""
        return self.submit_signed_dps(
            sign_nfse_dps_xml(unsigned_dps_xml, self._certificate)
        )
