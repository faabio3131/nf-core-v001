import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.revenue_item_catalog import ReviewedItemCatalog

MONTH = date(2026, 11, 1)
SOURCE = "https://www.gov.br/synthetic-fixture"
ITEM = dict(ncm="33041000", cest="2000900", cfop="5405", activity="commerce",
            market="domestic", operation_context="reviewed-retail-product")
RULE = dict(**ITEM, uf="SP", source_url=SOURCE, valid_from="2026-01-01",
            valid_until="2027-01-01", federal="monophase_downstream",
            local="icms_substituted", rule_reference="fixture-policy-1")


@pytest.mark.parametrize("changes", [
    {}, {"local": "icms_exempt"}, {"local": "icms_immune"},
    {"cfop": "7102", "market": "export", "local": "ordinary", "federal": "ordinary"},
])
def test_resolves_exact_reviewed_operation(changes):
    rule = RULE | changes
    item = {k: rule[k] for k in ITEM}
    actual = ReviewedItemCatalog([rule], MONTH, {SOURCE}).resolve(item, "SP")
    assert actual == (rule["federal"], rule["local"], rule["rule_reference"], None)


@pytest.mark.parametrize("extra", [
    [RULE], [RULE | {"valid_from": "2026-11-15"}],
])
def test_conflicts_block_the_month(extra):
    catalog = ReviewedItemCatalog([RULE, *extra], MONTH, {SOURCE})
    assert catalog.resolve(ITEM, "SP")[0] == "unknown"


@pytest.mark.parametrize("changes", [
    {"valid_from": "2026-11-15"}, {"valid_until": "2026-11-01"},
    {"valid_from": "2026-12-01"}, {"uf": "RJ"}, {"cest": None},
    {"operation_context": "manufacturer"}, {"ncm": "33041001"}, {"cfop": "5102"},
])
def test_no_guess_without_whole_month_match(changes):
    catalog = ReviewedItemCatalog([RULE | changes], MONTH, {SOURCE})
    assert catalog.resolve(ITEM, "SP")[1] == "unknown"


@pytest.mark.parametrize("changes", [
    {"ncm": 33041000}, {"cfop": "1234"}, {"cest": "bad"}, {"uf": "XY"},
    {"market": "export"}, {"operation_context": ""}, {"source_url": "unreviewed"},
    {"valid_until": "2025-01-01"}, {"rule_reference": ""},
])
def test_rejects_malformed_policy(changes):
    with pytest.raises(FiscalValidationError):
        ReviewedItemCatalog([RULE | changes], MONTH, {SOURCE})


def test_bound_and_override():
    with pytest.raises(FiscalValidationError):
        ReviewedItemCatalog([], MONTH, {SOURCE})
    with pytest.raises(FiscalValidationError):
        ReviewedItemCatalog([RULE], MONTH, {SOURCE}).resolve(ITEM | {"local": "ordinary"}, "SP")


def test_transition_requires_reviewed_tax_vector():
    rule = RULE | {"valid_until": "2028-01-01"}
    month = date(2027, 1, 1)
    with pytest.raises(FiscalValidationError):
        ReviewedItemCatalog([rule], month, {SOURCE})
    taxes = dict.fromkeys(("cbs", "ibs", "ipi", "icms", "iss"), "ordinary")
    catalog = ReviewedItemCatalog([rule | {"transition_treatments": taxes}], month, {SOURCE})
    assert catalog.resolve(ITEM, "SP")[3] == ("ordinary",) * 5


def test_documented_sp_candidate_ends_before_april():
    path = Path(__file__).resolve().parents[2] / "docs/NFCORE_T06_SP_REVENDA_2026T1.json"
    data = json.loads(path.read_text())
    rule, = data["item_rules"]
    sources = {source["url"] for source in data["sources"]}
    item = {k: rule[k] for k in ITEM}
    for month in (1, 2, 3, 4):
        catalog = ReviewedItemCatalog([rule], date(2026, month, 1), sources)
        result = catalog.resolve(item, "SP")
        assert result[1] == ("icms_substituted" if month < 4 else "unknown")
        assert catalog.resolve(item | {"cfop": "5102"}, "SP")[0] == "unknown"


def test_fiscal_release_routes_each_reviewed_item_across_april():
    import hashlib
    from importlib.resources import files

    from kordena_fiscal.tax.revenue_item_catalog import materialize_item_release

    assert materialize_item_release({}, MONTH) == {}
    raw = files("kordena_fiscal.tax").joinpath("official/sp_2026s1_v1.json").read_bytes()
    pack = json.loads(raw)
    citations = [{"source_url": s["url"], "source_sha256": s["sha256"]}
                 for s in pack["sources"].values()]
    policy = {"review_status": "reviewed", "item_catalog_sha256": hashlib.sha256(raw).hexdigest(),
              "legal_citations": citations}
    sources = {c["source_url"] for c in citations}
    assert len(pack["item_rules"]) == 15
    for month in (1, 3, 4, 6):
        day = date(2026, month, 1)
        active = materialize_item_release(policy, day)["item_rules"]
        catalog = ReviewedItemCatalog(active, day, sources)
        for rule in pack["item_rules"]:
            item = {k: rule[k] for k in ITEM}
            result = catalog.resolve(item, "SP")
            if rule["valid_from"] <= day.isoformat() < rule["valid_until"]:
                assert result[:3] == (rule["federal"], rule["local"], rule["rule_reference"])
            else:
                assert result[0] == "unknown"
            assert catalog.resolve(item, "RJ")[0] == "unknown"
            undocumented = item | {"operation_context": "sem_comprovacao"}
            assert catalog.resolve(undocumented, "SP")[0] == "unknown"
    with pytest.raises(FiscalValidationError, match="competence"):
        materialize_item_release(policy, date(2026, 7, 1))
    for overrides in ({"item_catalog_sha256": "f" * 64}, {"item_rules": []},
                      {"review_status": "draft"}, {"legal_citations": []},
                      {"legal_citations": None}):
        with pytest.raises(FiscalValidationError):
            materialize_item_release(policy | overrides, date(2026, 1, 1))
