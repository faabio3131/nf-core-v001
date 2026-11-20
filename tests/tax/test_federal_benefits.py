"""T08 domain gates: no benefit approval from a classification match."""
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.federal_benefits import (
    FACTS_SCHEMA,
    PROGRAMS,
    RULE_SCHEMA,
    ReviewedFederalIssuer,
    assess_federal_program,
    decode_facts,
    decode_policy,
)
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime


def policy(code="LEI_DO_BEM"):
    item = PROGRAMS[code]
    return {
        "schema_version": RULE_SCHEMA,
        "program_code": code, "review_status": "reviewed",
        "review_reference": "review-2026",
        "operation": item.operation,
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "reviewed_any", "allowed_cnaes": [],
        "ncm_scope": "reviewed_any", "allowed_ncms": [],
        "required_evidence": [],
        "valid_from": "2026-01-01", "valid_until": "2027-01-01",
        "legal_citations": [],
    }


def facts(code="LEI_DO_BEM"):
    item = PROGRAMS[code]
    return {
        "schema_version": FACTS_SCHEMA, "review_status": "reviewed",
        "review_reference": "review-2026", "activity_cnae": "6201501",
        "operation_ncm": None, "operation": item.operation,
        "evidence": {key: "proof-" + key for key in item.minimum_evidence},
    }


def issuer(regime=FederalIncomeTaxRegime.LUCRO_REAL):
    return ReviewedFederalIssuer(
        "12345678000195", "6201501", regime,
        ("fm-nfcore", "tenant-a", "unit-a", "homologation"),
    )


def evaluate(code="LEI_DO_BEM", *, period=date(2026, 11, 1), regime=None,
             facts_override=None, policy_override=None):
    rule = policy(code)
    row = facts(code)
    if facts_override:
        row.update(facts_override)
    if policy_override:
        rule.update(policy_override)
    program, allowed, cs, cnaes, ns, ncms, required = decode_policy(rule)
    cnae, ncm, operation, evidence = decode_facts(row)
    return assess_federal_program(
        program=program, competence=period,
        issuer=issuer(regime or FederalIncomeTaxRegime.LUCRO_REAL),
        activity_cnae=cnae, operation_ncm=ncm, operation=operation,
        allowed_regimes=allowed, cnae_scope=cs, allowed_cnaes=cnaes,
        ncm_scope=ns, allowed_ncms=ncms, required_evidence=required,
        evidence=evidence,
    )


def test_lei_do_bem_candidate_remains_unapproved_and_without_tax_amount():
    result = evaluate()
    assert result["status"] == "potential"
    assert result["advisory_only"] is True
    assert result["issuance_authorized"] is False
    assert result["eligibility_certified"] is False
    assert result["approved_cents"] is None
    assert result["estimated_cents"] is None
    assert result["realized_cents"] is None


def test_lei_do_bem_requires_canonical_lucro_real():
    assert evaluate(regime=FederalIncomeTaxRegime.SIMPLES_NACIONAL)[
        "status"
    ] == "not_applicable"
    assert evaluate(regime=FederalIncomeTaxRegime.LUCRO_PRESUMIDO)[
        "status"
    ] == "not_applicable"
    with pytest.raises(FiscalValidationError, match="Lucro Real"):
        decode_policy(policy() | {"allowed_regimes": ["simples_nacional"]})


def test_missing_supporting_evidence_never_becomes_eligibility():
    row = facts()
    del row["evidence"]["reviewed_rd_project"]
    result = evaluate(facts_override={"evidence": row["evidence"]})
    assert result["status"] == "insufficient_basis"
    assert "missing:reviewed_rd_project" in result["reason_codes"]


def test_cnae_and_ncm_coverage_explicit_and_strict():
    rule = {
        "cnae_scope": "allowlist", "allowed_cnaes": ["1111111"],
        "ncm_scope": "allowlist", "allowed_ncms": ["84713012"],
    }
    assert evaluate(policy_override=rule)["reason_codes"] == ["cnae_not_covered"]
    rule["allowed_cnaes"] = ["6201501"]
    assert evaluate(policy_override=rule)["reason_codes"] == ["ncm_not_reviewed"]
    assert evaluate(policy_override=rule, facts_override={
        "operation_ncm": "84713013",
    })["reason_codes"] == ["ncm_not_covered"]
    assert evaluate(policy_override=rule, facts_override={
        "operation_ncm": "84713012",
    })["status"] == "potential"
    with pytest.raises(FiscalValidationError):
        decode_policy(policy() | {"cnae_scope": "allowlist", "allowed_cnaes": []})


def test_cannot_weaken_program_evidence_by_omitting_required_evidence():
    rule = policy()
    rule["required_evidence"] = []
    assert decode_policy(rule)[0].minimum_evidence
    assert evaluate(policy_override=rule, facts_override={
        "evidence": {"reviewed_rd_project": "proof-reviewed"},
    })["status"] == "insufficient_basis"


def test_ibs_cbs_programs_are_not_available_in_2026():
    for code in ("IBS_CBS_RURAL", "IBS_CBS_RECICLAGEM"):
        assert evaluate(code, period=date(2026, 11, 1))["status"] == "not_applicable"
        assert evaluate(code, period=date(2027, 1, 1))["status"] == "potential"
        assert PROGRAMS[code].official_url.startswith("https://www2.camara.leg.br/")


def test_policy_and_facts_refuse_unreviewed_taxonomies():
    for change in (
        {"review_status": "draft"},
        {"cnae_scope": None},
        {"ncm_scope": None},
        {"allowed_regimes": ["not-a-regime"]},
        {"allowed_regimes": []},
        {"allowed_cnaes": ["62.01-5/01"]},
        {"required_evidence": [1]},
        {"operation": "fictitious"},
        {"program_code": "UNKNOWN"},
    ):
        with pytest.raises(FiscalValidationError):
            decode_policy(policy() | change)
    for change in (
        {"review_status": "draft"},
        {"activity_cnae": "ABC"},
        {"operation_ncm": "unknown"},
        {"operation": "fictitious"},
        {"evidence": {"x": ""}},
    ):
        with pytest.raises(FiscalValidationError):
            decode_facts(facts() | change)


def test_operation_requires_matching_program_and_extra_evidence():
    assert evaluate(facts_override={"operation": "rural_purchase"})[
        "status"
    ] == "not_applicable"
    assert evaluate(policy_override={
        "required_evidence": ["special-approval"],
    })["status"] == "insufficient_basis"
    assert evaluate(policy_override={
        "required_evidence": ["special-approval"],
    }, facts_override={
        "evidence": {**facts()["evidence"], "special-approval": "reviewed-proof"},
    })["status"] == "potential"


@pytest.mark.parametrize(
    "code", ["LEI_DO_BEM", "REIDI", "RECAP", "REINTEGRA",
             "SISPROM", "IPI_EXPORTADOR", "IBS_CBS_RURAL", "IBS_CBS_RECICLAGEM"],
)
def test_all_registered_federal_programs_require_advisory_human_review(code):
    result = evaluate(code, period=date(2027, 1, 1))
    assert result["status"] == "potential"
    assert result["requires_human_approval"] is True
    assert result["eligibility_certified"] is False
    assert result["estimated_cents"] is None
    assert result["issuance_authorized"] is False
    assert PROGRAMS[code].official_url.startswith("https://www.")
