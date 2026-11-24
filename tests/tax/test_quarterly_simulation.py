import hashlib
import json
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.quarterly_simulation import Quarter, simulate

FIXTURES = Path(__file__).parent / "fixtures"


def inputs(start=1):
    # First calculated item from the archived official replay. Its second item
    # is a deliberately rejected line and is exercised separately below.
    official = json.loads((FIXTURES / "rfb/rr_calc.json").read_text())
    raw = json.dumps({"objetos": official["objetos"][:1]})
    months = [{
        "competence": date(2026, month, 1).isoformat(), "cumulative_base": 100000,
        "noncumulative_base": 100000, "pis_credit": 2000, "cofins_credit": 6000,
        "ibs_credits": 20, "cbs_credits": 150, "rtc_evidence": "reconciled-month",
        "rtc_component": "app=1.7.2;db=V0073",
        "documents": [{"document_reference": f"doc-{month}", "item_numbers": [1],
                       "response": raw,
                       "response_sha256": hashlib.sha256(raw.encode()).hexdigest()}],
    } for month in range(start, start + 3)]
    return {"schema_version": "nfcore.quarterly-regime-facts/v1", "review_status": "reviewed",
            "review_reference": "accounting-reference", "period_start": months[0]["competence"],
            "scope": "consolidated_ordinary_nonfinancial_full_quarter_2026",
            "hypothesis": "ordinary_trade_and_general_services",
            "trade_revenue": 144000000, "services_revenue": 36000000,
            "irpj_ordinary_limit": 125000000, "csll_ordinary_limit": 125000000 if start > 1 else 0,
            "irpj_other_taxable": 0, "csll_other_taxable": 0, "real_accounting_result": 7000000,
            "irpj_additions": 100000, "irpj_exclusions": 50000, "csll_additions": 0,
            "csll_exclusions": 100000, "irpj_loss_applied": 0, "csll_loss_applied": 0,
            "months": months}


def run(data):
    return simulate(date.fromisoformat(data["period_start"]), Quarter.model_validate(data))


def test_accounting_reference_and_recorded_official_vat():
    result = run(inputs())
    sheet = ElementTree.parse(FIXTURES / "t11_quarter_reference.xml")
    for row in sheet.findall(".//{*}Row"):
        group, component, expected = (cell.find("{*}Data").text for cell in row)
        actual = result.get(group, result["months"][0].get(group))
        assert actual[component] == int(expected)
    assert result["payment_authorized"] is False
    assert run(inputs(4))["lucro_presumido"]["csll_base"] == 29680000


@pytest.mark.parametrize("failure", ["duplicate", "incomplete", "digest", "version", "missing",
                                     "loss", "period", "boolean", "rejected", "draft"])
def test_reject_unverifiable_period_or_evidence(failure):
    data = inputs()
    item = data["months"][0]["documents"][0]
    if failure == "duplicate":
        data["months"][1]["documents"][0]["document_reference"] = item["document_reference"]
    elif failure == "incomplete":
        item["item_numbers"] = [1, 2]
    elif failure == "digest":
        item["response_sha256"] = "b" * 64
    elif failure == "version":
        data["months"][0]["rtc_component"] = "unknown"
    elif failure == "missing":
        data["months"].pop()
    elif failure == "loss":
        data["irpj_loss_applied"] = 3000000
    elif failure == "period":
        data["months"][1]["competence"] = "2026-04-01"
    elif failure == "boolean":
        data["irpj_other_taxable"] = False
    elif failure == "draft":
        data["review_status"] = "draft"
    else:
        raw = (FIXTURES / "rfb/rr_calc.json").read_bytes()
        item.update(response=raw.decode(), response_sha256=hashlib.sha256(raw).hexdigest(),
                    item_numbers=[1, 2])
    with pytest.raises((FiscalValidationError, ValidationError)):
        run(data)
