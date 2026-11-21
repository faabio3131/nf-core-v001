"""Internal T09 review covers every state without claiming eligibility."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kordena_fiscal.tax.state_benefits import _UF_CODES

PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "NFCORE_T09_ICMS_ELIGIBILITY_SCREENING_27UFS_V1.json"
)


def inventory():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_state_eligibility_screening_covers_27_ufs_without_approval():
    data = inventory()
    assert data["schema_version"] == "nfcore.t09.icms-eligibility-screening/v1"
    assert data["import_authorized"] is False
    assert data["tax_calculation_authorized"] is False
    assert data["complete_normative_coverage"] is False
    assert data["independent_signoff"] is None
    assert len(data["states"]) == 27
    assert {row["uf"] for row in data["states"]} == set(_UF_CODES)
    assert all(row["ibge_uf_code"] == _UF_CODES[row["uf"]][1]
               for row in data["states"])


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_each_uf_has_specific_research_case_and_unmet_legal_gate(uf):
    item = next(x for x in inventory()["states"] if x["uf"] == uf)
    assert item["legal_anchor_to_verify"]
    assert item["case_study"]
    assert len(item["focus_checks"]) >= 3
    assert item["negative_test_scenario"]
    assert item["positive_case_status"] == "NOT_EXECUTED_REAL_LEGAL_CASE"
    assert item["negative_case_status"] == "NOT_EXECUTED_REAL_LEGAL_CASE"
    assert "parecer_contador_independente" in item["cross_cutting_review_gates"]
    assert item["source_sha256"] is None
    assert item["accountant_review"] is None
    assert item["eligible"] is False
    assert item["activation"] == "BLOCKED"
    source = urlsplit(item["source_url"])
    assert source.scheme == "https"
    assert source.hostname is not None
    assert source.hostname == "gov.br" or source.hostname.endswith(".gov.br")
    assert source.username is None and source.password is None


def test_revoked_ac_regime_and_sp_rs_pi_ma_never_claim_eligibility():
    data = {x["uf"]: x for x in inventory()["states"]}
    assert "REVOG" in data["AC"]["negative_test_scenario"].upper()
    assert "opção" in data["SP"]["focus_checks"][1]
    assert data["RS"]["eligibility_route"] == "individual_option"
    assert "Convênio ICMS 224/2017" in data["PI"]["focus_checks"][1]
    assert "CONDEP" in data["MA"]["focus_checks"][0]
    assert all(not x["legal_basis_approved"] for x in data.values())
