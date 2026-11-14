"""Jundiai official cancellation and read-only recovery proof regression.

These are municipal boundary tests authored by Agent A. Shared core review and
final certification are intentionally left to independent Agent B/coordinator.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.jundiai_giss_cancellation_result import (
    JundiaiGissCancelResultError,
    verify_jundiai_cancel_query,
    verify_jundiai_cancel_reply,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiGissReceipt
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_CANCEL = "http://www.giss.com.br/cancelar-nfse-resposta-v2_04.xsd"
_QUERY = "http://www.giss.com.br/consultar-nfse-rps-resposta-v2_04.xsd"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"


def _original() -> tuple[Sp4OriginalRps, Sp4VerifiedInvoice]:
    cnpj = Cnpj("11222333000181")
    scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="tenant-j", unit_id="unit-j",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="j-event-test",
    )
    source = Sp4OriginalRps(
        scope=scope, document_id="j-doc-7", request_fingerprint="a" * 64,
        issuer_cnpj=cnpj, issuer_ibge="3525904",
        competence_date=date(2026, 11, 13), rps_number="7", rps_series="R1",
        gross_amount=Decimal("100.00"), municipal_batch_id="15",
    )
    invoice = Sp4VerifiedInvoice(
        issuer_cnpj=cnpj, issuer_ibge=source.issuer_ibge,
        competence_date=source.competence_date,
        rps_number=source.rps_number, rps_series=source.rps_series,
        gross_amount=source.gross_amount, invoice_number="1234",
        verification_code="J-TEST", invoice_reference="1234",
        authorized_xml=b"<MunicipalNote/>",
    )
    return source, invoice


def _confirmation(*, number: str = "1234", cnpj: str = "11222333000181",
                  municipality: str = "3525904", reason: str = "1") -> str:
    return (
        "<t:NfseCancelamento><t:Confirmacao>"
        "<t:DataHora>2026-11-14T10:00:00</t:DataHora>"
        f"<t:Numero>{number}</t:Numero>"
        f"<t:Cnpj>{cnpj}</t:Cnpj>"
        f"<t:CodigoMunicipio>{municipality}</t:CodigoMunicipio>"
        f"<t:CodigoCancelamento>{reason}</t:CodigoCancelamento>"
        "</t:Confirmacao></t:NfseCancelamento>"
    )


def _reply(inner: str) -> bytes:
    return (
        f'<CancelarNfseResposta xmlns="{_CANCEL}" xmlns:t="{_TYPES}">'
        f"{inner}</CancelarNfseResposta>"
    ).encode("utf-8")


def _query(inner: str) -> bytes:
    return (
        f'<ConsultarNfseRpsResposta xmlns="{_QUERY}" xmlns:t="{_TYPES}">'
        f"{inner}</ConsultarNfseRpsResposta>"
    ).encode("utf-8")


def _receipt(method: str, xml: bytes) -> JundiaiGissReceipt:
    return JundiaiGissReceipt(
        method=method, batch_protocol=None, batch_state=None,
        authorized=False, response_xml=xml, official_response_xml=xml,
    )


def test_official_cancel_confirms_only_correlated_signed_municipal_note() -> None:
    original, issued = _original()
    validate = Mock()
    xml = _reply(_confirmation())
    result = verify_jundiai_cancel_reply(
        receipt=_receipt("CancelarNfse", xml), source=original, issued=issued,
        code="1", validate_official_response=validate,
    )
    assert result.confirmed is True
    assert result.rejection_code is None
    assert result.response_xml == xml
    validate.assert_called_once_with(xml)


@pytest.mark.parametrize(("field", "value"), [
    ("number", "5678"),
    ("cnpj", "99999999000191"),
    ("municipality", "3534401"),
    ("reason", "4"),
])
def test_cancel_proof_cannot_cross_authorized_note_or_reason(
    field: str, value: str,
) -> None:
    source, invoice = _original()
    xml = _reply(_confirmation(**{field: value}))
    with pytest.raises(JundiaiGissCancelResultError, match="differs"):
        verify_jundiai_cancel_reply(
            receipt=_receipt("CancelarNfse", xml),
            source=source, issued=invoice, code="1",
            validate_official_response=Mock(),
        )


def test_cancel_rejects_false_method_and_wrong_root() -> None:
    source, invoice = _original()
    with pytest.raises(JundiaiGissCancelResultError, match="scope mismatch"):
        verify_jundiai_cancel_reply(
            receipt=_receipt("ConsultarNfsePorRps", _reply(_confirmation())),
            source=source, issued=invoice, code="1",
            validate_official_response=Mock(),
        )
    with pytest.raises(JundiaiGissCancelResultError, match="Wrong official"):
        verify_jundiai_cancel_reply(
            receipt=_receipt("CancelarNfse", _query(_confirmation())),
            source=source, issued=invoice, code="1",
            validate_official_response=Mock(),
        )


def test_rejection_never_becomes_cancelled_and_is_auditable() -> None:
    source, invoice = _original()
    xml = _reply(
        "<t:ListaMensagemRetorno><t:MensagemRetorno>"
        "<t:Codigo>E123</t:Codigo><t:Mensagem>Invalido</t:Mensagem>"
        "</t:MensagemRetorno></t:ListaMensagemRetorno>"
    )
    result = verify_jundiai_cancel_reply(
        receipt=_receipt("CancelarNfse", xml), source=source, issued=invoice,
        code="1", validate_official_response=Mock(),
    )
    assert result.confirmed is False
    assert result.rejection_code == "E123"


def test_recovery_is_only_confirmed_with_source_correlated_signed_cancel() -> None:
    source, invoice = _original()
    xml = _query("<t:CompNfse>" + _confirmation() + "</t:CompNfse>")
    schema, verify = Mock(), Mock()
    result = verify_jundiai_cancel_query(
        receipt=_receipt("ConsultarNfsePorRps", xml),
        source=source, issued=invoice,
        validate_official_query=schema, verify_cancelled_note=verify,
    )
    assert result.confirmed is True
    assert result.response_xml == xml
    schema.assert_called_once_with(xml)
    verified = verify.call_args.args[0]
    assert b"NfseCancelamento" in verified
    assert b"3525904" in verified


def test_recovery_without_cancellation_is_indeterminate_never_rejected() -> None:
    source, invoice = _original()
    xml = _query("<t:CompNfse><t:Nfse/></t:CompNfse>")
    verify = Mock()
    result = verify_jundiai_cancel_query(
        receipt=_receipt("ConsultarNfsePorRps", xml),
        source=source, issued=invoice,
        validate_official_query=Mock(), verify_cancelled_note=verify,
    )
    assert result.confirmed is None
    verify.assert_not_called()


def test_recovery_with_wrong_invoice_identity_cannot_release_claim() -> None:
    source, invoice = _original()
    xml = _query(
        "<t:CompNfse>" + _confirmation(number="9876") + "</t:CompNfse>"
    )
    with pytest.raises(JundiaiGissCancelResultError, match="differs"):
        verify_jundiai_cancel_query(
            receipt=_receipt("ConsultarNfsePorRps", xml),
            source=source, issued=invoice,
            validate_official_query=Mock(), verify_cancelled_note=Mock(),
        )
