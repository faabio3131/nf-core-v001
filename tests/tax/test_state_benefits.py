"""T09 deterministic guards for every UF; no synthetic law is a real incentive."""
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    BENEFIT_KINDS, FACTS_SCHEMA, LEGAL_PATHS, RULE_SCHEMA, ReviewedStateIssuer,
    _COMMON_EVIDENCE, _ROUTE_EVIDENCE, _UF_CODES, assess_state_rule,
    decode_facts, decode_rule, state_index,
)

MONTH = date(2026, 11, 1)
SCOPE = ("fm-nfcore", "tenant-a", "unit-a", "homologation")


def policy(uf="SP", *, path="state_statute"):
    return {
        "schema_version": RULE_SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-review-T09",
        "uf": uf, "benefit_kind": "base_reduction", "legal_path": path,
        "state_normative_reference": "Decreto Estadual Sintetico 123/2026",
        "state_official_source_url": "https://www.gov.br/testes/sintetico/ato-estadual",
        "valid_from": "2026-01-01", "valid_until": "2027-01-01",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "allowlist", "allowed_cnaes": ["6201501"],
        "ncm_scope": "allowlist", "allowed_ncms": ["84713012"],
        "allowed_cfops": ["5102"], "allowed_operations": ["domestic_sale"],
        "required_evidence": [],
        "confaz_normative_reference": (
            "Convênio ICMS 190/2017" if path != "state_statute" else None
        ),
        "legal_citations": [],
    }


def facts(uf="SP", *, path="state_statute"):
    return {
        "schema_version": FACTS_SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-facts-T09",
        "uf": uf, "activity_cnae": "6201501",
        "operation_ncm": "84713012", "operation_cfop": "5102",
        "operation": "domestic_sale", "evidence": {
            key: "reviewed-synthetic-" + key
            for key in (*_COMMON_EVIDENCE, *_ROUTE_EVIDENCE[path])
        },
    }


def issuer(uf="SP", *, registration=True, cnae="6201501"):
    return ReviewedStateIssuer(
        "12345678000195", uf, cnae, FederalIncomeTaxRegime.LUCRO_REAL,
        registration, SCOPE,
    )


def evaluate(uf="SP", *, path="state_statute", issuer_override=None,
             policy_changes=None, fact_changes=None):
    p = policy(uf, path=path)
    f = facts(uf, path=path)
    if policy_changes:
        p.update(policy_changes)
    if fact_changes:
        f.update(fact_changes)
    return assess_state_rule(
        decode_rule(p), decode_facts(f),
        issuer_override or issuer(uf), MONTH,
    )


def test_geographic_catalog_has_27_canonical_units_with_distinct_ibge_codes():
    data = state_index()
    assert data["complete_geographic_index"] is True
    assert data["complete_state_benefit_coverage"] is False
    assert data["homologated_state_count"] == 0
    assert len(data["uf"]) == 27
    assert set(item["uf"] for item in data["uf"]) == set(_UF_CODES)
    assert len({item["ibge_uf_code"] for item in data["uf"]}) == 27
    assert all(item["benefits_homologated"] is False for item in data["uf"])


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_every_uf_supports_strictly_reviewed_icms_candidate(uf):
    result = evaluate(uf)
    assert result["status"] == "potential"
    assert result["advisory_only"] is True
    assert result["eligibility_certified"] is False
    assert result["approved_cents"] is None
    assert result["estimated_cents"] is None
    assert result["issuance_authorized"] is False


@pytest.mark.parametrize("kind", sorted(BENEFIT_KINDS))
def test_icms_categories_never_result_in_credit_or_issuance(kind):
    result = evaluate(policy_changes={"benefit_kind": kind})
    assert result["status"] == "potential"
    assert result["realized_cents"] is None
    assert result["tax_calculation_authorized"] is False


@pytest.mark.parametrize("path", sorted(LEGAL_PATHS))
def test_each_legal_route_requires_its_unforgeable_reviewed_evidence(path):
    result = evaluate(path=path)
    assert result["status"] == "potential"
    missing = facts(path=path)["evidence"]
    missing.pop(_ROUTE_EVIDENCE[path][0])
    result = evaluate(path=path, fact_changes={"evidence": missing})
    assert result["status"] == "insufficient_basis"
    assert any("missing:" in x for x in result["reason_codes"])


def test_jurisdiction_registration_and_authority_fail_closed():
    assert evaluate(issuer_override=issuer("RJ"))["reason_codes"] == [
        "state_jurisdiction_mismatch"
    ]
    assert evaluate(issuer_override=issuer(registration=False))["status"] == (
        "insufficient_basis"
    )
    assert evaluate(issuer_override=issuer(cnae="1111111"))["status"] == (
        "insufficient_basis"
    )


@pytest.mark.parametrize("fact_changes,expect", [
    ({"operation_cfop": "6102"}, "cfop_excluded"),
    ({"operation_ncm": "11111111"}, "ncm_excluded"),
    ({"operation_ncm": None}, "ncm_missing"),
    ({"activity_cnae": "1111111"}, "canonical_cnae_mismatch"),
    ({"operation": "import"}, "operation_excluded"),
])
def test_cnae_ncm_cfop_operation_are_never_assumed(fact_changes, expect):
    assert evaluate(fact_changes=fact_changes)["reason_codes"] == [expect]


def test_monthly_validity_and_regime_restrict_state_candidate():
    assert assess_state_rule(
        decode_rule(policy() | {"valid_until": "2026-11-15"}),
        decode_facts(facts()), issuer(), MONTH,
    )["status"] == "not_applicable"
    assert evaluate(policy_changes={"allowed_regimes": ["simples_nacional"]})[
        "reason_codes"
    ] == ["income_tax_regime_excluded"]


@pytest.mark.parametrize("change", [
    {"review_status": "draft"},
    {"uf": "XX"},
    {"benefit_kind": "unknown"},
    {"legal_path": "unchecked"},
    {"state_normative_reference": "x"},
    {"allowed_regimes": ["fictitious"]},
    {"allowed_regimes": []},
    {"allowed_cnaes": []},
    {"allowed_ncms": ["0"]},
    {"allowed_cfops": []},
    {"allowed_operations": []},
    {"required_evidence": [0]},
    {"valid_from": "not-a-date"},
    {"valid_until": "2025-01-01"},
])
def test_invalid_state_policy_never_becomes_candidate(change):
    with pytest.raises(FiscalValidationError):
        decode_rule(policy() | change)


@pytest.mark.parametrize("change", [
    {"review_status": "pending"},
    {"uf": "BR"},
    {"activity_cnae": "fake"},
    {"operation_cfop": "invalid"},
    {"operation_ncm": "bad"},
    {"operation": "fake"},
    {"evidence": {}},
])
def test_invalid_state_facts_fail_closed(change):
    with pytest.raises(FiscalValidationError):
        decode_facts(facts() | change)


def test_confaz_route_without_normative_reference_is_rejected():
    with pytest.raises(FiscalValidationError, match="CONFAZ"):
        decode_rule(policy(path="lc160_reinstituted") | {
            "confaz_normative_reference": None,
        })
