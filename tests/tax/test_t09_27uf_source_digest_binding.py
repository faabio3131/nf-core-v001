"""Tie each real SHA-256 capture receipt to its canonical UF dossier."""
from __future__ import annotations

import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _doc(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_all_27_dossiers_have_exact_captured_bytes_and_failed_sources():
    receipt = _doc("NFCORE_T09_43_OFFICIAL_SOURCE_BYTES_20261122.json")
    dossiers = _doc("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")["dossiers"]
    queue = _doc("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")[
        "work_items"
    ]
    assert len(dossiers) == len(queue) == 27
    assert len(receipt["entries"]) == 43
    total_ok = total_fail = 0
    for doc, item in zip(dossiers, queue, strict=True):
        uf = doc["uf"]
        assert uf == item["uf"]
        assert doc["candidate_id"] == item["candidate_id"]
        saved = doc["latest_43_source_capture_receipt"]
        marker = item["research_checkpoint_20261122"][
            "latest_43_source_capture_receipt"
        ]
        entries = [x for x in receipt["entries"] if x["uf"] == uf]
        verified = [x for x in entries if x["status"] == "captured_unreviewed"]
        rejected = [x for x in entries if x["status"] == "unavailable"]
        assert saved["bytes_verified_count"] == marker["bytes_verified_count"]
        assert saved["bytes_verified_count"] == len(verified)
        assert saved["unavailable_count"] == len(rejected)
        assert saved["normative_chain_consolidated"] is False
        assert saved["legal_publication_authenticated"] is False
        assert saved["independent_review_received"] is False
        assert saved["authorized_for_import"] is False
        assert doc["internal_acceptance"] is False
        assert item["internal_curatorial_accepted"] is False
        original = sorted(
            (r["url"], r["sha256"], r["bytes"])
            for r in saved["official_bytes"]
        )
        expected = sorted(
            (r["source_url"], r["source_sha256"], r["size_bytes"])
            for r in verified
        )
        assert original == expected
        assert sorted(r["url"] for r in saved["failed_sources"]) == sorted(
            r["source_url"] for r in rejected
        )
        total_ok += len(verified)
        total_fail += len(rejected)
    assert (total_ok, total_fail) == (34, 9)
