"""Reviewed 2027 segregation fixtures; not real PGDAS evidence."""
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode
from kordena_fiscal.tax.simples_nacional import Activity, MonthFacts, SimplesFacts
from kordena_fiscal.tax.simples_segregation import (
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    assess_segregated,
    classify_revenue,
)

PERIOD = date(2027, 1, 1)
UNIFIED = SimplesIbsCbsMode.SIMPLES_UNIFIED


def company(domestic=100_000, exported=0):
    return SimplesFacts(
        PERIOD, PERIOD, "SP", Activity.COMMERCE,
        (MonthFacts(PERIOD, domestic, exported, 0, "fixture"),),
        "company", "activity", "option",
    )


def line(market=Market.DOMESTIC, treatments=("ordinary", "ordinary", "non_incident",
                                             "ordinary", "non_incident")):
    return RevenueLine(
        "fixture", 100_000, Activity.COMMERCE, market, FederalTreatment.ORDINARY,
        LocalTreatment.ORDINARY, "document", "review", treatments,
    )


def test_unified_transition_ordinary_and_separate_option():
    unified = assess_segregated(
        company(), (line(),), domestic_cents=100_000, export_cents=0, mode=UNIFIED,
    )
    regular = assess_segregated(
        company(), (line(),), domestic_cents=100_000, export_cents=0,
        mode=SimplesIbsCbsMode.REGULAR_SEPARATE,
    )
    assert unified["status"] == regular["status"] == "estimated"
    assert unified["tax_cents"] == {
        "irpj": 220, "csll": 140, "cbs": 613, "cpp": 1660,
        "ipi": 0, "icms": 1360, "iss": 0, "ibs": 7,
    }
    assert regular["estimated_das_cents"] == 3380
    assert unified["estimated_das_cents"] == 4000
    assert unified["digest"] != regular["digest"]


def test_cbs_substitution_does_not_remove_ibs():
    item = line(treatments=("substituted", "ordinary", "non_incident",
                            "ordinary", "non_incident"))
    result = assess_segregated(
        company(), (item,), domestic_cents=100_000, export_cents=0, mode=UNIFIED,
    )
    assert result["tax_cents"]["cbs"] == 0
    assert result["tax_cents"]["ibs"] == 7


def test_export_keeps_unexcluded_tax_and_distinguishes_market():
    item = line(Market.EXPORT, ("export", "ordinary", "non_incident",
                               "export", "non_incident"))
    result = assess_segregated(
        company(0, 100_000), (item,), domestic_cents=0, export_cents=100_000, mode=UNIFIED,
    )
    assert result["tax_cents"]["cbs"] == result["tax_cents"]["icms"] == 0
    assert result["tax_cents"]["ibs"] == 7


@pytest.mark.parametrize("treatments", [None, ("unknown",) * 5, ("ordinary",) * 2])
def test_incomplete_transition_treatments_block(treatments):
    result = classify_revenue(
        PERIOD, (line(treatments=treatments),), domestic_cents=100_000, export_cents=0,
    )
    assert result["status"] == "blocked"


def test_transition_rejects_2026_cash_and_missing_mode():
    with pytest.raises(FiscalValidationError, match="cash recognition"):
        assess_segregated(
            company(), (line(),), domestic_cents=100_000, export_cents=0,
            mode=UNIFIED, cash=True,
        )
    with pytest.raises(FiscalValidationError, match="resolved IBS/CBS"):
        assess_segregated(company(), (line(),), domestic_cents=100_000, export_cents=0)
