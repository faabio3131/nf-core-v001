"""T04: independent legal table fixtures, cent precision, startup and limit gates."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import (
    Activity,
    Annex,
    LimitStatus,
    MonthFacts,
    SimplesFacts,
    UF_CODES,
    calculate_simples,
)

# Independently recorded nominal and deduction reference from LC 123 annexes.
@pytest.mark.parametrize("activity,annex,revenue,expected", [
    (Activity.COMMERCE, Annex.I, 180000, "0.04"),
    (Activity.COMMERCE, Annex.I, 360000, "0.0565"),
    (Activity.COMMERCE, Annex.I, 720000, "0.07575"),
    (Activity.COMMERCE, Annex.I, 1800000, "0.0945"),
    (Activity.COMMERCE, Annex.I, 3600000, "0.11875"),
    (Activity.COMMERCE, Annex.I, 4800000, "0.11125"),
    (Activity.INDUSTRY, Annex.II, 180000, "0.045"),
    (Activity.INDUSTRY, Annex.II, 360000, "0.0615"),
    (Activity.INDUSTRY, Annex.II, 720000, "0.08075"),
    (Activity.INDUSTRY, Annex.II, 1800000, "0.0995"),
    (Activity.INDUSTRY, Annex.II, 3600000, "0.12325"),
    (Activity.INDUSTRY, Annex.II, 4800000, "0.15"),
    (Activity.SERVICE_III, Annex.III, 180000, "0.06"),
    (Activity.SERVICE_III, Annex.III, 360000, "0.086"),
    (Activity.SERVICE_III, Annex.III, 720000, "0.1105"),
    (Activity.SERVICE_III, Annex.III, 1800000, "0.1402"),
    (Activity.SERVICE_III, Annex.III, 3600000, "0.1751"),
    (Activity.SERVICE_III, Annex.III, 4800000, "0.195"),
    (Activity.SERVICE_IV, Annex.IV, 180000, "0.045"),
    (Activity.SERVICE_IV, Annex.IV, 360000, "0.0675"),
    (Activity.SERVICE_IV, Annex.IV, 720000, "0.08475"),
    (Activity.SERVICE_IV, Annex.IV, 1800000, "0.1179"),
    (Activity.SERVICE_IV, Annex.IV, 3600000, "0.16895"),
    (Activity.SERVICE_IV, Annex.IV, 4800000, "0.1575"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 180000, "0.155"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 360000, "0.1675"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 720000, "0.18125"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 1800000, "0.1955"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 3600000, "0.21275"),
    (Activity.SERVICE_FACTOR_R, Annex.V, 4800000, "0.1925"),
])
def test_five_annexes_all_bands(activity, annex, revenue, expected):
    facts = established(activity, revenue * 100)
    result = calculate_simples(facts, ordinary_domestic_base_cents=100_000)
    assert result.annex is annex
    assert result.domestic.effective_rate == Decimal(expected)
    assert result.cpp_outside_das == (annex is Annex.IV)


def established(activity=Activity.COMMERCE, rolling=18_000_000, payroll=0):
    months = tuple(
        MonthFacts(date(2025, month, 1), rolling // 12 + (rolling % 12 if month == 12 else 0),
                   0, payroll // 12 + (payroll % 12 if month == 12 else 0), "fixture")
        for month in range(1, 13)
    ) + (MonthFacts(date(2026, 1, 1), 100_000, 0, 0, "fixture"),)
    return SimplesFacts(
        date(2026, 1, 1), date(2024, 1, 1), "SP", activity, months,
        "company-consolidated", "activity-reviewed", "optant-fixture",
    )


@pytest.mark.parametrize("payroll,annex", [
    (5_039_999, Annex.V), (5_040_000, Annex.III), (5_040_001, Annex.III),
])
def test_factor_r_exact_cent_boundary(payroll, annex):
    result = calculate_simples(
        established(Activity.SERVICE_FACTOR_R, payroll=payroll),
        ordinary_domestic_base_cents=100_000,
    )
    assert result.annex is annex


@pytest.mark.parametrize("payroll,revenue,expected", [
    (100, 0, "0.28"), (0, 0, "0.01"), (0, 100, "0.01"),
])
def test_factor_r_zero_rules(payroll, revenue, expected):
    result = calculate_simples(
        established(Activity.SERVICE_FACTOR_R, revenue, payroll),
        ordinary_domestic_base_cents=100_000,
    )
    assert result.factor_r == Decimal(expected)


def test_rounding_half_cent_and_art21_zero_denominator():
    result = calculate_simples(
        established(Activity.INDUSTRY, 0), ordinary_domestic_base_cents=100,
    )
    assert result.ordinary_domestic_estimate_cents == 5
    assert result.domestic.effective_rate == Decimal("0.045")


def startup(revenue, payroll=0, activity=Activity.COMMERCE):
    period = date(2026, 12, 1)
    return SimplesFacts(period, period, "MG", activity,
                        (MonthFacts(period, revenue, 0, payroll, "fixture"),),
                        "company", "activity", "optant")


def test_first_month_annualized_and_prorated_limits():
    result = calculate_simples(startup(1_500_000), ordinary_domestic_base_cents=1_500_000)
    assert result.domestic.rbt12_cents == 18_000_000
    assert result.ordinary_domestic_estimate_cents == 60_000
    assert result.sublimit_cents == 30_000_000
    assert result.limit_cents == 40_000_000


@pytest.mark.parametrize("revenue,status", [
    (30_000_000, LimitStatus.WITHIN),
    (30_000_001, LimitStatus.NEXT_YEAR),
    (36_000_000, LimitStatus.NEXT_YEAR),
    (36_000_001, LimitStatus.RETROACTIVE),
])
def test_startup_sublimit_strict_20_percent(revenue, status):
    result = calculate_simples(startup(revenue), ordinary_domestic_base_cents=revenue)
    assert result.sublimit_status is status
    if status is not LimitStatus.WITHIN:
        assert result.ordinary_domestic_estimate_cents is None


def test_startup_month_two_annualizes_previous_month_not_current():
    first = startup(1_000_000, 280_000, Activity.SERVICE_FACTOR_R)
    november = replace(first.months[0], competence=date(2026, 11, 1))
    facts = replace(first, opened_month=november.competence, months=(november, *first.months))
    result = calculate_simples(facts, ordinary_domestic_base_cents=1_000_000)
    assert result.domestic.rbt12_cents == 12_000_000
    assert result.factor_r == Decimal("0.28")


def test_separate_export_rate_and_combined_factor():
    facts = established(Activity.SERVICE_FACTOR_R, payroll=5_040_000)
    prior = tuple(replace(m, export_cents=m.domestic_cents) for m in facts.months[:-1])
    result = calculate_simples(
        replace(facts, months=(*prior, facts.months[-1])),
        ordinary_domestic_base_cents=100_000,
    )
    assert result.domestic.rbt12_cents == result.export.rbt12_cents == 18_000_000
    assert result.factor_r == Decimal("0.14")
    assert result.annex is Annex.V


def test_previous_year_sublimit_outside_local_tax():
    result = calculate_simples(established(rolling=360_000_001),
                               ordinary_domestic_base_cents=100_000)
    assert result.sublimit_status is LimitStatus.OUTSIDE
    assert result.domestic.local_effective_rate == 0
    assert result.ordinary_domestic_estimate_cents is not None


def test_previous_year_federal_limit_no_amount():
    result = calculate_simples(established(rolling=480_000_001),
                               ordinary_domestic_base_cents=100_000)
    assert result.limit_status is LimitStatus.OUTSIDE
    assert result.ordinary_domestic_estimate_cents is None


def test_fail_closed_missing_history_or_future_law_and_invalid_money():
    facts = established()
    with pytest.raises(FiscalValidationError):
        replace(facts, months=facts.months[1:])
    with pytest.raises(FiscalValidationError):
        replace(facts, competence=date(2027, 1, 1))
    with pytest.raises(FiscalValidationError):
        calculate_simples(facts, ordinary_domestic_base_cents=100_001)
    with pytest.raises(FiscalValidationError):
        MonthFacts(date(2026, 1, 1), True, 0, 0, "fixture")


def test_replay_content_digest_and_input_change():
    facts = established()
    a = calculate_simples(facts, ordinary_domestic_base_cents=100_000)
    b = calculate_simples(facts, ordinary_domestic_base_cents=99_999)
    assert a == calculate_simples(facts, ordinary_domestic_base_cents=100_000)
    assert a.calculation_digest != b.calculation_digest
    assert a.rule_digest == b.rule_digest


def test_official_receita_question_5_3_reference_arithmetic():
    # Receita's question 5.3: RBT12 220,000, base 25,000, DAS 1,150.
    # Reproduce the arithmetic with the same annex table in the 2026 policy.
    facts = established(rolling=22_000_000)
    last = replace(facts.months[-1], domestic_cents=2_500_000)
    result = calculate_simples(
        replace(facts, months=(*facts.months[:-1], last)),
        ordinary_domestic_base_cents=2_500_000,
    )
    assert result.domestic.effective_rate == Decimal("0.046")
    assert result.ordinary_domestic_estimate_cents == 115_000


@pytest.mark.parametrize("uf", sorted(UF_CODES))
def test_2026_sublimit_in_all_27_ufs(uf):
    result = calculate_simples(replace(established(), uf=uf), ordinary_domestic_base_cents=100)
    assert result.sublimit_cents == 360_000_000


@pytest.mark.parametrize("before,month,status", [
    (350_000_000, 10_000_000, LimitStatus.WITHIN),
    (350_000_000, 10_000_001, LimitStatus.NEXT_YEAR),
    (350_000_000, 82_000_000, LimitStatus.NEXT_YEAR),
    (350_000_000, 82_000_001, LimitStatus.NEXT_MONTH),
    (432_000_001, 100, LimitStatus.OUTSIDE),
])
def test_current_year_sublimit_effect(before, month, status):
    facts = established()
    january = replace(facts.months[-1], domestic_cents=before)
    february = MonthFacts(date(2026, 2, 1), month, 0, 0, "fixture")
    result = calculate_simples(
        replace(facts, competence=february.competence, months=(*facts.months[:-1],
                january, february)), ordinary_domestic_base_cents=month,
    )
    assert result.sublimit_status is status


@pytest.mark.parametrize("activity,expected", [
    (Activity.SERVICE_III, Decimal("0.05")),
    (Activity.SERVICE_IV, Decimal("0.05")),
    (Activity.SERVICE_FACTOR_R, Decimal("0.05")),
])
def test_iss_cap_and_federal_redistribution(activity, expected):
    result = calculate_simples(
        established(activity, 360_000_000), ordinary_domestic_base_cents=100_000,
    )
    assert result.domestic.local_effective_rate == expected
    assert result.domestic.federal_effective_rate + result.domestic.local_effective_rate == (
        result.domestic.effective_rate
    )


def test_opening_factor_exact_current_month():
    result = calculate_simples(
        startup(100_000, 28_000, Activity.SERVICE_FACTOR_R),
        ordinary_domestic_base_cents=100_000,
    )
    assert result.annex is Annex.III
    assert result.factor_r == Decimal("0.28")


def test_first_month_without_movement_is_not_fabricated_factor():
    with pytest.raises(FiscalValidationError, match="factor undefined"):
        calculate_simples(startup(0, 0, Activity.SERVICE_FACTOR_R), ordinary_domestic_base_cents=0)


@pytest.mark.parametrize("activity,annex", [
    (Activity.COMMERCE, Annex.I), (Activity.INDUSTRY, Annex.II),
    (Activity.SERVICE_III, Annex.III), (Activity.SERVICE_IV, Annex.IV),
    (Activity.SERVICE_FACTOR_R, Annex.V),
])
@pytest.mark.parametrize("ceiling", [18_000_000, 36_000_000, 72_000_000, 180_000_000, 360_000_000])
def test_one_cent_transitions(activity, annex, ceiling):
    a = calculate_simples(established(activity, ceiling), ordinary_domestic_base_cents=100)
    b = calculate_simples(established(activity, ceiling + 1), ordinary_domestic_base_cents=100)
    assert a.annex is b.annex is annex
    assert b.domestic.bracket == a.domestic.bracket + 1
