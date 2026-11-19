"""GeisWeb official lot recovery: only one RPS, CNPJ, month and value match."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarGeiswebResult
from kordena_fiscal.gateway.cajamar_geisweb_invoice_interpreter import (
    decode_cajamar_archived_invoice,
    interpret_cajamar_geisweb_result,
    interpret_cajamar_invoice_observation,
)
from kordena_fiscal.gateway.cajamar_geisweb_request_builder import (
    CajamarGeiswebBuilderError,
    prepare_cajamar_invoice_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="cajamar", unit_id="site", host_namespace="nfcore",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="GeisWeb",
        ),
        document_id="prepared-cajamar",
        request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 11, 13),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
    )


def _lot_xml(
    *, rps: str = "42", cnpj: str = "11222333000181",
    competence: str = "2026-11", amount: str = "150,00",
) -> str:
    return (
        "<ConsultaLoteRpsResposta><Rps>"
        "<IdentificacaoNfse>"
        f"<NumeroRps>{rps}</NumeroRps><NumeroNfse>8765</NumeroNfse>"
        "<CodigoVerificacao>ABCDEF1234</CodigoVerificacao>"
        "</IdentificacaoNfse>"
        f"<Competencia>{competence}</Competencia>"
        "<Servico><Valores>"
        f"<ValorServicos>{amount}</ValorServicos>"
        "</Valores><PrestadorServico><IdentificacaoPrestador>"
        f"<CnpjCpf>{cnpj}</CnpjCpf>"
        "</IdentificacaoPrestador></PrestadorServico></Servico>"
        "</Rps></ConsultaLoteRpsResposta>"
    )


def _receipt(
    xml: str, method: str = "ConsultaLoteRps",
) -> CajamarGeiswebResult:
    from xml.sax.saxutils import escape

    envelope = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:g="http://www.geisweb.com.br/"><soap:Body>'
        f"<g:{method}Response><g:{method}Result>{escape(xml)}"
        f"</g:{method}Result></g:{method}Response></soap:Body></soap:Envelope>"
    ).encode()
    return CajamarGeiswebResult(method=method, response_xml=envelope)


def _interpret(receipt: CajamarGeiswebResult):
    return interpret_cajamar_geisweb_result(
        receipt, Mock(spec=NfseAuthorizationRequest), _original(),
    )


def test_lot_query_returns_original_rps_source_correlated_note() -> None:
    result = _interpret(_receipt(_lot_xml()))
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.official_invoice is not None
    assert result.official_invoice.invoice_number == "8765"
    assert result.official_invoice.issuer_cnpj == Cnpj("11222333000181")
    assert result.official_invoice.gross_amount == Decimal("150.00")
    assert result.official_invoice.authorized_xml.startswith(b"<ConsultaLoteRpsResposta")


@pytest.mark.parametrize("change", [
    {"rps": "43"},
    {"cnpj": "00944029000121"},
    {"competence": "2026-10"},
    {"amount": "150,01"},
    {"amount": "1.50,00"},
])
def test_fiscal_mismatch_is_never_promoted(change: dict[str, str]) -> None:
    with pytest.raises(Sp4CanonicalMunicipalError):
        _interpret(_receipt(_lot_xml(**change)))


@pytest.mark.parametrize("note_number", ["0", "ABC123", "-1", "１２３"])
def test_lot_query_rejects_invalid_official_invoice_number(note_number: str) -> None:
    # Do not authorize a fiscal note without a valid municipal invoice number.
    xml = _lot_xml().replace(
        "<NumeroNfse>8765</NumeroNfse>",
        f"<NumeroNfse>{note_number}</NumeroNfse>",
    )
    with pytest.raises(Sp4CanonicalMunicipalError):
        _interpret(_receipt(xml))


def test_lot_query_rejects_extra_soap_body_results() -> None:
    receipt = _receipt(_lot_xml())
    invalid = receipt.response_xml.replace(
        b"</soap:Body>", b"<g:OtherResponse/></soap:Body>",
    )
    with pytest.raises(Sp4CanonicalMunicipalError):
        _interpret(CajamarGeiswebResult(
            method="ConsultaLoteRps", response_xml=invalid,
        ))


def test_lot_error_or_missing_note_remains_pending() -> None:
    for xml in (
        "<ConsultaLoteRpsResposta><Msg><Erro>68</Erro>"
        "<Status>RPS nao encontrado</Status></Msg></ConsultaLoteRpsResposta>",
        "<ConsultaLoteRpsResposta/>",
    ):
        assert _interpret(_receipt(xml)).status is AuthorizationStatus.PENDING


def test_batch_receipt_cannot_promote_note_even_if_it_has_identifiers() -> None:
    result = _interpret(_receipt(_lot_xml(), method="EnviaLoteRps"))
    assert result.status is AuthorizationStatus.PENDING


def test_ambiguous_multi_rps_response_is_rejected() -> None:
    xml = _lot_xml().replace("</ConsultaLoteRpsResposta>", "") + (
        "<Rps>" + _lot_xml().split("<Rps>", 1)[1].split("</Rps>", 1)[0]
    )
    xml = xml + "</Rps></ConsultaLoteRpsResposta>"
    with pytest.raises(Sp4CanonicalMunicipalError, match="multiple RPS"):
        _interpret(_receipt(xml))


def test_doctype_mismatch_and_non_fiscal_soap_response_rejected() -> None:
    with pytest.raises(Sp4CanonicalMunicipalError):
        _interpret(_receipt('<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                            + _lot_xml()))
    with pytest.raises(Sp4CanonicalMunicipalError, match="SOAP|method"):
        _interpret(CajamarGeiswebResult(
            method="ConsultaLoteRps",
            response_xml=b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/'
                         b'soap/envelope/"><soap:Body/></soap:Envelope>',
        ))


def test_exact_invoice_query_is_scoped_and_cannot_add_selectors() -> None:
    source = _original()
    issued = decode_cajamar_archived_invoice(_lot_xml().encode(), source)
    validator = Mock()
    prepared = prepare_cajamar_invoice_query(
        source=source, issued=issued, tax_regime=TaxRegimeCode.NORMAL,
        sign_document=lambda xml: xml, validate_signed_request=validator,
    )
    assert prepared.method == "ConsultaNfse"
    assert prepared.scope == source.scope
    assert b"<NumeroNfse>8765</NumeroNfse>" in prepared.signed_request_xml
    validator.assert_called_once_with(prepared.signed_request_xml)
    with pytest.raises(CajamarGeiswebBuilderError, match="selectors"):
        prepare_cajamar_invoice_query(
            source=source, issued=issued, tax_regime=TaxRegimeCode.NORMAL,
            sign_document=lambda xml: xml.replace(
                b"</Consulta>", b"<NumeroInicial>1</NumeroInicial></Consulta>",
            ),
            validate_signed_request=Mock(),
        )


def _query_xml() -> str:
    return _lot_xml().replace("ConsultaLoteRpsResposta", "ConsultaNfseResposta").replace(
        "<Rps>", "<Nfse>",
    ).replace("</Rps>", "</Nfse>")


def test_invoice_found_is_observation_only() -> None:
    source = _original()
    issued = decode_cajamar_archived_invoice(_lot_xml().encode(), source)
    validator = Mock()
    observation = interpret_cajamar_invoice_observation(
        _receipt(_query_xml(), method="ConsultaNfse"), source, issued,
        verify_official_response=validator,
    )
    assert observation.found is True
    assert observation.error_code is None
    assert observation.response_xml == _query_xml().encode()
    validator.assert_called_once_with(observation.response_xml)


@pytest.mark.parametrize("code", ["10", "2", "8"])
def test_query_error_is_observation_not_cancellation(code: str) -> None:
    source = _original()
    issued = decode_cajamar_archived_invoice(_lot_xml().encode(), source)
    xml = f"<ConsultaNfseResposta><Msg><Erro>{code}</Erro></Msg></ConsultaNfseResposta>"
    observation = interpret_cajamar_invoice_observation(
        _receipt(xml, method="ConsultaNfse"), source, issued,
        verify_official_response=Mock(),
    )
    assert observation.found is False
    assert observation.error_code == code


@pytest.mark.parametrize("original_value,changed", [
    ("<NumeroNfse>8765", "<NumeroNfse>8766"),
    ("<NumeroRps>42", "<NumeroRps>43"),
    ("ABCDEF1234", "OTHER"),
    ("11222333000181", "00944029000121"),
    ("150,00", "150,01"),
])
def test_invoice_observation_rejects_mismatched_identity(
    original_value: str, changed: str,
) -> None:
    source = _original()
    issued = decode_cajamar_archived_invoice(_lot_xml().encode(), source)
    with pytest.raises(Sp4CanonicalMunicipalError, match="differs"):
        interpret_cajamar_invoice_observation(
            _receipt(_query_xml().replace(original_value, changed), method="ConsultaNfse"),
            source, issued, verify_official_response=Mock(),
        )
