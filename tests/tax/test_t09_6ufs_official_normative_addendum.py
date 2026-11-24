"""Additional material legal restrictions researched in six state candidates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
STATES = ("AC", "RR", "RJ", "RN", "RS", "TO")


def _rows(path: str, field: str) -> dict:
    rows = json.loads((DOCS / path).read_text(encoding="utf-8"))[field]
    return {row["uf"]: row for row in rows}


@pytest.mark.parametrize("uf", STATES)
def test_official_material_research_is_not_automatic_state_tax_entitlement(uf):
    docs = _rows("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")
    checks = _rows("NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json",
                   "rows")
    queue = _rows("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json",
                  "work_items")
    row = docs[uf]
    note = row["additional_primary_device_research_20261122"]
    assert note["official_url"].startswith("https://")
    assert note["material_finding"] and note["negative_test"]
    for key in (
        "original_publication_bytes_archived_in_git",
        "all_amendments_verified",
        "full_competence_verified",
        "confaz_route_independently_verified",
        "legal_review_completed",
        "internal_acceptance",
        "eligible_for_real_fiscal_application",
    ):
        assert note[key] is False
    assert checks[uf]["additional_primary_device_research_20261122"][
        "approved"
    ] is False
    assert queue[uf]["internal_curatorial_accepted"] is False
    assert row["import_authorized"] is False


def test_roraima_2026_general_compilation_cannot_extend_lxvii_exemption():
    rr = _rows("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")["RR"]
    assertion = rr["additional_primary_device_research_20261122"]
    assert "31/12/2025" in assertion["material_finding"]
    assert "2026" in assertion["negative_test"]


def test_rs_option_requires_grant_to_be_effective_after_approval():
    rs = _rows("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")["RS"]
    note = rs["additional_primary_device_research_20261122"]
    assert "seis meses" in note["material_finding"]
    assert "deferimento" in note["negative_test"]


def test_rn_2025_amendment_cannot_cover_whole_march():
    rn = _rows("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")["RN"]
    note = rn["additional_primary_device_research_20261122"]
    assert "20/03/2025" in note["material_finding"]
    assert "mês inteiro" in note["negative_test"]


def test_rj_feccp_included_in_nominal_target_burden_not_extra_rate():
    rj = _rows("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")["RJ"]
    note = rj["additional_primary_device_research_20261122"]
    assert "1% FECP" in note["material_finding"]
    assert "30/11/2025" in note["material_finding"]
    assert note["eligible_for_real_fiscal_application"] is False
