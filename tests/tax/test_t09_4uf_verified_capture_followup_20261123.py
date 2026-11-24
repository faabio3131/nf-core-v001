"""Track actual downloaded primary bytes without fictitious legal approval."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_four_state_capture_receipts_are_real_and_unapproved() -> None:
    data = json.loads(
        (DOCS / "NFCORE_T09_4UF_VERIFIED_CAPTURE_FOLLOWUP_20261123.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["workflow_run"] == 45255832367
    assert data["source_count"] == len(data["entries"]) == 16
    assert (data["captured_count"], data["unavailable_count"]) == (7, 9)
    assert (data["originals_archived_pdf_count"], data["html_context_count"]) == (5, 2)
    assert data["tax_calculation_authorized"] is False
    assert data["import_authorized"] is False
    assert data["legal_certification_awarded"] is False
    assert data["independent_review"] is False
    assert data["verified_bytes"] is True
    counts = Counter(row["status"] for row in data["entries"])
    assert counts == {"captured_unreviewed": 7, "unavailable": 9}
    for row in data["entries"]:
        assert row["legal_applicability_approved"] is False
        if row["status"] == "captured_unreviewed":
            assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            assert row["size_bytes"] > 0
            assert row["format"] in {"pdf", "html"}


def test_paid_juridical_originals_do_not_imply_subsequent_approval() -> None:
    data = json.loads(
        (DOCS / "NFCORE_T09_4UF_VERIFIED_CAPTURE_FOLLOWUP_20261123.json").read_text(
            encoding="utf-8"
        )
    )
    cases = json.loads(
        (DOCS / "NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    pa = next(row for row in data["entries"] if row["url"].endswith("2018.03.23.DOE.pdf"))
    ap = next(row for row in data["entries"] if row["url"].endswith("/9901"))
    assert pa["sha256"] == "6dbf8fdb313e6673ce6105b9c6e74714070adaa220e39cbd2187840ef4abf0a0"
    assert ap["sha256"] == "8db2b8901a3774739846444691b8caced5bd549759537e28182fc19782bcf9c5"
    for uf in ("PA", "AP", "SE", "RR"):
        case = next(x for x in cases if x["uf"] == uf)
        assert case["production_enabled"] is False
        assert case["legal_certification_awarded"] is False
        assert case["decision_effect"] == "BLOCK_ICMS_BENEFIT_CALCULATION_AND_FISCAL_IMPORT"


def test_amapa_visualizer_html_cannot_be_mistaken_for_official_pdf() -> None:
    data = json.loads(
        (DOCS / "NFCORE_T09_4UF_VERIFIED_CAPTURE_FOLLOWUP_20261123.json").read_text(
            encoding="utf-8"
        )
    )
    viewer = next(x for x in data["entries"] if "visualizar_pdf/9915" in x["url"])
    assert viewer["format"] == "html"
    assert viewer["legal_applicability_approved"] is False
