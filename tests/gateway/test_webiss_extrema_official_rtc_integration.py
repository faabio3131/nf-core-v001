"""Extrema RTC XSD goldens and complete ten-method SOAP transport, no real POST.

Signed fixtures use the repository's synthetic A1 test certificate. Municipal
rejection receipts are XSD-valid but NEVER fiscal authorization evidence.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest
from lxml import etree
from test_mg_homologation_authorization import CNPJ, _request
from test_mg_homologation_authorization import material as material
from test_nfse_abrasf203_envelope import _CANCEL, _payload

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.mg_webiss_soap import (
    EXTREMA_WEBISS_PROVIDER_ID,
    WebissExtremaHomologationTransport,
    WebissMgContractError,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import (
    Abrasf203Operation,
    prepare_abrasf203_soap,
)
from kordena_fiscal.gateway.webiss_2026_schema import (
    WebissMunicipalSchemaUnverified,
    load_pinned_extrema_webiss_rtc_schema,
    require_extrema_rtc_destination_order,
)
from kordena_fiscal.xml.schema import XmlSchemaValidationError

_NS = "http://www.abrasf.org.br/nfse.xsd"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_SVC = "http://nfse.abrasf.org.br"
_CITY = BrazilianJurisdiction("MG", "3125101")
_QUERY_OPS = (
    Abrasf203Operation.QUERY_BATCH,
    Abrasf203Operation.QUERY_RPS,
    Abrasf203Operation.QUERY_ISSUED,
    Abrasf203Operation.QUERY_RECEIVED,
    Abrasf203Operation.QUERY_RANGE,
)
_METHOD_RESPONSE = {
    Abrasf203Operation.GENERATE: "GerarNfseResposta",
    Abrasf203Operation.SUBMIT_BATCH: "EnviarLoteRpsResposta",
    Abrasf203Operation.SUBMIT_BATCH_SYNC: "EnviarLoteRpsSincronoResposta",
    Abrasf203Operation.QUERY_BATCH: "ConsultarLoteRpsResposta",
    Abrasf203Operation.QUERY_RPS: "ConsultarNfseRpsResposta",
    Abrasf203Operation.QUERY_ISSUED: "ConsultarNfseServicoPrestadoResposta",
    Abrasf203Operation.QUERY_RECEIVED: "ConsultarNfseServicoTomadoResposta",
    Abrasf203Operation.QUERY_RANGE: "ConsultarNfseFaixaResposta",
    Abrasf203Operation.CANCEL: "CancelarNfseResposta",
    Abrasf203Operation.SUBSTITUTE: "SubstituirNfseResposta",
}


def _query_payload(operation: Abrasf203Operation, cnpj: str = CNPJ) -> bytes:
    name = operation.value[0]
    p = f"<Prestador><CpfCnpj><Cnpj>{cnpj}</Cnpj></CpfCnpj></Prestador>"
    if operation is Abrasf203Operation.QUERY_BATCH:
        inner = p + "<Protocolo>123</Protocolo>"
    elif operation is Abrasf203Operation.QUERY_RPS:
        inner = (
            "<IdentificacaoRps><Numero>123</Numero><Serie>A</Serie><Tipo>1</Tipo>"
            "</IdentificacaoRps>" + p
        )
    elif operation is Abrasf203Operation.QUERY_ISSUED:
        inner = p + "<Pagina>1</Pagina>"
    elif operation is Abrasf203Operation.QUERY_RECEIVED:
        inner = (
            f"<Consulente><CpfCnpj><Cnpj>{cnpj}</Cnpj></CpfCnpj></Consulente>"
            "<Pagina>1</Pagina>"
        )
    elif operation is Abrasf203Operation.QUERY_RANGE:
        inner = (
            p + "<Faixa><NumeroNfseInicial>1</NumeroNfseInicial></Faixa>"
            "<Pagina>1</Pagina>"
        )
    else:
        raise AssertionError("Unsupported synthetic query fixture")
    return f'<{name} xmlns="{_NS}">{inner}</{name}>'.encode()


def _payload_for(operation: Abrasf203Operation) -> bytes:
    if operation in _QUERY_OPS:
        return _query_payload(operation)
    if operation is Abrasf203Operation.CANCEL:
        return _CANCEL.encode()
    if operation is Abrasf203Operation.SUBSTITUTE:
        root = etree.Element(f"{{{_NS}}}SubstituirNfseEnvio", nsmap={None: _NS})
        group = etree.SubElement(root, f"{{{_NS}}}SubstituicaoNfse", Id="SUBST1")
        cancelled = etree.fromstring(_CANCEL.encode())
        replacement = etree.fromstring(_payload(Abrasf203Operation.GENERATE))
        group.append(cancelled[0])
        group.append(replacement[0])
        return etree.tostring(root)
    if operation is Abrasf203Operation.SUBMIT_BATCH_SYNC:
        raw = _payload(Abrasf203Operation.SUBMIT_BATCH)
        return raw.replace(b"EnviarLoteRpsEnvio", b"EnviarLoteRpsSincronoEnvio").replace(
            b'versao="2.03"', b'versao="2.02"',
        ).replace(b"5002704", b"3125101")
    return _payload(operation).replace(b"5002704", b"3125101").replace(
        b'versao="2.03"', b'versao="2.02"',
    )


def _error_xml(operation: Abrasf203Operation) -> bytes:
    name = _METHOD_RESPONSE[operation]
    situacao = "<Situacao>4</Situacao>" if operation is Abrasf203Operation.QUERY_BATCH else ""
    inner = (
        "<ListaMensagemRetorno><MensagemRetorno><Codigo>E160</Codigo>"
        "<Mensagem>Rejeicao sintetica XSD</Mensagem></MensagemRetorno>"
        "</ListaMensagemRetorno>"
    )
    return f'<{name} xmlns="{_NS}">{situacao}{inner}</{name}>'.encode()


def _soap_response(operation: Abrasf203Operation) -> bytes:
    soap = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(soap, f"{{{_SOAP}}}Body")
    wrapper = etree.SubElement(body, f"{{{_SVC}}}{operation.value[1]}Response")
    etree.SubElement(wrapper, "outputXML").text = _error_xml(operation).decode()
    return etree.tostring(soap)


def test_official_extrema_schema_is_pinned_and_reproducibly_compiles_offline():
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    assert evidence.municipality_ibge == "3125101"
    assert evidence.schema_version == "2.02"
    assert evidence.schema_package_sha256 == (
        "8e0f2a9174cbfafa5a601a7003c5f3d4408ceadd01de1e87b9be12c09cc762ee"
    )
    header = (
        f'<cabecalho xmlns="{_NS}" versao="2.02">'
        "<versaoDados>2.02</versaoDados></cabecalho>"
    ).encode()
    validator.validate_document(header)
    for op in Abrasf203Operation:
        validator.validate_document(_error_xml(op))


@pytest.mark.parametrize("operation", _QUERY_OPS)
def test_all_five_official_unsigned_queries_validate_and_keep_issuer_scope(operation):
    _, validator = load_pinned_extrema_webiss_rtc_schema()
    validator.validate_document(_query_payload(operation))
    with pytest.raises(XmlSchemaValidationError):
        validator.validate_document(_query_payload(operation).replace(
            b"<Pagina>1</Pagina>", b"", 1,
        )) if operation in (
            Abrasf203Operation.QUERY_ISSUED,
            Abrasf203Operation.QUERY_RECEIVED,
            Abrasf203Operation.QUERY_RANGE,
        ) else validator.validate_document(b"<bad/>")
    resolver = Mock()
    payload = _query_payload(operation, cnpj="0" * 14)
    with pytest.raises(FiscalValidationError, match="issuer mismatch"):
        prepare_abrasf203_soap(
            operation=operation, xml=payload, scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ), resolve_certificate=resolver,
            preaudit=Mock(), municipal_schema_version="2.02",
            municipal_validator=validator,
        )
    resolver.assert_not_called()


@pytest.mark.parametrize("operation", list(Abrasf203Operation))
def test_all_ten_fiscal_operations_round_trip_with_official_xsd_and_no_network(
    material, operation,
):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    calls = Mock()
    calls.cert.return_value = material
    calls.exchange.return_value = _soap_response(operation)
    payload = _payload_for(operation)
    validator.validate_document(payload)
    signed = prepare_abrasf203_soap(
        operation=operation, xml=payload, scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), resolve_certificate=calls.cert,
        preaudit=calls.audit, preaudit_cancel=calls.cancel_audit,
        municipal_schema_version="2.02", municipal_validator=validator,
    )
    assert signed.schema_version == "2.02"
    assert signed.schema_package_sha256 == evidence.schema_package_sha256
    calls.cert.reset_mock()
    calls.audit.reset_mock()
    calls.cancel_audit.reset_mock()
    resolver = Mock()
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=calls.cert,
        exchange=calls.exchange, municipal_schema_evidence=evidence,
        municipal_schema_validator=validator,
    )
    returned = gateway.exchange_prepared(
        envelope=signed, operation=operation, scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31), jurisdiction=_CITY,
    )
    assert returned == _error_xml(operation)
    assert calls.exchange.call_count == 1
    assert calls.cert.call_count == 1
    expected_binding_count = 2 if operation is Abrasf203Operation.SUBSTITUTE else 1
    assert resolver.resolve_provider_id.call_count == expected_binding_count
    calls.exchange.assert_called_once()
    assert signed.soap_action == f'"{_SVC}/{operation.value[1]}"'
    wrapper = etree.fromstring(signed.body)[0][0]
    content = etree.fromstring(wrapper.findtext("nfseDadosMsg").encode())
    signatures = content.findall(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
    expected_sigs = {
        Abrasf203Operation.GENERATE: 1,
        Abrasf203Operation.SUBMIT_BATCH: 2,
        Abrasf203Operation.SUBMIT_BATCH_SYNC: 2,
        Abrasf203Operation.CANCEL: 1,
        Abrasf203Operation.SUBSTITUTE: 3,
    }.get(operation, 0)
    assert len(signatures) == expected_sigs


def test_substitution_requires_independent_approve_and_cancel_bindings(material):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    resolver = Mock()
    resolver.resolve_provider_id.side_effect = [
        EXTREMA_WEBISS_PROVIDER_ID, "wrong-authorizer",
    ]
    get_cert = Mock(return_value=material)
    exchange = Mock()
    op = Abrasf203Operation.SUBSTITUTE
    signed = prepare_abrasf203_soap(
        operation=op, xml=_payload_for(op), scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), resolve_certificate=get_cert,
        preaudit=Mock(), preaudit_cancel=Mock(),
        municipal_schema_version="2.02", municipal_validator=validator,
    )
    get_cert.reset_mock()
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=get_cert,
        exchange=exchange, municipal_schema_evidence=evidence,
        municipal_schema_validator=validator,
    )
    with pytest.raises(WebissMgContractError, match="both cancellation and issuance"):
        gateway.exchange_prepared(
            envelope=signed, operation=op, scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31), jurisdiction=_CITY,
        )
    get_cert.assert_not_called()
    exchange.assert_not_called()


def test_wrong_municipality_and_prod_environment_never_reach_vault(material):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    operation = Abrasf203Operation.QUERY_RECEIVED
    prepared = prepare_abrasf203_soap(
        operation=operation, xml=_query_payload(operation), scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), resolve_certificate=Mock(), preaudit=Mock(),
        municipal_schema_version="2.02", municipal_validator=validator,
    )
    resolver, get_cert, exchange = Mock(), Mock(return_value=material), Mock()
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=get_cert,
        exchange=exchange, municipal_schema_evidence=evidence,
        municipal_schema_validator=validator,
    )
    for scope, municipality in (
        (_request().scope, BrazilianJurisdiction("MG", "3170107")),
        (replace(_request().scope, environment=FiscalEnvironment.PRODUCTION), _CITY),
    ):
        with pytest.raises(WebissMgContractError, match="scoped MG municipality"):
            gateway.exchange_prepared(
                envelope=prepared, operation=operation, scope=scope,
                issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
                competence_date=date(2026, 10, 31), jurisdiction=municipality,
            )
    get_cert.assert_not_called()
    exchange.assert_not_called()


def test_official_rtc_dest_order_remains_fail_closed_without_rewrite():
    ns = f'xmlns="{_NS}"'
    wrong = (
        f"<GerarNfseEnvio {ns}><Rps><InfDeclaracaoPrestacaoServico>"
        "<IBSCBS><indDest>1</indDest><dest>"
        "<xNome>Destinatario</xNome><CNPJ>11222333000181</CNPJ>"
        "</dest></IBSCBS></InfDeclaracaoPrestacaoServico></Rps></GerarNfseEnvio>"
    ).encode()
    with pytest.raises(WebissMunicipalSchemaUnverified, match="recipient identification"):
        require_extrema_rtc_destination_order(wrong)
