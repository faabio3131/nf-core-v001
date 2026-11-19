"""Official SEFAZ NF-e 4.00 homologation authorization over TLS/mTLS.

Operates only with an authorized, signed model-55 XML envelope and a
scope-bound A1 identity. No synthetic responses or production endpoints.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
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
from kordena_fiscal.signing.nfe_xmldsig import (
    NfeSignatureProfile,
    sign_nfe_envi_xml,
    verify_official_nfe4_signature,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

from .authorization import (
    AuthorizationRequest,
    AuthorizationResult,
    AuthorizationStatus,
    GatewayProviderMetadata,
)
from .fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context

NFE_SP_HOMOLOGATION_AUTHORIZATION_URL = resolve_sefaz_endpoint(
    state_ibge_code="35", document_kind=FiscalDocumentKind.NFE,
    environment=FiscalEnvironment.HOMOLOGATION, service=SefazService.AUTHORIZE,
).url
SOAP12_NAMESPACE = "http://www.w3.org/2003/05/soap-envelope"
NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
SERVICE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4"
XMLDSIG_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
_MAX_RESPONSE_BYTES = 2_097_152
_PROVIDER = GatewayProviderMetadata("sefaz-sp-homologacao-nfe4", "1.0")


class OfficialNfeTransportError(FiscalValidationError):
    """Sanitized transport failure, without certificate or response contents."""


def _parse_xml(data: bytes) -> etree._Element:
    if len(data) > _MAX_RESPONSE_BYTES or not data:
        raise OfficialNfeTransportError("XML fiscal ausente ou excede limite")
    try:
        return etree.fromstring(
            data, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise OfficialNfeTransportError("XML fiscal inválido") from None


def _text(element: etree._Element, name: str) -> str | None:
    found = element.find(".//{" + NFE_NAMESPACE + "}" + name)
    return found.text.strip() if found is not None and found.text else None


def _signed_homologation_xml(request: AuthorizationRequest, xml_bytes: bytes) -> etree._Element:
    if request.scope.environment is not FiscalEnvironment.HOMOLOGATION:
        raise OfficialNfeTransportError("Somente homologação (tpAmb=2) permitida")
    root = _parse_xml(xml_bytes)
    if root.tag != "{" + NFE_NAMESPACE + "}enviNFe":
        raise OfficialNfeTransportError("Autorização requer enviNFe 4.00")
    if root.get("versao") != "4.00":
        raise OfficialNfeTransportError("Versão de NF-e não suportada")
    invoices = root.findall("{" + NFE_NAMESPACE + "}NFe")
    if not invoices:
        raise OfficialNfeTransportError("Lote de NF-e vazio")
    for invoice in invoices:
        info = invoice.find("{" + NFE_NAMESPACE + "}infNFe")
        signature = invoice.find("{" + XMLDSIG_NAMESPACE + "}Signature")
        ambient = invoice.find(
            ".//{" + NFE_NAMESPACE + "}ide/{" + NFE_NAMESPACE + "}tpAmb"
        )
        if info is None or info.get("Id") != "NFe" + request.access_key.value:
            raise OfficialNfeTransportError("Chave de acesso não corresponde ao XML")
        if info is None or signature is None or ambient is None or ambient.text != "2":
            raise OfficialNfeTransportError("NF-e exige assinatura XMLDSig e tpAmb=2")
        signed_info = signature.find("{" + XMLDSIG_NAMESPACE + "}SignedInfo")
        sig_value = signature.find("{" + XMLDSIG_NAMESPACE + "}SignatureValue")
        if signed_info is None or sig_value is None or not sig_value.text:
            raise OfficialNfeTransportError("Assinatura XMLDSig incompleta")
    return root



def _authorized_nfe_proc(
    signed_envi: etree._Element, reply: etree._Element, request: AuthorizationRequest
) -> bytes:
    """Only matching protocol 100 + signed NFe become an archiveable nfeProc."""
    invoices = signed_envi.findall("{" + NFE_NAMESPACE + "}NFe")
    protocols = reply.findall(".//{" + NFE_NAMESPACE + "}protNFe")
    if len(invoices) != 1 or len(protocols) != 1:
        raise OfficialNfeTransportError("Autorização requer uma NF-e e protocolo únicos")
    protocol = protocols[0]
    info = protocol.find("{" + NFE_NAMESPACE + "}infProt")
    invoice_info = invoices[0].find("{" + NFE_NAMESPACE + "}infNFe")
    if (
        info is None or invoice_info is None
        or invoice_info.get("Id") != "NFe" + request.access_key.value
        or _text(info, "chNFe") != request.access_key.value
        or _text(info, "tpAmb") != "2"
        or _text(info, "cStat") != "100"
        or not _text(info, "nProt")
        or not _text(info, "digVal")
    ):
        raise OfficialNfeTransportError("Protocolo SEFAZ não corresponde à NF-e assinada")
    proc = etree.Element("{" + NFE_NAMESPACE + "}nfeProc", nsmap={None: NFE_NAMESPACE},  # type: ignore[dict-item]
                         versao="4.00")
    proc.append(etree.fromstring(etree.tostring(invoices[0])))
    proc.append(etree.fromstring(etree.tostring(protocol)))
    data = etree.tostring(proc, encoding="utf-8", xml_declaration=True)
    if len(data) > _MAX_RESPONSE_BYTES:
        raise OfficialNfeTransportError("XML protocolado excede limite")
    return data

def _soap_envelope(invoice_batch: etree._Element) -> bytes:
    envelope = etree.Element(
        "{" + SOAP12_NAMESPACE + "}Envelope",
        nsmap={None: SOAP12_NAMESPACE},  # type: ignore[dict-item]
    )
    body = etree.SubElement(envelope, "{" + SOAP12_NAMESPACE + "}Body")
    data = etree.SubElement(
        body, "{" + SERVICE_NAMESPACE + "}nfeDadosMsg", nsmap={None: SERVICE_NAMESPACE}  # type: ignore[dict-item]
    )
    data.append(invoice_batch)
    return etree.tostring(envelope, encoding="utf-8", xml_declaration=True)


def _tls_context(material: EphemeralCertificateMaterial) -> ssl.SSLContext:
    try:
        return build_fiscal_tls_context(material)
    except FiscalValidationError as exc:
        raise OfficialNfeTransportError(str(exc)) from None


MG_NFE_HOMOLOGATION_PROVIDER_ID = "sefaz-mg-homologacao-nfe4"
MG_NFCE_HOMOLOGATION_PROVIDER_ID = "sefaz-mg-homologacao-nfce4"


class HomologationAuthorizationTarget(StrEnum):
    """Engineering configuration only; never an HTTP/provider binding authority."""

    SP_NFE = "sp_nfe"
    MG_NFE = "mg_nfe"
    MG_NFCE = "mg_nfce"


def _validate_mg_authorization_scope(
    request: AuthorizationRequest, *, model: int = 55,
) -> None:
    """Fail closed on wrong state/model and malformed NFC-e QR before A1/HTTP."""
    if model not in (55, 65):
        raise OfficialNfeTransportError("MG authorizer supports only models 55 and 65")
    if request.scope.environment is not FiscalEnvironment.HOMOLOGATION:
        raise OfficialNfeTransportError("MG authorization requires tpAmb=2")
    if request.access_key.value[:2] != "31" or request.access_key.model.value != model:
        raise OfficialNfeTransportError(f"MG authorization requires model {model} key")
    root = _parse_xml(request.signed_xml)
    invoices = root.findall(f"{{{NFE_NAMESPACE}}}NFe")
    if root.tag != f"{{{NFE_NAMESPACE}}}enviNFe" or root.get("versao") != "4.00":
        raise OfficialNfeTransportError("MG authorization requires enviNFe 4.00")
    if len(invoices) != 1:
        raise OfficialNfeTransportError("MG authorization requires exactly one invoice")
    info = invoices[0].find(f"{{{NFE_NAMESPACE}}}infNFe")
    if info is None or info.get("Id") != "NFe" + request.access_key.value:
        raise OfficialNfeTransportError("MG XML access key mismatch")
    ide = info.find(f"{{{NFE_NAMESPACE}}}ide")
    issuer = info.find(f"{{{NFE_NAMESPACE}}}emit")
    if ide is None or issuer is None:
        raise OfficialNfeTransportError("MG XML fiscal identity missing")
    for field, expected in (("cUF", "31"), ("mod", str(model)), ("tpAmb", "2")):
        if ide.findtext(f"{{{NFE_NAMESPACE}}}{field}") != expected:
            raise OfficialNfeTransportError("MG XML state/model/environment mismatch")
    if issuer.findtext(f"{{{NFE_NAMESPACE}}}CNPJ") != request.access_key.issuer_identifier:
        raise OfficialNfeTransportError("MG XML issuer mismatch")
    if model == 65:
        # NFC-e 65 must use synchronous batch authorization, one invoice.
        if root.findtext(f"{{{NFE_NAMESPACE}}}indSinc") != "1":
            raise OfficialNfeTransportError("NFC-e MG65 requires synchronous authorization")
        supplement = invoices[0].find(f"{{{NFE_NAMESPACE}}}infNFeSupl")
        qr = supplement.findtext(f"{{{NFE_NAMESPACE}}}qrCode") if supplement is not None else None
        link = (
            supplement.findtext(f"{{{NFE_NAMESPACE}}}urlChave")
            if supplement is not None else None
        )
        if not qr or not link:
            raise OfficialNfeTransportError("NFC-e MG65 requires QR Code and consultation URL")
        qr_parts, link_parts = urlsplit(qr), urlsplit(link)
        qr_params = parse_qs(qr_parts.query)
        values = qr_params.get("p", [])
        qr_fields = values[0].split("|") if len(values) == 1 else []
        emission_type = ide.findtext(f"{{{NFE_NAMESPACE}}}tpEmis")
        if emission_type != "1":
            # QR v3 offline tpEmis=9 needs A1 signature on 8 fields.
            # Do not accept a fabricated 'assinatura' or fallback to CSC v2.
            raise OfficialNfeTransportError(
                "NFC-e MG65 contingencia exige QR v3 com assinatura certificada"
            )
        # NT 2025.001 v1.03: v3 online is exactly chave|3|tpAmb.
        # v3 contingency and v2 have different cryptographic contracts.
        if (
            qr_parts.scheme != "https"
            or qr_parts.netloc != "portalsped.fazenda.mg.gov.br"
            or qr_parts.path != "/portalnfce/sistema/qrcode.xhtml"
            or set(qr_params) != {"p"}
            or qr_fields != [request.access_key.value, "3", "2"]
            or link_parts.scheme != "https"
            or link_parts.netloc != "hportalsped.fazenda.mg.gov.br"
            or link_parts.path.rstrip("/") != "/portalnfce"
            or bool(link_parts.query)
        ):
            raise OfficialNfeTransportError("NFC-e MG65 QR/consulta divergem da SEFAZ")


class SefazHomologationAuthorizationGateway:
    """Shared SOAP authorization; explicit targets, no runtime auto-activation."""

    def __init__(
        self,
        *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        target: HomologationAuthorizationTarget = HomologationAuthorizationTarget.SP_NFE,
        validate_schema: Callable[[bytes], None] | None = None,
        timeout_seconds: float = 15.0,
        exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
    ) -> None:
        if not callable(resolve_certificate) or not 0 < timeout_seconds <= 60:
            raise ValueError("Invalid fiscal transport configuration")
        if not isinstance(target, HomologationAuthorizationTarget):
            raise ValueError("Unknown homologation authorization target")
        if target in {
            HomologationAuthorizationTarget.MG_NFE,
            HomologationAuthorizationTarget.MG_NFCE,
        } and not callable(validate_schema):
            raise ValueError("MG authorization requires a trusted XSD validator")
        self._target = target
        self._validate_schema = validate_schema
        self._endpoint = NFE_SP_HOMOLOGATION_AUTHORIZATION_URL
        self._provider = _PROVIDER
        if target in {
            HomologationAuthorizationTarget.MG_NFE,
            HomologationAuthorizationTarget.MG_NFCE,
        }:
            from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
            from kordena_fiscal.control_plane.mg_official_homologation_catalog import (
                mg_homologation_endpoint,
            )

            self._endpoint = mg_homologation_endpoint(
                document_kind=(
                    FiscalDocumentKind.NFCE
                    if target is HomologationAuthorizationTarget.MG_NFCE
                    else FiscalDocumentKind.NFE
                ),
                environment=FiscalEnvironment.HOMOLOGATION,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
            ).url
            provider_id = (
                MG_NFCE_HOMOLOGATION_PROVIDER_ID
                if target is HomologationAuthorizationTarget.MG_NFCE
                else MG_NFE_HOMOLOGATION_PROVIDER_ID
            )
            self._provider = GatewayProviderMetadata(provider_id, "1.0")
        self._resolve_certificate = resolve_certificate
        self._timeout = timeout_seconds
        self._exchange = exchange or self._https_exchange

    def _https_exchange(self, payload: bytes, context: ssl.SSLContext, timeout: float) -> bytes:
        req = Request(
            self._endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": (
                    "application/soap+xml; charset=utf-8; "
                    'action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote"'
                ),
                "Accept": "application/soap+xml",
            },
        )
        opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
        try:
            with opener.open(req, timeout=timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise OfficialNfeTransportError("Resposta fiscal excede limite")
            return bytes(raw)
        except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
            raise OfficialNfeTransportError(
                "Comunicação com a SEFAZ indisponível; verifique o resultado antes de reenviar"
            ) from None

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResult:
        if not isinstance(request, AuthorizationRequest):
            raise OfficialNfeTransportError("Solicitação de autorização fiscal inválida")
        mg_target = self._target in {
            HomologationAuthorizationTarget.MG_NFE,
            HomologationAuthorizationTarget.MG_NFCE,
        }
        if mg_target:
            _validate_mg_authorization_scope(
                request,
                model=65 if self._target is HomologationAuthorizationTarget.MG_NFCE else 55,
            )
            if self._validate_schema is None:
                raise OfficialNfeTransportError("MG XSD validator unavailable")
        material = self._resolve_certificate(
            request.scope, request.access_key.issuer_identifier
        )
        if not isinstance(material, EphemeralCertificateMaterial):
            raise OfficialNfeTransportError("Certificado A1 não cadastrado para o CNPJ emitente")
        validate_a1_for_issuer(
            material.pkcs12_bytes,
            material.password,
            issuer_cnpj=Cnpj(request.access_key.issuer_identifier),
            at=datetime.now(UTC),
        )
        unsigned = _parse_xml(request.signed_xml)
        signed_bytes = request.signed_xml
        if unsigned.find(".//{" + XMLDSIG_NAMESPACE + "}Signature") is None:
            signed_bytes = sign_nfe_envi_xml(
                request.signed_xml, material,
                profile=(
                    NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
                    if mg_target
                    else NfeSignatureProfile.RSA_SHA256
                ),
            )
        xml = _signed_homologation_xml(request, signed_bytes)
        if self._validate_schema is not None:
            self._validate_schema(signed_bytes)
        if mg_target:
            verify_official_nfe4_signature(xml, material)
        context = _tls_context(material)
        response = _parse_xml(
            self._exchange(_soap_envelope(xml), context, self._timeout)
        )
        if response.find(".//{" + SOAP12_NAMESPACE + "}Fault") is not None:
            raise OfficialNfeTransportError("SEFAZ retornou falha SOAP")
        result = response.find(".//{" + NFE_NAMESPACE + "}retEnviNFe")
        if result is None or _text(result, "tpAmb") != "2":
            raise OfficialNfeTransportError("Resposta da SEFAZ sem homologação válida")
        if mg_target:
            if _text(result, "cUF") != "31":
                raise OfficialNfeTransportError("MG response state mismatch")
        code = _text(result, "cStat")
        reason = _text(result, "xMotivo")
        if not code:
            raise OfficialNfeTransportError("Resposta de autorização sem código de status")
        receipt = _text(result, "nRec")
        if code in {"103", "104", "105"}:
            protocol = result.find(".//{" + NFE_NAMESPACE + "}infProt")
            authorization_code = _text(protocol, "cStat") if protocol is not None else None
            protocol_no = _text(protocol, "nProt") if protocol is not None else None
            if code == "104" and authorization_code == "100" and protocol_no:
                if mg_target:
                    digest = xml.findtext(".//{" + XMLDSIG_NAMESPACE + "}DigestValue")
                    if not digest or protocol is None or _text(protocol, "digVal") != digest:
                        raise OfficialNfeTransportError("MG protocol digest mismatch")
                authorized_xml = _authorized_nfe_proc(xml, result, request)
                return AuthorizationResult(
                    status=AuthorizationStatus.AUTHORIZED,
                    scope=request.scope,
                    access_key=request.access_key,
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request.request_fingerprint,
                    provider=self._provider,
                    provider_request_id=receipt,
                    protocol_reference=protocol_no,
                    authorized_xml=authorized_xml,
                )
            if code in {"103", "105"}:
                status = AuthorizationStatus.PENDING
            elif authorization_code and authorization_code not in {"100", "105"}:
                status = AuthorizationStatus.REJECTED
                code = authorization_code
                reason = _text(protocol, "xMotivo") if protocol is not None else reason
            else:
                status = AuthorizationStatus.PENDING
        else:
            status = AuthorizationStatus.REJECTED
        return AuthorizationResult(
            status=status,
            scope=request.scope,
            access_key=request.access_key,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=self._provider,
            provider_request_id=receipt,
            rejection_code=code if status is AuthorizationStatus.REJECTED else None,
            rejection_message=(reason or "Rejeição fiscal")[:512]
            if status is AuthorizationStatus.REJECTED else None,
        )


class SefazSpHomologationGateway(SefazHomologationAuthorizationGateway):
    """Compatibility entrypoint retaining SP-only engineering configuration."""

    def __init__(
        self,
        *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        timeout_seconds: float = 15.0,
        exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
    ) -> None:
        super().__init__(
            resolve_certificate=resolve_certificate,
            timeout_seconds=timeout_seconds,
            exchange=exchange,
            target=HomologationAuthorizationTarget.SP_NFE,
        )


def build_mg_nfe_homologation_gateway(
    *,
    resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
    timeout_seconds: float = 15.0,
    exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
) -> SefazHomologationAuthorizationGateway:
    """Compose MG with the pinned canonical invoice XSD validator, without activation."""
    from kordena_fiscal.xml.official_operation_schema import OfficialOperationXmlValidator

    validator = OfficialOperationXmlValidator(("NFeAutorizacao4",))

    def validate_envelope(xml: bytes) -> None:
        validator("NFeAutorizacao4", xml)

    return SefazHomologationAuthorizationGateway(
        target=HomologationAuthorizationTarget.MG_NFE,
        resolve_certificate=resolve_certificate,
        validate_schema=validate_envelope,
        timeout_seconds=timeout_seconds,
        exchange=exchange,
    )


def build_mg_nfce_homologation_gateway(
    *,
    resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
    timeout_seconds: float = 15.0,
    exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
) -> SefazHomologationAuthorizationGateway:
    """Explicit MG NFC-e model 65 gateway; no provider binding or runtime activation.

    QR Code must already be constructed for the authenticated issuer with its
    applicable NT version. The gateway refuses missing/wrong MG QR values
    before reading A1; schema/signature/authorization remain mandatory.
    """
    from kordena_fiscal.xml.official_operation_schema import OfficialOperationXmlValidator

    validator = OfficialOperationXmlValidator(("NFeAutorizacao4",))

    def validate_envelope(xml: bytes) -> None:
        validator("NFeAutorizacao4", xml)

    return SefazHomologationAuthorizationGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=resolve_certificate,
        validate_schema=validate_envelope,
        timeout_seconds=timeout_seconds,
        exchange=exchange,
    )
