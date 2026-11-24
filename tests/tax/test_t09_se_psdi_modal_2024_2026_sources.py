"""SE documented legal modalities and original hash must stay fail-closed."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
DOC = "NFCORE_T09_SE_PSDI_MODAL_MATRIX_20261123.json"
PGE_SHA = "ca18358fccdfd93259819b1ab1d2fe7347b7084cde54d9660b3c8d0ffc67b3b8"


def _evidence() -> dict:
    return json.loads((DOCS / DOC).read_text(encoding="utf-8"))


def test_pge_decree_bytes_sha_and_2014_historical_scope():
    data = _evidence()
    d = data["decree_historic_pge"]
    assert re.fullmatch(r"[a-f0-9]{64}", d["local_evidence_sha256"])
    assert d["local_evidence_sha256"] == PGE_SHA
    assert d["bytes"] == 171106
    assert d["pages"] == 37
    assert d["byte_identity_with_live_official_url_verified"] is False
    assert d["legal_in_force_for_all_months_through_2026"] is False


def test_decrees_2024_temporal_conflicts_cannot_disappear():
    effects = _evidence()["legal_timeline"]
    assert effects["Decreto 820/2024"]["published"] == "2024-10-16"
    assert effects["Decreto 820/2024"]["stated_effective_from"] == (
        "2024-07-23"
    )
    assert effects["Decreto 820/2024"]["retroactive_effects"] is True
    assert effects["Decreto 868/2024"]["published"] == "2024-11-26"
    assert effects["Decreto 868/2024"]["retroactive_effects"] is False
    assert effects["Decreto 868/2024"]["primary_doe_edition_archived"] is False


@pytest.mark.parametrize("mode", [
    "SE_PSDI_NEW_INDUSTRY_8", "SE_PSDI_NEW_INDUSTRY_6_2",
    "SE_PSDI_DOMESTIC_RAW_DEFERRAL",
    "SE_PSDI_CAPITAL_GOODS_DEFERRAL",
    "SE_PSDI_IMPORTED_RAW_DEFERRAL",
    "SE_PSDI_EXISTING_INDUSTRY_GROWTH",
])
def test_no_modal_specific_confaz_route_is_implicitly_certified(mode):
    source = _evidence()
    row = next(x for x in source["modes"] if x["id"] == mode)
    assert row["norms"] and row["negative"] and row["positive"]
    assert row["not_nominal_icms_rate"] is True
    assert "PENDING" in row["confaz_modal_route"] or (
        "NOT_PROVEN" in row["confaz_modal_route"]
    )
    assert row["certified"] is False
    assert source["import_authorized"] is False


def test_confaz_certificate_is_not_individual_grant_or_legal_route():
    c = _evidence()["specific_confaz_evidence"]
    assert c["act"] == "Certificado SE/CONFAZ 126/2024"
    assert c["registered_deposit_number"] == "125/2024"
    assert c["modal_links_established"] == []
    assert c["sufficient_to_certify_specific_modalities"] is False
    assert _evidence()["legal_certified"] is False


def test_8_and_6_2_are_of_icms_due_not_nominal_rates():
    modes = {x["id"]: x for x in _evidence()["modes"]}
    assert modes["SE_PSDI_NEW_INDUSTRY_8"]["percentage_of_icms_due"] == "8"
    assert modes["SE_PSDI_NEW_INDUSTRY_6_2"]["percentage_of_icms_due"] == "6.2"
    assert modes["SE_PSDI_DOMESTIC_RAW_DEFERRAL"][
        "percentage_of_icms_due"
    ] is None


def test_law_8490_2018_reinstitutes_3140_but_not_all_psdi_modalities():
    record = _evidence()["specific_confaz_evidence"][
        "base_law_reinstitution_2018"
    ]
    assert record["act"].startswith("Lei estadual 8.490/2018")
    assert record["confaz_certificate"] == "SE/CONFAZ 13/2018"
    assert "Lei 3.140/1991" in record["legal_institution"]
    assert record["law_reinstitutes_benefits_existing_on"] == "2017-08-08"
    assert record["original_doe_bytes_archived"] is False
    assert record["cert_13_2018_original_obtained"] is False
    assert record["specific_rules_8_6_2_and_deferral_2024_verified"] is False
    assert _evidence()["import_authorized"] is False
