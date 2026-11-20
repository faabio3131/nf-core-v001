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
    assert result["status"] == "classified"


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


def test_future_and_empty():
    with pytest.raises(FiscalValidationError):
        classify_revenue(date(2027, 1, 1), (), domestic_cents=0, export_cents=0)
    assert classify_revenue(
        PERIOD, (), domestic_cents=0, export_cents=0,
    )["status"] == "classified"
