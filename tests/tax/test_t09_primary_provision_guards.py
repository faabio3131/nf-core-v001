"""T09: source-backed necessary constraints, NOT real taxpayer entitlement.

CNAE, NCM, review references and individual dispensation here are synthetic.
No legal source hash is fabricated and no policy is imported by these tests.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    _COMMON_EVIDENCE,
    _ROUTE_EVIDENCE,
    FACTS_SCHEMA,
    RULE_SCHEMA,
    ReviewedStateIssuer,
    assess_state_rule,
    decode_facts,
    decode_rule,
)

DOSSIERS = (
    Path(__file__).resolve().parents[2]
    / "docs/NFCORE_T09_DOSSIE_RECONCILIATION_V1.json"
)
RECEIPTS = DOSSIERS.with_name("NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json")
REVIEW = "synthetic-t09-provision-review"
SCOPE = ("fm-nfcore", "tenant-test", "unit-test", "test")


def _dossier(uf):
    rows = json.loads(DOSSIERS.read_text(encoding="utf-8"))["dossiers"]
    return next(x for x in rows if x["uf"] == uf)


def _evaluate(uf, month, *, start="2026-01-01", omitted=(),
              operation="domestic_sale", cfop="5102"):
    inspected = _dossier(uf)["primary_provision_checkpoint_20261122"]
    required = inspected["evidence"]
    policy = {
        "schema_version": RULE_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": uf,
        "benefit_kind": "base_reduction",
        "legal_path": "state_statute",
        "state_normative_reference": inspected["articles"],
        "valid_from": start,
        "valid_until": "2027-01-01",
        "legal_valid_until_inclusive": "2026-12-31",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "reviewed_any",
        "allowed_cnaes": [],
        "ncm_scope": "reviewed_any",
        "allowed_ncms": [],
        "allowed_cfops": ["5102"],
        "allowed_operations": ["domestic_sale"],
        "required_evidence": required,
        "individual_concession_required": False,
    }
    evidence_keys = (
        *_COMMON_EVIDENCE,
        *_ROUTE_EVIDENCE["state_statute"],
        *required,
    )
    record = {
        "schema_version": FACTS_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": uf,
        "activity_cnae": "6201501",
        "operation_ncm": "84713012",
        "operation_cfop": cfop,
        "operation": operation,
        "evidence": {
            key: "synthetic-test-evidence"
            for key in evidence_keys if key not in omitted
        },
        "individual_concession": {
            "status": "not_required",
            "competence": month.isoformat(),
            "review_reference": REVIEW,
            "document_reference": "synthetic-test-dispensation",
        },
    }
    issuer = ReviewedStateIssuer(
        "12345678000195",
        uf,
        "6201501",
        FederalIncomeTaxRegime.LUCRO_REAL,
        True,
        SCOPE,
    )
    return assess_state_rule(
        decode_rule(policy), decode_facts(record), issuer, month,
    )


@pytest.mark.parametrize("uf", ["MG", "PB", "PE", "PI", "RN", "SP"])
def test_six_primary_source_reviews_do_not_certify_any_candidate(uf):
    row = _dossier(uf)
    review = row["primary_provision_checkpoint_20261122"]
    assert review["url"].startswith("https://")
    assert review["articles"] and review["finding"]
    assert review["evidence"] and review["unresolved"]
    assert review["status"] == "PARTIAL_PRIMARY_TEXT_REVIEW_ONLY"
    assert review["full_chain_verified"] is False
    assert review["legal_applicability_approved"] is False
    assert row["internal_acceptance"] is False
    assert row["import_authorized"] is False


@pytest.mark.parametrize("uf,omitted", [
    ("SP", "sp_nonreturn_credit_substitution"),
    ("MG", "mg_discount_invoice_note"),
    ("RN", "rn_option_term"),
    ("PB", "pb_ncm_first_four_digits"),
    ("PI", "pi_confaz_224_17"),
    ("PE", "pe_actual_amendments"),
])
def test_missing_act_specific_review_is_not_legal_eligibility(uf, omitted):
    outcome = _evaluate(uf, date(2026, 11, 1), omitted=(omitted,))
    assert outcome["status"] == "insufficient_basis"
    assert outcome["reason_codes"] == [f"missing:{omitted}"]
    assert outcome["tax_calculation_authorized"] is False
    assert outcome["eligibility_certified"] is False


@pytest.mark.parametrize("uf", ["SP", "MG", "PI"])
def test_internal_sale_hypotheses_exclude_interstate_sale(uf):
    outcome = _evaluate(
        uf, date(2026, 11, 1), operation="interstate_sale", cfop="6102",
    )
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["operation_excluded"]


@pytest.mark.parametrize("uf", ["SP", "MG"])
def test_stated_2026_legal_end_is_not_extended_into_2027(uf):
    outcome = _evaluate(uf, date(2027, 1, 1))
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]


@pytest.mark.parametrize("uf,start,month", [
    ("RN", "2025-03-20", date(2025, 3, 1)),
    ("PB", "2026-02-19", date(2026, 2, 1)),
])
def test_intramonth_amendment_cannot_automatically_cover_entire_month(
    uf, start, month,
):
    outcome = _evaluate(uf, month, start=start)
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]


def test_even_synthetic_complete_review_never_authorizes_real_tax():
    outcome = _evaluate("MG", date(2026, 11, 1))
    assert outcome["status"] == "potential"
    assert outcome["advisory_only"] is True
    assert outcome["eligibility_certified"] is False
    assert outcome["tax_calculation_authorized"] is False
    assert outcome["issuance_authorized"] is False
    assert outcome["approved_cents"] is None


def test_pe_decree_61000_excluded_from_prodepe_material_modifiers():
    row = _dossier("PE")
    assert "61.000" not in row["remaining_temporal_and_route_review"]
    assert "NÃO altera materialmente" in (
        row["primary_provision_checkpoint_20261122"]["finding"]
    )


def test_final_fifty_captures_linked_to_same_canonical_27_dossiers():
    rows = json.loads(DOSSIERS.read_text(encoding="utf-8"))["dossiers"]
    manifest = json.loads(RECEIPTS.read_text(encoding="utf-8"))
    assert len(rows) == 27
    assert len(manifest["files"]) == 50
    assert sum(
        row["final_intake_reconciliation_20261122"]["capture_count"]
        for row in rows
    ) == 50
    for row in rows:
        intake = row["final_intake_reconciliation_20261122"]
        assert intake["not_a_legal_approval"] is True
        assert intake["capture_count"] == len(intake["capture_filenames"])
        assert row["internal_acceptance"] is False
        assert row["import_authorized"] is False
