"""Official Osasco 2026 WCF RTC request: canonical RPS, receiver and tax provenance."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_issue_builder import (
    OsascoRtcIssueError,
    OsascoRtcRecipient,
    OsascoRtcTaxFields,
    build_osasco_rtc_issue_xml,
    prepare_osasco_rtc_issue,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_osasco_rtc_issue_request_factory,
)

_ISS = "http://schemas.datacontract.org/2004/07/Eissnfe.Dominio.DataTransferObject.Prestador"
_MSG = "http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem"
_TAKER = "http://schemas.datacontract.org/2004/07/Eissnfe.Dominio.DataTransferObject.Contribuinte"


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            tenant_id="osasco", unit_id="branch", host_namespace="nfcore",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="osasco-wcf",
        ),
        document_id="prepared-osasco", request_fingerprint="b" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge="3534401",
        competence_date=date(2026, 11, 12), rps_number="20261112001",
        rps_series="R1", gross_amount=Decimal("150.00"),
    )


def _request(original: Sp4OriginalRps) -> NfseAuthorizationRequest:
    request = Mock(spec=NfseAuthorizationRequest)
    d = request.document
    d.scope = original.scope
    d.document_id = original.document_id
    d.issuer.cnpj = original.issuer_cnpj
    d.issuer.tax_regime = TaxRegimeCode.NORMAL
    d.competence_date = original.competence_date
    d.totals.gross_amount.amount = original.gross_amount
    d.issued_at = datetime(2026, 11, 12, tzinfo=UTC)
    d.service_jurisdiction.municipality_ibge_code = "3534401"
    d.service_jurisdiction.state_code = "SP"
    service = Mock()
    service.gross_amount.amount = original.gross_amount
    service.deduction_amount.amount = Decimal("0")
    d.services = (service,)
    request.request_fingerprint = original.request_fingerprint
    return request


def _fields() -> OsascoRtcTaxFields:
    return OsascoRtcTaxFields(
        activity="14.01", class_trib="000001", nbs_code="1.2001.10.00",
        incidence_location="3", operation_indicator="050101",
        service_city="Osasco", service_city_ibge="3534401", service_state="SP",
        recipient=OsascoRtcRecipient(
            tax_id="11222333000181", name="Cliente Teste",
            street="Rua das Flores", street_type="RUA", number="120",
            neighborhood="Centro", postal_code="06018090",
            city="Osasco", city_ibge="3534401", state="SP",
        ),
    )


def test_rtc_xml_has_original_receipt_taker_tax_and_municipal_key_slot() -> None:
    original = _original()
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original, fields=_fields(),
    )
    root = etree.fromstring(xml)
    assert root.tag == "{http://tempuri.org/}RTC_EmitirNFE"
    note = root.find(f"{{http://tempuri.org/}}request/{{{_MSG}}}NotaFiscal_RTC")
    assert note is not None
    assert note.findtext(f"{{{_ISS}}}NumeroRecibo") == "20261112001"
    assert note.findtext(f"{{{_ISS}}}ChaveAutenticacao") in (None, "")
    assert note.findtext(f"{{{_ISS}}}Valor") == "150.00"
    assert note.findtext(f"{{{_ISS}}}ClassTrib") == "000001"
    assert note.findtext(f"{{{_ISS}}}Homologacao") == "false"
    taker = note.find(f"{{{_ISS}}}Tomador")
    assert taker is not None
    assert taker.findtext(f"{{{_TAKER}}}CNPJ") == "11222333000181"


@pytest.mark.parametrize("change", [
    {"document_id": "unrelated"},
    {"gross_amount": Decimal("149.99")},
    {"competence_date": date(2025, 11, 12)},
])
def test_original_receipt_cannot_be_replaced(change: dict[str, object]) -> None:
    original = _original()
    with pytest.raises(OsascoRtcIssueError, match="matching normal-regime"):
        build_osasco_rtc_issue_xml(
            request=_request(original), original=replace(original, **change),
            fields=_fields(),
        )


def test_rtc_tax_metadata_is_reviewed_not_synthesized() -> None:
    original = _original()
    for fields in (
        replace(_fields(), class_trib=""),
        replace(_fields(), incidence_location="unknown"),
        replace(_fields(), recipient=replace(_fields().recipient, tax_id="XXX")),
        replace(_fields(), iss_rate=Decimal("NaN")),
    ):
        with pytest.raises(OsascoRtcIssueError):
            build_osasco_rtc_issue_xml(
                request=_request(original), original=original, fields=fields,
            )


def test_2026_rtc_issue_builder_uses_official_schema_port() -> None:
    original = _original()
    validator = Mock()
    prepared = prepare_osasco_rtc_issue(
        request=_request(original), original=original, fields=_fields(),
        validate_request=validator,
    )
    assert prepared.method == "RTC_EmitirNFE"
    validator.assert_called_once_with(prepared.request_xml)
    factory = build_osasco_rtc_issue_request_factory(
        resolve_rtc_fields=lambda req, src: _fields(),
        validate_official_request=validator,
    )
    assert factory(_request(original), original, "RTC_EmitirNFE").method == (
        "RTC_EmitirNFE"
    )


def test_osasco_rtc_test_only_flag_is_configurable_not_fixed() -> None:
    original = _original()
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original,
        fields=replace(_fields(), test_only=True),
    )
    node = etree.fromstring(xml).find(
        f".//{{{_ISS}}}Homologacao"
    )
    assert node is not None and node.text == "true"


@pytest.mark.parametrize("rtc_overrides", [
    {"class_trib": "00001"},
    {"class_trib": "00000A"},
    {"class_trib": "0000001"},
    {"nbs_code": "120011000"},
    {"nbs_code": "1.2001.1.00"},
    {"nbs_code": "1.2001.A0.00"},
    {"incidence_location": "12"},
    {"operation_indicator": "50101"},
    {"operation_indicator": "05010X"},
    {"operation_indicator": "0050101"},
])
def test_osasco_municipal_manual_v21_exact_rtc_code_shapes(
    rtc_overrides: dict[str, str],
) -> None:
    original = _original()
    with pytest.raises(OsascoRtcIssueError):
        build_osasco_rtc_issue_xml(
            request=_request(original), original=original,
            fields=replace(_fields(), **rtc_overrides),
        )


def test_osasco_municipal_manual_v21_preserves_rtc_leading_zeroes() -> None:
    original = _original()
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original, fields=_fields(),
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{{{_ISS}}}ClassTrib") == "000001"
    assert root.findtext(f".//{{{_ISS}}}CodigoNBS") == "1.2001.10.00"
    assert root.findtext(f".//{{{_ISS}}}IdLocalIncidencia") == "3"
    assert root.findtext(f".//{{{_ISS}}}IndOperacao") == "050101"


def test_osasco_2026_construction_service_address_preserves_official_order() -> None:
    original = _original()
    extra = replace(
        _fields(), service_district="Centro",
        service_postal_code="06018090", service_street="Rua das Obras",
        service_number="250", service_complement="Bloco B",
        construction_code="OBRA123",
    )
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original, fields=extra,
    )
    root = etree.fromstring(xml)
    note = root.find(f".//{{{_MSG}}}NotaFiscal_RTC")
    assert note is not None
    local = [(etree.QName(n).localname, n.text) for n in note
             if n.tag.startswith("{" + _ISS + "}")]
    keys = [name for name, _ in local]
    assert keys.index("BairroPrestacaoServico") < keys.index("ChaveAutenticacao")
    assert keys.index("CEPPrestacaoServico") < keys.index("ChaveAutenticacao")
    assert keys.index("CidadePrestacaoServico") < keys.index("CodObra")
    assert keys.index("CodObra") < keys.index("CodigoCidadeIBGEPrestacaoServico")
    assert keys.index("ComplementoPrestacaoServico") < keys.index("DataRecibo")
    assert keys.index("EnderecoPrestacaoServico") < keys.index("EstadoPrestacaoServico")
    assert keys.index("NumeroPrestacaoServico") < keys.index("NumeroRecibo")
    assert dict(local)["CodObra"] == "OBRA123"
    assert dict(local)["CEPPrestacaoServico"] == "06018090"


@pytest.mark.parametrize("change", [
    {"service_district": "Centro"},
    {"service_postal_code": "06018090"},
    {"service_street": "Rua Nova"},
    {"service_number": "250"},
    {"service_complement": "Sala 2"},
    {"service_district": "Centro", "service_postal_code": "0601809",
     "service_street": "Rua Nova", "service_number": "250"},
])
def test_osasco_conditional_location_cannot_be_partially_prepared(
    change: dict[str, str],
) -> None:
    original = _original()
    with pytest.raises(OsascoRtcIssueError):
        build_osasco_rtc_issue_xml(
            request=_request(original), original=original,
            fields=replace(_fields(), **change),
        )
