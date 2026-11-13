"""Osasco RTC WCF SOAP 1.1 boundary, unprovisioned until official WSDL parity.

Fiscal method contracts and request fields come from municipality's April 2026
'Geracao de NFS-e via Web Service v2.1'; WSDL must be inspected using an
authorized taxpayer identity before activating. No hardcoded authentication key.
The caller supplies a trusted, fiscal-schema-validated WCF request XML, not raw
browser-supplied payloads or arbitrary SOAP envelopes.

Official manual:
https://nfe.osasco.sp.gov.br/EissnfeWebApp/Portal/Manual/Geracao%20de%20NFS-e%20Via%20Web%20Service%202.1.pdf
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects
from kordena_fiscal.gateway.provider import ProviderSelectionResolver

OSASCO_IBGE = "3534401"
OSASCO_RTC_PROVIDER_ID = "osasco-rtc-homologation"
OSASCO_HOMOLOGATION_URL = (
    "https://homolog-nfe.osasco.sp.gov.br/EissnfeWebServices/NotaFiscalEletronica.svc"
)
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_WCF = "http://tempuri.org/"
_DTO = "http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem"
_MAX = 2_097_152
_PRESTADOR = "http://schemas.datacontract.org/2004/07/Eissnfe.Dominio.DataTransferObject.Prestador"
_OPERATIONS = {
    "RTC_EmitirNFE": "authorize",
    "RTC_EmitirNFELote": "authorize",
    "RTC_ConsultarNFE": "query",
    "RTC_ConsultarLote": "query",
    "Consultar": "query",
    "Cancelar": "cancel",
    "ConsultarNotaCompleta": "query",
}


class OsascoRtcContractError(FiscalValidationError):
    """Sanitized WCF/municipal authorization or transport contract failure."""


@dataclass(frozen=True, slots=True)
class OsascoWcfContract:
    """Official WSDL-derived action; configured per pinned WSDL and method.

    This remains external metadata until the municipality's actual WSDL and
    taxpayer-specific auth key are checked; do not guess WCF SOAPAction.
    """

    action: str
    method: str
    wsdl_sha256: str

    def __post_init__(self) -> None:
        if (
            self.method not in _OPERATIONS
            or not self.action.startswith(_WCF)
            or len(self.action) > 256
            or any(c in self.action for c in '"\r\n<>')
            or len(self.wsdl_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.wsdl_sha256)
        ):
            raise OsascoRtcContractError("Unverified Osasco WSDL action contract")


@dataclass(frozen=True, slots=True)
class OsascoPreparedOperation:
    """Preaudited WCF request payload; never accepts an arbitrary SOAP envelope."""

    scope: ExecutionScope
    issuer_cnpj: Cnpj
    tax_regime: TaxRegimeCode
    competence_date: date
    method: str
    request_xml: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ExecutionScope)
            or self.scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not self.scope.host_namespace
            or not isinstance(self.issuer_cnpj, Cnpj)
            or not isinstance(self.tax_regime, TaxRegimeCode)
            or type(self.competence_date) is not date
            or self.method not in _OPERATIONS
            or not isinstance(self.request_xml, bytes)
            or not 0 < len(self.request_xml) <= _MAX
        ):
            raise OsascoRtcContractError("Unreviewed Osasco fiscal operation or scope")
        if _OPERATIONS[self.method] == "authorize":
            if (
                self.tax_regime is TaxRegimeCode.MEI
                and self.competence_date >= date(2023, 9, 1)
            ) or (
                self.tax_regime in (
                    TaxRegimeCode.SIMPLES_NACIONAL,
                    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
                )
                and self.competence_date >= date(2026, 11, 1)
            ):
                raise OsascoRtcContractError("National NFS-e required for taxpayer competence")


@dataclass(frozen=True, slots=True)
class OsascoNoteReference:
    """Municipal note identifiers, not independent tax authorization or XML."""

    number: str
    authenticator: str
    identifier: str

    def __post_init__(self) -> None:
        if (
            not self.number.isascii() or not self.number.isdecimal()
            or not 1 <= len(self.number) <= 20
            or not self.authenticator.isascii()
            or not 1 <= len(self.authenticator) <= 64
            or not self.authenticator.isalnum()
            or not self.identifier.isascii()
            or not 1 <= len(self.identifier) <= 64
            or not self.identifier.isalnum()
        ):
            raise OsascoRtcContractError("Invalid municipal note identity")


@dataclass(frozen=True, slots=True)
class OsascoOperationReceipt:
    method: str
    fiscal_error: bool
    # SOAP true/false and municipal number cannot independently authorize
    # the immutable original NFS-e without official document proof.
    confirmed_authorization: bool = False
    status_available: bool = True
    note_reference: OsascoNoteReference | None = None
    response_xml: bytes = field(default=b"", repr=False)


def _canonical_request(body: bytes, method: str) -> etree._Element:
    try:
        root = etree.fromstring(
            body, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise OsascoRtcContractError("Invalid Osasco WCF prepared XML") from None
    if (
        root.tag != f"{{{_WCF}}}{method}"
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise OsascoRtcContractError("Osasco WCF method root or DTD mismatch")
    wrappers = root.findall(f"{{{_WCF}}}request")
    if len(wrappers) != 1:
        raise OsascoRtcContractError("Osasco SOAP requires exactly one request object")
    # RTC_EmitirNFELote nests its key under the Notas DTO; the other
    # methods use a direct child. Match exactly one in either layout.
    keys = [
        node for node in wrappers[0].iter()
        if etree.QName(node).localname == "ChaveAutenticacao"
    ]
    if len(keys) != 1 or (keys[0].text or "") != "":
        # A secret is inserted below from a trusted provider; user XML must
        # never choose a foreign taxpayer authentication key.
        raise OsascoRtcContractError("Osasco WCF key placeholder is missing or supplied")
    return root


def _build_soap(prepared: OsascoPreparedOperation, key: str) -> bytes:
    if (
        not isinstance(key, str) or len(key) != 36 or not key.isascii()
        or not all(c.isalnum() or c == "-" for c in key)
    ):
        raise OsascoRtcContractError("Scoped municipality credential unavailable")
    root = _canonical_request(prepared.request_xml, prepared.method)
    nodes = [
        node for node in root.iter()
        if etree.QName(node).localname == "ChaveAutenticacao"
    ]
    if len(nodes) != 1:
        raise OsascoRtcContractError("Credential placement not found")
    nodes[0].text = key
    soap = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(soap, f"{{{_SOAP}}}Body")
    body.append(root)
    return etree.tostring(soap, encoding="utf-8", xml_declaration=True)


def _exchange(body: bytes, action: str, timeout: float) -> bytes:
    """WCF HTTPS only; the per-CNPJ auth key lives in SOAP, never the URL."""
    req = Request(
        OSASCO_HOMOLOGATION_URL, data=body, method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"' + action + '"',
            "Accept": "text/xml",
        },
    )
    try:
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()),
                              RejectFiscalRedirects())
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(_MAX + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError):
        raise OsascoRtcContractError(
            "Osasco WCF indisponivel; consultar nota antes de retransmitir"
        ) from None
    if not 0 < len(raw) <= _MAX:
        raise OsascoRtcContractError("Osasco SOAP reply exceeded limit or is empty")
    return bytes(raw)


def _parse_reply(raw: bytes, method: str) -> OsascoOperationReceipt:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX:
        raise OsascoRtcContractError("Missing bounded Osasco SOAP reply")
    try:
        root = etree.fromstring(
            raw, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise OsascoRtcContractError("Invalid Osasco response XML") from None
    if root.tag != f"{{{_SOAP}}}Envelope" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise OsascoRtcContractError("Invalid Osasco SOAP root")
    body = root.find(f"{{{_SOAP}}}Body")
    if body is None or body.find(f"{{{_SOAP}}}Fault") is not None:
        raise OsascoRtcContractError("Osasco SOAP fault")
    nodes = body.findall(f"{{{_WCF}}}{method}Response")
    if len(nodes) != 1:
        raise OsascoRtcContractError("Osasco response operation mismatch")
    results = nodes[0].findall(f"{{{_WCF}}}{method}Result")
    if len(results) != 1:
        raise OsascoRtcContractError("Osasco response result mismatch")
    errors = results[0].findall(f".//{{{_DTO}}}Erro")
    if not errors and method == "ConsultarNotaCompleta":
        # Municipal v2.1 returns complete XML rather than Erro boolean.
        # Preserve evidence but keep official authorization unconfirmed.
        return OsascoOperationReceipt(
            method=method, fiscal_error=False, status_available=False,
            response_xml=raw,
        )
    if len(errors) != 1 or (errors[0].text or "").strip().lower() not in (
        "true", "false",
    ):
        raise OsascoRtcContractError("Osasco response lacks canonical fiscal status")
    failed = (errors[0].text or "").strip().lower() == "true"
    note: OsascoNoteReference | None = None
    references = results[0].findall(f"{{{_DTO}}}NotaFiscalGerada")
    if len(references) > 1:
        raise OsascoRtcContractError("Ambiguous municipal note references")
    if references and failed:
        raise OsascoRtcContractError("Osasco response carries contradictory note and error")
    if references:
        candidate = references[0]
        def one(name: str) -> str:
            nodes = candidate.findall(f"{{{_PRESTADOR}}}{name}")
            if len(nodes) != 1 or not nodes[0].text:
                raise OsascoRtcContractError("Osasco note identity incomplete")
            return nodes[0].text.strip()
        note = OsascoNoteReference(
            number=one("Numero"),
            authenticator=one("Autenticador"),
            identifier=one("Identificador"),
        )
    return OsascoOperationReceipt(
        method=method, fiscal_error=failed,
        note_reference=note,
        response_xml=raw,
    )


class OsascoRtcHomologationTransport:
    """Opt-in municipal WebService access with two independent local authorities."""

    def __init__(
        self, *,
        resolver: ProviderSelectionResolver,
        resolve_key: Callable[[ExecutionScope, str], str],
        validated_request: Callable[[bytes, str], None],
        contract_for_method: Callable[[str], OsascoWcfContract],
        exchange: Callable[[bytes, str, float], bytes] | None = None,
    ) -> None:
        if not all(callable(x) for x in (
            getattr(resolver, "resolve_provider_id", None), resolve_key,
            validated_request, contract_for_method,
        )):
            raise ValueError("Osasco requires durable provider, credential and WSDL ports")
        self._resolver = resolver
        self._key = resolve_key
        self._validator = validated_request
        self._contract = contract_for_method
        self._exchange = exchange or _exchange

    def invoke(self, prepared: OsascoPreparedOperation) -> OsascoOperationReceipt:
        if not isinstance(prepared, OsascoPreparedOperation):
            raise OsascoRtcContractError("Trusted Osasco fiscal payload required")
        method = prepared.method
        contract = self._contract(method)
        if not isinstance(contract, OsascoWcfContract) or contract.method != method:
            raise OsascoRtcContractError("Osasco WSDL method binding not verified")
        selected = self._resolver.resolve_provider_id(
            scope=prepared.scope,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", OSASCO_IBGE),
            operation=_OPERATIONS[method],
        )
        if selected != OSASCO_RTC_PROVIDER_ID:
            raise OsascoRtcContractError("Osasco durable provider mismatch")
        _canonical_request(prepared.request_xml, method)
        self._validator(prepared.request_xml, contract.wsdl_sha256)
        key = self._key(prepared.scope, prepared.issuer_cnpj.value)
        body = _build_soap(prepared, key)
        raw = self._exchange(body, contract.action, 15)
        return _parse_reply(raw, method)
