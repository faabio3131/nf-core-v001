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


def test_rtc_projection_reuses_same_rates_and_is_never_issuance() -> None:
    from decimal import Decimal

    from kordena_fiscal.application.simples_rtc_bridge import project_rtc_rates

    result = project_rtc_rates(company(), (line(),), UNIFIED)
    assert result["issuance_authorized"] is False
    assert result["regular_calculator_required"] is False
    assert Decimal(result["domestic"]["anexoI"]["pCBSSN"]) == Decimal("0.6132")
    assert Decimal(result["domestic"]["anexoI"]["pIBSSN"]) == Decimal("0.0068")
    separate = project_rtc_rates(company(), (line(),), SimplesIbsCbsMode.REGULAR_SEPARATE)
    assert separate["regular_calculator_required"] is True
    assert "domestic" not in separate


def test_nfse_comparison_calls_pinned_calculator_with_projected_rates() -> None:
    import json
    from dataclasses import replace
    from decimal import Decimal
    from pathlib import Path

    from kordena_fiscal.application.simples_rtc_bridge import (
        execute_nfse_comparisons,
        plan_nfse_comparisons,
    )
    from kordena_fiscal.tax.rfb_simples_calculator import RfbSimplesCalculatorClient

    item = replace(
        line(), activity=Activity.SERVICE_III,
        transition_treatments=("ordinary", "ordinary", "non_incident",
                               "non_incident", "ordinary"),
    )
    raw = {
        "line_id": item.line_id, "document_reference": item.evidence_reference,
        "review_reference": "fixture-review", "occurred_at": "2027-01-10T10:00:00-03:00",
        "simples_base_cents": item.cents, "activity_code": "08",
        "c_class_trib": "000001", "nbs": "114051100",
        "iss_taxation": "1", "iss_withheld": False,
    }
    plan = plan_nfse_comparisons(company(), (item,), UNIFIED, [raw])
    assert len(plan) == 1
    calls = []
    fixture_dir = Path(__file__).parent / "fixtures" / "rfb"

    def transport(method, url, body, timeout):
        calls.append((method, url, body))
        filename = "sn_versao.json" if method == "GET" else "sn_nfse_calc.json"
        return (fixture_dir / filename).read_bytes(), {}

    client = RfbSimplesCalculatorClient(base_url="http://rtc-simples:8082/api",
                                        transport=transport)
    output = execute_nfse_comparisons(plan, client, None)
    sent = json.loads(calls[-1][2])
    assert sent["tpDoc"] == "91"
    assert Decimal(sent["aliquotasEfetivas"]["anexoIII"]["pCBSSN"]) == Decimal("0.9258")
    # Recorded response has a different base/rate, so must diverge.
    assert output["status"] == "review_required"
    assert output["operations"][0]["status"] == "divergent"
    assert plan[0].expected["vCBSSN"] == Decimal("9.30")
    assert plan[0].monthly_reference["vCBSSN"] == Decimal("9.26")
    assert output["official_pgdas_certification"] is False
    assert execute_nfse_comparisons(plan, None, None)["status"] == "review_required"
    with pytest.raises(FiscalValidationError, match="document"):
        plan_nfse_comparisons(
            company(), (item,), UNIFIED, [{**raw, "document_reference": "foreign"}],
        )


def test_reviewed_nfse_comparison_matches_and_rejects_wrong_database() -> None:
    import json
    from decimal import Decimal

    from kordena_fiscal.application.simples_rtc_bridge import (
        NfseComparisonPlan,
        execute_nfse_comparisons,
    )
    from kordena_fiscal.tax.rfb_simples_calculator import RfbSimplesCalculatorClient

    expected = {"vBC": Decimal("1000"), "vCBSSN": Decimal("9.30"), "vIBSSN": Decimal("0.10")}
    plan = NfseComparisonPlan("x", "simples", {"itens": [{"numero": 1}]}, expected)

    def client(database="V0073"):
        def transport(method, url, body, timeout):
            response = (
                {"versaoApp": "1.0.2", "versaoDb": database} if method == "GET" else
                {"objetos": [{"nObj": 1, "estadoItem": "CALCULADO",
                              "tribCalc": {key: str(val) for key, val in expected.items()}}]}
            )
            return json.dumps(response).encode(), {}

        return RfbSimplesCalculatorClient(base_url="http://rtc-simples:8082/api",
                                          transport=transport)

    assert execute_nfse_comparisons((plan,), client(), None)["status"] == "match"
    assert execute_nfse_comparisons((plan,), client("V9999"), None)["status"] == "review_required"
