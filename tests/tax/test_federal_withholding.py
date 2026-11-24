from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.issuance.nfse_archive import decode_prepared_nfse, encode_prepared_nfse
from kordena_fiscal.issuance.nfse_dps_builder import build_unsigned_dps
from kordena_fiscal.tax.federal_withholding import (
    RULESET_STATUS,
    FederalWithholding,
    WithholdingCategory,
    propose_federal_withholding,
)

NS = "{http://www.sped.fazenda.gov.br/nfse}"
_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _request(**service_overrides) -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        tenant_id="tenant-a", unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-withholding-1", host_namespace="host-a",
    )
    issuer = FiscalProfile(
        profile_id="issuer-withholding-1", scope=scope, cnpj=Cnpj("11222333000181"),
        legal_name="Empresa Sintetica de Servicos Ltda", tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="100", district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"), postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    fields = dict(
        line_number=1, municipal_service_code="0107", national_taxation_code="010701",
        description="Servico sintetico de tecnologia", gross_amount=Money(Decimal("100.00")),
        iss_amount=Money(Decimal("3.00")), iss_withheld=False,
    )
    fields.update(service_overrides)
    document = NfseCanonicalDocument(
        document_id="nfse-withholding-doc-1", scope=scope,
        source=SourceReference("service-order", "order-withholding-1"),
        issued_at=_NOW, competence_date=_NOW.date(), issuer=issuer,
        service_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        services=(NfseServiceLine(**fields),), service_taker_reference="taker-ref-1",
        dps_number=1,
    )
    return NfseAuthorizationRequest.build(document)


def _p(amount: str, **kw):
    args = dict(taker_is_legal_entity=True, issuer_in_simples_nacional=False,
                category=WithholdingCategory.PROFESSIONAL)
    args.update(kw)
    return propose_federal_withholding(gross_amount=Decimal(amount), **args)


def test_professional_service_to_pj_withholds_irrf_and_pcc() -> None:
    p = _p("10000.00")
    assert (p.irrf, p.pis, p.cofins, p.csll) == (
        Decimal("150.00"), Decimal("65.00"), Decimal("300.00"), Decimal("100.00"))
    assert p.retention_type == "3" and p.status == RULESET_STATUS


def test_cleaning_security_labor_uses_irrf_one_percent() -> None:
    assert _p("10000.00", category=WithholdingCategory.CLEANING_SECURITY_LABOR).irrf == Decimal(
        "100.00")


def test_dispensed_up_to_ten_reais() -> None:
    p = _p("200.00")  # IRRF 3.00, PCC 9.30
    assert p.irrf == p.pis == p.cofins == p.csll == Decimal("0.00")
    assert p.retention_type == "0" and len(p.reasons) == 2
    q = _p("700.00")  # IRRF 10.50 withheld; PCC 32.55 withheld
    assert q.irrf == Decimal("10.50") and q.csll == Decimal("7.00")


@pytest.mark.parametrize("kw", [
    {"taker_is_legal_entity": False},
    {"issuer_in_simples_nacional": True},
    {"category": WithholdingCategory.NONE},
])
def test_no_withholding_cases(kw) -> None:
    p = _p("10000.00", **kw)
    assert p.irrf + p.pis + p.cofins + p.csll == 0 and p.retention_type == "0"


def test_dps_requires_accountant_review_reference() -> None:
    with pytest.raises(FiscalValidationError):
        _p("10000.00").approve("  ")


def _with_withholding(withholding: FederalWithholding | None) -> NfseAuthorizationRequest:
    base = _request(gross_amount=Money(Decimal("10000.00")), iss_amount=Money(Decimal("300.00")))
    document = base.document
    issuer = replace(document.issuer, tax_regime=TaxRegimeCode.NORMAL)
    return NfseAuthorizationRequest.build(
        replace(document, issuer=issuer, federal_withholding=withholding))


def test_reviewed_withholding_goes_to_tribfed_and_passes_the_official_xsd() -> None:
    reviewed = _p("10000.00").approve("Parecer contadora 2026-11-20")
    request = _with_withholding(reviewed)
    root = etree.fromstring(build_unsigned_dps(request))
    fed = root.find(f".//{NS}tribFed")
    assert fed is not None
    assert fed.findtext(f"{NS}piscofins/{NS}vPis") == "65.00"
    assert fed.findtext(f"{NS}piscofins/{NS}vCofins") == "300.00"
    assert fed.findtext(f"{NS}piscofins/{NS}tpRetPisCofins") == "3"
    assert fed.findtext(f"{NS}vRetIRRF") == "150.00"
    assert fed.findtext(f"{NS}vRetCSLL") == "100.00"
    # Withholding is part of the fingerprint and survives the archive.
    assert request.request_fingerprint != _with_withholding(None).request_fingerprint
    decoded = decode_prepared_nfse(encode_prepared_nfse(request), scope=request.document.scope)
    assert decoded.document.federal_withholding == reviewed


def test_without_withholding_xml_has_no_tribfed() -> None:
    root = etree.fromstring(build_unsigned_dps(_with_withholding(None)))
    assert root.find(f".//{NS}tribFed") is None


def test_withholding_base_must_match_service_value() -> None:
    wrong = _p("9000.00").approve("Parecer")
    with pytest.raises(FiscalValidationError):
        build_unsigned_dps(_with_withholding(wrong))
