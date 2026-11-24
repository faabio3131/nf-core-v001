"""AC, RR, SE retry is official HTTPS evidence only, never automatic law."""
from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).resolve().parents[2]
HELPER = run_path(str(ROOT / "scripts/nfcore_t09_capture_alternatives.py"))
verify_workset = HELPER["verify_workset"]


def test_missing_three_state_sources_are_approved_for_capture_only():
    drafts = json.loads(
        (ROOT / "docs/NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
        .read_text(encoding="utf-8")
    )
    alt = json.loads(
        (ROOT / "docs/NFCORE_T09_RETRY_OFFICIAL_SOURCES_3UFS_V1.json")
        .read_text(encoding="utf-8")
    )
    sources = verify_workset(drafts, alt)
    assert len(sources) == 10
    assert {s["uf"] for s in sources} == {"AC", "RR", "SE"}
    assert all(s["source_url"].startswith("https://") for s in sources)
    assert all(s["review_status"] == "unreviewed" for s in sources)
    assert all(s["eligible_for_tax_calculation"] is False for s in sources)
    assert alt["authorized_for_import"] is False
    assert alt["legal_validity_certified"] is False
    assert alt["independent_approval_received"] is False
