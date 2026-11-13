"""Osasco WCF: offline official contract, authentication and tenant boundaries."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OSASCO_RTC_PROVIDER_ID,
    OsascoPreparedOperation,
    OsascoRtcContractError,
    OsascoRtcHomologationTransport,
    OsascoWcfContract,
    _build_soap,
    _parse_reply,
)


def _operation(
    method: str = "RTC_EmitirNFE",
    regime: TaxRegimeCode = TaxRegimeCode.NORMAL,
    competence: date = date(2026, 11, 13),
) -> OsascoPreparedOperation:
    content = (
        '<tem:' + method + ' xmlns:tem="http://tempuri.org/" '
        'xmlns:eis="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Negocio.WebServices.Mensagem">'
        '<tem:request><eis:ChaveAutenticacao/></tem:request>'
        '</tem:' + method + '>'
    ).encode()
    return OsascoPreparedOperation(
        scope=ExecutionScope(
            tenant_id="test-tenant", unit_id="test-unit",
            host_namespace="nfcore", environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="osasco",
        ),
        issuer_cnpj=Cnpj("11222333000181"),
        tax_regime=regime,
        competence_date=competence,
        method=method,
        request_xml=content,
    )


def _contract(method: str) -> OsascoWcfContract:
    return OsascoWcfContract(
        method=method,
        action="http://tempuri.org/INotaFiscalEletronica/" + method,
        wsdl_sha256="a" * 64,
    )


@pytest.mark.parametrize("method", ["RTC_EmitirNFE", "RTC_EmitirNFELote"])
@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
])
def test_post_cutover_national_issuer_does_not_use_osasco_municipal(
    method: str, regime: TaxRegimeCode, competence: date,
) -> None:
    with pytest.raises(OsascoRtcContractError, match="National NFS-e"):
        _operation(method, regime, competence)


def test_wcf_request_scopes_key_and_escapes_output() -> None:
    secret = "12345678-1234-1234-1234-123456789012"
    req = _operation()
    xml = _build_soap(req, secret)
    assert secret.encode() in xml
    assert b"RTC_EmitirNFE" in xml
    assert b"<soap:Envelope" in xml
    assert secret.encode() not in req.request_xml


def test_wcf_cannot_accept_untrusted_authentication_key_from_client() -> None:
    req = _operation()
    from dataclasses import replace

    tampered = replace(req, request_xml=req.request_xml.replace(
        b"ChaveAutenticacao/>", b"ChaveAutenticacao>bad</eis:ChaveAutenticacao>"
    ))
    with pytest.raises(OsascoRtcContractError, match="placeholder"):
        _build_soap(tampered, "12345678-1234-1234-1234-123456789012")


def test_mismatched_provider_denies_key_and_transport() -> None:
    res, key, exchange = Mock(), Mock(), Mock()
    res.resolve_provider_id.return_value = "unapproved-osasco"
    adapter = OsascoRtcHomologationTransport(
        resolver=res, resolve_key=key, validated_request=Mock(),
        contract_for_method=_contract, exchange=exchange,
    )
    with pytest.raises(OsascoRtcContractError, match="provider mismatch"):
        adapter.invoke(_operation())
    key.assert_not_called()
    exchange.assert_not_called()


def test_wcf_reply_never_infers_authorization_from_success_boolean() -> None:
    raw = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        b'xmlns:t="http://tempuri.org/" '
        b'xmlns:a="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Negocio.WebServices.Mensagem">'
        b'<s:Body><t:RTC_EmitirNFEResponse><t:RTC_EmitirNFEResult>'
        b'<a:Erro>false</a:Erro></t:RTC_EmitirNFEResult></t:RTC_EmitirNFEResponse>'
        b'</s:Body></s:Envelope>'
    )
    result = _parse_reply(raw, "RTC_EmitirNFE")
    assert result.fiscal_error is False
    assert result.confirmed_authorization is False


def test_rtc_soap_verified_binding_and_key_offline() -> None:
    res = Mock()
    res.resolve_provider_id.return_value = OSASCO_RTC_PROVIDER_ID
    key = Mock(return_value="12345678-1234-1234-1234-123456789012")
    validator = Mock()
    reply = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        b'xmlns:t="http://tempuri.org/" '
        b'xmlns:a="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Negocio.WebServices.Mensagem">'
        b'<s:Body><t:RTC_EmitirNFEResponse><t:RTC_EmitirNFEResult>'
        b'<a:Erro>false</a:Erro></t:RTC_EmitirNFEResult></t:RTC_EmitirNFEResponse>'
        b'</s:Body></s:Envelope>'
    )
    exchange = Mock(return_value=reply)
    adapter = OsascoRtcHomologationTransport(
        resolver=res, resolve_key=key, validated_request=validator,
        contract_for_method=_contract, exchange=exchange,
    )
    value = adapter.invoke(_operation())
    assert value.confirmed_authorization is False
    validator.assert_called_once()
    assert res.resolve_provider_id.call_args.kwargs["operation"] == "authorize"
    key.assert_called_once()
    exchange.assert_called_once()


def test_osasco_official_sync_note_reference_is_preserved_but_not_authorized() -> None:
    from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoNoteReference

    raw = (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        b'xmlns:t="http://tempuri.org/" '
        b'xmlns:a="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Negocio.WebServices.Mensagem" '
        b'xmlns:b="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Dominio.DataTransferObject.Prestador">'
        b'<s:Body><t:RTC_EmitirNFEResponse><t:RTC_EmitirNFEResult>'
        b'<a:Erro>false</a:Erro><a:NotaFiscalGerada>'
        b'<b:Numero>99999</b:Numero><b:Autenticador>EMOLQEHA</b:Autenticador>'
        b'<b:Identificador>000000</b:Identificador>'
        b'</a:NotaFiscalGerada></t:RTC_EmitirNFEResult>'
        b'</t:RTC_EmitirNFEResponse></s:Body></s:Envelope>'
    )
    receipt = _parse_reply(raw, "RTC_EmitirNFE")
    assert receipt.note_reference == OsascoNoteReference(
        number="99999", authenticator="EMOLQEHA", identifier="000000",
    )
    assert receipt.confirmed_authorization is False
    assert receipt.response_xml == raw


@pytest.mark.parametrize("alter", [
    ("<b:Numero>99999</b:Numero>", "<b:Numero>-1</b:Numero>"),
    ("<b:Autenticador>EMOLQEHA</b:Autenticador>",
     "<b:Autenticador>admin token</b:Autenticador>"),
    ("<b:Identificador>000000</b:Identificador>", ""),
])
def test_osasco_malformed_note_reference_is_not_fiscal_proof(
    alter: tuple[str, str],
) -> None:
    original = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:t="http://tempuri.org/" '
        'xmlns:a="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Negocio.WebServices.Mensagem" '
        'xmlns:b="http://schemas.datacontract.org/2004/07/'
        'Eissnfe.Dominio.DataTransferObject.Prestador">'
        '<s:Body><t:RTC_EmitirNFEResponse><t:RTC_EmitirNFEResult>'
        '<a:Erro>false</a:Erro><a:NotaFiscalGerada>'
        '<b:Numero>99999</b:Numero><b:Autenticador>EMOLQEHA</b:Autenticador>'
        '<b:Identificador>000000</b:Identificador>'
        '</a:NotaFiscalGerada></t:RTC_EmitirNFEResult>'
        '</t:RTC_EmitirNFEResponse></s:Body></s:Envelope>'
    )
    raw = original.replace(*alter).encode()
    with pytest.raises(OsascoRtcContractError, match="note identity"):
        _parse_reply(raw, "RTC_EmitirNFE")
