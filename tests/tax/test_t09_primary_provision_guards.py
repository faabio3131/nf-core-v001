"""T09: source-backed necessary constraints, NOT real taxpayer entitlement.

CNAE, NCM, review references and individual dispensation here are synthetic.
No legal source hash is fabricated and no policy is imported by these tests.
"""
import json
from datetime import date, timedelta
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
              operation="domestic_sale", cfop="5102",
              legal_last_day="2026-12-31"):
    row = _dossier(uf)
    inspected = row.get("primary_provision_checkpoint_20261122")
    if inspected is None and uf == "AP":
        ap = row["supervening_official_20261122"]
        inspected = {
            "articles": "Decreto 2.656/2026 art. 9",
            "evidence": ap["required_review_keys"],
        }
    if inspected is None and uf in ("RR", "MT"):
        # Primary official consultation indicates a specific term, not a
        # completed state benefit review or authorization.
        inspected = {
            "articles": row["reference"],
            "evidence": ("state_uf_statute_scope_review",),
        }
    if inspected is None:
        raise KeyError("source-specific test case not defined")
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
        "valid_until": (date.fromisoformat(legal_last_day) + timedelta(days=1)).isoformat(),
        "legal_valid_until_inclusive": legal_last_day,
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "reviewed_any",
        "allowed_cnaes": [],
        "ncm_scope": "reviewed_any",
        "allowed_ncms": [],
        "allowed_cfops": ["5102"],
        "allowed_operations": ["domestic_sale"],
        "required_evidence": list(required),
        "individual_concession_required": False,
    }
    if uf == "RR":
        policy["program_id"] = "RR_LXVII_AGRO"
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
    ("PB", "pb_fain_fgts_crf_renewal"),
    ("PE", "pe_efd_regular_delivery_art21a"),
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


def test_pe_decree_61000_changes_prodepe_efd_compliance_not_credit_rate():
    row = _dossier("PE")
    text = row["primary_provision_checkpoint_20261122"]["finding"]
    assert "art.21-A §10" in text
    assert "EFD-ICMS/IPI" in text
    assert "NÃO muda diretamente percentual" in text
    assert "não cria benefício" in row["remaining_temporal_and_route_review"]
    assert "pe_efd_regular_delivery_art21a" in (
        row["primary_provision_checkpoint_20261122"]["evidence"]
    )


def test_pb_decree_48405_adds_fgts_compliance_to_fain_renewals():
    row = _dossier("PB")
    assert "48.405/2026" in row["reference"]
    assert "pb_fain_fgts_crf_renewal" in (
        row["primary_provision_checkpoint_20261122"]["evidence"]
    )
    claim = row["supervening_2026_primary_examination"]
    assert "FGTS" in claim["article_or_change"]
    assert claim["competence_change_start_reference"] == "2026-07-04"
    assert claim["internal_acceptance"] is False


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



def test_amapa_april_2026_successor_decree_cannot_backdate_entire_month():
    ap = _dossier("AP")
    chain = ap["supervening_official_20261122"]["regulations"]
    assert chain[0]["act"] == "Decreto 2.349/2026"
    assert chain[0]["status"] == "REVOKED_2026_04_17"
    assert chain[1]["act"] == "Decreto 2.656/2026"
    assert chain[1]["published"] == "2026-04-17"
    assert chain[2]["act"] == "Lei 3.490/2026"
    assert ap["internal_acceptance"] is False
    assert ap["import_authorized"] is False
    # Synthetic advisory policy effective only from successor publication;
    # full month of April cannot be granted automatically.
    event = _evaluate("AP", date(2026, 4, 1), start="2026-04-17")
    assert event["status"] == "not_applicable"
    assert event["reason_codes"] == ["state_rule_not_effective_entire_month"]
    assert event["tax_calculation_authorized"] is False


def test_mt_2027_end_requires_source_specific_route_not_generic_convênio():
    mt = _dossier("MT")
    note = mt["official_consultation_20261122"]
    assert note["status"] == "STATE_TAX_AUTHORITY_INTERPRETIVE_INFORMATION_NOT_DOE"
    assert "Decreto1802/2025" in note["legal_route"].replace(" ", "")
    assert "2027-12-31" in note["legal_route"]
    assert mt["internal_acceptance"] is False
    assert mt["import_authorized"] is False


def test_pa_and_rr_unresolved_judicial_and_state_extension_never_approved():
    pa = _dossier("PA")["judicial_source_checkpoint_20261122"]
    rr = _dossier("RR")["official_consultation_20261122"]
    assert "STF_DECISION_IDENTIFIED" in pa["status"]
    assert pa["2019_majority_modulation_denied"] is True
    assert "superseding valid law" in pa["still_unverified"]
    assert "2025" in rr["findings"]
    assert "2026" in rr["unresolved"]
    assert not _dossier("PA")["import_authorized"]
    assert not _dossier("RR")["import_authorized"]



# T09 temporal authority cases bind specific official research to the canonical
# monthly validity checker. The synthetic policy cannot grant real tax relief.
TEMPORAL_DOC = DOSSIERS.with_name("NFCORE_T09_TEMPORAL_AUTHORITY_20261122.json")


def _temporal_case(uf):
    data = json.loads(TEMPORAL_DOC.read_text(encoding="utf-8"))
    return next(case for case in data["cases"] if case["uf"] == uf)


def test_mg_federal_renewal_cannot_overrule_earlier_state_legal_end():
    case = _temporal_case("MG")
    assert case["state_end_inclusive_observed"] == "2026-12-31"
    assert case["federal_end_reported"] == "2028-12-31"
    assert case["federal_2028_extension_identified_for_exact_convention"] is False
    # Even if a federal convention has later dates, state authorization cannot
    # be extended without the applicable state act being effective.
    outcome = _evaluate("MG", date(2027, 1, 1),
                        legal_last_day=case["state_end_inclusive_observed"])
    assert outcome["status"] == "not_applicable"
    assert outcome["tax_calculation_authorized"] is False
    assert case["approved"] is False


def test_sp_art41_new_2023_rate_cannot_backdate_january_month():
    case = _temporal_case("SP")
    assert len(case["periods_observed"]) == 3
    assert [p["credit_percent_of_eligible_sale"] for p in case["periods_observed"]] == [
        "9.7", "9", "12",
    ]
    latest = case["periods_observed"][-1]
    outcome = _evaluate("SP", date(2023, 1, 1),
                        start=latest["from"],
                        legal_last_day=latest["to_inclusive"])
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]
    assert not outcome["tax_calculation_authorized"]


def test_rr_federal_extension_is_not_automatic_state_2026_authorization():
    case = _temporal_case("RR")
    assert not case["state_extension_2026_found"]
    outcome = _evaluate("RR", date(2026, 1, 1), start="2025-01-01",
                        legal_last_day=case["state_end_inclusive_last_text"])
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]
    assert not outcome["eligibility_certified"]


def test_mt_last_day_december_2027_excludes_january_2028():
    case = _temporal_case("MT")
    outcome = _evaluate("MT", date(2028, 1, 1),
                        legal_last_day=case["state_end_inclusive_observed"])
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]


@pytest.mark.parametrize("uf", ["MG", "SP", "RN", "AP", "RR", "MT"])
def test_temporal_research_stays_uncertified_and_cannot_import(uf):
    case = _temporal_case(uf)
    assert case["verified"]
    assert case["approved"] is False
    assert _dossier(uf)["internal_acceptance"] is False
    assert _dossier(uf)["import_authorized"] is False


def test_temporal_matrix_does_not_replace_27uf_legal_curation():
    data = json.loads(TEMPORAL_DOC.read_text(encoding="utf-8"))
    assert data["schema_version"] == "nfcore.t09.temporal-authority-review/v1"
    assert len(data["cases"]) == 6
    assert len({x["uf"] for x in data["cases"]}) == 6
    assert data["accepted_count"] == 0
    assert not data["import_authorized"]
    assert not data["source_originals_archived"]
    assert not data["independent_review_passed"]



@pytest.mark.parametrize("missing", [
    "mg_cohab_recognition_per_invoice",
    "mg_project_quantity_limit",
    "mg_invoice_recognition_number_date",
    "mg_invoice_tax_dispensation_amount",
])
def test_mg_cohab_individual_invoice_recognition_required_for_advisory(missing):
    """Necessary conditions of SEF/MG Resolução Conjunta 01/1998, not a grant."""
    row = _dossier("MG")
    original = row["primary_provision_checkpoint_20261122"][
        "resolution_1998_original_evidence"
    ]
    assert original["source_url"].endswith("rr0001_1998.html")
    assert original["capture_sha256"] == (
        "125b051af5214d535ffa97b81ec2cab01c44620f73748be6f66876587c7d7edc"
    )
    assert original["additional_normative_reconciliation_pending"]
    result = _evaluate("MG", date(2026, 11, 1), omitted=(missing,))
    assert result["status"] == "insufficient_basis"
    assert result["reason_codes"] == [f"missing:{missing}"]
    assert not result["eligibility_certified"]
    assert not result["tax_calculation_authorized"]


def test_mg_source_is_not_an_automatic_benefit_permission():
    row = _dossier("MG")
    scope = row["primary_provision_checkpoint_20261122"]
    assert "mg_cohab_recognition_per_invoice" in scope["evidence"]
    assert row["internal_acceptance"] is False
    assert row["import_authorized"] is False
    result = _evaluate("MG", date(2026, 11, 1))
    assert result["status"] == "potential"
    assert result["advisory_only"] is True
    assert result["tax_calculation_authorized"] is False
