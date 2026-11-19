"""Official-XSD positive municipal response contracts, all values synthetic.

Receiving a schema-valid invoice is deliberately NOT proof of municipal
homologation and this parser never promotes an application AuthorizationStatus.
"""
from __future__ import annotations

import pytest
from lxml import etree
from test_mg_homologation_authorization import CNPJ

from kordena_fiscal.domain import Cnpj
from kordena_fiscal.gateway.mg_webiss_soap import (
    WebissMgContractError,
    parse_webiss_soap_response,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import Abrasf203Operation
from kordena_fiscal.gateway.webiss_2026_schema import load_pinned_extrema_webiss_rtc_schema

_NS = "http://www.abrasf.org.br/nfse.xsd"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_SVC = "http://nfse.abrasf.org.br"
_OTHER_CNPJ = "98765432000100"


def _comp_nfse(*, issuer: str = CNPJ, buyer: str = CNPJ, number: str = "123") -> str:
    """Complete minimal authorized-looking receipt strictly for XSD and correlation tests."""
    source = (
        '<InfDeclaracaoPrestacaoServico Id="RPS1">'
        "<Competencia>2026-11-06</Competencia><Servico><Valores>"
        "<ValorServicos>100.00</ValorServicos><Aliquota>2.00</Aliquota></Valores>"
        "<IssRetido>2</IssRetido><ItemListaServico>01.01</ItemListaServico>"
        "<Discriminacao>Operacao sintetica, sem efeitos fiscais</Discriminacao>"
        "<CodigoMunicipio>3125101</CodigoMunicipio><ExigibilidadeISS>1</ExigibilidadeISS>"
        "</Servico>"
        f"<Prestador><CpfCnpj><Cnpj>{issuer}</Cnpj></CpfCnpj></Prestador>"
        "<Tomador><IdentificacaoTomador>"
        f"<CpfCnpj><Cnpj>{buyer}</Cnpj></CpfCnpj>"
        "</IdentificacaoTomador></Tomador>"
        "<OptanteSimplesNacional>2</OptanteSimplesNacional>"
        "<IncentivoFiscal>2</IncentivoFiscal></InfDeclaracaoPrestacaoServico>"
    )
    access_key = "312510100" + ("0" * 12) + ("0" * 29)
    return (
        '<CompNfse><Nfse versao="2.02"><InfNfse>'
        f"<Numero>{number}</Numero><CodigoVerificacao>ABC123</CodigoVerificacao>"
        "<DataEmissao>2026-11-11T00:00:00</DataEmissao>"
        "<ValoresNfse><ValorLiquidoNfse>100.00</ValorLiquidoNfse></ValoresNfse>"
        "<PrestadorServico><IdentificacaoPrestador><CpfCnpj>"
        f"<Cnpj>{issuer}</Cnpj></CpfCnpj></IdentificacaoPrestador>"
        "<RazaoSocial>Contribuinte sintetico</RazaoSocial><Endereco>"
        "<CodigoMunicipio>3125101</CodigoMunicipio><Uf>MG</Uf>"
        "</Endereco></PrestadorServico>"
        "<OrgaoGerador><CodigoMunicipio>3125101</CodigoMunicipio>"
        "<Uf>MG</Uf></OrgaoGerador>"
        f"<DeclaracaoPrestacaoServico>{source}</DeclaracaoPrestacaoServico>"
        f"<ChaveAcesso>{access_key}</ChaveAcesso>"
        "</InfNfse></Nfse></CompNfse>"
    )


def _accepted_xml(
    operation: Abrasf203Operation,
    *, buyer: str = CNPJ,
    issuer: str = CNPJ,
    municipality: str = "3125101",
) -> bytes:
    comp = _comp_nfse(issuer=issuer, buyer=buyer)
    name = {
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
    }[operation]
    if operation is Abrasf203Operation.SUBMIT_BATCH:
        inner = (
            "<NumeroLote>1</NumeroLote><DataRecebimento>2026-11-11T00:00:00</DataRecebimento>"
            "<Protocolo>98765</Protocolo>"
        )
    elif operation is Abrasf203Operation.CANCEL:
        inner = (
            '<RetCancelamento><NfseCancelamento versao="2.02"><Confirmacao>'
            '<Pedido><InfPedidoCancelamento Id="CANCEL1"><IdentificacaoNfse>'
            "<Numero>123</Numero><CpfCnpj>"
            f"<Cnpj>{issuer}</Cnpj></CpfCnpj>"
            f"<CodigoMunicipio>{municipality}</CodigoMunicipio>"
            "</IdentificacaoNfse><CodigoCancelamento>1</CodigoCancelamento>"
            "</InfPedidoCancelamento></Pedido>"
            "<DataHora>2026-11-11T00:00:00</DataHora>"
            "</Confirmacao></NfseCancelamento></RetCancelamento>"
        )
    elif operation is Abrasf203Operation.SUBSTITUTE:
        new = _comp_nfse(issuer=issuer, buyer=buyer, number="124")
        inner = (
            f"<RetSubstituicao><NfseSubstituida>{comp}</NfseSubstituida>"
            f"<NfseSubstituidora>{new}</NfseSubstituidora></RetSubstituicao>"
        )
    elif operation is Abrasf203Operation.QUERY_RPS:
        inner = comp
    elif operation is Abrasf203Operation.QUERY_BATCH:
        inner = f"<Situacao>4</Situacao><ListaNfse>{comp}</ListaNfse>"
    else:
        inner = f"<ListaNfse>{comp}</ListaNfse>"
    return f'<{name} xmlns="{_NS}">{inner}</{name}>'.encode()


def _wrap_soap(operation: Abrasf203Operation, inner: bytes) -> bytes:
    soap = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(soap, f"{{{_SOAP}}}Body")
    response = etree.SubElement(body, f"{{{_SVC}}}{operation.value[1]}Response")
    etree.SubElement(response, "outputXML").text = inner.decode()
    return etree.tostring(soap)


@pytest.mark.parametrize("operation", list(Abrasf203Operation))
def test_all_ten_positive_response_shapes_validate_official_xsd_and_round_trip(operation):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    kwargs = {"issuer": _OTHER_CNPJ} if operation is Abrasf203Operation.QUERY_RECEIVED else {}
    xml = _accepted_xml(operation, **kwargs)
    validator.validate_document(xml)
    received = parse_webiss_soap_response(
        _wrap_soap(operation, xml), operation,
        evidence=evidence, municipal_validator=validator,
        issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
    )
    assert received == xml


@pytest.mark.parametrize("operation", [
    Abrasf203Operation.GENERATE,
    Abrasf203Operation.QUERY_RPS,
    Abrasf203Operation.SUBSTITUTE,
])
def test_invoice_from_another_issuer_is_rejected_even_if_xsd_valid(operation):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    xml = _accepted_xml(operation, issuer=_OTHER_CNPJ)
    validator.validate_document(xml)
    with pytest.raises(WebissMgContractError, match="issuer or municipality"):
        parse_webiss_soap_response(
            _wrap_soap(operation, xml), operation,
            evidence=evidence, municipal_validator=validator,
            issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
        )


def test_received_invoice_must_belong_to_current_consulente():
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    operation = Abrasf203Operation.QUERY_RECEIVED
    xml = _accepted_xml(operation, issuer=_OTHER_CNPJ, buyer=_OTHER_CNPJ)
    validator.validate_document(xml)
    with pytest.raises(WebissMgContractError, match="bound consulente"):
        parse_webiss_soap_response(
            _wrap_soap(operation, xml), operation,
            evidence=evidence, municipal_validator=validator,
            issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
        )


def test_successful_cancellation_must_correlate_issuer_and_city():
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    operation = Abrasf203Operation.CANCEL
    for kwargs in ({"issuer": _OTHER_CNPJ}, {"municipality": "3170107"}):
        xml = _accepted_xml(operation, **kwargs)
        validator.validate_document(xml)
        with pytest.raises(WebissMgContractError, match="another fiscal issuer"):
            parse_webiss_soap_response(
                _wrap_soap(operation, xml), operation,
                evidence=evidence, municipal_validator=validator,
                issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
            )


def test_async_acceptance_is_only_a_protocol_not_fiscal_authorization():
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    operation = Abrasf203Operation.SUBMIT_BATCH
    xml = _accepted_xml(operation)
    assert b"<Protocolo>" in xml
    assert b"<CompNfse>" not in xml
    response = parse_webiss_soap_response(
        _wrap_soap(operation, xml), operation,
        evidence=evidence, municipal_validator=validator,
        issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
    )
    assert response == xml


def test_rejects_cross_soap_method_even_with_well_formed_accepted_xml():
    op = Abrasf203Operation.QUERY_RPS
    good_xml = _accepted_xml(op)
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    with pytest.raises(WebissMgContractError, match="method does not match"):
        parse_webiss_soap_response(
            _wrap_soap(Abrasf203Operation.GENERATE, good_xml),
            op, evidence=evidence, municipal_validator=validator,
            issuer_cnpj=Cnpj(CNPJ), municipality_ibge="3125101",
        )
