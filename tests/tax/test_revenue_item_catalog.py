from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.revenue_item_catalog import ReviewedItemCatalog

MONTH = date(2026, 11, 1)
SOURCE = "https://www.gov.br/synthetic-fixture"
ITEM = dict(ncm="33041000", cest="2000100", cfop="5405", activity="commerce",
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
