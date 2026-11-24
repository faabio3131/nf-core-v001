"""T09 four-state legal evidence identities, no false positive tax status."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _doc(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_four_state_reconciliation_and_exact_dossier_identity():
    studies = _doc("NFCORE_T09_SE_AP_PA_RR_CLOSEOUT_20261123.json")
    dossiers = _doc("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")
    matrix = _doc("NFCORE_T09_27UF_EVIDENCE_MATRIX_20261123.json")
    queue = _doc("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")
    assert [r["uf"] for r in studies["case_studies"]] == [
        "SE", "AP", "PA", "RR"
    ]
    assert studies["approved_count"] == 0
    assert studies["authorized_for_import"] is False
    for item in studies["case_studies"]:
        uf = item["uf"]
        dossier = next(x for x in dossiers["dossiers"] if x["uf"] == uf)
        current = next(x for x in matrix["rows"] if x["uf"] == uf)
        work = next(x for x in queue["work_items"] if x["uf"] == uf)
        assert item["legacy_candidate_id"] == dossier["candidate_id"]
        assert current["candidate_id"] == item["legacy_candidate_id"]
        assert work["candidate_id"] == item["legacy_candidate_id"]
        assert dossier["priority_closeout_20261123"][
            "internal_curatorial_accepted"
        ] is False
        assert current["modal_specific_confaz"][
            "specific_modality_proven"
        ] is False
        assert work["internal_curatorial_accepted"] is False
        assert item["primary_source_all_sha_verified"] is False
        assert item["complete_temporal_consolidation"] is False
        assert item["legal_curadoria_certified"] is False


def test_amapa_material_reselection_separates_fish_deferral_from_credit():
    item = _doc("NFCORE_T09_SE_AP_PA_RR_CLOSEOUT_20261123.json")[
        "case_studies"
    ][1]
    material = item["material_replacement"]
    assert material["candidate_id"] == (
        "AP-PESCADO-DEC3599-LEI3395-MATERIAL-V1"
    )
    assert material["kind"] == "deferral"
    assert "art415" in material["replaces_procedural"].lower()
    assert "primeira operação interna" in material["operation"]
    assert material["status"].endswith("CONFAZ_CERTIFICATE")
    assert item["legal_curadoria_certified"] is False


def test_pa_2018_inventory_2019_adi_and_2019_law_do_not_auto_revalidate():
    item = _doc("NFCORE_T09_SE_AP_PA_RR_CLOSEOUT_20261123.json")[
        "case_studies"
    ][2]
    acts = {x["act"]: x for x in item["chronology"]}
    assert any("ADI 3779" in a for a in acts)
    decree = next(x for x in item["chronology"] if "2.014" in x["act"])
    assert "item13" in decree["effect"]
    assert "Lei 8.930/2019" in acts
    assert item["status"] == "ORIGINAL_INVALIDATED_SUCCESSOR_UNPROVEN"


def test_rr_historical_end_2025_does_not_imply_2026_extension():
    item = _doc("NFCORE_T09_SE_AP_PA_RR_CLOSEOUT_20261123.json")[
        "case_studies"
    ][3]
    assert "2025" in item["chronology"][0]["effect"]
    assert item["status"] == "EXPIRED_2025_SPECIFIC_2026_EXTENSION_UNPROVEN"


@pytest.mark.parametrize("uf", ["SE", "AP", "PA", "RR"])
def test_new_source_workset_is_not_legal_authority(uf):
    workset = _doc("NFCORE_T09_PRIORITY_4UF_SOURCE_WORKSET_V1.json")
    originals = _doc("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    originals = {x["uf"]: x for x in originals["candidates"]}
    rows = [x for x in workset["entries"] if x["uf"] == uf]
    assert rows
    assert len({x["source_url"] for x in rows}) == len(rows)
    assert all(x["candidate_id"] == originals[uf]["candidate_id"] for x in rows)
    assert all(x["review_status"] == "unreviewed" for x in rows)
    assert all(x["eligible_for_tax_calculation"] is False for x in rows)
    assert workset["legal_validity_certified"] is False
    assert workset["authorized_for_import"] is False
