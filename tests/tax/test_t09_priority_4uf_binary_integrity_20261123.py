"""Four-UF evidence digest receipt: original bytes verified, law not certified."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _read(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_ten_official_capture_attempts_and_four_sha256_verified():
    receipt = _read("NFCORE_T09_PRIORITY_4UF_BYTES_AUDIT_20261123.json")
    dossiers = _read("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")["dossiers"]
    assert len(receipt["entries"]) == receipt["checked_source_count"] == 10
    assert (receipt["captured"], receipt["unavailable"]) == (4, 6)
    assert receipt["legal_approval"] is False
    assert Counter(x["status"] for x in receipt["entries"]) == {
        "captured_unreviewed": 4, "unavailable": 6,
    }
    for uf in ("SE", "AP", "PA", "RR"):
        doc = next(x for x in dossiers if x["uf"] == uf)
        saved = doc["priority_4uf_binary_evidence_20261123"]
        rows = [x for x in receipt["entries"] if x["uf"] == uf]
        good = [x for x in rows if x["status"] == "captured_unreviewed"]
        bad = [x for x in rows if x["status"] == "unavailable"]
        assert len(saved["captured_files"]) == len(good)
        assert len(saved["failed_sources"]) == len(bad)
        assert {x["sha256"] for x in saved["captured_files"]} == {
            x["sha256"] for x in good
        }
        assert all(re.fullmatch(r"[a-f0-9]{64}", x["sha256"])
                   for x in saved["captured_files"])
        assert saved["complete_legal_chain_verified"] is False
        assert saved["independent_review"] is False
        assert doc["internal_acceptance"] is False


@pytest.mark.parametrize("uf", ["SE", "RR"])
def test_missing_primary_capture_not_faked_as_success(uf):
    audit = _read("NFCORE_T09_PRIORITY_4UF_BYTES_AUDIT_20261123.json")
    assert not any(x["status"] == "captured_unreviewed"
                   for x in audit["entries"] if x["uf"] == uf)
