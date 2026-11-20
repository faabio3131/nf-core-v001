"""Osasco full-note XML: correlate unique official receipt before authorization.

The V10.6 2024 structure is historical municipal documentation; current
WSDL/XSD validation stays a separate required port in the runtime.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoOperationReceipt
from kordena_fiscal.gateway.osasco_rtc_invoice_interpreter import (
    OsascoFullInvoiceError,
    decode_osasco_archived_full_invoice,
    interpret_osasco_full_note_result,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="tenant-osasco", unit_id="unit-osasco",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="full-note", host_namespace="fm-nfcore",
        ),
        document_id="original-osasco",
        request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 10, 31),
        rps_number="42", rps_series="R1", gross_amount=Decimal("150.00"),
    )


def _xml() -> bytes:
    return (
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        b'xmlns:t="http://tempuri.org/" '
        b'xmlns:a="http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem" '
        b'xmlns:b="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Dominio.DataTransferObject.Prestador" '
        b'xmlns:c="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Dominio.DataTransferObject.Contribuinte">'
        b'<s:Body><t:ConsultarNotaCompletaResponse>'
        b'<t:ConsultarNotaCompletaResult>'
        b'<a:Erro>false</a:Erro>'
        b'<a:NotasGeradas><b:NotaFiscalRelatorioDTO>'
        b'<b:Numero>8001</b:Numero>'
        b'<b:NumeroRecibo>42</b:NumeroRecibo>'
        b'<b:CodigoAutenticidade>OSASCO1234</b:CodigoAutenticidade>'
        b'<b:Prestador><c:CNPJ>11222333000181</c:CNPJ></b:Prestador>'
        b'<b:Valor>150.00</b:Valor>'
        b'</b:NotaFiscalRelatorioDTO></a:NotasGeradas>'
        b'<a:QtdeNotas>1</a:QtdeNotas>'
        b'</t:ConsultarNotaCompletaResult>'
        b'</t:ConsultarNotaCompletaResponse></s:Body></s:Envelope>'
    )


def test_osasco_full_invoice_correlates_issuer_receipt_and_amount() -> None:
    invoice = decode_osasco_archived_full_invoice(_xml(), _original())
    assert invoice.invoice_number == "8001"
    assert invoice.rps_number == "42"
    assert invoice.issuer_cnpj == Cnpj("11222333000181")
    assert invoice.gross_amount == Decimal("150.00")
    assert invoice.authorized_xml == _xml()


@pytest.mark.parametrize("old,new", [
    (b"<b:NumeroRecibo>42", b"<b:NumeroRecibo>43"),
    (b"<c:CNPJ>11222333000181", b"<c:CNPJ>00944029000121"),
    (b"<b:Valor>150.00", b"<b:Valor>150.01"),
    (b"<b:Numero>8001", b"<b:Numero>0"),
    (b"<a:QtdeNotas>1", b"<a:QtdeNotas>2"),
    (b"<a:Erro>false", b"<a:Erro>true"),
    (b"<b:CodigoAutenticidade>OSASCO1234", b"<b:CodigoAutenticidade>"),
])
def test_osasco_full_note_disallows_wrong_official_identity(old: bytes, new: bytes) -> None:
    with pytest.raises(OsascoFullInvoiceError):
        decode_osasco_archived_full_invoice(_xml().replace(old, new), _original())


def test_osasco_full_note_rejects_ambiguous_notes_cancelled_and_dtd() -> None:
    with pytest.raises(OsascoFullInvoiceError):
        decode_osasco_archived_full_invoice(
            _xml().replace(
                b"</a:NotasGeradas>",
                b"<b:NotaFiscalRelatorioDTO/></a:NotasGeradas>",
            ), _original(),
        )
    with pytest.raises(OsascoFullInvoiceError):
        decode_osasco_archived_full_invoice(
            _xml().replace(
                b"</b:Numero>",
                b"</b:Numero><b:DataCancelamento>2026-11-12</b:DataCancelamento>",
            ), _original(),
        )
    with pytest.raises(OsascoFullInvoiceError):
        decode_osasco_archived_full_invoice(
            b'<!DOCTYPE s:Envelope [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + _xml(),
            _original(),
        )


def test_osasco_no_authorization_from_transport_status_alone() -> None:
    request = Mock(spec=NfseAuthorizationRequest)
    request.document.document_id = "original-osasco"
    request.request_fingerprint = "a" * 64
    pending = OsascoOperationReceipt(
        method="ConsultarNotaCompleta", fiscal_error=False, status_available=False,
        response_xml=_xml(),
    )
    assert interpret_osasco_full_note_result(
        pending, request, _original(),
    ).status is AuthorizationStatus.PENDING
    done = OsascoOperationReceipt(
        method="ConsultarNotaCompleta", fiscal_error=False, response_xml=_xml(),
    )
    result = interpret_osasco_full_note_result(done, request, _original())
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.official_invoice is not None
