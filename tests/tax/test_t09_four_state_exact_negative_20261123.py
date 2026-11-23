"""Capture-grounded negative limits for AP, PA and RR."""
from __future__ import annotations

import json
from pathlib import Path

FILE = (
    Path(__file__).resolve().parents[2]
    / "docs/NFCORE_T09_SE_AP_PA_RR_CLOSEOUT_20261123.json"
)


def _state(uf: str) -> dict:
    doc = json.loads(FILE.read_text(encoding="utf-8"))
    return next(x for x in doc["case_studies"] if x["uf"] == uf)


def test_amapa_annex_2026_cannot_silently_extend_fish():
    a = _state("AP")["annex_3490_negative"]
    assert a["pages"] == 132
    assert a["source_integrity_verified"] is True
    assert a["annex_includes_decree_3599_2001"] is False
    assert a["automatic_fish_extension_from_this_law"] is False
    assert a["not_proof_fish_itself_expired"] is True


def test_pa_stf_captured_dispositive_not_confused_with_initial_petition():
    a = _state("PA")["adi3779_official_digest"]
    assert a["initial_petition_numbers"] == "6882–6885"
    assert a["final_dispositive_numbers"] == "6912–6915"
    assert a["majority_modulation_denied"] is True
    assert a["successor_8930_individual_legality_certified"] is False


def test_rr_source_unavailability_does_not_mean_2026_exemption():
    a = _state("RR")["lxvii_2026_unresolved"]
    assert a["2025_last_known_valid_day"] == "2025-12-31"
    assert a["2026_specific_extension_official_text_found"] is False
    assert a["2026_tax_benefit_permitted"] is False
