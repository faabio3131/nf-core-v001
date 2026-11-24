"""Synthetic annual comparison; official calculators remain covered by T11 tests."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.annual_regime_comparison import AnnualComparison, compare

FIXTURE = Path(__file__).parent / "fixtures/t12_reviewed_annual_example.json"


def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["facts"]


def test_annual_known_reference_and_sensitivity():
    result = compare(AnnualComparison.model_validate(bundle()))
    base = result["scenarios"]["baseline"]
    assert base["revenue_cents"] == 12000000
    assert base["annual_tax_cents"] == {
        "simples_nacional": 1860012, "lucro_presumido": 2079600, "lucro_real": 2118000,
    }
    assert result["sensitivity_tax_delta_cents"]["margin"]["lucro_real"] == 72000
    assert result["sensitivity_tax_delta_cents"]["payroll"]["simples_nacional"] < 0
    assert result["recommendation"]["candidates"] == ["simples_nacional"]
    assert result["regime_change_authorized"] is False
    assert result["payment_authorized"] is False
    assert base["accounting_margin_bps"] == 1000
    assert base["qualifying_payroll_bps"] == 2000
    assert len(base["months"]) == 12
    assert len(base["quarters"]) == 4


@pytest.mark.parametrize("failure", [
    "missing", "history", "revenue", "quarter", "credit", "outside", "double_count",
    "no_sensitivity", "prior_payroll", "boolean", "review", "duplicate_review",
    "opening", "presumption_band", "loss", "extra_revenue", "basis",
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
    elif failure == "opening":
        base["opened_month"] = "2025-02-01"
    elif failure == "presumption_band":
        base["quarters"][1]["irpj_ordinary_limit"] = 0
    elif failure == "loss":
        base["quarters"][0]["irpj_loss_applied"] = 1
    elif failure == "extra_revenue":
        base["quarters"][0]["irpj_other_taxable"] = 1
    elif failure == "basis":
        data["data_basis"] = "actual_certified"
    else:
        data["payroll"]["review_reference"] = "baseline"
    with pytest.raises((FiscalValidationError, ValidationError)):
        compare(AnnualComparison.model_validate(data))
