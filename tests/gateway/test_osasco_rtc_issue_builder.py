"""Official Osasco 2026 WCF RTC request: canonical RPS, receiver and tax provenance."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    MunicipalRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.osasco_rtc_cancellation_builder import build_osasco_cancel_request
from kordena_fiscal.gateway.osasco_rtc_issue_builder import (
    OsascoReviewedCartorioValues,
    OsascoRtcIssueError,
    OsascoRtcRecipient,
    OsascoRtcTaxFields,
    build_osasco_rtc_issue_xml,
    prepare_osasco_rtc_issue,
)
from kordena_fiscal.gateway.osasco_rtc_request_builder import (
    build_osasco_original_note_query,
)
from kordena_fiscal.gateway.osasco_rtc_tax_policy import (
    OsascoReviewedRtcPolicy,
    OsascoReviewedTaxPolicyError,
    build_osasco_reviewed_tax_resolver,
    reviewed_osasco_rtc_fields,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseServiceTaker,
)
from kordena_fiscal.runtime.osasco_official_schema import compile_osasco_official_xsd
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


def _reviewed_rtc_policy() -> OsascoReviewedRtcPolicy:
    return OsascoReviewedRtcPolicy(
        source_normative="urn:nfcore:osasco:reviewed-2026",
        rule_version=12, effective_from=date(2026, 1, 1),
        effective_through=date(2026, 12, 31),
        municipal_service_code="14.01", national_taxation_code="010701",
        activity="14.01", class_trib="000001", nbs_code="1.2001.10.00",
        incidence_location="3", operation_indicator="050101",
        service_city="Osasco", service_city_ibge="3534401", service_state="SP",
        recipient_street_type="RUA", iss_rate=Decimal("3"),
        pis=Decimal("0.00"), cofins=Decimal("0.00"),
        csll=Decimal("0.00"), income_tax=Decimal("0.00"),
        inss=Decimal("0.00"), other_taxes=Decimal("0.00"),
        test_only=False,
    )


def _reviewed_request(original: Sp4OriginalRps) -> NfseAuthorizationRequest:
    req = _request(original)
    d = req.document
    d.issuer.address.jurisdiction = BrazilianJurisdiction("SP", "3534401")
    d.issuer.municipal_registration = MunicipalRegistration("123456")
    d.service_taker = NfseServiceTaker(
        tax_id=Cnpj("11222333000181"), legal_name="Cliente Fiscal",
        address=FiscalAddress(
            street="Rua Sintetica", number="120", district="Centro",
            municipality_name="Osasco",
            jurisdiction=BrazilianJurisdiction("SP", "3534401"),
            postal_code="06018090",
        ),
    )
    item = d.services[0]
    item.iss_amount.amount = Decimal("4.50")
    item.taxable_amount.amount = Decimal("150.00")
    item.municipal_service_code = "14.01"
    item.national_taxation_code = "010701"
    item.source_normative = "urn:nfcore:osasco:reviewed-2026"
    item.rule_version = 12
    item.iss_withheld = False
    return req


def test_osasco_reviewed_policy_binds_canonical_iss_without_guessing_taxes() -> None:
    original = _original()
    req = _reviewed_request(original)
    resolver = build_osasco_reviewed_tax_resolver(
        lambda _request, _original: _reviewed_rtc_policy(),
    )
    fields = resolver(req, original)
    assert fields.iss_rate == Decimal("3")
    assert fields.recipient.tax_id == original.issuer_cnpj.value
    assert fields.recipient.street_type == "RUA"
    assert fields.test_only is False
    xml = build_osasco_rtc_issue_xml(
        request=req, original=original, fields=fields,
    )
    assert b"<" in xml
    assert b"ValorPisPasep" in xml


def test_osasco_reviewed_policy_rejects_missing_sources_and_wrong_iss() -> None:
    original = _original()
    req = _reviewed_request(original)
    policy = _reviewed_rtc_policy()
    assert reviewed_osasco_rtc_fields(req, original, policy).class_trib == "000001"
    for change in (
        {"rule_version": 11},
        {"effective_from": date(2026, 11, 13)},
        {"iss_rate": Decimal("4")},
        {"service_city_ibge": "3550308"},
        {"source_normative": "unreviewed"},
    ):
        with pytest.raises(OsascoReviewedTaxPolicyError):
            reviewed_osasco_rtc_fields(req, original, replace(policy, **change))
    req.document.issuer.municipal_registration = None
    with pytest.raises(OsascoReviewedTaxPolicyError, match="registration"):
        reviewed_osasco_rtc_fields(req, original, policy)


def test_municipal_manual_v22_normal_rate_and_taxpayer_are_explicit() -> None:
    """Out/2026 official manual: normal regime sends Aliquota=0, payer P."""
    original = _original()
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original,
        fields=replace(_fields(), iss_rate=Decimal("3.20")),
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{{{_ISS}}}Aliquota") == "0.00"
    assert root.findtext(f".//{{{_ISS}}}ResponsavelTributario") == "P"
    assert root.findtext(f".//{{{_ISS}}}SimplesNacional") == "false"


def test_municipal_manual_v22_outside_service_tax_substitution_rate() -> None:
    original = _original()
    request = _request(original)
    request.document.service_jurisdiction.municipality_ibge_code = "3550308"
    fields = replace(
        _fields(), iss_rate=Decimal("3.50"), iss_withheld=True,
        service_city="São Paulo", service_city_ibge="3550308",
    )
    xml = build_osasco_rtc_issue_xml(
        request=request, original=original, fields=fields,
    )
    root = etree.fromstring(xml)
    assert root.findtext(f".//{{{_ISS}}}Aliquota") == "3.50"
    assert root.findtext(f".//{{{_ISS}}}ResponsavelTributario") == "T"
    assert root.findtext(f".//{{{_ISS}}}SubstituicaoTributaria") == "true"


def test_municipal_manual_v22_rejects_unsupported_iss_variants() -> None:
    original = _original()
    for fields in (
        replace(_fields(), activity="1401"),
        replace(_fields(), iss_withheld=True),
        replace(_fields(), no_iss_incidence=True),
    ):
        with pytest.raises(OsascoRtcIssueError):
            build_osasco_rtc_issue_xml(
                request=_request(original), original=original,
                fields=fields,
            )


def test_municipal_manual_v22_separates_own_and_withheld_taxes() -> None:
    original = _original()
    fields = replace(
        _fields(), pis=Decimal("1.10"), pis_own=Decimal("2.30"),
        cofins=Decimal("3.40"), cofins_own=Decimal("4.50"),
    )
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original, fields=fields,
    )
    root = etree.fromstring(xml)
    for name, expected in (
        ("ValorPisPasep", "1.10"),
        ("ValorPisProprio", "2.30"),
        ("ValorCofins", "3.40"),
        ("ValorCofinsProprio", "4.50"),
    ):
        assert root.findtext(f".//{{{_ISS}}}{name}") == expected


def test_municipal_manual_v22_restricts_cartorio_special_deductions() -> None:
    original = _original()
    special = OsascoReviewedCartorioValues(
        vl_contrib_sta_casa=Decimal("0"),
        vl_emolumento=Decimal("10.00"),
        vl_fundo_tj=Decimal("0"),
        vl_intimacao=Decimal("0"),
        vl_min_publico=Decimal("0"),
        vl_repasse_estadual=Decimal("0"),
        vl_sefaz=Decimal("0"),
        vl_sinoreg=Decimal("0"),
    )
    fields = replace(_fields(), cartorio_values=special)
    xml = build_osasco_rtc_issue_xml(
        request=_request(original), original=original, fields=fields,
    )
    root = etree.fromstring(xml)
    group = root.find(f".//{{{_ISS}}}ValoresCartorios")
    assert group is not None
    assert len(group) == 8
    assert group.findtext(f"{{{_ISS}}}vlEmolumento") == "10.00"
    for invalid in (
        replace(fields, iss_withheld=True),
        replace(fields, cartorio_values=replace(
            special, vl_emolumento=Decimal("NaN"),
        )),
        replace(fields, cartorio_values=replace(
            special, vl_emolumento=Decimal("0"),
        )),
    ):
        with pytest.raises(OsascoRtcIssueError):
            build_osasco_rtc_issue_xml(
                request=_request(original), original=original,
                fields=invalid,
            )



def _official_xsd_validator():
    """Byte-for-byte municipal schemas, downloaded by GET from public WCF."""
    base = (
        Path(__file__).resolve().parents[2]
        / "contracts/official/osasco/homologation"
    )
    return compile_osasco_official_xsd({
        f"inline-xsd-{n:03}.xsd": (
            base / f"inline-xsd-{n:03}.xsd"
        ).read_bytes()
        for n in range(6)
    })


def test_osasco_actual_municipal_xsd_validates_canonical_rtc_issue_xml() -> None:
    """Official 2026 WSDL, not a synthetic permissive anyType schema."""
    validator = _official_xsd_validator()
    xml = build_osasco_rtc_issue_xml(
        request=_request(_original()), original=_original(), fields=_fields(),
    )
    validator.validate_document(xml)


def test_osasco_actual_municipal_xsd_validates_query_and_cancel_xml() -> None:
    validator = _official_xsd_validator()
    source = _original()
    query = build_osasco_original_note_query(
        original=source, regime=TaxRegimeCode.NORMAL,
    )
    validator.validate_document(query.request_xml)
    issued = Sp4VerifiedInvoice(
        issuer_cnpj=source.issuer_cnpj, issuer_ibge=source.issuer_ibge,
        competence_date=source.competence_date, rps_number=source.rps_number,
        rps_series=source.rps_series, gross_amount=source.gross_amount,
        invoice_number="900123", verification_code="VALIDA123",
        invoice_reference="900123", authorized_xml=b"<SyntheticInvoice/>",
    )
    cancel = build_osasco_cancel_request(
        source=source, issued=issued, regime=TaxRegimeCode.NORMAL,
        cancel_type="N", reason="Solicitacao revisada de teste",
        human_approved=True,
    )
    validator.validate_document(cancel.request_xml)
    cancel_s = build_osasco_cancel_request(
        source=source, issued=issued, regime=TaxRegimeCode.NORMAL,
        cancel_type="S", reason="Substituicao revisada de teste",
        human_approved=True,
    )
    validator.validate_document(cancel_s.request_xml)


def test_osasco_actual_schema_accepts_typed_cancel_result_but_not_unknown_method() -> None:
    from kordena_fiscal.xml.schema import XmlSchemaValidationError

    validator = _official_xsd_validator()
    xml = (
        b'<t:CancelarResponse xmlns:t="http://tempuri.org/" '
        b'xmlns:a="http://schemas.datacontract.org/2004/07/'
        b'Eissnfe.Negocio.WebServices.Mensagem">'
        b'<t:CancelarResult><a:Erro>false</a:Erro>'
        b'</t:CancelarResult></t:CancelarResponse>'
    )
    validator.validate_document(xml)
    with pytest.raises(XmlSchemaValidationError):
        validator.validate_document(xml.replace(b"CancelarResponse", b"UntrustedReply"))
