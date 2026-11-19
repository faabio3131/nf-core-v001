"""Engineering evidence gate, NOT an issuer/provider authorization source.

Prevent calling any MG-W1 municipality internally complete without a validated
municipal envelope, signature, transport, operations and Web CI on exact SHAs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kordena_fiscal.control_plane.mg_economic_priority_inventory import MG_ECONOMIC_WAVE_1

_LEDGER = (
    Path(__file__).resolve().parents[2]
    / "docs" / "coverage" / "NFCORE_MG_W1_MUNICIPAL_CELLS_2026-11-11.json"
)
_SHA_FIELDS = (
    "nfse_envelope_xml_signature_ci_sha",
    "nfse_http_transport_ci_sha",
    "nfse_application_web_ci_sha",
)
_FINISHED_OPERATIONS = {"INTERNAL_TESTED", "NOT_APPLICABLE_VERIFIED"}
_FINISHED_STATES = {"INTERNAL_COMPLETE", "EXTERNAL_HOMOLOGATED", "PRODUCTION_LIVE"}


def _load() -> dict:
    return json.loads(_LEDGER.read_text(encoding="utf-8"))


def _validate_completed_cell(cell: dict) -> None:
    """Completion requires evidence; public metadata alone never closes a city."""
    if cell["state"] not in _FINISHED_STATES:
        return
    if cell["nfse_emitter_evidence"] in ("UNVERIFIED", "NATIONAL_ANNOUNCED"):
        raise ValueError("Municipal issuer contract not verified")
    source = urlsplit(cell["municipal_source"] or "")
    if source.scheme != "https" or not source.hostname:
        raise ValueError("Missing official municipal source")
    if not cell["nfse_envelope_contract_version"]:
        raise ValueError("Missing municipal envelope contract version")
    digest = cell["nfse_envelope_xsd_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Missing hash-pinned municipal envelope XSD")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("Invalid envelope XSD hash") from exc
    for field in _SHA_FIELDS:
        sha = cell.get(field)
        if not isinstance(sha, str) or len(sha) != 40:
            raise ValueError(f"Missing CI proof for {field}")
        try:
            int(sha, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid CI proof for {field}") from exc
    if cell["nfe_mg55_state"] != "INTERNAL_COMPLETE":
        raise ValueError("State NF-e 55 is not complete")
    if cell["nfce_mg65_state"] != "INTERNAL_COMPLETE":
        raise ValueError("State NFC-e 65 is not complete")
    if any(
        state not in _FINISHED_OPERATIONS
        for state in cell["nfse_operations"].values()
    ):
        raise ValueError("NFS-e municipal operations are not certified")
    if cell["state"] in {"EXTERNAL_HOMOLOGATED", "PRODUCTION_LIVE"} and not (
        cell["nfse_issuer_a1_official_homologation"]
    ):
        raise ValueError("Missing exact official municipality/taxpayer proof")
    if cell["state"] == "PRODUCTION_LIVE" and not cell["production_approved"]:
        raise ValueError("No human-approved production activation")


def test_mg_wave1_ledger_has_one_cell_per_selected_municipality_in_order() -> None:
    doc = _load()
    assert doc["schema"] == "nfcore.mg_w1_coverage_cells.v1"
    assert doc["is_runtime_authority"] is False
    cells = doc["municipal_cells"]
    assert len(cells) == len(MG_ECONOMIC_WAVE_1) == 20
    assert [x["ibge"] for x in cells] == [x.municipality_ibge for x in MG_ECONOMIC_WAVE_1]
    assert [x["municipality"] for x in cells] == [x.municipality for x in MG_ECONOMIC_WAVE_1]
    assert [x["economic_priority"] for x in cells] == list(range(1, 21))
    assert len({x["ibge"] for x in cells}) == 20
    assert doc["latest_regulatory_review"]["gate_state"] == "INTERNAL_NOT_COMPLETE"
    assert doc["latest_regulatory_review"]["dps_numbering"] == (
        "HASH_PLACEHOLDER_NOT_SEQUENTIAL"
    )
    for cell in cells:
        expected_cutoff = doc["latest_regulatory_review"]["earlier_municipal_simples_cutovers"].get(
            cell["ibge"], "2026-11-01"
        )
        assert cell["simples_national_required_from_competence"] == expected_cutoff
        assert cell["nfse_current_restricted_schema_tested"] is False
        assert cell["nfse_numbering_sequential_authority"] is False
        assert cell["nfse_integration_web_e2e_certified"] is False
        assert cell["nfce_qr_version_contract_certified"] is False
        assert cell["nfce_mg65_state"] == "PREFLIGHT_IMPLEMENTED_NOT_CERTIFIED"
        assert cell["nfce_qr_generation_and_signature_certified"] is False
        assert cell["nfce_operations_lifecycle_certified"] is False
        assert cell["nfce_runtime_binding_enabled"] is False
        assert cell["national_issuer_guard_ci_sha"] is None


def test_municipal_envelopes_must_be_verified_individually() -> None:
    doc = _load()
    by_code = {item["ibge"]: item for item in doc["municipal_cells"]}
    assert by_code["3106200"]["nfse_emitter_evidence"] == "NATIONAL_DPS_JSON"
    assert by_code["3106705"]["nfse_emitter_evidence"] == "NATIONAL_DPS_JSON"
    assert by_code["3170206"]["nfse_emitter_evidence"] == "NATIONAL_ANNOUNCED"
    assert by_code["3118601"]["nfse_emitter_evidence"] == "MUNICIPAL_WITH_FEDERAL_SIMPLES_NATIONAL"
    assert sum(x["nfse_emitter_evidence"] == "UNVERIFIED" for x in by_code.values()) == 0
    assert doc["coverage_summary"]["municipal_official_source_mapped"] == 20
    for code in ("3170107", "3125101", "3127701", "3131703"):
        assert by_code[code]["state"] == "CHANNEL_RESEARCHED"
        assert by_code[code]["municipal_source"].startswith("https://")
        assert by_code[code]["nfse_envelope_contract_version"] is None
    assert doc["coverage_summary"]["municipal_contract_version_and_envelope_certified"] == 0
    assert doc["coverage_summary"]["external_homologated"] == 0
    assert doc["federal_national_simples_rule"]["effective_competence_from"] == "2026-11-01"
    assert doc["federal_national_simples_rule"]["national_channel_required"] is True
    assert by_code["3136702"]["nfse_emitter_evidence"] == "NATIONAL_EMITTER_MUNICIPAL_DEADLINE"
    assert by_code["3152501"]["nfse_emitter_evidence"] == "MUNICIPAL_UNTIL_2026_FOR_NON_SIMPLES"
    for cell in doc["municipal_cells"]:
        valid_states = {
            "CHANNEL_RESEARCHED", "RESEARCH_REQUIRED", "IMPLEMENTING",
        } | _FINISHED_STATES
        assert cell["state"] in valid_states
        if cell["state"] == "CHANNEL_RESEARCHED":
            source = urlsplit(cell["municipal_source"])
            assert source.scheme == "https"
            assert source.hostname
        _validate_completed_cell(cell)
        if cell["state"] not in _FINISHED_STATES:
            assert not cell["production_approved"]


@pytest.mark.parametrize(
    "missing",
    [
        "nfse_envelope_contract_version",
        "nfse_envelope_xsd_sha256",
        "nfse_envelope_xml_signature_ci_sha",
        "nfse_http_transport_ci_sha",
        "nfse_application_web_ci_sha",
    ],
)
def test_cannot_mark_research_city_complete_by_filling_one_checkbox(missing: str) -> None:
    cell = copy.deepcopy(_load()["municipal_cells"][0])
    cell["state"] = "INTERNAL_COMPLETE"
    cell[missing] = None
    with pytest.raises(ValueError):
        _validate_completed_cell(cell)


def test_no_external_certification_without_official_evidence() -> None:
    cell = copy.deepcopy(_load()["municipal_cells"][0])
    cell["state"] = "EXTERNAL_HOMOLOGATED"
    with pytest.raises(ValueError):
        _validate_completed_cell(cell)
