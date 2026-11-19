"""Real SEFAZ-SP NF-e 4.00 homologation query, cancellation and inutilization.

HTTPS/mTLS to fixed, government-published homologation endpoints; only
tenant-bound A1 material is accepted. Responses are normalized strictly.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.control_plane.sefaz_endpoint_catalog import SefazService, resolve_sefaz_endpoint
from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import GatewayProviderMetadata
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects
from kordena_fiscal.gateway.nfe_sp_homologation import (
    MG_NFCE_HOMOLOGATION_PROVIDER_ID,
    MG_NFE_HOMOLOGATION_PROVIDER_ID,
    NFE_NAMESPACE,
    SOAP12_NAMESPACE,
    HomologationAuthorizationTarget,
    _parse_xml,
    _tls_context,
)
from kordena_fiscal.operations import (
    CancellationRequest,
    CancellationResult,
    FiscalEventStatus,
    FiscalQueryRequest,
    FiscalQueryResult,
    FiscalQueryStatus,
    InutilizationRequest,
    InutilizationResult,
)
from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_event_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

_SERVICE_ROOT = "http://www.portalfiscal.inf.br/nfe/wsdl/"
_PROVIDER = GatewayProviderMetadata("sefaz-sp-homologacao-nfe4", "1.0")
_MAX_RESPONSE_BYTES = 2_097_152
_SERVICES = {
    "NFeConsultaProtocolo4": (SefazService.QUERY, "nfeConsultaNF"),
    "NFeRecepcaoEvento4": (SefazService.CANCEL, "nfeRecepcaoEvento"),
    "NFeInutilizacao4": (SefazService.INUTILIZE, "nfeInutilizacaoNF"),
}


class OfficialNfeOperationsError(FiscalValidationError):
    """Non-secret transport or provider response failure."""


def _tag(parent: etree._Element, local: str, value: str) -> etree._Element:
    child = etree.SubElement(parent, f"{{{NFE_NAMESPACE}}}{local}")
    child.text = value
    return child


def _value(node: etree._Element, tag: str) -> str | None:
    element = node.find(".//{" + NFE_NAMESPACE + "}" + tag)
    return element.text.strip() if element is not None and element.text else None


def _envelope(data: etree._Element, service: str) -> bytes:
    parent = etree.Element(
        f"{{{SOAP12_NAMESPACE}}}Envelope", nsmap={None: SOAP12_NAMESPACE}  # type: ignore[dict-item]
    )
    body = etree.SubElement(parent, f"{{{SOAP12_NAMESPACE}}}Body")
    msg = etree.SubElement(
        body, f"{{{_SERVICE_ROOT}{service}}}nfeDadosMsg",
        nsmap={None: _SERVICE_ROOT + service},  # type: ignore[dict-item]
    )
    msg.append(data)
    return etree.tostring(parent, encoding="utf-8", xml_declaration=True)


def _post_official(
    service: str, payload: bytes, context: ssl.SSLContext, timeout: float
) -> bytes:
    if service not in _SERVICES:
        raise OfficialNfeOperationsError("Unsupported SP fiscal service")
    route_service, _ = _SERVICES[service]
    endpoint = resolve_sefaz_endpoint(
        state_ibge_code="35", document_kind=FiscalDocumentKind.NFE,
        environment=FiscalEnvironment.HOMOLOGATION, service=route_service,
    ).url
    return _post_xml(service, endpoint, payload, context, timeout)


def _post_xml(
    service: str, endpoint: str, payload: bytes, context: ssl.SSLContext, timeout: float
) -> bytes:
    operation = _SERVICES[service][1]
    request = Request(
        endpoint, method="POST", data=payload,
        headers={
            "Content-Type": (
                "application/soap+xml; charset=utf-8; "
                f'action="{_SERVICE_ROOT}{service}/{operation}"'
            ),
            "Accept": "application/soap+xml",
        },
    )
    try:
        opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as answer:
            result = answer.read(_MAX_RESPONSE_BYTES + 1)
        if len(result) > _MAX_RESPONSE_BYTES:
            raise OfficialNfeOperationsError("Resposta SEFAZ excede limite")
        return bytes(result)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise OfficialNfeOperationsError(
            "SEFAZ indisponível; consulte resultado antes de retransmitir"
        ) from None


class SefazHomologationOperationsGateway:
    """Real operations adapter for query, cancel and inutilize in tpAmb=2."""

    def __init__(
        self,
        *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        resolve_issuer: Callable[[ExecutionScope], str] | None = None,
        target: HomologationAuthorizationTarget = HomologationAuthorizationTarget.SP_NFE,
        exchange: Callable[[str, bytes, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if not callable(resolve_certificate) or not 0 < timeout_seconds <= 60:
            raise ValueError("Fiscal operations require approved A1 resolver")
        if not isinstance(target, HomologationAuthorizationTarget):
            raise ValueError("Unknown fiscal operations target")
        self._target = target
        self._state = (
            "31" if target in {
                HomologationAuthorizationTarget.MG_NFE,
                HomologationAuthorizationTarget.MG_NFCE,
            } else "35"
        )
        self._model = "65" if target is HomologationAuthorizationTarget.MG_NFCE else "55"
        if target is HomologationAuthorizationTarget.MG_NFCE:
            self._provider = GatewayProviderMetadata(MG_NFCE_HOMOLOGATION_PROVIDER_ID, "1.0")
        elif target is HomologationAuthorizationTarget.MG_NFE:
            self._provider = GatewayProviderMetadata(MG_NFE_HOMOLOGATION_PROVIDER_ID, "1.0")
        else:
            self._provider = _PROVIDER
        self._profile = (
            NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
            if self._state == "31" else NfeSignatureProfile.RSA_SHA256
        )
        self._validator: Callable[[str, bytes], None] | None = None
        self._mg_endpoints: dict[str, str] = {}
        if self._state == "31":
            from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
            from kordena_fiscal.control_plane.mg_official_homologation_catalog import (
                mg_homologation_endpoint,
            )
            from kordena_fiscal.xml.official_operation_schema import OfficialOperationXmlValidator
            self._validator = OfficialOperationXmlValidator(tuple(_SERVICES))
            for service, operation in (
                ("NFeConsultaProtocolo4", ConfiguredFiscalOperation.QUERY),
                ("NFeRecepcaoEvento4", ConfiguredFiscalOperation.CANCEL),
                ("NFeInutilizacao4", ConfiguredFiscalOperation.INUTILIZE),
            ):
                self._mg_endpoints[service] = mg_homologation_endpoint(
                    document_kind=(
                        FiscalDocumentKind.NFCE
                        if self._model == "65" else FiscalDocumentKind.NFE
                    ),
                    environment=FiscalEnvironment.HOMOLOGATION, operation=operation,
                ).url
        self._resolve_certificate = resolve_certificate
        self._resolve_issuer = resolve_issuer
        self._exchange = exchange or self._https_exchange
        self._timeout = timeout_seconds

    def _https_exchange(
        self, service: str, payload: bytes, context: ssl.SSLContext, timeout: float,
    ) -> bytes:
        if self._state == "35":
            return _post_official(service, payload, context, timeout)
        if service not in self._mg_endpoints:
            raise OfficialNfeOperationsError("Unknown MG fiscal operation")
        return _post_xml(service, self._mg_endpoints[service], payload, context, timeout)

    def _validate_key(self, value: str) -> None:
        if value[:2] != self._state or (self._state == "31" and value[20:22] != self._model):
            raise OfficialNfeOperationsError("Fiscal operation state/model mismatch")

    def _certificate(
        self, scope: ExecutionScope, issuer_cnpj: str
    ) -> EphemeralCertificateMaterial:
        if scope.environment is not FiscalEnvironment.HOMOLOGATION:
            raise OfficialNfeOperationsError("Somente ambiente tpAmb=2 permitido")
        material = self._resolve_certificate(scope, issuer_cnpj)
        if not isinstance(material, EphemeralCertificateMaterial):
            raise OfficialNfeOperationsError("Scoped A1 certificate unavailable")
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=Cnpj(issuer_cnpj), at=datetime.now(UTC),
        )
        return material

    def _send(
        self, service: str, root: etree._Element,
        material: EphemeralCertificateMaterial,
    ) -> etree._Element:
        if self._validator is not None:
            self._validator(service, etree.tostring(root, encoding="utf-8"))
        response = _parse_xml(self._exchange(
            service, _envelope(root, service), _tls_context(material), self._timeout,
        ))
        if response.find(f".//{{{SOAP12_NAMESPACE}}}Fault") is not None:
            raise OfficialNfeOperationsError("SEFAZ retornou falha SOAP")
        return response

    def query(self, request: FiscalQueryRequest) -> FiscalQueryResult:
        self._validate_key(request.access_key.value)
        material = self._certificate(request.scope, request.access_key.issuer_identifier)
        root = etree.Element(
            f"{{{NFE_NAMESPACE}}}consSitNFe",
            nsmap={None: NFE_NAMESPACE},  # type: ignore[dict-item]
            versao="4.00",
        )
        _tag(root, "tpAmb", "2")
        _tag(root, "xServ", "CONSULTAR")
        _tag(root, "chNFe", request.access_key.value)
        answer = self._send("NFeConsultaProtocolo4", root, material)
        response = answer.find(f".//{{{NFE_NAMESPACE}}}retConsSitNFe")
        if response is None or _value(response, "tpAmb") != "2":
            raise OfficialNfeOperationsError("Resposta de consulta não é homologação")
        if self._state == "31" and _value(response, "cUF") != "31":
            raise OfficialNfeOperationsError("MG query response state mismatch")
        if self._state == "31" and _value(response, "chNFe") != request.access_key.value:
            raise OfficialNfeOperationsError("MG query response key mismatch")
        code = _value(response, "cStat")
        if code == "100":
            protocol = _value(response, "nProt")
            if not protocol:
                raise OfficialNfeOperationsError("Protocolo de autorização ausente")
            status = FiscalQueryStatus.AUTHORIZED
        elif code in {"101", "151"}:
            protocol = None
            status = FiscalQueryStatus.CANCELLED
        elif code == "217":
            protocol = None
            status = FiscalQueryStatus.NOT_FOUND
        elif code in {"105", "106", "108", "109"}:
            protocol = None
            status = FiscalQueryStatus.PENDING
        else:
            raise OfficialNfeOperationsError("Consulta fiscal rejeitada ou inconsistente")
        return FiscalQueryResult(
            status=status, scope=request.scope, access_key=request.access_key,
            provider=self._provider, protocol_reference=protocol,
        )

    def cancel(self, request: CancellationRequest) -> CancellationResult:
        self._validate_key(request.access_key.value)
        issuer = request.access_key.issuer_identifier
        material = self._certificate(request.scope, issuer)
        root = etree.Element(
            f"{{{NFE_NAMESPACE}}}envEvento",
            nsmap={None: NFE_NAMESPACE},  # type: ignore[dict-item]
            versao="1.00",
        )
        _tag(root, "idLote", "1")
        event = etree.SubElement(root, f"{{{NFE_NAMESPACE}}}evento", versao="1.00")
        info = etree.SubElement(
            event, f"{{{NFE_NAMESPACE}}}infEvento",
            Id="ID110111" + request.access_key.value + "01",
        )
        for name, value in (
            ("cOrgao", self._state), ("tpAmb", "2"), ("CNPJ", issuer),
            ("chNFe", request.access_key.value),
            ("dhEvento", datetime.now().astimezone().isoformat(timespec="seconds")),
            ("tpEvento", "110111"), ("nSeqEvento", "1"), ("verEvento", "1.00"),
        ):
            _tag(info, name, value)
        details = etree.SubElement(info, f"{{{NFE_NAMESPACE}}}detEvento", versao="1.00")
        for name, value in (
            ("descEvento", "Cancelamento"), ("nProt", request.authorization_protocol),
            ("xJust", request.justification),
        ):
            _tag(details, name, value)
        signed = sign_nfe_event_xml(
            etree.tostring(root), material,
            root_name="envEvento", signed_name="infEvento", parent_name="evento",
            profile=self._profile,
        )
        answer = self._send(
            "NFeRecepcaoEvento4", _parse_xml(signed), material,
        )
        result = answer.find(f".//{{{NFE_NAMESPACE}}}retEvento/{{{NFE_NAMESPACE}}}infEvento")
        if result is None or _value(result, "tpAmb") != "2":
            raise OfficialNfeOperationsError("Resposta de cancelamento inconsistente")
        if self._state == "31" and any(
            _value(result, name) != expected for name, expected in (
                ("cOrgao", "31"), ("chNFe", request.access_key.value),
                ("tpEvento", "110111"), ("nSeqEvento", "1"),
            )
        ):
            raise OfficialNfeOperationsError("MG cancellation response correlation mismatch")
        code = _value(result, "cStat")
        if code in {"135", "155"} and _value(result, "nProt"):
            return CancellationResult(
                status=FiscalEventStatus.ACCEPTED, scope=request.scope,
                access_key=request.access_key, request_id=request.request_id,
                provider=self._provider, event_protocol_reference=_value(result, "nProt"),
            )
        if code is None:
            raise OfficialNfeOperationsError("Status de cancelamento ausente")
        return CancellationResult(
            status=FiscalEventStatus.REJECTED, scope=request.scope,
            access_key=request.access_key, request_id=request.request_id,
            provider=self._provider, rejection_code=code,
            rejection_message=(_value(result, "xMotivo") or "Cancelamento rejeitado")[:512],
        )

    def inutilize(self, request: InutilizationRequest) -> InutilizationResult:
        if request.scope.environment is not FiscalEnvironment.HOMOLOGATION:
            raise OfficialNfeOperationsError("Only homologation inutilization allowed")
        if request.model.value != int(self._model):
            raise OfficialNfeOperationsError(
                f"Inutilization model {request.model.value} disagrees with "
                f"gateway model {self._model}"
            )
        if self._resolve_issuer is None:
            raise OfficialNfeOperationsError("Emitente da unidade não configurado")
        issuer = self._resolve_issuer(request.scope)
        material = self._certificate(request.scope, issuer)
        year = datetime.now(UTC).strftime("%y")
        identifier = (
            "ID" + self._state + year + issuer + self._model + f"{request.series:03}"
            + f"{request.first_number:09}" + f"{request.last_number:09}"
        )
        root = etree.Element(
            f"{{{NFE_NAMESPACE}}}inutNFe",
            nsmap={None: NFE_NAMESPACE},  # type: ignore[dict-item]
            versao="4.00",
        )
        info = etree.SubElement(root, f"{{{NFE_NAMESPACE}}}infInut", Id=identifier)
        for name, value in (
            ("tpAmb", "2"), ("xServ", "INUTILIZAR"), ("cUF", self._state),
            ("ano", year), ("CNPJ", issuer), ("mod", self._model),
            ("serie", str(request.series)), ("nNFIni", str(request.first_number)),
            ("nNFFin", str(request.last_number)), ("xJust", request.justification),
        ):
            _tag(info, name, value)
        signed = sign_nfe_event_xml(
            etree.tostring(root), material,
            root_name="inutNFe", signed_name="infInut", parent_name="inutNFe",
            profile=self._profile,
        )
        answer = self._send("NFeInutilizacao4", _parse_xml(signed), material)
        result = answer.find(f".//{{{NFE_NAMESPACE}}}retInutNFe/{{{NFE_NAMESPACE}}}infInut")
        if result is None or _value(result, "tpAmb") != "2":
            raise OfficialNfeOperationsError("Resposta de inutilização inconsistente")
        if self._state == "31" and any(
            _value(result, name) != expected for name, expected in (
                ("cUF", "31"), ("ano", year), ("CNPJ", issuer), ("mod", self._model),
                ("serie", str(request.series)), ("nNFIni", str(request.first_number)),
                ("nNFFin", str(request.last_number)),
            )
        ):
            raise OfficialNfeOperationsError("MG inutilization response correlation mismatch")
        code = _value(result, "cStat")
        if code == "102" and _value(result, "nProt"):
            return InutilizationResult(
                status=FiscalEventStatus.ACCEPTED, scope=request.scope,
                model=request.model, series=request.series,
                first_number=request.first_number, last_number=request.last_number,
                request_id=request.request_id, provider=self._provider,
                event_protocol_reference=_value(result, "nProt"),
            )
        if code is None:
            raise OfficialNfeOperationsError("Status de inutilização ausente")
        return InutilizationResult(
            status=FiscalEventStatus.REJECTED, scope=request.scope,
            model=request.model, series=request.series,
            first_number=request.first_number, last_number=request.last_number,
            request_id=request.request_id, provider=self._provider,
            rejection_code=code,
            rejection_message=(_value(result, "xMotivo") or "Inutilização rejeitada")[:512],
        )


class SefazSpHomologationOperationsGateway(SefazHomologationOperationsGateway):
    """Compatibility wrapper fixed to SP; generic target is never inherited from HTTP."""

    def __init__(
        self, *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        resolve_issuer: Callable[[ExecutionScope], str] | None = None,
        exchange: Callable[[str, bytes, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        super().__init__(
            resolve_certificate=resolve_certificate, resolve_issuer=resolve_issuer,
            exchange=exchange, timeout_seconds=timeout_seconds,
            target=HomologationAuthorizationTarget.SP_NFE,
        )
