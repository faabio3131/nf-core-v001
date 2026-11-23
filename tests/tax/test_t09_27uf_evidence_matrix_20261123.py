"""Snapshot 27-UF research matrix must bind actual captured SHA sources."""
from __future__ import annotations

import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _json(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_27uf_matrix_matches_canonical_identity_and_capture_records():
    matrix = _json("NFCORE_T09_27UF_EVIDENCE_MATRIX_20261123.json")
    dossiers = _json("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")["dossiers"]
    queue = _json("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")[
        "work_items"
    ]
    assert matrix["internally_certified"] == 0
    assert matrix["import_authorized"] is False
    assert len(matrix["rows"]) == len(dossiers) == len(queue) == 27
    row_by_uf = {r["uf"]: r for r in matrix["rows"]}
    assert len(row_by_uf) == 27
    for doc, work in zip(dossiers, queue, strict=True):
        entry = row_by_uf[doc["uf"]]
        assert entry["candidate_id"] == doc["candidate_id"]
        assert entry["candidate_id"] == work["candidate_id"]
        known_sha = {
            x["sha256"] for x in doc.get(
                "latest_43_source_capture_receipt", {}
            ).get("official_bytes", [])
        }
        known_sha |= {
            x["sha256"] for x in doc.get(
                "retry_3_official_sources_20261122", {}
            ).get("official_source_sha256", [])
        }
        if doc["uf"] == "SE":
            known_sha.add(doc[
                "official_alese_compilation_user_html_20261123"
            ]["uploaded_sha256"])
        if doc["uf"] == "SE":
            known_sha.add(
                doc["decree_29935_2014_archived_20261123"][
                    "local_evidence_sha256"
                ]
            )
        if work.get("source_publication_and_original_bytes_digest"):
            known_sha.add(work["source_publication_and_original_bytes_digest"])
        registered = {
            item["sha256"] for item in entry["official_source_sha256_records"]
        }
        assert registered == known_sha
        assert all(re.fullmatch(r"[a-f0-9]{64}", x) for x in registered)
        assert entry["original_doe_edition_and_completeness_verified"] is False
        assert entry["internally_curated"] is False
        assert entry["fiscally_importable"] is False
        assert entry["fiscal_calculation_allowed"] is False
        assert entry["modal_specific_confaz"]["specific_modality_proven"] is False
        assert entry["positive_negative_tests"][
            "legal_2026_current_act_verified_for_all_cases"
        ] is False
        assert doc["internal_acceptance"] is False
        assert work["internal_curatorial_accepted"] is False


def test_critical_state_specific_noncertification_is_preserved():
    matrix = _json("NFCORE_T09_27UF_EVIDENCE_MATRIX_20261123.json")
    ufs = {x["uf"]: x for x in matrix["rows"]}
    assert ufs["AP"]["status_real"] == (
        "BLOCKED_MATERIAL_CANDIDATE_RESELECTION"
    )
    assert ufs["PA"]["status_real"] == "BLOCKED_CONSTITUTIONAL_ROUTE"
    assert ufs["RR"]["status_real"] == "BLOCKED_VALIDITY_EXTENSION"
    assert ufs["SE"]["status_real"] == "BLOCKED_MODAL_CONFAZ_AND_DOE_AMENDMENT"
    assert ufs["SE"]["modal_specific_confaz"]["act"] == "SE/CONFAZ nº 126/2024"
    assert ufs["SE"]["modal_specific_confaz"][
        "specific_modality_proven"
    ] is False
