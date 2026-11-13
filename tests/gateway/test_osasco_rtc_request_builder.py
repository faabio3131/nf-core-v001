"""Osasco official 2026 WCF full-note query request and taxpayer isolation."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_request_builder import (
    OsascoWcfBuilderError,
    build_osasco_original_note_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)


def _rps() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-test", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="osasco-wcf",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
    )


def test_official_full_note_query_is_source_scoped_and_keyless() -> None:
    query = build_osasco_original_note_query(
        original=_rps(), regime=TaxRegimeCode.NORMAL,
    )
    assert query.method == "ConsultarNotaCompleta"
    assert query.scope.identity_partition_key == _rps().scope.identity_partition_key
    root = etree.fromstring(query.request_xml)
    assert root.tag == "{http://tempuri.org/}ConsultarNotaCompleta"
    request = root.find("{http://tempuri.org/}request")
    assert request is not None
    children = list(request)
    assert len(children) == 2
    assert [etree.QName(node).localname for node in children] == [
        "ChaveAutenticacao", "NumeroReciboUnico",
    ]
    assert children[0].text is None
    assert children[1].text == "42"
    assert b"senha" not in query.request_xml.lower()


@pytest.mark.parametrize("number", ["0", "NaN", "1.1", "", "12/4", "١٢٣"])
def test_invalid_source_receipt_cannot_be_queried(number: str) -> None:
    with pytest.raises((OsascoWcfBuilderError, Sp4CanonicalMunicipalError)):
        build_osasco_original_note_query(
            original=replace(_rps(), rps_number=number),
            regime=TaxRegimeCode.NORMAL,
        )


def test_municipal_builder_rejects_wrong_city_provider() -> None:
    with pytest.raises(OsascoWcfBuilderError):
        build_osasco_original_note_query(
            original=replace(_rps(), issuer_ibge="3505708"),
            regime=TaxRegimeCode.NORMAL,
        )
