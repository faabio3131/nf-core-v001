"""Synthetic annual comparison; official calculators remain covered by T11 tests."""
import hashlib
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
    assert result["sensitivity_tax_delta_cents"]["payroll"] == {
        "simples_nacional": -665007, "lucro_presumido": 480000, "lucro_real": 192000,
    }
    assert result["scenarios"]["payroll"]["real_accounting_result_cents"] == -1680000
    assert all(q["lucro_real"]["irpj"] == q["lucro_real"]["csll"] == 0
               for q in result["scenarios"]["payroll"]["quarters"])
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


@pytest.mark.parametrize("scenario", ["margin", "payroll"])
@pytest.mark.parametrize("field", ["iss", "pis_credit", "irpj_additions", "rtc", "eligibility"])
def test_no_hidden_sensitivity_mutations(scenario, field):
    data = bundle()
    variant = data[scenario]
    if field == "iss":
        variant["outside"][0]["lucro_presumido"]["iss"] += 1
    elif field == "pis_credit":
        variant["quarters"][0]["months"][0]["pis_credit"] += 1
    elif field == "irpj_additions":
        variant["quarters"][0]["irpj_additions"] += 1
    elif field == "rtc":
        variant["quarters"][0]["months"][0]["ibs_credits"] += 1
    else:
        variant["eligibility_reference"] = "baseline"
    with pytest.raises(FiscalValidationError, match="sensitivity"):
        compare(AnnualComparison.model_validate(data))


def test_payroll_result_cannot_ignore_added_expenses():
    data = bundle()
    data["payroll"]["quarters"][0]["real_accounting_result"] = 300000
    with pytest.raises(FiscalValidationError, match="payroll accounting"):
        compare(AnnualComparison.model_validate(data))


@pytest.mark.parametrize("mutation", ["digest", "missing", "duplicate"])
def test_evidence_artifacts_fail_closed(mutation):
    data = bundle()
    evidence = data["evidence_artifacts"]
    if mutation == "digest":
        evidence[0]["content"] += " altered"
    elif mutation == "missing":
        evidence.pop(0)
    else:
        evidence.append(evidence[0])
    with pytest.raises(FiscalValidationError, match="evidence"):
        compare(AnnualComparison.model_validate(data))


def test_zero_outside_tax_requires_specific_review():
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["outside"][0]["lucro_presumido"]["iss"] = 0
    with pytest.raises(FiscalValidationError, match="zero-tax"):
        compare(AnnualComparison.model_validate(data))
    text = "Synthetic test only: specific zero ISS reason"
    data["evidence_artifacts"].append({
        "reference": "zero-iss-specific", "content": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    })
    for name in ("baseline", "margin", "payroll"):
        data[name]["outside"][0]["lucro_presumido"]["zero_justifications"] = {
            "iss": "zero-iss-specific",
        }
    assert compare(AnnualComparison.model_validate(data))["status"] == "compared"


@pytest.mark.parametrize("extra,expected", [(219588, "tie"), (300000, "review_required")])
def test_tie_and_ranking_inversion(extra, expected):
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["outside"][0]["simples_nacional"]["other_mandatory_taxes"] = extra
    result = compare(AnnualComparison.model_validate(data))
    assert result["recommendation"]["status"] == expected
    assert result["recommendation"]["sensitivity_stable"] is False
    if expected == "tie":
        assert result["recommendation"]["candidates"] == [
            "simples_nacional", "lucro_presumido",
        ]
    else:
        assert result["recommendation"]["candidates"] == ["lucro_presumido"]
    assert result["scenarios"]["payroll"]["lowest_tax_burden"] == ["simples_nacional"]


def test_mixed_trade_services_and_annex_iv():
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        scenario = data[name]
        scenario["service_activity"] = "service_iv"
        for month in scenario["history"]:
            month["trade_revenue"], month["service_revenue"] = 300000, 700000
        for q in scenario["quarters"]:
            q["trade_revenue"], q["services_revenue"] = 900000, 2100000
        for outside in scenario["outside"]:
            outside["simples_nacional"]["employer_contributions"] = (
                80000 if name == "payroll" else 40000
            )
            for regime in ("lucro_presumido", "lucro_real"):
                outside[regime]["icms"] = 10000
    result = compare(AnnualComparison.model_validate(data))
    assert result["scenarios"]["baseline"]["revenue_cents"] == 12000000
    assert result["scenarios"]["baseline"]["months"][0]["outside"]["simples_nacional"][
        "employer_contributions"
    ] == 40000


def test_additional_irpj():
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["quarters"][0]["real_accounting_result"] += 7000000
    result = compare(AnnualComparison.model_validate(data))
    assert result["scenarios"]["baseline"]["quarters"][0]["lucro_real"]["additional_irpj"] == 130000


def test_duplicate_rtc_across_quarters():
    data = bundle()
    doc = json.loads((FIXTURE.parent / "t11_reviewed_example.json").read_text(
        encoding="utf-8"))["facts"]["months"][0]["documents"][0]
    for name in ("baseline", "margin", "payroll"):
        for q in data[name]["quarters"][:2]:
            q["months"][0]["documents"] = [doc]
    with pytest.raises(FiscalValidationError, match="duplicate RTC"):
        compare(AnnualComparison.model_validate(data))


def test_sublimit_and_federal_base():
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["history"][0]["service_revenue"] = 360000001
    with pytest.raises(FiscalValidationError, match="sublimit"):
        compare(AnnualComparison.model_validate(data))
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["quarters"][0]["months"][0]["cumulative_base"] = 1000001
    with pytest.raises(FiscalValidationError, match="bases exceed"):
        compare(AnnualComparison.model_validate(data))


def test_annual_presumption_available_band():
    data = bundle()
    for name in ("baseline", "margin", "payroll"):
        data[name]["quarters"][2]["irpj_ordinary_limit"] = 375000000
    with pytest.raises(FiscalValidationError, match="presumption uplift"):
        compare(AnnualComparison.model_validate(data))
