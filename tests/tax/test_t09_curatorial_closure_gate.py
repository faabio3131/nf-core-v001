"""T09 curatorial status reconciliation must fail closed on premature promotion."""
from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest

# Only the Python package under src/ is importable in the CI runner. Keep the
# T09 research audit as a read-only script, not a new domain authority.
AUDIT_SOURCE = (
    Path(__file__).resolve().parents[2] / "scripts/nfcore_t09_curatorial_closure.py"
)
AUDIT_FUNCTIONS = run_path(str(AUDIT_SOURCE), run_name="t09_curatorial_audit_test")
audit_curation = AUDIT_FUNCTIONS["audit_curation"]
audit_files = AUDIT_FUNCTIONS["audit_files"]


def _fixture():
    import json
    from pathlib import Path

    docs = Path(__file__).resolve().parents[2] / "docs"
    names = (
        "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json",
        "NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json",
        "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json",
    )
    return [
        json.loads((docs / name).read_text(encoding="utf-8"))
        for name in names
    ]


def test_t09_audit_reports_all_27_internal_gaps_without_releasing_fiscal_right():
    report = audit_files()
    assert report["schema_version"] == "nfcore.t09.internal-curation-audit/v1"
    assert report["status"] == "INTERNAL_CURATORIAL_BLOCKED"
    assert report["representative_ufs"] == 27
    assert report["internally_accepted_ufs"] == 0
    assert len(report["missing_gates_by_uf"]) == 27
    assert report["fiscal_application_authorized"] is False
    assert report["all_internal_gates_recorded"] is False


@pytest.mark.parametrize("fake_field", [
    "legally_importable",
    "eligible_for_fiscal_application",
])
def test_queue_cannot_mark_real_fiscal_use_on_draft(fake_field):
    q, c, d = deepcopy(_fixture())
    q["work_items"][0][fake_field] = True
    with pytest.raises(ValueError, match="prematurely promoted"):
        audit_curation(q, c, d)


def test_catalog_import_cannot_be_enabled_by_changing_its_boolean():
    q, c, d = deepcopy(_fixture())
    c["candidates"][0]["import_authorized"] = True
    with pytest.raises(ValueError, match="prematurely promoted"):
        audit_curation(q, c, d)


def test_curatorial_approval_requires_real_original_and_separate_review():
    q, c, d = deepcopy(_fixture())
    q["work_items"][0]["internal_curatorial_accepted"] = True
    with pytest.raises(ValueError, match="premature or inconsistent"):
        audit_curation(q, c, d)


def test_unverified_dossier_claim_of_approval_is_rejected():
    q, c, d = deepcopy(_fixture())
    d["dossiers"][0]["internal_acceptance"] = True
    with pytest.raises(ValueError, match="premature or inconsistent"):
        audit_curation(q, c, d)


def test_t09_mismatched_research_identity_fails_the_whole_gate():
    q, c, d = deepcopy(_fixture())
    d["dossiers"][0]["candidate_id"] = "not-the-canonical-candidate"
    with pytest.raises(ValueError, match="IDs diverged"):
        audit_curation(q, c, d)


def test_t09_duplicate_uf_is_rejected_without_partial_acceptance():
    q, c, d = deepcopy(_fixture())
    d["dossiers"][0]["uf"] = d["dossiers"][1]["uf"]
    with pytest.raises(ValueError, match="duplicated UF/candidate"):
        audit_curation(q, c, d)


def test_human_product_approval_is_external_and_not_an_internal_gate():
    """Even all synthetic internal checks cannot grant a production release."""
    q, c, d = deepcopy(_fixture())
    for item, row in zip(q["work_items"], d["dossiers"], strict=True):
        for key in (
            "full_amendment_chain_verified",
            "applicability_by_competence_verified",
            "confaz_legal_route_verified",
            "scope_and_negative_cases_legally_grounded",
            "independent_agent_counter_review_passed",
            "technical_tests_certified_for_real_act",
        ):
            item[key] = True
        # Synthetic proof is deliberately NOT a real source attestation.
        item["source_publication_and_original_bytes_digest"] = "a" * 64
        item["individual_concession_normative_requirement_verified"] = True
        item["internal_curatorial_accepted"] = True
        row["evidence_status"] = "COMPLETE_RESEARCH_INTERNALLY_VERIFIED"
        row["independent_counter_review"] = True
        row["internal_acceptance"] = True
        # Neither an external human approval nor accountant opinion is supplied.
        assert "human_approval_record" not in item
        assert item["accountant_external_opinion"] == "PENDING_NOT_RECEIVED"
    report = audit_curation(q, c, d)
    assert report["all_internal_gates_recorded"] is True
    assert report["internally_accepted_ufs"] == 27
    assert report["missing_gates_by_uf"] == {}
    assert all(
        "human_product_owner_approval" in blockers
        for blockers in report["external_activation_gates_pending_by_uf"].values()
    )
    assert report["external_activation_gates_separate_from_internal"] is True
    assert report["external_approval_validated_by_this_script"] is False
    assert report["fiscal_application_authorized"] is False
    assert c["import_authorized"] is False
    assert all(item["legally_importable"] is False for item in q["work_items"])


def test_only_external_records_do_not_fabricate_internal_curation():
    q, c, d = deepcopy(_fixture())
    for item in q["work_items"]:
        item["human_approval_record"] = {
            "reviewer": "synthetic-test",
            "approval_id": "fake-not-verified",
            "approved_at": "2026-11-22",
            "head_sha": "b" * 64,
        }
    report = audit_curation(q, c, d)
    assert report["all_internal_gates_recorded"] is False
    assert report["internally_accepted_ufs"] == 0
    assert report["fiscal_application_authorized"] is False


def test_missing_external_receipt_does_not_hide_internal_deficiencies():
    q, c, d = deepcopy(_fixture())
    report = audit_curation(q, c, d)
    for blockers in report["missing_gates_by_uf"].values():
        assert "human_approval_record" not in blockers
        assert "full_amendment_chain_verified" in blockers
    assert report["external_activation_gates_separate_from_internal"] is True


def test_actual_taxpayer_grant_is_external_normative_predicate_is_internal():
    q, _, _ = _fixture()
    assert "human_product_owner_approval_of_curatorial_release" not in q[
        "completion_gates"
    ]
    assert "individual_grant_adhesion_and_maintenance_when_required" not in q[
        "internal_completion_gates"
    ]
    assert "individual_grant_requirement_and_conditions_normatively_established" in q[
        "internal_completion_gates"
    ]
    assert "individual_grant_adhesion_and_maintenance_when_required" in q[
        "external_release_gates"
    ]
    assert q["external_dependency_separation_20261122"][
        "external_not_a_blocker_for_internal_closeout"
    ] is True
