"""T09 internal official-source recovery must not turn discovery into ICMS grants."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.tax.t09_priority_state_guards import assess_priority_state_context

DOCS = Path(__file__).resolve().parents[2] / "docs"
WORKSET = DOCS / "NFCORE_T09_PRIORITY_4UF_SOURCE_WORKSET_V1.json"
TERMINAL = DOCS / "NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json"


def test_four_state_recovery_queue_is_internal_and_fail_closed() -> None:
    queue = json.loads(WORKSET.read_text(encoding="utf-8"))
    entries = queue["entries"]
    assert len(entries) >= 16
    assert {row["uf"] for row in entries} == {"SE", "AP", "PA", "RR"}
    assert queue["authorized_for_import"] is False
    assert queue["legal_validity_certified"] is False
    assert queue["independent_approval_received"] is False
    assert len({row["source_url"] for row in entries}) == len(entries)
    for row in entries:
        assert row["review_status"] == "unreviewed"
        assert row["eligible_for_tax_calculation"] is False
        assert row["source_url"].startswith("https://")


@pytest.mark.parametrize("uf,required_url", [
    ("SE", "https://pge.se.gov.br/wp-content/uploads/2025/09/processo-585.2024-PRO.ADM-CODISE.pdf"),
    ("AP", "https://diofe.portal.ap.gov.br/portal/edicoes/download/9901"),
    ("PA", "https://bancodeleis.alepa.pa.gov.br/arquivos/lei2490_2006_53513.pdf"),
    ("RR", "https://www.sefaz.rr.gov.br/cidadao/downloads?catid=1063&id=23153&m=0&task=download.send"),
])
def test_primary_publication_evidence_in_queue_is_not_auto_imported(
    uf: str, required_url: str,
) -> None:
    queue = json.loads(WORKSET.read_text(encoding="utf-8"))
    row = next(row for row in queue["entries"] if row["source_url"] == required_url)
    assert row["uf"] == uf
    assert row["verification_note"]
    assert row["eligible_for_tax_calculation"] is False
    terminal = json.loads(TERMINAL.read_text(encoding="utf-8"))
    case = next(case for case in terminal["cases"] if case["uf"] == uf)
    assert case["production_enabled"] is False
    assert case["legal_certification_awarded"] is False
    assert case["decision_effect"] == (
        "BLOCK_ICMS_BENEFIT_CALCULATION_AND_FISCAL_IMPORT"
    )


@pytest.mark.parametrize("program,context,competence", [
    ("PA_6913_ADI3779", {"lc160_reinstated": True}, date(2026, 11, 23)),
    ("RR_LXVII_AGRO", {"confaz_extended": True}, date(2026, 11, 23)),
    ("AP_FISH_3599", {"claimed_3490_extension_for_fish": True}, date(2026, 11, 23)),
])
def test_additional_official_documents_do_not_bypass_existing_guard(
    program: str, context: dict[str, bool], competence: date,
) -> None:
    result = assess_priority_state_context(program, context, competence)
    assert result["status"] == "insufficient_basis"
    assert result["tax_calculation_authorized"] is False
    assert result["approved_cents"] is None
