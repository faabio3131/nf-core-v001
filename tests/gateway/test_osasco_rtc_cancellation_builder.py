"""Osasco official 2.1 cancellation and replacement intent are distinct."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_cancellation_builder import (
    OsascoCancelBuilderError,
    build_osasco_cancel_request,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_D = "{http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem}"


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="org", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cancel",
        ),
        document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 10, 31), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
    )


def _note() -> Sp4VerifiedInvoice:
    return Sp4VerifiedInvoice(
        issuer_cnpj=_source().issuer_cnpj, issuer_ibge="3534401",
        competence_date=_source().competence_date, rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        invoice_number="8765", verification_code="ABCD1234",
        invoice_reference="8765", authorized_xml=b"<note-xml/>",
    )


@pytest.mark.parametrize("kind", ["N", "S"])
def test_cancel_or_substitute_uses_official_v21_method_and_source_number(kind: str) -> None:
    op = build_osasco_cancel_request(
        source=_source(), issued=_note(), regime=TaxRegimeCode.NORMAL,
        cancel_type=kind, reason="Documento emitido em duplicidade",
        human_approved=True,
    )
    assert op.method == "Cancelar"
    root = etree.fromstring(op.request_xml)
    assert root.tag == "{http://tempuri.org/}Cancelar"
    req = root.find("{http://tempuri.org/}request")
    assert req is not None
    fields = [(etree.QName(n).localname, n.text) for n in req]
    assert [a for a, _ in fields] == [
        "ChaveAutenticacao", "Homologacao", "Motivo",
        "NumeroNota", "TipoCancelamento",
    ]
    assert req.findtext(f"{_D}NumeroNota") == "8765"
    assert req.findtext(f"{_D}TipoCancelamento") == kind
    assert req.findtext(f"{_D}Homologacao") == "true"
    assert req.find(f"{_D}ChaveAutenticacao").text is None


def test_unapproved_cancel_never_builds_mutating_operation() -> None:
    with pytest.raises(OsascoCancelBuilderError):
        build_osasco_cancel_request(
            source=_source(), issued=_note(), regime=TaxRegimeCode.NORMAL,
            cancel_type="N", reason=None, human_approved=False,
        )


def test_source_and_invoice_from_different_rps_cannot_be_cancelled() -> None:
    with pytest.raises(OsascoCancelBuilderError):
        build_osasco_cancel_request(
            source=_source(),
            issued=replace(_note(), rps_number="43"),
            regime=TaxRegimeCode.NORMAL,
            cancel_type="S", reason="Cancelamento para substituição",
            human_approved=True,
        )


def test_cancel_cannot_retarget_invoice_from_another_service_competence() -> None:
    with pytest.raises(OsascoCancelBuilderError):
        build_osasco_cancel_request(
            source=_source(),
            issued=replace(_note(), competence_date=date(2026, 9, 30)),
            regime=TaxRegimeCode.NORMAL,
            cancel_type="N", reason="Erro de emissao",
            human_approved=True,
        )


def test_unknown_cancellation_type_not_treated_as_normal() -> None:
    with pytest.raises(OsascoCancelBuilderError):
        build_osasco_cancel_request(
            source=_source(), issued=_note(), regime=TaxRegimeCode.NORMAL,
            cancel_type="X", reason=None, human_approved=True,
        )
