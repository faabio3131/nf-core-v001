"""GeisWeb 10.2 §13.4 original fiscal note cancellation builder."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from lxml import etree

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarGeiswebCancellationError,
    build_cajamar_cancel_xml,
    prepare_cajamar_cancel,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="org", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="cancel",
        ),
        document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 10, 31), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def _invoice() -> Sp4VerifiedInvoice:
    s = _source()
    return Sp4VerifiedInvoice(
        issuer_cnpj=s.issuer_cnpj, issuer_ibge=s.issuer_ibge,
        competence_date=s.competence_date, rps_number=s.rps_number,
        rps_series=s.rps_series, gross_amount=s.gross_amount,
        invoice_number="8765", verification_code="ABCD1234",
        invoice_reference="8765", authorized_xml=b"<MunicipalInvoice/>",
    )


def test_geisweb_cancel_xml_has_original_issuer_and_invoice_number() -> None:
    xml = build_cajamar_cancel_xml(source=_source(), issued=_invoice())
    root = etree.fromstring(xml)
    assert root.tag == "CancelaNfse"
    assert root.findtext("CnpjCpf") == "11222333000181"
    assert root.findtext("Cancela/CnpjCpfPrestador") == "11222333000181"
    assert root.findtext("Cancela/NumeroNfse") == "8765"
    assert root.find("EnviaLoteRps") is None


def test_geisweb_cancel_passes_signed_xml_to_schema_validator() -> None:
    sign = Mock(side_effect=lambda raw: raw)
    verify = Mock()
    req = prepare_cajamar_cancel(
        source=_source(), issued=_invoice(),
        regime=TaxRegimeCode.NORMAL, human_approved=True,
        sign_document=sign, validate_signed_request=verify,
    )
    assert req.method == "CancelaNfse"
    assert req.human_approved is True
    assert req.scope.identity_partition_key == _source().scope.identity_partition_key
    sign.assert_called_once()
    verify.assert_called_once_with(req.signed_request_xml)


def test_cajamar_cancel_needs_approved_action_not_an_issuance_lock() -> None:
    with pytest.raises(CajamarGeiswebCancellationError):
        prepare_cajamar_cancel(
            source=_source(), issued=_invoice(), regime=TaxRegimeCode.NORMAL,
            human_approved=False, sign_document=Mock(),
            validate_signed_request=Mock(),
        )


@pytest.mark.parametrize("changes", [
    {"invoice_number": "0"}, {"invoice_number": "12/13"},
    {"rps_number": "43"}, {"gross_amount": Decimal("149.99")},
])
def test_issued_fiscal_identity_must_match_original(changes: dict[str, object]) -> None:
    with pytest.raises(CajamarGeiswebCancellationError):
        build_cajamar_cancel_xml(
            source=_source(), issued=replace(_invoice(), **changes),
        )


def test_signer_cannot_retarget_cancel_to_different_taxpayer_invoice() -> None:
    verify = Mock()
    def tamper(xml: bytes) -> bytes:
        return xml.replace(b"<NumeroNfse>8765</NumeroNfse>",
                           b"<NumeroNfse>8766</NumeroNfse>")
    with pytest.raises(CajamarGeiswebCancellationError, match="original fiscal note"):
        prepare_cajamar_cancel(
            source=_source(), issued=_invoice(), regime=TaxRegimeCode.NORMAL,
            human_approved=True, sign_document=tamper,
            validate_signed_request=verify,
        )
    verify.assert_not_called()
