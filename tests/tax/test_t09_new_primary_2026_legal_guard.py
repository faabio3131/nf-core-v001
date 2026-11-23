"""2026 exact-material research cannot promote five state benefit drafts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _records(name: str, field: str) -> dict:
    data = json.loads((DOCS / name).read_text(encoding="utf-8"))
    return {x["uf"]: x for x in data[field]}


@pytest.mark.parametrize("uf", ["AM", "AP", "BA", "DF", "ES"])
def test_official_2026_primary_case_and_negative_review_is_explicit(uf):
    dossiers = _records("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")
    drafts = _records("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json",
                      "candidates")
    queue = _records("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json",
                     "work_items")
    cross = _records("NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json",
                     "rows")
    item = dossiers[uf]
    evidence = item["primary_legal_checkpoint_v2_20261122"]
    assert evidence["official_url"].startswith("https://")
    assert evidence["provisions_reviewed"] and evidence["negative_case"]
    assert evidence["official_pdf_original_sha256"] is None
    assert evidence["complete_amendment_chain_verified"] is False
    assert evidence["independent_review_passed"] is False
    assert evidence["research_internal_accepted"] is False
    assert evidence["actual_tax_benefit_authorized"] is False
    assert cross[uf]["primary_legal_checkpoint_v2_20261122"]["accepted"] is False
    assert drafts[uf]["review_status"] == "draft"
    assert drafts[uf]["import_authorized"] is False
    assert queue[uf]["internal_curatorial_accepted"] is False
    assert queue[uf]["eligible_for_fiscal_application"] is False


def test_am_retroactive_effects_cannot_be_confused_with_publication():
    d = _records("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json",
                 "dossiers")["AM"]
    act = d["supervening_2026_primary_examination"]
    assert act["official_publication_date"] == "2026-02-06"
    assert act["competence_change_start_reference"] == "2026-01-01"
    assert act["retroactive_effects_confirmed_in_art4"] is True
    assert not d["internal_acceptance"]


def test_ap_procedural_art415_is_not_certified_material_icms():
    d = _records("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json",
                 "dossiers")["AP"]
    assert d["material_candidate_reselection_required"] is True
    assert d["material_normative_alternative"]["status"] == (
        "RESEARCHED_NOT_CANONICALLY_RESELECTED"
    )
    assert "2.656/2026" in d["material_normative_alternative"]["regulation"]
    assert d["internal_acceptance"] is False
