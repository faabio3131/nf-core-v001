"""SE PSDI: prevent 2018 LegisWeb snapshot from being treated as 2026 law."""
from __future__ import annotations

import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
SHA = "710660329fbdfac01faa327ef2874ec62f7ddff65eeacd5a0f9f12abda205c5a"


def _uf(name: str, field: str, uf: str = "SE") -> dict:
    source = json.loads((DOCS / name).read_text(encoding="utf-8"))[field]
    return next(row for row in source if row["uf"] == uf)


def test_se_1991_statute_copy_has_actual_bytes_but_is_not_current_law():
    se = _uf("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")
    proof = se["historical_statute_user_pdf_checkpoint_20261123"]
    assert proof["pages"] == 6
    assert re.fullmatch("[a-f0-9]{64}", proof["sha256"])
    assert proof["sha256"] == SHA
    assert proof["text_cutoff"] == "2018-10-21"
    assert proof["original_bytes_integrity_checked"] is True
    assert proof["matches_government_archived_copy_bytewise"] is False
    assert proof["is_authentic_original_official_diary"] is False
    assert proof["legal_current_in_2026"] is False
    assert proof["full_amendment_chain_verified"] is False
    assert proof["independent_counter_review"] is False
    assert proof["import_authorized"] is False
    assert se["internal_acceptance"] is False


def test_se_all_specific_legal_restrictions_are_explicit():
    se = _uf("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")
    proof = se["historical_statute_user_pdf_checkpoint_20261123"]
    found = {item["provision"] for item in proof["material_findings"]}
    assert {"art. 3º §17", "art. 3º-B", "art. 8º"}.issubset(found)
    updated = {item["act"] for item in proof["post_2018_acts_requiring_reconciliation"]}
    assert {"Lei 9.812/2025", "Lei 9.943/2026"}.issubset(updated)
    assert any("DESENQUADRADO" in x for x in proof["negative_scenarios"])
    assert any("25% do ICMS" in x for x in proof["negative_scenarios"])
    assert any("6,2%" in x for x in proof["negative_scenarios"])


def test_se_gates_remain_unverified_with_historical_statute():
    row = _uf(
        "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json", "work_items"
    )
    cross = _uf("NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json", "rows")
    candidate = _uf(
        "NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json", "candidates"
    )
    record = row["research_checkpoint_20261122"]["user_lei3140_pdf_20261123"]
    assert record["sha256"] == SHA
    assert record["post_2018_consolidation_complete"] is False
    assert record["external_material_needed_from_owner"] is False
    assert cross["user_lei3140_pdf_20261123"]["review_accepted"] is False
    assert row["full_amendment_chain_verified"] is False
    assert row["applicability_by_competence_verified"] is False
    assert row["internal_curatorial_accepted"] is False
    assert row["legally_importable"] is False
    assert candidate["review_status"] == "draft"
    assert candidate["source_sha256"] is None
    assert candidate["import_authorized"] is False
