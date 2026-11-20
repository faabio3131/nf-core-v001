from datetime import date
from fractions import Fraction

import pytest

from kordena_fiscal.tax.simples_nacional import (
    Activity,
    Annex,
    MonthFacts,
    SimplesFacts,
    assessment_partition,
    calculate_simples,
    partition_effective_rate,
)
from kordena_fiscal.tax.simples_segregation import (
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    assess_segregated,
)

PERIOD = date(2026, 1, 1)


def facts(domestic=100000, export=0, payroll=0):
    return SimplesFacts(
        PERIOD, PERIOD, "SP", Activity.COMMERCE,
        (MonthFacts(PERIOD, domestic, export, payroll, "fixture"),),
        "company", "activity", "optant",
    )


def line(activity=Activity.COMMERCE, market=Market.DOMESTIC,
         federal=FederalTreatment.ORDINARY, local=LocalTreatment.ORDINARY):
    return RevenueLine("a", 100000, activity, market, federal, local, "doc", "review")


@pytest.mark.parametrize(("activity", "amount"), [
    (Activity.COMMERCE, 4000),
    (Activity.INDUSTRY, 4502),
    (Activity.SERVICE_III, 6000),
    (Activity.SERVICE_IV, 4500),
    (Activity.SERVICE_FACTOR_R, 15501),
])
def test_first_band(activity, amount):
    result = assess_segregated(facts(), (line(activity),),
                               domestic_cents=100000, export_cents=0)
    assert result["estimated_das_cents"] == amount
    assert result["advisory_only"] is True


@pytest.mark.parametrize(("federal", "local", "amount"), [
    (FederalTreatment.MONOPHASE, LocalTreatment.ORDINARY, 3380),
    (FederalTreatment.ORDINARY, LocalTreatment.ICMS_SUBSTITUTED, 2640),
    (FederalTreatment.MONOPHASE, LocalTreatment.ICMS_FINAL_ADVANCE, 2020),
    (FederalTreatment.ORDINARY, LocalTreatment.ICMS_SUBSTITUTE, 4000),
])
def test_goods_exclusions(federal, local, amount):
    result = assess_segregated(facts(), (line(federal=federal, local=local),),
                               domestic_cents=100000, export_cents=0)
    assert result["estimated_das_cents"] == amount


def test_export_and_iss():
    result = assess_segregated(
        facts(domestic=0, export=100000), (line(market=Market.EXPORT),),
        domestic_cents=0, export_cents=100000,
    )
    assert result["estimated_das_cents"] == 2020
    result = assess_segregated(
        facts(), (line(Activity.SERVICE_III, local=LocalTreatment.ISS_WITHHELD),),
        domestic_cents=100000, export_cents=0,
    )
    assert result["estimated_das_cents"] == 3990


def test_factor_r_reuses_existing_authority():
    result = assess_segregated(
        facts(payroll=28000), (line(Activity.SERVICE_FACTOR_R),),
        domestic_cents=100000, export_cents=0,
    )
    assert result["estimated_das_cents"] == 6000


@pytest.mark.parametrize("annex", list(Annex))
@pytest.mark.parametrize("rbt", [10000000, 30000000, 50000000, 100000000, 350000000])
def test_partition_preserves_total_and_iss_cap(annex, rbt):
    parts = partition_effective_rate(annex, Fraction(rbt))
    assert sum(parts.values()) > 0
    assert all(value >= 0 for value in parts.values())
    assert parts["iss"] <= Fraction(5, 100)
    if annex is Annex.ANNEX_IV:
        assert not parts["cpp"]


def test_blocked_classification_and_annual_limit():
    result = assess_segregated(
        facts(), (line(federal=FederalTreatment.UNKNOWN),),
        domestic_cents=100000, export_cents=0,
    )
    assert result["estimated_das_cents"] is None
    result = assess_segregated(
        facts(domestic=500000000), (line(),),
        domestic_cents=100000, export_cents=0,
    )
    assert result["estimated_das_cents"] is None


def test_ordinary_matches_t04_first_band():
    estimate = calculate_simples(facts(), ordinary_domestic_base_cents=100000)
    result = assess_segregated(facts(), (line(),), domestic_cents=100000, export_cents=0)
    assert result["estimated_das_cents"] == estimate.ordinary_domestic_estimate_cents


def test_manual_pgdas_example_8_sixth_band_iss_redistribution():
    # Manual PGDAS-D, example 8, pp. 117–118: equivalent 2026 accrual
    # history, RBT12 4.5m, annual revenue 4m incl. 1m current month.
    months = tuple(
        MonthFacts(date(2025, month, 1), 0 if month <= 6 else 25_000_000,
                   0, 0, "manual-example-8")
        for month in range(1, 13)
    ) + tuple(
        MonthFacts(date(2026, month, 1), 50_000_000 if month < 7 else 100_000_000,
                   0, 0, "manual-example-8")
        for month in range(1, 8)
    )
    history = SimplesFacts(
        date(2026, 7, 1), date(2025, 1, 1), "SP", Activity.SERVICE_III,
        months, "company", "activity", "optant",
    )
    rates, federal_excess, local_excess = assessment_partition(
        history, Annex.ANNEX_III, export=False, outside_local=False,
    )
    assert federal_excess == 0
    assert local_excess == Fraction(2, 5)
    assert rates["iss"] == Fraction(5, 100)
    # The manual's two raw local supplements are 6.09968% and 5.86585%.
    expected = Fraction(186, 1000) + (
        Fraction(609968, 10000000) * Fraction(3, 5)
        + Fraction(586585, 10000000) * Fraction(2, 5)
    )
    assert sum(rates.values()) == expected
    assert rates["irpj"] == Fraction(651, 10000) + (
        expected - Fraction(236, 1000)
    ) * Fraction(602, 10000)
    result = assess_segregated(
        history, (RevenueLine("manual", 100_000_000, Activity.SERVICE_III,
                              Market.DOMESTIC, FederalTreatment.ORDINARY,
                              LocalTreatment.ORDINARY, "manual", "review"),),
        domestic_cents=100_000_000, export_cents=0,
    )
    # Exact expected cents using the engine\'s documented aggregate rounding.
    assert result["tax_cents"] == {
        "irpj": 6_570_570, "csll": 2_842_923, "cofins": 3_175_565,
        "pis": 687_477, "cpp": 6_329_612, "ipi": 0, "icms": 0,
        "iss": 5_000_000,
    }
    assert result["estimated_das_cents"] == 24_606_147
