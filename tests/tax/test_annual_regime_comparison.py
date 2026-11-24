"""Synthetic annual comparison; official calculators remain covered by T11 tests."""
from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.annual_regime_comparison import AnnualComparison, compare
from kordena_fiscal.tax.rfb_regime_regular_calculator import (
    CALCULATOR_DATABASE_VERSION,
    REGIME_REGULAR_CALCULATOR_PIN,
)


def scenario(reference):
    history = [
        {"competence": date(y, m, 1).isoformat(), "trade_revenue": 0,
         "service_revenue": 1000000, "payroll": 200000, "evidence": f"history-{y}-{m}"}
        for y in (2025, 2026) for m in range(1, 13)
    ]
    version = (f"app={REGIME_REGULAR_CALCULATOR_PIN.application_version};"
               f"db={CALCULATOR_DATABASE_VERSION}")
    outside_tax = {"icms": 0, "iss": 0, "employer_contributions": 0,
                   "other_mandatory_taxes": 0, "rtc_net_increment": 0, "evidence": "review"}
    outside = [
        {"competence": m["competence"], "simples_nacional": deepcopy(outside_tax),
         "lucro_presumido": {**outside_tax, "iss": 20000, "employer_contributions": 40000},
         "lucro_real": {**outside_tax, "iss": 20000, "employer_contributions": 40000}}
        for m in history[12:]
    ]
    quarters = [
        {"schema_version": "nfcore.quarterly-regime-facts/v1", "review_status": "reviewed",
         "review_reference": reference, "period_start": date(2026, start, 1).isoformat(),
         "scope": "consolidated_ordinary_nonfinancial_full_quarter_2026",
         "hypothesis": "ordinary_trade_and_general_services",
         "trade_revenue": 0, "services_revenue": 3000000,
         "irpj_ordinary_limit": 125000000, "csll_ordinary_limit": 0 if start == 1 else 125000000,
         "irpj_other_taxable": 0, "csll_other_taxable": 0,
         "real_accounting_result": 300000, "irpj_additions": 0, "irpj_exclusions": 0,
         "csll_additions": 0, "csll_exclusions": 0, "irpj_loss_applied": 0, "csll_loss_applied": 0,
         "months": [{"competence": date(2026, m, 1).isoformat(), "cumulative_base": 1000000,
                     "noncumulative_base": 1000000, "pis_credit": 0, "cofins_credit": 0,
                     "documents": [], "ibs_credits": 0, "cbs_credits": 0,
                     "rtc_evidence": "reviewed-no-rtc-debit", "rtc_component": version}
                    for m in range(start, start + 3)]}
        for start in (1, 4, 7, 10)
    ]
    return {"review_reference": reference, "eligibility_reference": "eligibility-reviewed",
            "accounting_scope": "all_establishments_ordinary_domestic_accrual",
            "settlement_scope": "reviewed_net_tax_burden_no_unallocated_credit",
            "uf": "SP", "service_activity": "service_factor_r",
            "history": history, "outside": outside, "quarters": quarters}


def bundle():
    base = scenario("baseline")
    margin = scenario("margin")
    margin["quarters"][0]["real_accounting_result"] = 600000
    payroll = scenario("payroll")
    for m in payroll["history"][12:]:
        m["payroll"] = 400000
    for m in payroll["outside"]:
        for regime in ("lucro_presumido", "lucro_real"):
            m[regime]["employer_contributions"] = 80000
    return {"schema_version": "nfcore.annual-regime-comparison/v1", "review_status": "reviewed",
            "data_basis": "reviewed_annual_scenarios",
            "baseline": base, "margin": margin, "payroll": payroll}


def test_annual_known_reference_and_sensitivity():
    result = compare(AnnualComparison.model_validate(bundle()))
    base = result["scenarios"]["baseline"]
    assert base["revenue_cents"] == 12000000
    assert base["annual_tax_cents"] == {
        "simples_nacional": 1860000, "lucro_presumido": 2079600, "lucro_real": 2118000,
    }
    assert result["sensitivity_tax_delta_cents"]["margin"]["lucro_real"] == 72000
    assert result["sensitivity_tax_delta_cents"]["payroll"]["simples_nacional"] < 0
    assert result["recommendation"]["candidates"] == ["simples_nacional"]
    assert result["regime_change_authorized"] is False
    assert result["payment_authorized"] is False
    assert len(base["months"]) == 12
    assert len(base["quarters"]) == 4


@pytest.mark.parametrize("failure", [
    "missing", "history", "revenue", "quarter", "credit", "outside", "double_count",
    "no_sensitivity", "prior_payroll", "boolean", "review", "duplicate_review",
])
def test_fail_closed(failure):
    data = bundle()
    base = data["baseline"]
    if failure == "missing":
        base["quarters"].pop()
    elif failure == "history":
        base["history"][0]["competence"] = "2025-02-01"
    elif failure == "revenue":
        data["margin"]["history"][13]["service_revenue"] += 1
    elif failure == "quarter":
        base["quarters"][0]["services_revenue"] += 1
    elif failure == "credit":
        base["quarters"][0]["months"][0]["pis_credit"] = 20000
    elif failure == "outside":
        del base["outside"][0]["lucro_real"]["iss"]
    elif failure == "double_count":
        base["outside"][0]["simples_nacional"]["iss"] = 1
    elif failure == "no_sensitivity":
        data["margin"]["quarters"][0]["real_accounting_result"] = 300000
    elif failure == "prior_payroll":
        data["payroll"]["history"][0]["payroll"] = 0
    elif failure == "boolean":
        base["history"][0]["payroll"] = False
    elif failure == "review":
        data["review_status"] = "draft"
    else:
        data["payroll"]["review_reference"] = "baseline"
    with pytest.raises((FiscalValidationError, ValidationError)):
        compare(AnnualComparison.model_validate(data))
