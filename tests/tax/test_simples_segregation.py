from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import Activity
from kordena_fiscal.tax.simples_segregation import (
    FederalTreatment as F,
)
from kordena_fiscal.tax.simples_segregation import (
    LocalTreatment as L,
)
from kordena_fiscal.tax.simples_segregation import (
    Market,
    RevenueLine,
    classify_revenue,
)

PERIOD = date(2026, 11, 1)


def line(key="a", cents=100, activity=Activity.COMMERCE,
         market=Market.DOMESTIC, federal=F.ORDINARY, local=L.ORDINARY):
    return RevenueLine(key, cents, activity, market, federal, local, "doc", "review")


@pytest.mark.parametrize("federal", [F.ORDINARY, F.MONOPHASE])
@pytest.mark.parametrize("local", [
    L.ORDINARY, L.ICMS_SUBSTITUTED, L.ICMS_SUBSTITUTE, L.ICMS_FINAL_ADVANCE,
])
@pytest.mark.parametrize("activity", [Activity.COMMERCE, Activity.INDUSTRY])
def test_goods_combined_treatments(activity, federal, local):
    result = classify_revenue(PERIOD, (line(activity=activity, federal=federal, local=local),),
                              domestic_cents=100, export_cents=0)
    assert result["status"] == "classified"
    assert result["buckets"] == [{
        "activity": activity.value, "market": "domestic",
        "federal": federal.value, "local": local.value, "cents": 100,
    }]


@pytest.mark.parametrize("activity", [
    Activity.SERVICE_III, Activity.SERVICE_IV, Activity.SERVICE_FACTOR_R,
])
@pytest.mark.parametrize("local", [L.ORDINARY, L.ISS_WITHHELD])
def test_service_treatment(activity, local):
    result = classify_revenue(PERIOD, (line(activity=activity, local=local),),
                              domestic_cents=100, export_cents=0)
    assert result["status"] == "classified"


@pytest.mark.parametrize("activity", list(Activity))
def test_export_distinct(activity):
    result = classify_revenue(PERIOD, (line(activity=activity, market=Market.EXPORT),),
                              domestic_cents=0, export_cents=100)
    if activity is Activity.INDUSTRY_WITHOUT_IPI:
        assert result["status"] == "blocked"
        assert result["buckets"] == []
        assert result["blocked"] == [{
            "line_id": "a", "reason": "transition_treatment_unavailable_in_2026",
        }]
    else:
        assert result["status"] == "classified"
        assert result["buckets"] == [{
            "activity": activity.value, "market": "export",
            "federal": "ordinary", "local": "ordinary", "cents": 100,
        }]


@pytest.mark.parametrize("market", list(Market))
def test_industry_without_ipi_requires_2027_and_reviewed_treatments(market):
    from dataclasses import replace

    item = line(activity=Activity.INDUSTRY_WITHOUT_IPI, market=market)
    totals = {
        "domestic_cents": 100 if market is Market.DOMESTIC else 0,
        "export_cents": 100 if market is Market.EXPORT else 0,
    }
    transition = date(2027, 1, 1)
    assert classify_revenue(PERIOD, (item,), **totals)["status"] == "blocked"
    incomplete = classify_revenue(transition, (item,), **totals)
    assert incomplete["status"] == "blocked"
    assert incomplete["buckets"] == []
    assert incomplete["blocked"] == [{
        "line_id": "a", "reason": "explicit_2027_per_tax_treatment_required",
    }]
    treatment = "export" if market is Market.EXPORT else "ordinary"
    reviewed = replace(item, transition_treatments=(
        treatment, treatment, "non_incident", treatment, "non_incident",
    ))
    result = classify_revenue(transition, (reviewed,), **totals)
    assert result["status"] == "classified"
    assert result["buckets"] == [{
        "activity": "industry_without_ipi", "market": market.value,
        "federal": "ordinary", "local": "ordinary", "cents": 100,
        "transition_treatments": {
            "cbs": treatment, "ibs": treatment, "ipi": "non_incident",
            "icms": treatment, "iss": "non_incident",
        },
    }]
    assert classify_revenue(PERIOD, (reviewed,), **totals)["status"] == "blocked"


@pytest.mark.parametrize("row", [
    line(federal=F.UNKNOWN), line(local=L.UNKNOWN),
    line(activity=Activity.SERVICE_III, federal=F.MONOPHASE),
    line(activity=Activity.SERVICE_IV, local=L.ICMS_SUBSTITUTED),
    line(local=L.ISS_WITHHELD),
    line(market=Market.EXPORT, local=L.ICMS_SUBSTITUTED),
])
def test_unresolved_or_incompatible_blocks_all_buckets(row):
    result = classify_revenue(
        PERIOD, (row, line("other", cents=50)),
        domestic_cents=50 + (100 if row.market is Market.DOMESTIC else 0),
        export_cents=100 if row.market is Market.EXPORT else 0,
    )
    assert result["status"] == "blocked"
    assert result["buckets"] == []
    assert len(result["blocked"]) == 1


def test_reconciliation_and_replay():
    rows = (line("a"), line("b", cents=200), line("c", local=L.ICMS_SUBSTITUTE))
    result = classify_revenue(PERIOD, rows, domestic_cents=400, export_cents=0)
    assert result == classify_revenue(
        PERIOD, rows[::-1], domestic_cents=400, export_cents=0,
    )
    assert sum(b["cents"] for b in result["buckets"]) == 400
    with pytest.raises(FiscalValidationError, match="reconcile"):
        classify_revenue(PERIOD, rows, domestic_cents=399, export_cents=0)
    with pytest.raises(FiscalValidationError, match="duplicate"):
        classify_revenue(PERIOD, (rows[0], rows[0]), domestic_cents=200, export_cents=0)


@pytest.mark.parametrize("amount", [-1, True, 1.2, 10**16])
def test_invalid_money(amount):
    with pytest.raises(FiscalValidationError):
        line(cents=amount)


@pytest.mark.parametrize("competence", [date(2025, 12, 1), date(2028, 1, 1), date(2027, 1, 2)])
def test_unsupported_competence(competence):
    with pytest.raises(FiscalValidationError, match="2026/2027 competence"):
        classify_revenue(competence, (), domestic_cents=0, export_cents=0)


@pytest.mark.parametrize("competence,version", [
    (PERIOD, "simples-segregation-2026/v1"),
    (date(2027, 1, 1), "simples-segregation-2027/v1"),
    (date(2027, 12, 1), "simples-segregation-2027/v1"),
])
def test_empty_reconciled_competence(competence, version):
    result = classify_revenue(competence, (), domestic_cents=0, export_cents=0)
    assert result["status"] == "classified"
    assert result["version"] == version
    assert result["buckets"] == result["blocked"] == result["evidence"] == []
    with pytest.raises(FiscalValidationError, match="reconcile"):
        classify_revenue(competence, (), domestic_cents=1, export_cents=0)
