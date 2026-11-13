"""Jundiai GissOnline ABRASF204: offline guarded operations and receipt states."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    _GISS_REQUEST_ROOTS,
    JUNDIAI_GISS_PROVIDER_ID,
    JundiaiGissContractError,
    JundiaiGissHomologationTransport,
    JundiaiGissWsdlContract,
    JundiaiSignedOperation,
    _parse_reply,
    _soap,
)


def _request(
    method: str = "RecepcionarLoteRps",
    regime: TaxRegimeCode = TaxRegimeCode.NORMAL,
    competence: date = date(2026, 11, 13),
    approved: bool = False,
) -> JundiaiSignedOperation:
    root, namespace = _GISS_REQUEST_ROOTS[method]
    xml = f'<{root} xmlns="{namespace}"></{root}>'.encode()
    return JundiaiSignedOperation(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-j", unit_id="unit-j",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="giss-test",
        ),
        issuer_cnpj=Cnpj("11222333000181"),
        tax_regime=regime,
        competence_date=competence,
        method=method,
        signed_xml=xml,
        human_approved=approved,
    )


def _contract(method: str) -> JundiaiGissWsdlContract:
    return JundiaiGissWsdlContract(
        method=method, action="http://giss.com.br/" + method,
        service_namespace="http://giss.com.br/ws",
        xsd_package_sha256="a" * 64, wsdl_sha256="b" * 64,
    )


@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 13)),
])
def test_national_channel_rejects_municipal_issue(
    regime: TaxRegimeCode, competence: date,
) -> None:
    with pytest.raises(JundiaiGissContractError, match="National NFS-e"):
        _request(regime=regime, competence=competence)


def test_cancellation_must_have_human_approval() -> None:
    with pytest.raises(JundiaiGissContractError, match="Human approval"):
        _request(method="CancelarNfse")
    request = _request(method="CancelarNfse", approved=True)
    assert request.human_approved is True


def test_contract_preserves_escaped_signed_abrasf_xml() -> None:
    request = _request()
    packed = _soap(request, _contract(request.method))
    assert b"nfseCabecMsg" in packed
    assert b"nfseDadosMsg" in packed
    assert b"RecepcionarLoteRpsRequest" in packed
    assert b"&lt;EnviarLoteRpsEnvio" in packed
    assert b"http://www.giss.com.br/enviar-lote-rps-envio-v2_04.xsd" in packed
    assert b"http://www.giss.com.br/cabecalho-v2_04.xsd" in packed
    assert b"2.04" in packed


def test_processed_batch_not_equivalent_to_correlated_authorization() -> None:
    body = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        b'<s:Body><response><Protocolo>1234567890</Protocolo>'
        b'<Situacao>4</Situacao></response></s:Body></s:Envelope>'
    )
    result = _parse_reply(body, "ConsultarLoteRps")
    assert result.batch_protocol == "1234567890"
    assert result.batch_state == 4
    assert result.authorized is True
    assert result.confirmed_document_authorization is False


def test_provider_mismatch_denies_cert_and_network() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    resolver.resolve_provider_id.return_value = "ginfes-old"
    adapter = JundiaiGissHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        contract_for_method=_contract, validate_signed_xml=Mock(),
        exchange=exchange,
    )
    with pytest.raises(JundiaiGissContractError, match="durable binding missing"):
        adapter.invoke(_request())
    cert.assert_not_called()
    exchange.assert_not_called()


def test_unvalidated_signed_xml_denies_cert_and_http() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    resolver.resolve_provider_id.return_value = JUNDIAI_GISS_PROVIDER_ID
    validator = Mock(side_effect=JundiaiGissContractError("XSD/signature invalid"))
    adapter = JundiaiGissHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        contract_for_method=_contract, validate_signed_xml=validator,
        exchange=exchange,
    )
    with pytest.raises(JundiaiGissContractError, match="signature invalid"):
        adapter.invoke(_request())
    cert.assert_not_called()
    exchange.assert_not_called()


def test_approved_cancel_needs_separate_cancellation_binding() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    resolver.resolve_provider_id.return_value = "unapproved"
    adapter = JundiaiGissHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        contract_for_method=_contract, validate_signed_xml=Mock(),
        exchange=exchange,
    )
    with pytest.raises(JundiaiGissContractError, match="durable binding missing"):
        adapter.invoke(_request(method="CancelarNfse", approved=True))
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == "cancel"


@pytest.mark.parametrize("method", sorted(_GISS_REQUEST_ROOTS))
def test_real_giss_204_root_namespaces_are_not_generic_abrasf(method: str) -> None:
    from kordena_fiscal.gateway.jundiai_giss_homologation import _validate_xml_shape

    request = _request(method=method, approved=method == "CancelarNfse")
    parsed = _validate_xml_shape(request.signed_xml, method)
    assert parsed.tag.startswith("{http://www.giss.com.br/")
    legacy = request.signed_xml.replace(
        _GISS_REQUEST_ROOTS[method][1].encode(),
        b"http://www.abrasf.org.br/nfse.xsd",
    )
    with pytest.raises(JundiaiGissContractError, match="operation XML root"):
        _validate_xml_shape(legacy, method)


def test_escaped_giss_204_official_result_is_retained_without_authorizing() -> None:
    from xml.sax.saxutils import escape

    official = (
        '<ConsultarLoteRpsResposta '
        'xmlns="http://www.giss.com.br/consultar-lote-rps-resposta-v2_04.xsd">'
        '<Protocolo>1234</Protocolo><Situacao>4</Situacao>'
        '</ConsultarLoteRpsResposta>'
    )
    soap = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><ns:ConsultarLoteRpsResponse xmlns:ns="http://nfse.abrasf.org.br">'
        '<outputXML>' + escape(official) + '</outputXML>'
        '</ns:ConsultarLoteRpsResponse></soap:Body></soap:Envelope>'
    ).encode()
    result = _parse_reply(soap, "ConsultarLoteRps")
    assert result.batch_protocol == "1234"
    assert result.batch_state == 4
    assert result.confirmed_document_authorization is False
    assert result.official_response_xml == official.encode()
    assert "outputXML" not in repr(result)


def test_giss_204_official_reply_from_other_method_cannot_be_reused() -> None:
    from xml.sax.saxutils import escape

    other = (
        '<ConsultarLoteRpsResposta '
        'xmlns="http://www.giss.com.br/consultar-lote-rps-resposta-v2_04.xsd"/>'
    )
    soap = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><ns:ConsultarNfsePorRpsResponse xmlns:ns="http://nfse.abrasf.org.br">'
        '<outputXML>' + escape(other) + '</outputXML>'
        '</ns:ConsultarNfsePorRpsResponse></soap:Body></soap:Envelope>'
    ).encode()
    with pytest.raises(JundiaiGissContractError, match="namespace mismatch"):
        _parse_reply(soap, "ConsultarNfsePorRps")
