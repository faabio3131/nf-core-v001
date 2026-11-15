"""Jundiaí GissOnline V2 NFS-e ABRASF 2.04 mTLS SOAP boundary.

Public city-linked WSDL: https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl
Docs and current XSD: https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html

Signed and schema-validating ABRASF 2.04 XML must be prepared by an
independent canonical service. This module does not pretend that the MG
ABRASF 2.03 or WebISS XSD is GissOnline's current official schema.
The externally verified WSDL action/namespace must be configured with
a checked sha256, not inferred from similar Ginfes provider names.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

JUNDIAI_IBGE = "3525904"
JUNDIAI_GISS_PROVIDER_ID = "jundiai-giss-v2-homologation"
JUNDIAI_GISS_TEST_URL = "https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_GISS = "http://www.giss.com.br/"
_GISS_HEADER = _GISS + "cabecalho-v2_04.xsd"
_GISS_REQUEST_ROOTS = {
    "RecepcionarLoteRps": (
        "EnviarLoteRpsEnvio", _GISS + "enviar-lote-rps-envio-v2_04.xsd",
    ),
    "ConsultarLoteRps": (
        "ConsultarLoteRpsEnvio", _GISS + "consultar-lote-rps-envio-v2_04.xsd",
    ),
    "ConsultarNfsePorRps": (
        "ConsultarNfseRpsEnvio", _GISS + "consultar-nfse-rps-envio-v2_04.xsd",
    ),
    "CancelarNfse": (
        "CancelarNfseEnvio", _GISS + "cancelar-nfse-envio-v2_04.xsd",
    ),
}
_GISS_RESPONSE_ROOTS = {
    "RecepcionarLoteRps": (
        "EnviarLoteRpsResposta", _GISS + "enviar-lote-rps-resposta-v2_04.xsd",
    ),
    "ConsultarLoteRps": (
        "ConsultarLoteRpsResposta", _GISS + "consultar-lote-rps-resposta-v2_04.xsd",
    ),
    "ConsultarNfsePorRps": (
        "ConsultarNfseRpsResposta", _GISS + "consultar-nfse-rps-resposta-v2_04.xsd",
    ),
    "CancelarNfse": (
        "CancelarNfseResposta", _GISS + "cancelar-nfse-resposta-v2_04.xsd",
    ),
}
_MAX = 2_097_152
_OPERATION_MAP = {
    "RecepcionarLoteRps": "authorize",
    "ConsultarLoteRps": "query",
    "ConsultarNfsePorRps": "query",
    "CancelarNfse": "cancel",
}


class JundiaiGissContractError(FiscalValidationError):
    """Municipality-specific, sanitized SOAP and fiscal policy failure."""


@dataclass(frozen=True, slots=True)
class JundiaiGissWsdlContract:
    """Official action and method namespace pin; cannot guess Ginfes or WebISS."""

    method: str
    action: str
    service_namespace: str
    xsd_package_sha256: str
    wsdl_sha256: str

    def __post_init__(self) -> None:
        if (
            self.method not in _OPERATION_MAP
            or not self.action.startswith("http")
            or not self.service_namespace.startswith("http")
            or any(x in self.action + self.service_namespace for x in '"<>\r\n ')
            or any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
                   for x in (self.xsd_package_sha256, self.wsdl_sha256))
        ):
            raise JundiaiGissContractError("Unverified Jundiai Giss contract or schema")


@dataclass(frozen=True, slots=True)
class JundiaiSignedOperation:
    scope: ExecutionScope
    issuer_cnpj: Cnpj
    tax_regime: TaxRegimeCode
    competence_date: date
    method: str
    # Official signed ABRASF XML payload to be XSD-validated by trusted port.
    signed_xml: bytes = field(repr=False)
    # Required for all mutating NFS-e events, never implicit.
    human_approved: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ExecutionScope)
            or self.scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not self.scope.host_namespace
            or not isinstance(self.issuer_cnpj, Cnpj)
            or not isinstance(self.tax_regime, TaxRegimeCode)
            or type(self.competence_date) is not date
            or self.method not in _OPERATION_MAP
            or not isinstance(self.signed_xml, bytes)
            or not 0 < len(self.signed_xml) <= _MAX
        ):
            raise JundiaiGissContractError("Invalid Jundiai prepared fiscal request")
        if self.method == "CancelarNfse" and self.human_approved is not True:
            raise JundiaiGissContractError("Human approval required for cancellation")
        if self.method == "RecepcionarLoteRps":
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
                raise JundiaiGissContractError("National NFS-e required for issuer")


@dataclass(frozen=True, slots=True)
class JundiaiGissReceipt:
    method: str
    # These statuses are only evidence from the municipal result document.
    batch_protocol: str | None
    batch_state: int | None
    authorized: bool
    # Canonical authorization requires invoice identity correlation, XML
    # archive and audited lifecycle separately.
    confirmed_document_authorization: bool = False
    response_xml: bytes = field(default=b"", repr=False)
    official_response_xml: bytes = field(default=b"", repr=False)


def _validate_xml_shape(payload: bytes, method: str) -> etree._Element:
    if method not in _OPERATION_MAP:
        raise JundiaiGissContractError("Unknown Jundiai operation")
    try:
        root = etree.fromstring(
            payload, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissContractError("Invalid Giss XML") from None
    if bool(getattr(root.getroottree().docinfo, "doctype", "")):
        raise JundiaiGissContractError("Giss DTD is forbidden")
    expected_root, namespace = _GISS_REQUEST_ROOTS[method]
    if root.tag != f"{{{namespace}}}{expected_root}":
        raise JundiaiGissContractError("Giss NFS-e operation XML root mismatch")
    return root


def _soap(operation: JundiaiSignedOperation, contract: JundiaiGissWsdlContract) -> bytes:
    # SOAP 1.1 document/literal wrapped; caller's XSD and XMLDSig validators
    # must run separately before this method is called.
    root = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soapenv": _SOAP})
    body = etree.SubElement(root, f"{{{_SOAP}}}Body")
    method_node = etree.SubElement(
        body, f"{{{contract.service_namespace}}}{operation.method}Request"
    )
    header = etree.SubElement(method_node, "nfseCabecMsg")
    header.text = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<cabecalho versao="2.04" xmlns="http://www.giss.com.br/cabecalho-v2_04.xsd">'
        '<versaoDados>2.04</versaoDados></cabecalho>'
    )
    message = etree.SubElement(method_node, "nfseDadosMsg")
    message.text = operation.signed_xml.decode("utf-8")
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def _exchange(data: bytes, action: str, tls: ssl.SSLContext, timeout: float) -> bytes:
    request = Request(
        JUNDIAI_GISS_TEST_URL, data=data, method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"' + action + '"',
            "Accept": "text/xml",
        },
    )
    try:
        opener = build_opener(HTTPSHandler(context=tls), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(_MAX + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise JundiaiGissContractError(
            "GissOnline indisponivel; consultar protocolo antes de retransmitir"
        ) from None
    if not 0 < len(raw) <= _MAX:
        raise JundiaiGissContractError("Invalid GissOnline SOAP size")
    return bytes(raw)


def _parse_reply(raw: bytes, method: str) -> JundiaiGissReceipt:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX:
        raise JundiaiGissContractError("Missing GissOnline SOAP response")
    try:
        root = etree.fromstring(
            raw, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissContractError("Invalid GissOnline SOAP XML") from None
    if root.tag != f"{{{_SOAP}}}Envelope" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise JundiaiGissContractError("Unexpected GissOnline SOAP root")
    body = root.find(f"{{{_SOAP}}}Body")
    if body is None or body.find(f"{{{_SOAP}}}Fault") is not None:
        raise JundiaiGissContractError("GissOnline SOAP Fault")
    # GissOnline JAX-WS returns escaped, service-specific XML inside outputXML.
    # Preserve it so the separately pinned XSD and official signature verifier
    # can correlate CompNfse with the originally reserved RPS.
    embedded = [
        n for n in body.iter()
        if etree.QName(n).localname == "outputXML"
    ]
    if len(embedded) > 1:
        raise JundiaiGissContractError("Ambiguous GissOnline outputXML")
    official = b""
    fiscal_root = body
    if embedded:
        node = embedded[0]
        parent = node.getparent()
        if (
            parent is None
            or etree.QName(parent).localname != method + "Response"
            or not isinstance(node.text, str)
            or not node.text.strip()
        ):
            raise JundiaiGissContractError("GissOnline outputXML wrapper mismatch")
        official = node.text.strip().encode("utf-8")
        if len(official) > _MAX:
            raise JundiaiGissContractError("GissOnline official reply exceeds limit")
        try:
            fiscal_root = etree.fromstring(
                official, parser=etree.XMLParser(
                    resolve_entities=False, no_network=True, load_dtd=False,
                ),
            )
        except etree.XMLSyntaxError:
            raise JundiaiGissContractError("GissOnline returned invalid official XML") from None
        expected, namespace = _GISS_RESPONSE_ROOTS[method]
        if (
            fiscal_root.tag != f"{{{namespace}}}{expected}"
            or bool(getattr(fiscal_root.getroottree().docinfo, "doctype", ""))
        ):
            raise JundiaiGissContractError("GissOnline fiscal response namespace mismatch")
    leaves = list(fiscal_root.iter())
    protocols = [
        n.text for n in leaves
        if etree.QName(n).localname == "Protocolo" and n.text
    ]
    situations = [
        n.text for n in leaves
        if etree.QName(n).localname == "Situacao" and n.text
    ]
    if len(protocols) > 1 or len(situations) > 1:
        raise JundiaiGissContractError("Ambiguous GissOnline result")
    state = int(situations[0]) if situations and situations[0] in {"1", "2", "3", "4"} else None
    if situations and state is None:
        raise JundiaiGissContractError("Invalid Giss batch state")
    if protocols and len(protocols[0]) > 128:
        raise JundiaiGissContractError("GissOnline protocol exceeds limit")
    # Even status 4 requires query by the durable RPS plus XSD/XML proof;
    # the SOAP status itself can never authorize or cancel a fiscal invoice.
    return JundiaiGissReceipt(
        method=method, batch_protocol=protocols[0] if protocols else None,
        batch_state=state, authorized=state == 4,
        response_xml=raw, official_response_xml=official,
    )


class JundiaiGissHomologationTransport:
    """Requires strict tenant binding, A1 identity and official 2.04 XSD/signatures."""

    def __init__(
        self, *,
        resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        contract_for_method: Callable[[str], JundiaiGissWsdlContract],
        validate_signed_xml: Callable[[bytes, str, str], None],
        exchange: Callable[[bytes, str, ssl.SSLContext, float], bytes] | None = None,
    ) -> None:
        if not all(callable(x) for x in (
            getattr(resolver, "resolve_provider_id", None),
            resolve_certificate, contract_for_method, validate_signed_xml,
        )):
            raise ValueError("Jundiai requires reviewed WSDL, signature and schema ports")
        self._resolver = resolver
        self._certificate = resolve_certificate
        self._contract = contract_for_method
        self._validate = validate_signed_xml
        self._exchange = exchange or _exchange

    def invoke(self, request: JundiaiSignedOperation) -> JundiaiGissReceipt:
        if not isinstance(request, JundiaiSignedOperation):
            raise JundiaiGissContractError("Canonical Giss NFS-e payload required")
        contract = self._contract(request.method)
        if not isinstance(contract, JundiaiGissWsdlContract) or contract.method != request.method:
            raise JundiaiGissContractError("Jundiai Giss WSDL method mismatch")
        selected = self._resolver.resolve_provider_id(
            scope=request.scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", JUNDIAI_IBGE),
            operation=_OPERATION_MAP[request.method],
        )
        if selected != JUNDIAI_GISS_PROVIDER_ID:
            raise JundiaiGissContractError("Jundiai durable binding missing")
        _validate_xml_shape(request.signed_xml, request.method)
        self._validate(
            request.signed_xml, contract.xsd_package_sha256, contract.wsdl_sha256,
        )
        cert = self._certificate(request.scope, request.issuer_cnpj.value)
        validate_a1_for_issuer(
            cert.pkcs12_bytes, cert.password, issuer_cnpj=request.issuer_cnpj,
            at=datetime.now(UTC),
        )
        raw = self._exchange(
            _soap(request, contract), contract.action,
            build_fiscal_tls_context(cert), 15,
        )
        return _parse_reply(raw, request.method)
