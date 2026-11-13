"""GissOnline query serializes exact persisted RPS identity, no real transport."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.jundiai_giss_homologation import _validate_xml_shape
from kordena_fiscal.gateway.jundiai_giss_rps_query_builder import build_jundiai_rps_query
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)

_TYPES = "{http://www.giss.com.br/tipos-v2_04.xsd}"


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="giss", unit_id="tax-unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="request",
        ),
        document_id="rps42", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3525904",
        competence_date=date(2026, 11, 13),
        rps_number="42", rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="123",
    )


def test_query_by_original_rps_builds_giss_2_04_wire_xml() -> None:
    source = _original()
    operation = build_jundiai_rps_query(
        source, TaxRegimeCode.NORMAL, municipal_registration="1234567",
    )
    assert operation.method == "ConsultarNfsePorRps"
    root = _validate_xml_shape(operation.signed_xml, operation.method)
    assert root.find(f"{_TYPES}IdentificacaoRps/{_TYPES}Numero").text == "42"
    assert root.find(f"{_TYPES}IdentificacaoRps/{_TYPES}Serie").text == "NF"
    assert root.find(f"{_TYPES}IdentificacaoRps/{_TYPES}Tipo").text == "1"
    assert root.find(f"{_TYPES}Prestador/{_TYPES}InscricaoMunicipal").text == "1234567"
    assert root.find(f"{_TYPES}Prestador/{_TYPES}CpfCnpj/{_TYPES}Cnpj").text == (
        source.issuer_cnpj.value
    )
    assert etree.QName(root).localname == "ConsultarNfseRpsEnvio"


@pytest.mark.parametrize("registration", ["", "abc", "00 11", "../wrong"])
def test_no_unscoped_municipal_registration(registration: str) -> None:
    with pytest.raises(Sp4CanonicalMunicipalError):
        build_jundiai_rps_query(
            _original(), TaxRegimeCode.NORMAL, municipal_registration=registration,
        )
