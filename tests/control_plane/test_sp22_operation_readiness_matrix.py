"""Prevent treating a 22-city routing catalog as 22 certified NFS-e emitters."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kordena_fiscal.gateway.municipal_sp_routing import SP_MUNICIPAL_CANDIDATES

_MATRIX = (
    Path(__file__).resolve().parents[2]
    / "docs" / "coverage" / "NFCORE_SP22_OPERATION_READINESS_2026-11-12.json"
)
_OPERATIONS = {
    "preparation", "authorization", "query", "cancel",
    "substitution", "recovery", "xml_pdf",
}
_DONE = {"INTERNAL_COMPLETE", "EXTERNAL_HOMOLOGATED", "PRODUCTION_LIVE"}


def _load() -> dict:
    return json.loads(_MATRIX.read_text(encoding="utf-8"))


def _validate_completion(cell: dict, state_wide: dict) -> None:
    """A document with a city name or a candidate provider is not evidence."""
    if cell["status"] not in _DONE:
        return
    official = urlsplit(cell.get("municipal_authoritative_url") or "")
    if (
        not cell["municipal_contract_verified"]
        or not cell["issuer_profile_specific_rules_verified"]
        or official.scheme != "https"
        or not official.hostname
        or not cell["municipal_layout_version"]
        or not cell["approved_transport_endpoint"]
        or not cell["signature_interoperability_verified"]
        or not cell["tenant_unit_binding_proven"]
    ):
        raise ValueError("Municipality lacks verified issuer/transport contract")
    digest = cell["municipal_xsd_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Municipality lacks official XSD digest")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("Municipality has invalid XSD digest") from exc
    ci_sha = cell["full_functional_e2e_ci_sha"]
    if not isinstance(ci_sha, str) or len(ci_sha) != 40:
        raise ValueError("Municipality lacks HEAD CI proof")
    if any(x != "INTERNAL_TESTED" for x in cell["nfse_operations"].values()):
        raise ValueError("Municipality lacks fiscal journey coverage")
    if (
        state_wide["nfe55"] != "INTERNAL_COMPLETE"
        or state_wide["nfce65"] != "INTERNAL_COMPLETE"
    ):
        raise ValueError("State-wide NF-e/NFC-e integration is not certified")
    if cell["status"] in {"EXTERNAL_HOMOLOGATED", "PRODUCTION_LIVE"} and not (
        cell["official_taxpayer_homologation"]
    ):
        raise ValueError("Municipality lacks official taxpayer A1 homologation")
    if cell["status"] == "PRODUCTION_LIVE" and not cell["production_authorization"]:
        raise ValueError("Municipality lacks explicit production approval")


def test_sp22_ledger_matches_only_the_canonical_candidate_catalog() -> None:
    matrix = _load()
    assert matrix["schema"] == "nfcore.sp22.coverage.v1"
    assert matrix["is_runtime_authority"] is False
    assert matrix["snapshot_main"].startswith("ef7ebe7e")
    cells = matrix["municipal_cells"]
    assert len(cells) == len(SP_MUNICIPAL_CANDIDATES) == 22
    assert len({row["ibge"] for row in cells}) == 22
    assert [row["ibge"] for row in cells] == list(SP_MUNICIPAL_CANDIDATES)
    for i, row in enumerate(cells):
        name, provider_labels = SP_MUNICIPAL_CANDIDATES[row["ibge"]]
        assert row["priority"] == i + 1
        assert row["municipality"] == name
        assert row["candidate_provider_labels"] == list(provider_labels)
        assert row["status"] in {"INTERNAL_INCOMPLETE", *_DONE}
        assert set(row["nfse_operations"]) == _OPERATIONS
        _validate_completion(row, matrix["state_wide"])


def test_city_cannot_be_certified_by_copying_catalog_labels() -> None:
    matrix = _load()
    for candidate in matrix["municipal_cells"]:
        fake = {**candidate, "status": "INTERNAL_COMPLETE"}
        with pytest.raises(ValueError, match="verified"):
            _validate_completion(fake, matrix["state_wide"])


def test_sp_federal_competence_and_legacy_boundary_are_explicit() -> None:
    matrix = _load()
    assert matrix["nfse_policy"]["me_epp_simples_competence_national_from"] == "2026-11-01"
    assert matrix["nfse_policy"]["capital_legacy_simples_issuance_from_date"] == (
        "BLOCKED_BY_COMPETENCE"
    )
    assert matrix["nfse_policy"]["retroactive_competence_before_date"] == (
        "REQUIRES_REVIEWED_MUNICIPAL_CONTRACT"
    )
    assert matrix["state_wide"]["inutilization_from"] == "2026-11-01"
    assert matrix["state_wide"]["inutilization"] == "PROHIBITED_BY_SEFAZ_SP"
