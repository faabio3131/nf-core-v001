"""One-shot legal intake closure cannot certify from missing government files."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.tax.t09_priority_state_guards import (
    assess_priority_state_context,
)

ROOT = Path(__file__).resolve().parents[2] / "docs"
PATH = ROOT / "NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json"


def test_all_four_are_fiscally_blocked_without_false_certification():
    j = json.loads(PATH.read_text(encoding="utf-8"))
    assert j["technical_decision_final_for_this_evidence"] == (
        "DENY_BENEFIT_ALL_FOUR"
    )
    assert (j["certified_positive"], j["certified_negative"]) == (0, 0)
    assert j["not_certified"] == 4
    assert j["independent_contradictory_review_received"] is False
    assert {x["uf"] for x in j["cases"]} == {"SE", "AP", "PA", "RR"}
    for x in j["cases"]:
        assert x["decision_effect"] == (
            "BLOCK_ICMS_BENEFIT_CALCULATION_AND_FISCAL_IMPORT"
        )
        assert x["internal_curatorial_accepted"] is False
        assert x["legal_certification_awarded"] is False
        assert x["production_enabled"] is False
        assert x["no_further_proactive_capture_retries"] is True
        assert x["why_not_certifiable"]


@pytest.mark.parametrize("uf", ["SE", "AP", "PA", "RR"])
def test_master_queue_and_dossier_all_hold_fiscal_block(uf):
    dossier = json.loads(
        (ROOT / "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json").read_text(
            encoding="utf-8"
        )
    )
    master = json.loads(
        (ROOT / "NFCORE_T09_27UF_EVIDENCE_MATRIX_20261123.json").read_text(
            encoding="utf-8"
        )
    )
    queue = json.loads(
        (
            ROOT / "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json"
        ).read_text(encoding="utf-8")
    )
    d = next(x for x in dossier["dossiers"] if x["uf"] == uf)
    m = next(x for x in master["rows"] if x["uf"] == uf)
    q = next(x for x in queue["work_items"] if x["uf"] == uf)
    assert d["terminal_operational_decision_20261123"]["fiscal_blocked"] is True
    assert m["terminal_operational_decision_20261123"]["fiscal_blocked"] is True
    assert q["research_checkpoint_20261122"][
        "terminal_operational_decision_20261123"
    ]["fiscal_blocked"] is True
    assert d["internal_acceptance"] is False
    assert q["internal_curatorial_accepted"] is False
    assert m["fiscally_importable"] is False


@pytest.mark.parametrize("uf,program,reason", [
    ("PA", "PA_6913_ADI3779",
     "pa_adi3779_original_law_invalid_successor_not_certified"),
    ("RR", "RR_LXVII_AGRO",
     "rr_lxvii_2026_specific_state_extension_not_proven"),
])
def test_judicial_and_state_deadline_2026_remain_blocked(uf, program, reason):
    decision = assess_priority_state_context(program, {}, date(2026, 11, 1))
    assert decision["status"] == "insufficient_basis"
    assert decision["reason_codes"] == [reason]
    assert decision["tax_calculation_authorized"] is False
    assert decision["approved_cents"] is None


def test_ap_2026_3490_is_not_proof_of_expiry_or_fish_extension():
    j = json.loads(PATH.read_text(encoding="utf-8"))
    ap = next(x for x in j["cases"] if x["uf"] == "AP")
    assert ap["assessment"] == (
        "FISH_DEFERRAL_IDENTIFIED_BUT_2026_EFFECT_NOT_PROVEN"
    )
    assert any("3.490" in x["doc"] for x in ap["material_evidence"])
    assert ap["legal_negative_certifiable"] is False


def test_se_2018_normative_reinstitution_rules_out_generic_absence_claim():
    j = json.loads(PATH.read_text(encoding="utf-8"))
    se = next(x for x in j["cases"] if x["uf"] == "SE")
    assert se["assessment"] == (
        "BASE_REINSTITUTION_IDENTIFIED_MODAL_PROOF_INCOMPLETE"
    )
    assert any("8.490" in x["doc"] for x in se["material_evidence"])
    assert se["legal_negative_certifiable"] is False
