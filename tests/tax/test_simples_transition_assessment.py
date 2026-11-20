"""CGSN 190: timing, exact components and fail-closed regime input."""
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode
from kordena_fiscal.tax.simples_nacional import (
    Activity,
    Annex,
    LimitStatus,
    MonthFacts,
    SimplesFacts,
    assessment_partition,
    calculate_simples,
    transition_effective_rate,
)

UNIFIED = SimplesIbsCbsMode.SIMPLES_UNIFIED
REGULAR = SimplesIbsCbsMode.REGULAR_SEPARATE


def facts(period, rows, *, opened=date(2024, 1, 1), activity=Activity.SERVICE_FACTOR_R):
    return SimplesFacts(
        period, opened, "SP", activity,
        tuple(MonthFacts(day, revenue, exported, payroll, "fixture")
              for day, revenue, exported, payroll in rows),
        "company", "activity", "option",
    )


def test_lagged_window_excludes_december_and_current_january():
    rows = [(date(2025, 12, 1), 1_500_000, 0, 420_000)]
    rows.extend((date(2026, m, 1), 1_500_000, 0, 420_000) for m in range(1, 12))
    rows.extend([(date(2026, 12, 1), 8_000_000, 0, 0),
                 (date(2027, 1, 1), 100_000, 0, 0)])
    item = facts(date(2027, 1, 1), rows)
    result = calculate_simples(item, ordinary_domestic_base_cents=100_000, mode=UNIFIED)
    assert result.domestic.rbt12_cents == 18_000_000
    assert result.factor_r == Decimal("0.28")
    assert result.annex is Annex.ANNEX_III
    assert result.ordinary_domestic_estimate_cents == 6000
    with pytest.raises(FiscalValidationError, match="resolved IBS/CBS"):
        calculate_simples(item, ordinary_domestic_base_cents=100_000)
    with pytest.raises(FiscalValidationError, match="missing"):
        facts(date(2027, 1, 1), rows[1:])


def test_startup_first_two_months_and_third_month():
    rows = [(date(2027, 1, 1), 3_000_000, 0, 0),
            (date(2027, 2, 1), 100_000, 0, 5_000_000),
            (date(2027, 3, 1), 100_000, 0, 0)]
    for index in (0, 1):
        item = facts(rows[index][0], rows[:index + 1], opened=rows[0][0])
        result = calculate_simples(item, ordinary_domestic_base_cents=100_000, mode=UNIFIED)
        assert result.annex is Annex.ANNEX_III
        assert result.factor_r == Decimal("0.28")
        assert result.domestic.bracket == 1
    third = facts(rows[2][0], rows, opened=rows[0][0])
    result = calculate_simples(third, ordinary_domestic_base_cents=100_000, mode=UNIFIED)
    assert result.domestic.rbt12_cents == 36_000_000
    assert result.annex is Annex.ANNEX_V
    assert result.factor_r == Decimal("0.01")


def test_art_22a_regular_option_deducts_only_ibs_and_cbs():
    period = date(2027, 1, 1)
    rate = transition_effective_rate(
        period, Annex.ANNEX_I, Fraction(18_000_000), outside_local=False, mode=UNIFIED,
    )
    separate = transition_effective_rate(
        period, Annex.ANNEX_I, Fraction(18_000_000), outside_local=False, mode=REGULAR,
    )
    assert rate["cbs"] == Fraction(6132, 1_000_000)
    assert rate["ibs"] == Fraction(68, 1_000_000)
    assert sum(rate.values()) == Fraction(4, 100)
    assert separate["cbs"] == separate["ibs"] == 0
    assert all(rate[tax] == separate[tax] for tax in rate if tax not in {"cbs", "ibs"})


def test_sixth_band_includes_fifth_band_ibs_before_impediment():
    period = date(2027, 1, 1)
    rbt = Fraction(400_000_000)
    inside = transition_effective_rate(
        period, Annex.ANNEX_I, rbt, outside_local=False, mode=UNIFIED,
    )
    outside = transition_effective_rate(
        period, Annex.ANNEX_I, rbt, outside_local=True, mode=UNIFIED,
    )
    assert inside["ibs"] == Fraction(1430, 10_000) * Fraction(17, 10_000) - (
        Fraction(8_730_000) / rbt * Fraction(17, 10_000)
    )
    assert outside["ibs"] == outside["icms"] == outside["iss"] == 0
    assert inside["cbs"] == outside["cbs"]


def test_2027_excess_uses_single_effective_rate():
    rows = [(date(2025, 12, 1), 0, 0, 0)]
    rows.extend((date(2026, m, 1), 0, 0, 0) for m in range(1, 13))
    rows.extend([(date(2027, 1, 1), 350_000_000, 0, 0),
                 (date(2027, 2, 1), 20_000_000, 0, 0)])
    item = facts(date(2027, 2, 1), rows, activity=Activity.COMMERCE)
    result = calculate_simples(item, ordinary_domestic_base_cents=20_000_000, mode=UNIFIED)
    rate, federal_excess, local_excess = assessment_partition(
        item, result.annex, export=False, outside_local=False, mode=UNIFIED,
    )
    assert result.sublimit_status is LimitStatus.NEXT_YEAR
    assert federal_excess == local_excess == 0
    assert sum(rate.values()) == Fraction(4, 100)
    assert result.ordinary_domestic_estimate_cents == 800_000


def test_iss_cap_includes_ibs_redistribution():
    period = date(2027, 1, 1)
    rate = transition_effective_rate(
        period, Annex.ANNEX_III, Fraction(360_000_000),
        outside_local=False, mode=UNIFIED,
    )
    no_redistribution = transition_effective_rate(
        period, Annex.ANNEX_III, Fraction(360_000_000),
        outside_local=False, mode=UNIFIED, redistribute_iss=False,
    )
    assert rate["iss"] == Fraction(5, 100)
    assert rate["ibs"] > no_redistribution["ibs"]
    assert rate["cbs"] > no_redistribution["cbs"]
    assert sum(rate.values()) == Fraction(1751, 10_000)
