"""Jurisdictional legal proof prevents negative conclusions contradicted by 2026 law."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date

import pytest

from kordena_fiscal.tax.t09_priority_state_guards import assess_priority_state_context

D=Path(__file__).resolve().parents[2]/"docs"

def _read(filename: str)->dict:
    return json.loads((D/filename).read_text(encoding="utf-8"))

def test_current_prior_ci_success_and_all_four_fiscally_denied()->None:
    j=_read("NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json")
    p=j["additional_legal_cross_examination_20261123"]
    assert p["ci_prerequisite"]["head_sha"]=="161743ce577c3d7f99bc51441af53e66cdcd0721"
    assert p["ci_prerequisite"]["run_id"]==45256835394
    assert p["ci_prerequisite"]["conclusion"]=="success"
    assert p["fiscal_import_authorized"] is False
    assert p["full_four_state_positive_certified"]==0
    assert p["full_four_state_negative_certified"]==0
    assert {x["uf"] for x in j["cases"]}=={"SE","AP","PA","RR"}
    assert all(x["production_enabled"] is False and x["legal_certification_awarded"] is False for x in j["cases"])

def test_pa_standalone_legacy_negative_is_not_successor_negative()->None:
    j=_read("NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json")
    pa=next(x for x in j["cases"] if x["uf"]=="PA")
    narrow=pa["scoped_standalone_original_law_final"]
    assert narrow["decision"]=="NAO_APLICAVEL_CERTIFICADO"
    assert len(narrow["evidence_sha256"])==64
    assert narrow["underlying_successor_chain_certified"] is False
    verdict=assess_priority_state_context("PA_6913_ADI3779",{},date(2026,11,23))
    assert verdict["tax_calculation_authorized"] is False

def test_amapa_2026_fish_law_precludes_fictitious_global_expiry()->None:
    j=_read("NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json")
    ap=next(x for x in j["cases"] if x["uf"]=="AP")["2026_material_counterevidence"]
    assert ap["decree_2349_article27_fish_included"] is True
    assert ap["decree_2349_article29_deferral"] is True
    assert ap["decree_2656_article3_fish_included"] is True
    assert ap["decree_2656_article9_revokes_2349"] is True
    assert ap["proves_no_fish_incentive_in_2026"] is False
    assert ap["enable_fiscal"] is False
    r=assess_priority_state_context("AP_FISH_3599",{"claimed_3490_extension_for_fish":True},date(2026,11,23))
    assert r["tax_calculation_authorized"] is False

def test_rr_2021_expiry_cannot_automatically_certify_no_decree_2026()->None:
    j=_read("NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json")
    rr=next(x for x in j["cases"] if x["uf"]=="RR")["2026_lxvii_scoped_fiscal_denial"]
    assert rr["historical_expiry"]=="2025-12-31"
    assert rr["negative_nonexistence_certified"] is False
    assert rr["non_import_authorized"] is True
    r=assess_priority_state_context("RR_LXVII_AGRO",{"state_extension":True},date(2026,11,23))
    assert r["tax_calculation_authorized"] is False

def test_all_six_sergipe_modalities_remain_separate_no_authorization()->None:
    j=_read("NFCORE_T09_FOUR_STATE_TERMINAL_OPERATIONS_20261123.json")
    se=next(x for x in j["cases"] if x["uf"]=="SE")["2026_status_by_mode"]
    real=_read("NFCORE_T09_SE_PSDI_MODAL_MATRIX_20261123.json")["modes"]
    assert len(se["rows"])==len(real)==6
    assert {x["id"] for x in se["rows"]}=={x["id"] for x in real}
    assert all(x["certified"] is False and x["import_enabled"] is False for x in se["rows"])

def test_new_official_capture_direct_url_preserves_fail_closed()->None:
    w=_read("NFCORE_T09_PRIORITY_4UF_SOURCE_WORKSET_V1.json")
    assert w["authorized_for_import"] is False
    assert w["legal_validity_certified"] is False
    assert w["independent_approval_received"] is False
    assert any(x["source_url"]=="https://diofe.portal.ap.gov.br/portal/edicoes/download/9915" and x["eligible_for_tax_calculation"] is False for x in w["entries"])
    assert len({x["source_url"] for x in w["entries"]})==len(w["entries"])
