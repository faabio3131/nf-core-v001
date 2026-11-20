"""T05 deterministic diagnostics; no external fiscal operation."""
from dataclasses import replace
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_diagnostic import PayrollScenario, diagnose_simples
from kordena_fiscal.tax.simples_nacional import Activity, MonthFacts

from .test_simples_nacional import established


def _diagnose(facts, scenario=None):
    return diagnose_simples(facts, ordinary_domestic_base_cents=100_000, scenario=scenario)


def _scenario(extra=0, cost=None, **kwargs):
    return PayrollScenario(
        MonthFacts(date(2026, 2, 1), 100_000, 0, 99_000_000, "forecast"),
        100_000, extra, cost, "estimated-taxes" if cost is not None else None,
        **kwargs,
    )


@pytest.mark.parametrize("payroll,gap", [
    (5_039_999, 1), (5_040_000, 0), (5_040_001, 0), (0, 5_040_000),
])
def test_current_gap_exact_cents(payroll, gap):
    data = _diagnose(established(Activity.SERVICE_FACTOR_R, payroll=payroll))
    assert data["current"]["factor_gap_cents"] == gap
    assert data["advisory_only"]
    assert not data["final_pgdas_assessment"]


def test_next_period_rolloff_and_immutable_source():
    facts = established(Activity.SERVICE_FACTOR_R, payroll=0)
    target = _diagnose(facts, _scenario())["scenario"]
    # Jan 2025 leaves the window, Jan 2026 revenue enters it.
    assert target["baseline"]["factor_revenue_cents"] == 16_600_000
    gap = target["minimum_additional_qualifying_payroll_cents"]
    assert gap == 4_648_000
    one_short = _diagnose(facts, _scenario(gap - 1))["scenario"]
    exact = _diagnose(facts, _scenario(gap, 1_000))
    assert not one_short["transition_v_to_iii"]
    assert exact["scenario"]["transition_v_to_iii"]
    assert exact["current"]["annex"] == "V"
    assert exact["scenario"]["projected"]["annex"] == "III"
    assert facts.months[-1].payroll_cents == 0
    assert exact["scenario"]["net_estimated_tax_saving_cents"] == (
        exact["scenario"]["gross_ordinary_das_saving_cents"] - 1_000
    )
    assert exact == _diagnose(facts, _scenario(gap, 1_000))


def test_cost_unknown_is_not_zero_or_profit():
    facts = established(Activity.SERVICE_FACTOR_R)
    scenario = _diagnose(facts, _scenario(5_000_000))["scenario"]
    assert scenario["gross_ordinary_das_saving_cents"] > 0
    assert scenario["net_estimated_tax_saving_cents"] is None
    assert scenario["total_business_cash_impact_cents"] is None


def test_current_factor_not_applicable_to_commerce():
    facts = established()
    assert _diagnose(facts)["current"]["factor_gap_cents"] is None
    with pytest.raises(FiscalValidationError):
        _diagnose(facts, _scenario(100))


def test_zero_revenue_no_payroll_target():
    data = _diagnose(established(Activity.SERVICE_FACTOR_R, rolling=0))
    assert data["current"]["factor_gap_cents"] is None


@pytest.mark.parametrize("revenue,severity", [
    (288_000_000, "warning"),
    (324_000_000, "critical"),
    (360_000_000, "at_limit"),
    (360_000_001, "exceeded"),
])
def test_sublimit_alerts(revenue, severity):
    facts = established()
    current = replace(facts.months[-1], domestic_cents=revenue)
    result = _diagnose(replace(facts, months=(*facts.months[:-1], current)))
    assert any(a["kind"] == "sublimit" and a["severity"] == severity
               for a in result["current"]["alerts"])


def test_prior_year_excess_visible_even_at_low_current_revenue():
    result = _diagnose(established(rolling=360_000_001))
    assert any(a["kind"] == "sublimit" and a["severity"] == "legal_review"
               for a in result["current"]["alerts"])


def test_exceeded_local_limit_blocks_misleading_savings():
    facts = established(Activity.SERVICE_FACTOR_R, rolling=360_000_001)
    result = _diagnose(facts, _scenario(200_000_000, 0))
    assert result["scenario"]["gross_ordinary_das_saving_cents"] is None
    assert result["scenario"]["net_estimated_tax_saving_cents"] is None


def test_wrong_month_and_unreviewed_2027_fail_closed():
    facts = established(Activity.SERVICE_FACTOR_R)
    wrong = replace(_scenario(), next_month=MonthFacts(date(2026, 3, 1), 100_000, 0, 0, "p"))
    with pytest.raises(FiscalValidationError):
        _diagnose(facts, wrong)
    months = facts.months + tuple(
        MonthFacts(date(2026, m, 1), 100_000, 0, 0, "fixture") for m in range(2, 13)
    )
    december = replace(facts, competence=date(2026, 12, 1), months=months)
    future = replace(_scenario(), next_month=MonthFacts(date(2027, 1, 1), 100_000, 0, 0, "p"))
    with pytest.raises(FiscalValidationError):
        _diagnose(december, future)


@pytest.mark.parametrize("extra,cost", [(True, None), (-1, None), (100, -1), (100, 0.5)])
def test_exact_currency_only(extra, cost):
    with pytest.raises(FiscalValidationError):
        _scenario(extra, cost)
