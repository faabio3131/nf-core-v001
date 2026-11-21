"""T09 Windows hash-only package must not turn local documents into tax rules."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KIT = run_path(str(ROOT / "scripts/obter_e_hashear_fontes.py"))
build_manifest = KIT["build_manifest"]


def _queue():
    return json.loads(
        (ROOT / "docs/NFCORE_T09_WINDOWS_LOCAL_SOURCE_QUEUE_V1.json")
        .read_text(encoding="utf-8"),
    )


def test_queue_keeps_two_lots_with_at_least_eight_states():
    queue = _queue()
    assert {x["uf"] for x in queue["entries"]} == {
        "AC", "AL", "AP", "PA", "PI", "RJ", "RN", "SE",
    }
    assert {x["lot"] for x in queue["entries"]} == {"A", "B"}
    assert all(x["source_url_review_status"] for x in queue["entries"])
    assert all(x["required_for_internal_reconciliation"] for x in queue["entries"])
    assert not any("140_2025" in x["filename"] for x in queue["entries"])
    assert not any("Noticia" in x["filename"] for x in queue["entries"])


def test_empty_local_kit_has_no_fake_hash_or_approval(tmp_path):
    data = build_manifest(_queue(), tmp_path)
    assert data["hashed_count"] == 0
    assert data["missing_count"] == len(_queue()["entries"])
    assert data["rejected_count"] == 0
    assert data["source_origin_authenticated"] is False
    assert data["import_authorized"] is False
    assert data["approved_for_tax"] is False
    assert all(x["status"] == "missing" for x in data["sources"])


def test_real_sha256_is_computed_only_from_valid_local_bytes(tmp_path):
    q = _queue()
    entry = next(x for x in q["entries"] if x["filename"].endswith(".html"))
    selected = {**q, "entries": [entry]}
    source = tmp_path / entry["filename"]
    source.write_bytes(
        b"<!doctype html><html><body>"
        + b"Lei vigente para teste isolado de integridade. " * 18
        + b"</body></html>"
    )
    data = build_manifest(selected, tmp_path)
    row = data["sources"][0]
    assert row["status"] == "bytes_hashed_unreviewed"
    assert row["sha256_real"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert row["user_source_attribution_not_independently_verified"] is True
    assert row["source_matches_normative_act_verified"] is False
    assert row["import_authorized"] is False


@pytest.mark.parametrize("body", [
    b"<!doctype html><html><body>403 Forbidden</body></html>",
    b"<html><body>Site em manutencao</body></html>",
    b"%PDF-1.7 incomplete pdf",
])
def test_hash_local_rejects_error_pages_and_truncated_pdfs(tmp_path, body):
    q = _queue()
    name = "AC_Lei_1358_2000.html" if body.startswith(b"<") else (
        "PA_Decreto_2490_2006.pdf"
    )
    entry = next(x for x in q["entries"] if x["filename"] == name)
    (tmp_path / name).write_bytes(body)
    result = build_manifest({**q, "entries": [entry]}, tmp_path)["sources"][0]
    assert result["status"] == "rejected"
    assert "sha256_real" not in result


def test_hash_local_rejects_symlink(tmp_path):
    q = _queue()
    entry = q["entries"][0]
    external = tmp_path.parent / "other-legislation.html"
    external.write_text("<html></html>", encoding="utf-8")
    (tmp_path / entry["filename"]).symlink_to(external)
    result = build_manifest({**q, "entries": [entry]}, tmp_path)["sources"][0]
    assert result["status"] == "rejected"
    assert "sha256_real" not in result


@pytest.mark.parametrize("mutation", [
    ("source_url", "https://gov.br.attacker.invalid/lei"),
    ("filename", "../AC_evil.html"),
    ("uf", "ZZ"),
])
def test_hash_local_rejects_untrusted_metadata(tmp_path, mutation):
    q = copy.deepcopy(_queue())
    q["entries"] = q["entries"][:1]
    q["entries"][0][mutation[0]] = mutation[1]
    with pytest.raises(ValueError, match="untrusted"):
        build_manifest(q, tmp_path)
