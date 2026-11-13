"""GeisWeb20 read-only original lot query follows manual 10.2 §13.3."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_lot_query_builder import (
    build_cajamar_lot_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="cajamar", unit_id="unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="query",
        ),
        document_id="original", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3509205",
        competence_date=date(2026, 11, 13),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def test_rps_original_lot_query_has_cnpj_and_immutable_batch() -> None:
    original = _original()
    prepared = build_cajamar_lot_query(original, TaxRegimeCode.NORMAL)
    assert prepared.method == "ConsultaLoteRps"
    root = etree.fromstring(prepared.signed_request_xml)
    assert root.tag == "ConsultaLoteRps"
    assert root.find("CnpjCpf").text == original.issuer_cnpj.value
    assert root.find("Consulta/CnpjCpfPrestador").text == original.issuer_cnpj.value
    assert root.find("Consulta/NumeroLote").text == original.municipal_batch_id
    assert len(root) == 2


@pytest.mark.parametrize("batch", [None, "12345678901"])
def test_unallocated_or_oversized_original_batch_not_used(batch: str | None) -> None:
    from dataclasses import replace

    original = _original()
    with pytest.raises(Sp4CanonicalMunicipalError):
        build_cajamar_lot_query(
            replace(original, municipal_batch_id=batch), TaxRegimeCode.NORMAL,
        )
