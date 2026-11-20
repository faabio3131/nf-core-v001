"""Cajamar cancellation: typed verified response, never a SOAP-200 assumption."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock
from xml.sax.saxutils import escape

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarGeiswebCancellationError,
    interpret_cajamar_cancel_response,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarGeiswebResult
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="org", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cancel",
        ),
        document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 10, 31), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="42",
    )


def _issued() -> Sp4VerifiedInvoice:
    original = _original()
    return Sp4VerifiedInvoice(
        issuer_cnpj=original.issuer_cnpj, issuer_ibge=original.issuer_ibge,
        competence_date=original.competence_date, rps_number=original.rps_number,
        rps_series=original.rps_series, gross_amount=original.gross_amount,
        invoice_number="8765", verification_code="ABCDEF1234",
        invoice_reference="8765",
        authorized_xml=b"<ConsultaLoteRpsResposta>archive</ConsultaLoteRpsResposta>",
    )


def _soap(inner: str) -> CajamarGeiswebResult:
    xml = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:g="http://www.geisweb.com.br/"><soap:Body>'
        '<g:CancelaNfseResponse><g:CancelaNfseResult>'
        f'{escape(inner)}</g:CancelaNfseResult></g:CancelaNfseResponse>'
        '</soap:Body></soap:Envelope>'
    ).encode()
    return CajamarGeiswebResult(method="CancelaNfse", response_xml=xml)


def _success() -> str:
    return (
        "<CancelaNfseResposta><Nfse><IdentificacaoNfse>"
        "<NumeroRps>42</NumeroRps><NumeroNfse>8765</NumeroNfse>"
        "<CodigoVerificacao>ABCDEF1234</CodigoVerificacao>"
        "</IdentificacaoNfse></Nfse></CancelaNfseResposta>"
    )


def test_official_cancellation_needs_correlated_identification_and_xml_validation() -> None:
    verifier = Mock()
    outcome = interpret_cajamar_cancel_response(
        receipt=_soap(_success()), source=_original(),
        issued=_issued(), verify_official_response=verifier,
    )
    assert outcome.confirmed
    assert outcome.rejection_code is None
    assert outcome.response_xml == _success().encode()
    verifier.assert_called_once_with(outcome.response_xml)


@pytest.mark.parametrize("inner", [
    "<CancelaNfseResposta/>",
    "<CancelaNfseResposta><Status>OK</Status></CancelaNfseResposta>",
    _success().replace("<NumeroNfse>8765", "<NumeroNfse>8766"),
    _success().replace("<NumeroRps>42", "<NumeroRps>43"),
    _success().replace("<CodigoVerificacao>ABCDEF1234", "<CodigoVerificacao>XYZ"),
    _success().replace("</Nfse>", "</Nfse><Nfse/>"),
])
def test_no_confirmation_from_status_or_wrong_original_invoice(inner: str) -> None:
    with pytest.raises(CajamarGeiswebCancellationError):
        interpret_cajamar_cancel_response(
            receipt=_soap(inner), source=_original(),
            issued=_issued(), verify_official_response=Mock(),
        )


def test_geisweb_explicit_rejection_is_not_cancelled_and_preserves_official_xml() -> None:
    verifier = Mock()
    inner = (
        "<CancelaNfseResposta><Msg><Erro>8</Erro>"
        "<Status>Usuario nao autorizado</Status></Msg></CancelaNfseResposta>"
    )
    result = interpret_cajamar_cancel_response(
        receipt=_soap(inner), source=_original(),
        issued=_issued(), verify_official_response=verifier,
    )
    assert result.confirmed is False
    assert result.rejection_code == "8"
    verifier.assert_called_once()


def test_geisweb_cancellation_rejects_fake_confirmed_flag_without_soap_proof() -> None:
    verifier = Mock()
    with pytest.raises(CajamarGeiswebCancellationError):
        interpret_cajamar_cancel_response(
            receipt=CajamarGeiswebResult(
                method="CancelaNfse", confirmed_authorization=True, response_xml=b"",
            ),
            source=_original(), issued=_issued(),
            verify_official_response=verifier,
        )
    verifier.assert_not_called()


def test_cancellation_rejects_extra_soap_body_result() -> None:
    receipt = _soap(_success())
    invalid = receipt.response_xml.replace(
        b"</soap:Body>", b"<g:OtherResponse/></soap:Body>",
    )
    with pytest.raises(CajamarGeiswebCancellationError):
        interpret_cajamar_cancel_response(
            receipt=CajamarGeiswebResult(
                method="CancelaNfse", response_xml=invalid,
            ),
            source=_original(), issued=_issued(),
            verify_official_response=Mock(),
        )


def test_geisweb_cancellation_validator_failure_cannot_be_accepted() -> None:
    verifier = Mock(side_effect=CajamarGeiswebCancellationError("Invalid XSD"))
    with pytest.raises(CajamarGeiswebCancellationError, match="Invalid XSD"):
        interpret_cajamar_cancel_response(
            receipt=_soap(_success()), source=_original(),
            issued=_issued(), verify_official_response=verifier,
        )


def test_geisweb_cancel_reply_does_not_accept_different_issuer_invoice() -> None:
    with pytest.raises(CajamarGeiswebCancellationError):
        interpret_cajamar_cancel_response(
            receipt=_soap(_success()), source=_original(),
            issued=replace(_issued(), issuer_cnpj=Cnpj("00944029000121")),
            verify_official_response=Mock(),
        )
