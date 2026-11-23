"""T09 deterministic guards for every UF; no synthetic law is a real incentive."""
from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    _COMMON_EVIDENCE,
    _ROUTE_EVIDENCE,
    _UF_CODES,
    BENEFIT_KINDS,
    FACTS_SCHEMA,
    LEGAL_PATHS,
    RULE_SCHEMA,
    ReviewedStateIssuer,
    assess_state_rule,
    decode_facts,
    decode_rule,
    state_exclusive_after_legal_end,
    state_index,
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
        "legal_valid_until_inclusive": "2026-12-31",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "allowlist", "allowed_cnaes": ["6201501"],
        "ncm_scope": "allowlist", "allowed_ncms": ["84713012"],
        "allowed_cfops": ["5102"], "allowed_operations": ["domestic_sale"],
        "required_evidence": [],
        "individual_concession_required": True,
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
        "individual_concession": {
            "status": "active", "competence": MONTH.isoformat(),
            "review_reference": "synthetic-review-T09",
            "document_reference": "synthetic-individual-grant",
            "issuer_cnpj": "12345678000195", "uf": uf,
            "valid_from": "2026-01-01", "valid_until": "2027-01-01",
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
        decode_rule(policy() | {
            "valid_until": "2026-11-16",
            "legal_valid_until_inclusive": "2026-11-15",
        }),
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


@pytest.mark.parametrize("operation,wrong_cfop", [
    ("domestic_sale", "6102"),
    ("interstate_sale", "5102"),
    ("domestic_purchase", "2102"),
    ("interstate_purchase", "1102"),
    ("import", "1102"),
    ("asset_acquisition", "5551"),
])
def test_cfop_direction_conflict_never_gives_potential(operation, wrong_cfop):
    result = evaluate(
        policy_changes={
            "allowed_operations": [operation],
            "allowed_cfops": [wrong_cfop],
        },
        fact_changes={"operation": operation, "operation_cfop": wrong_cfop},
    )
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == ["cfop_operation_mismatch"]
    assert result["eligibility_certified"] is False
    assert result["approved_cents"] is None


@pytest.mark.parametrize("operation,correct_cfop", [
    ("domestic_sale", "5102"),
    ("interstate_sale", "6102"),
    ("domestic_purchase", "1102"),
    ("interstate_purchase", "2102"),
    ("import", "3101"),
    ("asset_acquisition", "1551"),
])
def test_matching_cfop_prefix_only_allows_advisory_potential(
    operation, correct_cfop,
):
    result = evaluate(
        policy_changes={
            "allowed_operations": [operation],
            "allowed_cfops": [correct_cfop],
        },
        fact_changes={"operation": operation, "operation_cfop": correct_cfop},
    )
    assert result["status"] == "potential"
    assert result["eligibility_certified"] is False
    assert result["tax_calculation_authorized"] is False


def test_transport_cfop_requires_document_specific_legal_review():
    result = evaluate(
        policy_changes={
            "allowed_operations": ["transport_service"],
            "allowed_cfops": ["1352"],
            "required_evidence": ["transport-document-review"],
        },
        fact_changes={"operation": "transport_service", "operation_cfop": "1352"},
    )
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == ["missing:transport-document-review"]



def test_end_of_legal_month_is_normalized_without_extending_rights():
    assert state_exclusive_after_legal_end(date(2026, 11, 30)) == date(2026, 12, 1)
    policy_nov = policy() | {
        "valid_until": "2026-12-01",
        "legal_valid_until_inclusive": "2026-11-30",
    }
    assert evaluate(policy_changes=policy_nov)["status"] == "potential"
    with pytest.raises(FiscalValidationError, match="validity conflict"):
        decode_rule(policy() | {
            "valid_until": "2026-11-30",
            "legal_valid_until_inclusive": "2026-11-30",
        })


def test_exclusive_validity_requires_original_legal_deadline():
    with pytest.raises(FiscalValidationError, match="inclusive end"):
        decode_rule(policy() | {"legal_valid_until_inclusive": None})
    with pytest.raises(FiscalValidationError, match="validity conflict"):
        decode_rule(policy() | {"legal_valid_until_inclusive": "2026-11-30"})


@pytest.mark.parametrize("missing", [
    "state_registration_regular_review",
    "icms_st_applicability_review",
    "difal_applicability_review",
    "individual_concession_review",
])
def test_state_specific_tax_treatment_is_never_assumed(missing):
    f = facts()
    f["evidence"].pop(missing)
    result = evaluate(fact_changes={"evidence": f["evidence"]})
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == [f"missing:{missing}"]
    assert result["eligibility_certified"] is False
    assert result["tax_calculation_authorized"] is False


@pytest.mark.parametrize("status", ["revoked", "expired", "suspended", "denied"])
def test_individual_grant_negative_status_blocks_potential(status):
    claim = {**facts()["individual_concession"], "status": status}
    result = evaluate(fact_changes={"individual_concession": claim})
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == [f"individual_concession_{status}"]


@pytest.mark.parametrize("change,reason", [
    (None, "individual_concession_missing"),
    ({"status": "pending"}, "individual_concession_unverified"),
    ({"issuer_cnpj": "99999999000199"}, "individual_concession_taxpayer_mismatch"),
    ({"uf": "RJ"}, "individual_concession_taxpayer_mismatch"),
    ({"competence": "2026-10-01"}, "individual_concession_review_mismatch"),
    ({"review_reference": "outdated-review"}, "individual_concession_review_mismatch"),
    ({"document_reference": ""}, "individual_concession_document_missing"),
    ({"valid_from": "2026-11-15"}, "individual_concession_not_valid_entire_month"),
    ({"valid_until": "2026-11-15"}, "individual_concession_not_valid_entire_month"),
    ({"valid_until": None}, "individual_concession_dates_unverified"),
])
def test_individual_grant_missing_stale_or_mismatched_blocks_potential(change, reason):
    original = facts()["individual_concession"]
    claim = None if change is None else {**original, **change}
    result = evaluate(fact_changes={"individual_concession": claim})
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == [reason]


def test_grant_not_required_needs_explicit_signed_normative_decision():
    f = facts()
    f["individual_concession"] = {
        "status": "not_required", "competence": MONTH.isoformat(),
        "review_reference": "synthetic-review-T09",
        "document_reference": "synthetic-waiver-review",
    }
    assert assess_state_rule(
        decode_rule(policy() | {"individual_concession_required": False}),
        decode_facts(f), issuer(), MONTH,
    )["status"] == "potential"
    assert assess_state_rule(
        decode_rule(policy()),
        decode_facts(f), issuer(), MONTH,
    )["reason_codes"] == ["individual_concession_required"]


def test_legacy_unreviewed_grant_requirement_is_rejected():
    p = policy()
    p.pop("individual_concession_required")
    with pytest.raises(FiscalValidationError, match="concession requirement"):
        decode_rule(p)


# Non-executable per-act research scenarios. The fixtures intentionally keep
# synthetic codes and signatures; these tests exercise the canonical evidence
# gate, NOT a finding that the whole act is in force or a taxpayer qualifies.
def _research_dossiers():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs/NFCORE_T09_DOSSIE_RECONCILIATION_V1.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_per_act_research_condition_is_required_by_canonical_motor(uf):
    row = next(x for x in _research_dossiers()["dossiers"] if x["uf"] == uf)
    key = row["required_review_evidence"]
    assert row["reference"] and row["conditional_positive"] and row["negative"]
    assert row["remaining_temporal_and_route_review"]
    assert row["import_authorized"] is False
    changes = {"required_evidence": [key]}
    result = evaluate(uf, policy_changes=changes)
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == [f"missing:{key}"]
    # Supply a controlled review reference, not an actual taxpayer grant.
    evidence = facts(uf)["evidence"] | {key: "synthetic-act-condition-review"}
    result = evaluate(uf, policy_changes=changes, fact_changes={"evidence": evidence})
    assert result["status"] == "potential"
    assert result["eligibility_certified"] is False
    assert result["tax_calculation_authorized"] is False
    assert result["issuance_authorized"] is False


def test_research_dossier_evidence_queue_preserves_missing_and_rejected_records():
    data = _research_dossiers()
    assert len(data["source_records"]) == 22
    assert len({r["expected_filename"] for r in data["source_records"]}) == 22
    assert len(data["dossiers"]) == 27
    assert {r["uf"] for r in data["dossiers"]} == set(_UF_CODES)
    assert not data["archived_originals_verified"]
    assert all(not r["eligible_for_import"] for r in data["source_records"])
    assert all(not r["internal_acceptance"] for r in data["dossiers"])
    assert len([
        r for r in data["source_records"]
        if r["identity_status"] == "no_received_act_in_audited_batches"
    ]) == 3
    rj = next(r for r in data["source_records"] if "362_2024" in r["expected_filename"])
    assert rj["capture_sha256"] is None
    assert any("CAPTCHA" in x["reason"] for x in data["invalid_and_superseded"])
    for record in data["source_records"]:
        digest = record["capture_sha256"]
        if digest is not None:
            assert len(digest) == 64
            assert all(c in "0123456789abcdef" for c in digest)


@pytest.mark.parametrize("uf", ["PI", "MG", "SP"])
def test_internal_operation_limitation_from_selected_acts(uf):
    # PI art.25-A; MG Annex II item 26; SP Annex III art.41.
    # Necessary negative condition only; no implied legal approval.
    result = evaluate(uf, fact_changes={
        "operation": "interstate_sale", "operation_cfop": "6102",
    })
    assert result["status"] == "not_applicable"
    assert result["reason_codes"] == ["operation_excluded"]


def test_pi_art25a_cannot_cover_march_2025():
    # The addition takes effect 01/04/2025; other gates remain unresolved.
    result = assess_state_rule(
        decode_rule(policy("PI") | {"valid_from": "2025-04-01"}),
        decode_facts(facts("PI")), issuer("PI"), date(2025, 3, 1),
    )
    assert result["reason_codes"] == ["state_rule_not_effective_entire_month"]
    assert result["tax_calculation_authorized"] is False


@pytest.mark.parametrize("uf", ["RJ", "SE"])
def test_simplified_regime_exclusion_from_selected_textile_and_psdi_acts(uf):
    # RJ Lei 6331 art.2 §9 and SE Lei 3140 art.3 §17.
    # Controlled case assumes simplified ICMS; no inference for sublimite cases.
    simplified = ReviewedStateIssuer(
        "12345678000195", uf, "6201501", FederalIncomeTaxRegime.SIMPLES_NACIONAL,
        True, SCOPE,
    )
    result = evaluate(uf, issuer_override=simplified)
    assert result["reason_codes"] == ["income_tax_regime_excluded"]
    assert result["eligibility_certified"] is False


def test_se_psdi_specific_program_rejects_absent_signed_context():
    result = evaluate(
        "SE", policy_changes={
            "program_id": "SE_PSDI",
            "state_normative_reference": "Lei 3.140/1991 e Decreto 29.935/2014",
        },
    )
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == ["se_psdi_context_missing"]
    assert result["tax_calculation_authorized"] is False


@pytest.mark.parametrize("ref", [
    "Lei 3.140/1991", "Decreto 29.935/2014",
    "Programa PSDI Sergipe", "Decreto 29935/2014",
])
def test_psdi_reviewed_policy_cannot_bypass_program_router(ref):
    with pytest.raises(FiscalValidationError, match="program-specific"):
        decode_rule(policy("SE") | {"state_normative_reference": ref})


def test_psdi_program_identity_cannot_be_reused_by_other_state():
    with pytest.raises(FiscalValidationError, match="program identity"):
        decode_rule(policy("AL") | {"program_id": "SE_PSDI"})


def test_se_psdi_real_motor_does_not_grant_even_synthetic_program_status():
    c = {
        "mode": "new_industry_8",
        "alese_amendments_by_competence_checked": True,
        "decree_29935_and_amendments_checked": True,
        "confaz_specific_modal_route_checked": True,
        "cdi_resolution_signed_and_published": True,
        "operation_ncm_cfop_cnae_reviewed": True,
        "state_icms_st_difal_checked": True,
        "current_simples_taxpayer": False,
        "cdi_grant_status": "active",
        "operation_authorized_by_resolution": True,
        "maintenance_and_compliance_confirmed": True,
        "cdi_cnpj_match": True,
        "grant_valid_from": "2026-01-01",
        "grant_valid_through": "2026-12-31",
        "operational_mode": "reviewed_2026",
        "icms_st_withheld": False,
        "final_consumer_operation": False,
        "operation": "incentivized_industrial_own_activity",
        "enterprise_type": "new",
        "new_enterprise_one_year_requirement_reviewed": True,
        "individual_cdi_resolution_percentage": "8",
    }
    result = evaluate(
        "SE",
        policy_changes={
            "program_id": "SE_PSDI",
            "state_normative_reference": "Lei 3.140/1991 PSDI - hypothetical",
        },
        fact_changes={"psdi_context": c},
    )
    assert result["status"] == "potential"
    assert result["tax_calculation_authorized"] is False
    assert result["approved_cents"] is None
    c["cdi_grant_status"] = "revoked"
    denied = evaluate(
        "SE",
        policy_changes={
            "program_id": "SE_PSDI",
            "state_normative_reference": "Lei 3.140/1991 PSDI - hypothetical",
        },
        fact_changes={"psdi_context": c},
    )
    assert denied["status"] == "insufficient_basis"
    assert denied["reason_codes"] == ["se_psdi_grant_revoked"]


@pytest.mark.parametrize("invalid", [[], {}, ["SE_PSDI"], 123])
def test_invalid_unhashable_program_identity_fails_closed(invalid):
    with pytest.raises(FiscalValidationError, match="program identity"):
        decode_rule(policy("AP") | {"program_id": invalid})
