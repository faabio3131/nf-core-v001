"""Cajamar GeisWeb municipal NFS-e with explicit WSDL/XSD/A1 safeguards.

The platform has operated GeisWeb and requires taxpayer-specific WebService
enablement. Do not assume a third-party connector URI proves a current
municipal production service. Endpoint and SOAP action are explicitly
approved from the authority's WSDL, by SHA-256 pin, on a per-tenant basis.

Municipal evidence and provider manual:
https://cajamar.sp.gov.br/fazenda/servicos-online/
CGSN Resolution 191/2026 ME/EPP Nov 1 by service competence:
https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026
https://atendimento.tecnospeed.com.br/hc/pt-br/articles/1500006998382-Documentacao-Tecnica-Padrao-GeisWeb20
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
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

CAJAMAR_IBGE = "3509205"
CAJAMAR_GEISWEB_PROVIDER = "cajamar-geisweb-homologation"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_LIMIT = 2_097_152
_ALLOWED_HOSTS = frozenset({
    "geisweb.net.br", "www.geisweb.net.br", "www.gerenciadecidades.com.br",
    "gerenciadecidades.com.br",
})
_METHODS = {
    "EnviaLoteRps": "authorize",
    "ConsultaLoteRps": "query",
    "ConsultaNfse": "query",
    "CancelaNfse": "cancel",
}


class CajamarGeiswebContractError(FiscalValidationError):
    """Sanitized municipal GeisWeb provider boundary failure."""


@dataclass(frozen=True, slots=True)
class CajamarGeiswebWsdl:
    """Official endpoint and XSD version must be proven before each activation."""

    endpoint: str
    namespace: str
    wsdl_sha256: str
    xsd_package_sha256: str
    method_actions: dict[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or not self.endpoint.endswith("/GeisWebServiceImpl.php")
            or not self.namespace.startswith("http")
            or any(x in self.namespace for x in '<>\r\n" ')
            or any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
                   for x in (self.wsdl_sha256, self.xsd_package_sha256))
            or set(self.method_actions) != set(_METHODS)
            or not all(
                isinstance(action, str) and action.startswith("http")
                and not any(c in action for c in '<>\r\n" ')
                for action in self.method_actions.values()
            )
        ):
            raise CajamarGeiswebContractError("Unverified Cajamar municipal WSDL/XSD")


@dataclass(frozen=True, slots=True)
class CajamarPreparedNfse:
    scope: ExecutionScope
    issuer_cnpj: Cnpj
    tax_regime: TaxRegimeCode
    competence_date: date
    method: str
    signed_request_xml: bytes = field(repr=False)
    human_approved: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ExecutionScope)
            or self.scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not self.scope.host_namespace
            or not isinstance(self.issuer_cnpj, Cnpj)
            or not isinstance(self.tax_regime, TaxRegimeCode)
            or type(self.competence_date) is not date
            or self.method not in _METHODS
            or not isinstance(self.signed_request_xml, bytes)
            or not 0 < len(self.signed_request_xml) <= _LIMIT
        ):
            raise CajamarGeiswebContractError("Unreviewed Cajamar fiscal operation")
        if self.method == "EnviaLoteRps":
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
                raise CajamarGeiswebContractError(
                    "National NFS-e required for Cajamar fiscal competence"
                )
        if self.method == "CancelaNfse" and self.human_approved is not True:
            raise CajamarGeiswebContractError("Cancellation requires human approval")


@dataclass(frozen=True, slots=True)
class CajamarGeiswebResult:
    method: str
    # XML response requires independent correlation of original issuer, RPS
    # and official note reference before the canonical lifecycle is updated.
    confirmed_authorization: bool = False
    response_xml: bytes = field(default=b"", repr=False)


def _soap(req: CajamarPreparedNfse, contract: CajamarGeiswebWsdl) -> bytes:
    root = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(root, f"{{{_SOAP}}}Body")
    method = etree.SubElement(body, f"{{{contract.namespace}}}{req.method}")
    payload = etree.SubElement(method, "xml")
    payload.text = req.signed_request_xml.decode("utf-8")
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def _exchange(
    endpoint: str, soap_action: str, body: bytes, ssl_context: ssl.SSLContext, timeout: float,
) -> bytes:
    request = Request(
        endpoint, data=body, method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"' + soap_action + '"',
            "Accept": "text/xml",
        },
    )
    try:
        opener = build_opener(HTTPSHandler(context=ssl_context), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(_LIMIT + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise CajamarGeiswebContractError(
            "Cajamar GeisWeb indisponivel; consulte antes de retransmitir"
        ) from None
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise CajamarGeiswebContractError("Cajamar returned invalid SOAP payload")
    return raw


class CajamarGeiswebHomologationTransport:
    """Strict fiscal transport, never built from browser input or catalog labels."""

    def __init__(
        self, *,
        resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        signed_xml_validator: Callable[[bytes, str], None],
        contract: CajamarGeiswebWsdl,
        exchange: Callable[[str, str, bytes, ssl.SSLContext, float], bytes] | None = None,
    ) -> None:
        if not all(callable(x) for x in (
            getattr(resolver, "resolve_provider_id", None),
            resolve_certificate, signed_xml_validator,
        )) or not isinstance(contract, CajamarGeiswebWsdl):
            raise ValueError("Cajamar requires pinned WSDL/XSD, signing and A1 ports")
        self._resolver = resolver
        self._resolve_certificate = resolve_certificate
        self._validate = signed_xml_validator
        self._contract = contract
        self._exchange = exchange or _exchange

    def invoke(self, req: CajamarPreparedNfse) -> CajamarGeiswebResult:
        if not isinstance(req, CajamarPreparedNfse):
            raise CajamarGeiswebContractError("Canonical Cajamar operation required")
        selected = self._resolver.resolve_provider_id(
            scope=req.scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", CAJAMAR_IBGE),
            operation=_METHODS[req.method],
        )
        if selected != CAJAMAR_GEISWEB_PROVIDER:
            raise CajamarGeiswebContractError("Cajamar durable provider binding missing")
        try:
            root = etree.fromstring(
                req.signed_request_xml,
                parser=etree.XMLParser(resolve_entities=False, no_network=True),
            )
        except etree.XMLSyntaxError:
            raise CajamarGeiswebContractError("Invalid Cajamar XML") from None
        if bool(getattr(root.getroottree().docinfo, "doctype", "")):
            raise CajamarGeiswebContractError("Cajamar XML DTD forbidden")
        self._validate(req.signed_request_xml, self._contract.xsd_package_sha256)
        a1 = self._resolve_certificate(req.scope, req.issuer_cnpj.value)
        validate_a1_for_issuer(
            a1.pkcs12_bytes, a1.password, issuer_cnpj=req.issuer_cnpj,
            at=datetime.now(UTC),
        )
        raw = self._exchange(
            self._contract.endpoint, self._contract.method_actions[req.method],
            _soap(req, self._contract), build_fiscal_tls_context(a1), 15,
        )
        if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
            raise CajamarGeiswebContractError("Invalid bounded Cajamar SOAP result")
        try:
            node = etree.fromstring(
                raw, parser=etree.XMLParser(resolve_entities=False, no_network=True),
            )
        except etree.XMLSyntaxError:
            raise CajamarGeiswebContractError("Invalid Cajamar SOAP result") from None
        if node.tag != f"{{{_SOAP}}}Envelope" or bool(
            getattr(node.getroottree().docinfo, "doctype", "")
        ):
            raise CajamarGeiswebContractError("Unexpected Cajamar SOAP result")
        body = node.find(f"{{{_SOAP}}}Body")
        if body is None or body.find(f"{{{_SOAP}}}Fault") is not None:
            raise CajamarGeiswebContractError("Cajamar SOAP rejected operation")
        return CajamarGeiswebResult(method=req.method, response_xml=raw)
