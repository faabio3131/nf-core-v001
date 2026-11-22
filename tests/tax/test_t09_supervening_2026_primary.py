"""T09 new 2026 legal changes: source-specific checks, never tax permission.

This module tests research provenance and necessary blockers. Official portal
texts do not replace authenticated DOE originals, legal chain or reviewer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
DOSSIER_FILE = DOCS / "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json"
CROSS_FILE = DOCS / "NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json"
DRAFT_FILE = DOCS / "NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json"
QUEUE_FILE = DOCS / "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json"

LATEST = {
    "AM": ("53.496/2026", "AM_PROCESSO_ELEMENTAR_PPB_CODAM"),
    "DF": ("6/2025", "DF_IN_VERSOES_TARE"),
    "GO": ("24.441/2026", "GO_ADESAO_ESPECIFICA_24441"),
    "MT": ("1.802/2025", "MT_ART31A_EXTENSAO_ESTADUAL"),
    "PB": ("48.405/2026", "PB_FAIN_CRF_FGTS_2026"),
    "PE": ("61.000/2026", "PE_PRODEPE_EFD_CONFORMIDADE"),
    "PR": ("13.467/2026", "PR_7721_ART12_SUPERVENIENTE"),
    "SC": ("008/2026", "SC_PROEMPREGO_CUMULACAO"),
}


def _rows(path: Path, key: str) -> dict:
    return {
        r["uf"]: r for r in json.loads(path.read_text(encoding="utf-8"))[key]
    }


@pytest.mark.parametrize("uf,act_and_gate", sorted(LATEST.items()))
def test_recent_act_and_negative_controls_are_recorded(uf, act_and_gate):
    act, gate = act_and_gate
    dossier = _rows(DOSSIER_FILE, "dossiers")[uf]
    record = dossier["supervening_2026_primary_examination"]
    cross = _rows(CROSS_FILE, "rows")[uf]
    assert act in record["act"]
    assert gate == record["gate"]
    assert record["official_url"].startswith("https://")
    assert record["article_or_change"]
    assert record["critical_negative"]
    assert record["government_source_byte_snapshot_sha256"] is None
    assert record["authoritative_doe_chain_archived"] is False
    assert record["independent_counter_review"] is False
    assert record["internal_acceptance"] is False
    assert cross["amendment_2026_checked"]["official_url"] == record["official_url"]
    assert cross["amendment_2026_checked"]["negative"] == record["critical_negative"]
    assert cross["amendment_2026_checked"]["competence_consistency_not_certified"]
    assert cross["internal_curation_accepted"] is False
    assert cross["autoriza_aplicacao_fiscal"] is False
    assert dossier["import_authorized"] is False


def test_pb_fgts_renewal_and_pe_efd_prodepe_are_not_dismissed():
    rows = _rows(DOSSIER_FILE, "dossiers")
    pb = rows["PB"]
    pe = rows["PE"]
    assert "FGTS" in pb["supervening_2026_primary_examination"]["article_or_change"]
    assert pb["supervening_2026_primary_examination"][
        "competence_change_start_reference"
    ] == "2026-07-04"
    assert "pb_fain_fgts_crf_renewal" in (
        pb["primary_provision_checkpoint_20261122"]["evidence"]
    )
    assert "art.21-A §10" in pe["primary_provision_checkpoint_20261122"]["finding"]
    assert "pe_efd_regular_delivery_art21a" in (
        pe["primary_provision_checkpoint_20261122"]["evidence"]
    )
    assert "percentual" in (
        pe["supervening_2026_primary_examination"]["article_or_change"]
    )


def test_pr_amendment_takes_effect_during_april_not_from_may():
    pr = _rows(DOSSIER_FILE, "dossiers")["PR"]
    check = pr["supervening_2026_primary_examination"]
    assert "13.467" in check["act"]
    assert check["competence_change_start_reference"] == "2026-04-27"
    assert "art.12" in check["article_or_change"]
    assert not check["authoritative_doe_chain_archived"]


@pytest.mark.parametrize("uf", sorted(LATEST))
def test_new_supervening_findings_never_promote_canonical_fiscal_rule(uf):
    draft = _rows(DRAFT_FILE, "candidates")[uf]
    queue = _rows(QUEUE_FILE, "work_items")[uf]
    assert draft["review_status"] == "draft"
    assert draft["import_authorized"] is False
    assert draft["eligibility_certified"] is False
    assert queue["internal_curatorial_accepted"] is False
    assert queue["legally_importable"] is False
    assert queue["eligible_for_fiscal_application"] is False


def test_ro_consolidated_government_law_does_not_auto_create_grant():
    ro = _rows(DOSSIER_FILE, "dossiers")["RO"]
    source = ro["official_compiled_text_chain_20261122"]
    assert "1.283/2025" in source["law"]
    assert "30.916/2025" in source["regulation"]
    assert "CONDER" in source["grant_condition"]
    assert source["original_doe_chain_archived"] is False
    assert source["full_2026_legality_consolidated"] is False
    assert source["approved"] is False
    assert ro["import_authorized"] is False


def test_rr_tax_code_2026_copy_is_not_benefit_extension_evidence():
    rr = _rows(DOSSIER_FILE, "dossiers")["RR"]
    source = rr["official_2026_compilation_locator"]
    assert "39.893" in source["normative_description"]
    assert source["source_sha256"] is None
    assert source["extension_2026_verified"] is False
    assert rr["internal_acceptance"] is False


def test_27_uf_matrix_has_one_real_row_per_state():
    raw = (DOCS / "NFCORE_T09_RESEARCH_RESIDUAL_27UFS_20261122.md").read_text(
        encoding="utf-8"
    )
    assert raw.splitlines()[0].endswith("(22/11/2026)")
    for uf in _rows(DOSSIER_FILE, "dossiers"):
        assert sum(line.startswith(f"| {uf} |") for line in raw.splitlines()) == 1
