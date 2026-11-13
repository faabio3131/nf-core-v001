"""Cajamar GeisWeb 10.2 section 13.3 lot lookup and signer/source integrity."""
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
from kordena_fiscal.gateway.cajamar_geisweb_request_builder import (
    CajamarGeiswebBuilderError,
    build_cajamar_lot_query_xml,
    prepare_cajamar_original_lot_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps


def _source() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="customer", unit_id="branch",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="lot",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 10, 25),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def test_original_geisweb_lot_xml_preserves_exact_taxpayer_identity() -> None:
    xml = build_cajamar_lot_query_xml(
        issuer_cnpj=_source().issuer_cnpj,
        original_lot="12345",
    )
    root = etree.fromstring(xml)
    assert root.tag == "ConsultaLoteRps"
    assert root.findtext("CnpjCpf") == "11222333000181"
    assert root.findtext("Consulta/CnpjCpfPrestador") == "11222333000181"
    assert root.findtext("Consulta/NumeroLote") == "12345"


def test_signed_query_passes_current_schema_validator_port() -> None:
    validator = Mock()
    signer = Mock(side_effect=lambda payload: payload)
    req = prepare_cajamar_original_lot_query(
        source=_source(), tax_regime=TaxRegimeCode.NORMAL,
        sign_document=signer, validate_signed_request=validator,
    )
    assert req.method == "ConsultaLoteRps"
    assert req.issuer_cnpj == _source().issuer_cnpj
    validator.assert_called_once_with(req.signed_request_xml)
    signer.assert_called_once()


@pytest.mark.parametrize("lot", ["0", "12345678901", "../3", "a12", "", "١٢٣"])
def test_invalid_origins_cannot_be_used_as_lot_ids(lot: str) -> None:
    with pytest.raises(CajamarGeiswebBuilderError):
        build_cajamar_lot_query_xml(
            issuer_cnpj=_source().issuer_cnpj, original_lot=lot,
        )


def test_cajamar_signer_cannot_change_scope_or_numbered_original_lot() -> None:
    def unsafe(_: bytes) -> bytes:
        return b"<ConsultaLoteRps><CnpjCpf>11222333000181</CnpjCpf>" + (
            b"<Consulta><CnpjCpfPrestador>11222333000181</CnpjCpfPrestador>"
            b"<NumeroLote>12346</NumeroLote></Consulta></ConsultaLoteRps>"
        )
    validator = Mock()
    with pytest.raises(CajamarGeiswebBuilderError, match="persisted source"):
        prepare_cajamar_original_lot_query(
            source=_source(), tax_regime=TaxRegimeCode.NORMAL,
            sign_document=unsafe, validate_signed_request=validator,
        )
    validator.assert_not_called()


def test_build_cajamar_lot_query_refuses_missing_reservation() -> None:
    with pytest.raises(CajamarGeiswebBuilderError):
        prepare_cajamar_original_lot_query(
            source=replace(_source(), municipal_batch_id=None),
            tax_regime=TaxRegimeCode.NORMAL,
            sign_document=Mock(), validate_signed_request=Mock(),
        )
