"""Osasco Apr/2026 WCF query builder, original receipt and secret injection."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.osasco_full_note_query_builder import (
    build_osasco_full_note_query,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    _build_soap,
    _canonical_request,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps


def test_full_query_uses_original_source_and_credential_injection_boundary() -> None:
    scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="tenant", unit_id="unit",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="query",
    )
    original = Sp4OriginalRps(
        scope=scope, document_id="doc", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 11, 13), rps_number="98761",
        rps_series="A", gross_amount=Decimal("150.00"),
    )
    operation = build_osasco_full_note_query(original, TaxRegimeCode.NORMAL)
    assert operation.method == "ConsultarNotaCompleta"
    root = _canonical_request(operation.request_xml, operation.method)
    wrap = root[0]
    assert [etree.QName(child).localname for child in wrap] == [
        "CNPJTomador", "CPFTomador", "ChaveAutenticacao", "DataFinal",
        "DataInicial", "NumeroNotaFinal", "NumeroNotaInicial", "NumeroReciboFinal",
        "NumeroReciboInicial", "NumeroReciboUnico",
    ]
    assert wrap[-1].text == "98761"
    assert wrap[2].text is None
    xml = _build_soap(operation, "12345678-1234-1234-1234-123456789012")
    body = etree.fromstring(xml)
    values = [
        el for el in body.iter()
        if etree.QName(el).localname == "ChaveAutenticacao"
    ]
    assert len(values) == 1
    assert values[0].text == "12345678-1234-1234-1234-123456789012"
    assert b"12345678-" not in operation.request_xml
