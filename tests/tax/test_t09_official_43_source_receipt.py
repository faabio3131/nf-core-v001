"""Evidence provenance of 43 official-source capture ATTEMPTS from T09.

This proves the immutable MANIFEST shape; original bytes are in the private
evidence archive and MUST be checked before using any specific normative claim.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
SOURCES = DOCS / "NFCORE_T09_43_OFFICIAL_SOURCE_BYTES_20261122.json"
WORKSET = DOCS / "NFCORE_T09_OFFICIAL_ALTERNATIVE_SOURCE_TRIAL_V1.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(proof: dict, workset: dict) -> None:
    assert proof["schema_version"] == "nfcore.t09.43-official-source-byte-check/v1"
    assert proof["source_integrity_pass"] is True
    assert proof["legal_validity_certified"] is False
    assert proof["import_authorized"] is False
    entries = proof["entries"]
    requested = workset["entries"]
    assert len(entries) == len(requested) == 43
    ids = {(r["uf"], r["source_url"], r["candidate_id"]) for r in requested}
    assert {(r["uf"], r["source_url"], r["candidate_id"]) for r in entries} == ids
    assert len(ids) == 43
    counts = Counter(row["status"] for row in entries)
    assert counts == {"captured_unreviewed": 34, "unavailable": 9}
    assert proof["capture_count"] == counts["captured_unreviewed"]
    assert proof["unavailable_count"] == counts["unavailable"]
    successful = set()
    for row in entries:
        if row["status"] == "captured_unreviewed":
            assert row["digest_verified"] is True
            assert re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"])
            assert row["size_bytes"] > 255
            assert row["relative_path"].startswith("sources/")
            successful.add(row["uf"])
        else:
            assert row["uf"] not in proof["successful_ufs"] or any(
                x["uf"] == row["uf"] and x["status"] == "captured_unreviewed"
                for x in entries
            )
            assert row.get("digest_verified") is not True
    assert set(proof["successful_ufs"]) == successful
    assert set(proof["without_captured_source_in_run"]) == {
        "AC", "RR", "SE"
    }
    assert len(successful) == 24
    assert set(proof["without_captured_source_in_run"]).isdisjoint(successful)
    assert successful | set(proof["without_captured_source_in_run"]) == {
        x["uf"] for x in requested
    }


def test_43_reproducible_official_source_capture_manifest():
    _validate(_json(SOURCES), _json(WORKSET))


@pytest.mark.parametrize("mutated", [
    "fake_digest", "unauthorized_source", "false_capture", "fake_legal_approval",
])
def test_capture_receipt_cannot_misstate_proof(mutated):
    proof, workset = _json(SOURCES), _json(WORKSET)
    if mutated == "fake_digest":
        row = next(x for x in proof["entries"] if x["status"] == "captured_unreviewed")
        row["source_sha256"] = "invalid"
    elif mutated == "unauthorized_source":
        proof["entries"][0]["source_url"] = "https://invalid.example"
    elif mutated == "false_capture":
        proof["entries"][0]["status"] = "captured_unreviewed"
    else:
        proof["legal_validity_certified"] = True
    with pytest.raises(AssertionError):
        _validate(proof, workset)
