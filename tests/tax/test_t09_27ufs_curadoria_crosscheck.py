"""T09 traceability of 27 independent normative hypotheses and captured evidence.

These tests deliberately cannot approve an ICMS policy; they validate the
research index and the negative controls that reviewers must inspect.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
CROSSCHECK = DOCS / "NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json"
DRAFTS = DOCS / "NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json"
QUEUE = DOCS / "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json"
CAPTURES = DOCS / "NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json"
UF_CODES = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_crosscheck(cross: dict, draft: dict, queue: dict, captures: dict) -> None:
    assert cross["schema_version"] == "nfcore.t09.research-crosscheck-27ufs/v1"
    assert cross["internal_curation_complete"] is False
    assert cross["import_authorized"] is False
    assert cross["reviewed_rules"] == 0
    assert cross["no_fiscal_decision_from_this_file"] is True
    assert cross["archive_not_in_git"] is True
    assert re.fullmatch(r"[a-f0-9]{64}", cross["archive_sha256"]) is not None

    rows = cross["rows"]
    assert isinstance(rows, list) and len(rows) == 27
    assert {r["uf"] for r in rows} == UF_CODES
    assert len({r["candidate_id"] for r in rows}) == 27
    canonical = {r["uf"]: r["candidate_id"] for r in draft["candidates"]}
    waiting = {r["uf"]: r["candidate_id"] for r in queue["work_items"]}
    assert {r["uf"]: r["candidate_id"] for r in rows} == canonical == waiting

    source_files = {(f["uf"], f["nome"]): f for f in captures["files"]}
    assert len(source_files) == len(captures["files"]) == 50
    counted = Counter()
    for r in rows:
        uf = r["uf"]
        assert isinstance(r["constatacao_de_pesquisa"], str)
        assert len(r["constatacao_de_pesquisa"]) > 60
        assert isinstance(r["cenario_negativo_obrigatorio"], str)
        assert len(r["cenario_negativo_obrigatorio"]) > 40
        assert r["source_of_primary_review"].startswith("https://")
        assert r["independent_adversarial_review"] is False
        assert r["internal_curation_accepted"] is False
        assert r["autoriza_aplicacao_fiscal"] is False
        assert draft["import_authorized"] is False

        for capture in r["original_captures_in_50_lot"]:
            key = (uf, capture["file"])
            assert key in source_files
            assert capture["sha256"] == source_files[key]["sha256"]
            assert re.fullmatch(r"[a-f0-9]{64}", capture["sha256"]) is not None
            # Hash of a collected file is not certification of the publisher.
            assert capture["publisher_original_authenticated"] is False
            counted[key] += 1

    assert len(counted) == 50
    assert all(n == 1 for n in counted.values())


def test_t09_documentary_crosscheck_covers_all_27_without_approving_anything():
    _validate_crosscheck(_read(CROSSCHECK), _read(DRAFTS), _read(QUEUE), _read(CAPTURES))


@pytest.mark.parametrize("uf,signal", [
    ("PA", "ADI 3779"),
    ("MS", "ADI 3794"),
    ("RR", "2025"),
    ("SP", "31/12/2026"),
    ("PB", "47.898/2026"),
    ("PE", "61.000/2026"),
    ("GO", "24.441/2026"),
    ("RS", "CLXXXVI"),
    ("AP", "MATERIAL"),
])
def test_t09_specific_adverse_evidence_is_not_lost(uf: str, signal: str):
    row = next(r for r in _read(CROSSCHECK)["rows"] if r["uf"] == uf)
    assert signal.lower() in (
        row["constatacao_de_pesquisa"] + " " + row["cenario_negativo_obrigatorio"]
        + " " + row["dispositivo_ou_risco_especifico"]
    ).lower()


def test_t09_false_archive_identity_is_rejected_in_reconciliation():
    cross = _read(CROSSCHECK)
    cross["rows"][0]["original_captures_in_50_lot"][0]["sha256"] = "f" * 64
    with pytest.raises(AssertionError):
        _validate_crosscheck(cross, _read(DRAFTS), _read(QUEUE), _read(CAPTURES))


def test_t09_captured_sources_cannot_claim_publisher_authenticity_by_flag():
    cross = _read(CROSSCHECK)
    cross["rows"][0]["original_captures_in_50_lot"][0][
        "publisher_original_authenticated"
    ] = True
    with pytest.raises(AssertionError):
        _validate_crosscheck(cross, _read(DRAFTS), _read(QUEUE), _read(CAPTURES))


def test_t09_cannot_erase_a_jurisdiction_or_promote_by_changing_a_flag():
    cross = _read(CROSSCHECK)
    cross["rows"].pop()
    with pytest.raises(AssertionError):
        _validate_crosscheck(cross, _read(DRAFTS), _read(QUEUE), _read(CAPTURES))
    cross = _read(CROSSCHECK)
    cross["rows"][0]["internal_curation_accepted"] = True
    with pytest.raises(AssertionError):
        _validate_crosscheck(cross, _read(DRAFTS), _read(QUEUE), _read(CAPTURES))
