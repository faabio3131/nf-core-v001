"""T09 retry sources record exact hashes without inventing missing SE evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _get(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("uf", ["AC", "RR", "SE"])
def test_source_recovery_never_certifies_a_normative_state(uf):
    receipt = _get("NFCORE_T09_RETRY_3UFS_CAPTURE_RECEIPT_20261122.json")
    dossier = _get("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")["dossiers"]
    queue = _get("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")[
        "work_items"
    ]
    d = next(x for x in dossier if x["uf"] == uf)
    q = next(x for x in queue if x["uf"] == uf)
    status = d["retry_3_official_sources_20261122"]
    rows = [x for x in receipt["entries"] if x["uf"] == uf]
    successes = [x for x in rows if x["status"] == "captured_unreviewed"]
    failures = [x for x in rows if x["status"] == "unavailable"]
    assert status["captured_ok"] == len(successes)
    assert status["failed"] == len(failures)
    assert status["attempts"] == len(rows)
    assert q["research_checkpoint_20261122"][
        "retry_3_official_sources_20261122"
    ]["captured_ok"] == len(successes)
    for src in status["official_source_sha256"]:
        assert re.fullmatch(r"[0-9a-f]{64}", src["sha256"])
        assert (src["source_url"], src["sha256"]) in {
            (x["source_url"], x["source_sha256"]) for x in successes
        }
    assert status["actual_original_legal_statute_certified"] is False
    assert status["complete_normative_chain_verified"] is False
    assert status["independent_counter_review"] is False
    assert status["internal_curation_accepted"] is False
    assert d["internal_acceptance"] is False
    assert q["internal_curatorial_accepted"] is False
    assert q["eligible_for_fiscal_application"] is False


def test_se_timeout_is_not_fabricated_as_a_captured_source():
    receipt = _get("NFCORE_T09_RETRY_3UFS_CAPTURE_RECEIPT_20261122.json")
    entries = receipt["entries"]
    assert len(entries) == 9
    assert receipt["captured"] == 2
    assert receipt["unavailable"] == 7
    assert receipt["unable_to_capture"] == ["SE"]
    assert not any(
        x["status"] == "captured_unreviewed" for x in entries if x["uf"] == "SE"
    )
    assert receipt["legal_validity_certified"] is False
    assert receipt["import_authorized"] is False
