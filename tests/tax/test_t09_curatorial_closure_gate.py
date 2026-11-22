"""T09 curatorial status reconciliation must fail closed on premature promotion."""
from copy import deepcopy

import pytest

from scripts.nfcore_t09_curatorial_closure import audit_curation, audit_files


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
