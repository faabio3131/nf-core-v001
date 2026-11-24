"""T09: official legal crosschecks are research, never tax eligibility."""
import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
CHECKED = {"AC", "PB", "MS", "TO", "PR"}


def _dossiers():
    data = json.loads(
        (DOCS / "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json").read_text(
            encoding="utf-8"
        )
    )
    return {row["uf"]: row for row in data["dossiers"]}


@pytest.mark.parametrize("uf", sorted(CHECKED))
def test_official_2026_followup_does_not_promote_fiscal_benefit(uf):
    dossiers = _dossiers()
    assert len(dossiers) == 27
    row = dossiers[uf]
    proof = row["official_crosscheck_late_2026"]
    assert proof["uf"] == uf
    assert proof["url"].startswith("https://")
    assert proof["related_url"].startswith("https://")
    assert proof["material"] and proof["caution"]
    assert proof["conditions"]
    assert proof["legal_chain_complete"] is False
    assert proof["source_original_archived_verified"] is False
    assert proof["not_a_fiscal_policy"] is True
    assert proof["internal_acceptance"] is False
    assert row["internal_acceptance"] is False
    assert row["import_authorized"] is False


def test_pb_fgts_condition_is_for_grant_or_renewal_not_every_invoice():
    pb = _dossiers()["PB"]["official_crosscheck_late_2026"]
    assert "48.405/2026" in pb["act"]
    assert "CRF/FGTS" in pb["material"]
    assert "pedido/renovação" in pb["additional"]
    assert pb["legal_chain_complete"] is False


def test_ms_constitutional_history_never_becomes_universal_concession():
    ms = _dossiers()["MS"]["official_crosscheck_late_2026"]
    assert "ADI 3794" in ms["act"]
    assert "art.24-F" in ms["caution"]
    assert "ms_adi3794_constitutionality_chain" in ms["conditions"]


def test_ac_difal_regime_is_not_an_automatic_state_tax_credit():
    ac = _dossiers()["AC"]["official_crosscheck_late_2026"]
    assert "DIFAL" in ac["material"]
    assert "não criam automaticamente" in ac["material"]


def test_pr_credit_transfer_rule_not_a_ncm_eligibility_allowlist():
    pr = _dossiers()["PR"]["official_crosscheck_late_2026"]
    assert "227/2026" in pr["act"]
    assert "lista de NCM" in pr["material"]


def test_to_reinstitution_not_an_individual_grant():
    to = _dossiers()["TO"]["official_crosscheck_late_2026"]
    assert "3.577/2019" in to["act"]
    assert "carta-consulta" in to["material"]
    assert to["internal_acceptance"] is False


def test_official_followups_remain_a_strict_subset_of_27_drafts():
    data = _dossiers()
    actual = {uf for uf, row in data.items() if "official_crosscheck_late_2026" in row}
    assert actual == CHECKED
    assert all(not item["import_authorized"] for item in data.values())
