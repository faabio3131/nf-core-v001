"""GeisWeb official lot recovery: only one RPS, CNPJ, month and value match."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarGeiswebResult
from kordena_fiscal.gateway.cajamar_geisweb_invoice_interpreter import (
    interpret_cajamar_geisweb_result,
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
    with pytest.raises(Sp4CanonicalMunicipalError, match="method"):
        _interpret(CajamarGeiswebResult(
            method="ConsultaLoteRps",
            response_xml=b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/'
                         b'soap/envelope/"><soap:Body/></soap:Envelope>',
        ))
