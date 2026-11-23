"""Official ALESE 2026 consolidated law received, but not a 1991 DOE issue."""
from __future__ import annotations

import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
SHA = "520b1a1f93b9a1c6c8ec5d315d5d885ec436df4236f7c46dfbdc9a21b9c080a5"


def _se(name: str, section: str) -> dict:
    data = json.loads((DOCS / name).read_text(encoding="utf-8"))
    return next(r for r in data[section] if r["uf"] == "SE")


def test_se_official_legislative_2026_snapshot_not_misidentified_as_doe():
    se = _se("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")
    a = se["official_alese_compilation_user_html_20261123"]
    assert re.fullmatch(r"[a-f0-9]{64}", SHA)
    assert a["uploaded_sha256"] == SHA
    assert a["uploaded_bytes"] == 223828
    assert a["document_type"] == (
        "OFFICIAL_STATE_LEGISLATIVE_COMPILATION_HTML_NOT_ORIGINAL_DOE_ISSUE"
    )
    assert a["original_doe_statement"].startswith("Este texto não substitui")
    assert a["explicitly_contains_amendments_until"] == "2026-04-01"
    assert a["archived_original_gazette_issue_verified"] is False
    assert a["full_2026_normative_amendment_chain_verified"] is False
    assert a["confaz_route_verified"] is False
    assert a["independent_counter_review_passed"] is False
    assert a["fiscal_application_authorized"] is False
    assert se["internal_acceptance"] is False


def test_se_amendments_are_material_and_temporal_not_generic_tax_rates():
    a = _se("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json", "dossiers")[
        "official_alese_compilation_user_html_20261123"
    ]
    clauses = {r["provision"]: r for r in a["sections_examined"]}
    assert "DESENVOLVE-SE" in clauses["art. 1º §§1º-3º"]["finding"]
    assert "Lei 9.943/2026" == clauses["art. 8º II,V,VI"]["latest_2026_act"]
    assert "§31" in clauses["art. 3º IV d e §31"]["provision"]
    assert "§5º-B" in clauses["art. 3º §5º-B"]["provision"]
    assert "DESENQUADRADA" in clauses["art. 4º §3º"]["finding"]
    assert "concomitantemente" in clauses["art. 3º §17"]["finding"]
    assert any("riscadas" in x for x in a["negative_cases"])
    assert any("CONFAZ" in x for x in a["negative_cases"])


def test_se_current_archival_evidence_never_grants_tax_permission():
    q = _se("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json", "work_items")
    c = _se("NFCORE_T09_CURADORIA_27UFS_CROSSCHECK_20261122.json", "rows")
    record = q["research_checkpoint_20261122"][
        "official_alese_compilation_user_html_20261123"
    ]
    assert record["uploaded_sha256"] == SHA
    assert record["compilation_includes_2026"] is True
    assert record["original_gazette_issue"] is False
    assert record["all_amendments_reconciled"] is False
    assert record["external_owner_document_required"] is False
    assert c["official_alese_compilation_user_html_20261123"][
        "official_doe_original_confirmed"
    ] is False
    assert q["internal_curatorial_accepted"] is False
    assert q["legally_importable"] is False
    assert q["eligible_for_fiscal_application"] is False
