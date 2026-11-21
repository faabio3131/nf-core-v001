"""T09 legal research: source anchors do not become approved fiscal policies."""
import json
from pathlib import Path

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.state_benefits import _UF_CODES, decode_rule

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _document(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_27_uf_normative_index_never_implies_approved_benefit():
    data = _document("NFCORE_T09_STATE_NORMATIVE_SOURCE_INVENTORY_V1.json")
    assert data["schema_version"] == "nfcore.t09.state-normative-source-inventory/v1"
    assert not data["approved_for_eligibility"]
    assert not data["import_authorized"]
    states = data["states"]
    assert len(states) == 27
    assert {item["uf"] for item in states} == set(_UF_CODES)
    for row in states:
        assert row["source_url"].startswith("https://")
        assert not row["official_full_consolidation_reviewed"]
        assert not row["exact_benefit_provision_reviewed"]
        assert not row["benefit_eligibility_reviewed"]
        assert not row["import_authorized"]
        assert row["source_sha256"] is None
        assert row["legal_reviewer"] is None


def test_researched_candidates_are_versioned_and_fail_closed():
    drafts = _document("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    assert drafts["advisory_only"] and not drafts["import_authorized"]
    candidates = drafts["candidates"]
    assert len(candidates) == 2
    assert {c["uf"] for c in candidates} == {"SP", "RS"}
    assert len({c["candidate_id"] for c in candidates}) == len(candidates)
    for item in candidates:
        assert item["candidate_version"] == 1
        assert item["review_status"] == "draft"
        assert item["mandatory_missing"]
        assert item["state_official_source_url"].startswith("https://")
        with pytest.raises(FiscalValidationError, match="not human reviewed"):
            decode_rule(item)


def test_inventory_cannot_sneak_in_forged_reviewed_hash():
    data = _document("NFCORE_T09_STATE_NORMATIVE_SOURCE_INVENTORY_V1.json")
    assert all(row["source_sha256"] is None for row in data["states"])
