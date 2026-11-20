from __future__ import annotations

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.runtime.sale_facts import parse_sale_rule
from kordena_fiscal.tax.models import SIMPLES_ACTIVITY_CODES


def _rule(**outcome_extra) -> dict:
    return {
        "rule_id": "r1", "version": 1, "priority": 1, "source_normative": "LC 123/2006",
        "effective_from": "2026-01-01T00:00:00+00:00",
        "selector": {"state_code": "MG", "tax_regime": 1, "recipient_profile": "consumer_final",
                     "ncm_prefix": "8471"},
        "outcome": {"cfop": "5102", "icms_code": "102", "pis_cst": "49", "cofins_cst": "49",
                    "nfe_rates": {"icms_rate": "0", "pis_rate": "0", "cofins_rate": "0",
                                  "pis_base": "net", "cofins_base": "net"},
                    **outcome_extra},
    }


def test_official_codes_match_the_receita_table() -> None:
    assert SIMPLES_ACTIVITY_CODES == {f"{n:02d}" for n in range(1, 15)} | {"90"}


def test_policy_rule_carries_cativsn() -> None:
    assert parse_sale_rule(_rule(simples_activity_code="09")).outcome.simples_activity_code == "09"
    assert parse_sale_rule(_rule()).outcome.simples_activity_code is None


@pytest.mark.parametrize("code", ["15", "00", "1", "AA"])
def test_unknown_cativsn_is_refused(code: str) -> None:
    with pytest.raises(FiscalValidationError):
        parse_sale_rule(_rule(simples_activity_code=code))
