"""GissOnline municipal V1.8 original RPS consultation (ABRASF 2.04)."""
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
from kordena_fiscal.gateway.jundiai_giss_request_builder import (
    JundiaiGissBuilderError,
    build_jundiai_original_rps_query_xml,
    prepare_jundiai_original_rps_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps

_R = "{http://www.giss.com.br/consultar-nfse-rps-envio-v2_04.xsd}"
_T = "{http://www.giss.com.br/tipos-v2_04.xsd}"


def _rps() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-x", unit_id="u",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="giss-query",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3525904",
        competence_date=date(2026, 11, 13), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
    )


def test_giss_current_query_contains_one_original_rps_and_prestador() -> None:
    xml = build_jundiai_original_rps_query_xml(
        original=_rps(), municipal_registration="1234567",
    )
    root = etree.fromstring(xml)
    assert etree.QName(root).localname == "ConsultarNfseRpsEnvio"
    assert root.findtext(f".//{_R}IdentificacaoRps/{_T}Numero") == "42"
    assert root.findtext(f".//{_R}IdentificacaoRps/{_T}Serie") == "NF"
    assert root.findtext(f".//{_R}IdentificacaoRps/{_T}Tipo") == "1"
    assert root.findtext(f".//{_R}Prestador/{_T}CpfCnpj/{_T}Cnpj") == (
        "11222333000181"
    )
    assert root.findtext(f".//{_R}Prestador/{_T}InscricaoMunicipal") == "1234567"


def test_signed_giss_query_preserves_original_issuer_and_number() -> None:
    signer = Mock(side_effect=lambda raw: raw)
    validator = Mock()
    prepared = prepare_jundiai_original_rps_query(
        original=_rps(), regime=TaxRegimeCode.NORMAL,
        municipal_registration="1234567", sign_document=signer,
        validate_signed_request=validator,
    )
    assert prepared.method == "ConsultarNfsePorRps"
    assert prepared.issuer_cnpj == _rps().issuer_cnpj
    signer.assert_called_once()
    validator.assert_called_once_with(prepared.signed_xml)


@pytest.mark.parametrize("municipal_registration", [
    "", "ABC", "0", "123 456", "../tenant", "١٢٣",
])
def test_bad_municipal_registration_refused(municipal_registration: str) -> None:
    with pytest.raises(JundiaiGissBuilderError):
        build_jundiai_original_rps_query_xml(
            original=_rps(), municipal_registration=municipal_registration,
        )


def test_signer_cannot_change_original_rps_number() -> None:
    validator = Mock()
    def rewrite(raw: bytes) -> bytes:
        return raw.replace(b"<tipos:Numero>42</tipos:Numero>",
                           b"<tipos:Numero>43</tipos:Numero>")
    with pytest.raises(JundiaiGissBuilderError, match="original issuer RPS"):
        prepare_jundiai_original_rps_query(
            original=_rps(), regime=TaxRegimeCode.NORMAL,
            municipal_registration="1234567", sign_document=rewrite,
            validate_signed_request=validator,
        )
    validator.assert_not_called()


def test_query_builder_rejects_cross_city_issuer() -> None:
    with pytest.raises(JundiaiGissBuilderError):
        build_jundiai_original_rps_query_xml(
            original=replace(_rps(), issuer_ibge="3509205"),
            municipal_registration="1234567",
        )
