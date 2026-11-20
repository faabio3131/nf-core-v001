"""Synthetic benefit contract tests; no real fiscal authorization."""
from dataclasses import replace
from decimal import Decimal

import pytest
from lxml import etree

from kordena_fiscal.documents.serialization import _tax_decision
from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.issuance.nfe_builder import _taxes
from kordena_fiscal.tax.models import TaxDecision, TaxRuleOutcome
from kordena_fiscal.tax.nfe_calculation import (
    NfeRateParameters,
    ReviewedIcmsBenefit,
    calculate_nfe_line,
)


def decision(cst: str, *, deduct: bool = False) -> TaxDecision:
    reason = None if cst == "51" else 9
    benefit = ReviewedIcmsBenefit(
        "SP123456", "synthetic-reviewer", "synthetic-approval",
        deson_mode="nominal_minus_due" if reason is not None else None,
        deson_rate=Decimal("18") if reason is not None else None,
        deson_reason=reason,
        deduct_deson=deduct if reason is not None else None,
        deferral_rate=Decimal("50") if cst == "51" else None,
    )
    rates = NfeRateParameters(
        icms_rate=Decimal("0" if cst in {"40", "41"} else "18"),
        pis_rate=Decimal("0"), cofins_rate=Decimal("0"),
        pis_base="net", cofins_base="net",
        icms_reduction_rate=Decimal("20") if cst == "20" else None,
        icms_benefit=benefit,
    )
    return TaxDecision(
        rule_id="synthetic", rule_version=1, source_normative="synthetic-only",
        rank=(8, 8, 1), outcome=TaxRuleOutcome(
            cfop="5102", icms_code=cst, pis_cst="07", cofins_cst="07", nfe_rates=rates,
        ),
    )


@pytest.mark.parametrize(
    ("cst", "due", "deson", "deferred"),
    [
        ("20", "14.40", "3.60", "0.00"),
        ("40", "0.00", "18.00", "0.00"),
        ("41", "0.00", "18.00", "0.00"),
        ("51", "9.00", "0.00", "9.00"),
    ],
)
def test_benefit_calculation_xml_and_evidence(cst, due, deson, deferred):
    value = decision(cst)
    taxes = calculate_nfe_line(
        value, net_amount=Decimal("100.00"), regime=TaxRegimeCode.NORMAL,
    )
    assert taxes.icms_amount == Decimal(due)
    assert taxes.icms_deson_amount == Decimal(deson)
    assert taxes.icms_deferred_amount == Decimal(deferred)
    assert taxes.icms_deson_deduction == 0
    parent = etree.Element("imposto")
    _taxes(parent, value.outcome, 0, taxes)
    assert parent.xpath("string(.//*[local-name()='CST'])") == cst
    if cst == "51":
        assert parent.xpath("string(.//*[local-name()='vICMSDif'])") == deferred
    else:
        assert parent.xpath("string(.//*[local-name()='vICMSDeson'])") == deson
        assert parent.xpath("string(.//*[local-name()='indDeduzDeson'])") == "0"
    evidence = _tax_decision(value)["outcome"]["nfe_rates"]["icms_benefit"]
    assert evidence["code"] == "SP123456"
    assert evidence["approval_reference"] == "synthetic-approval"


def test_deduction_only_when_explicit():
    value = decision("20", deduct=True)
    taxes = calculate_nfe_line(
        value, net_amount=Decimal("100.00"), regime=TaxRegimeCode.NORMAL,
    )
    assert taxes.icms_deson_deduction == Decimal("3.60")


def test_cst51_rejects_absent_evidence():
    value = decision("51")
    rates = value.outcome.nfe_rates
    assert rates is not None
    changed = replace(value, outcome=replace(
        value.outcome, nfe_rates=replace(rates, icms_benefit=None),
    ))
    with pytest.raises(FiscalValidationError, match="reviewed benefit"):
        calculate_nfe_line(
            changed, net_amount=Decimal("100.00"), regime=TaxRegimeCode.NORMAL,
        )
