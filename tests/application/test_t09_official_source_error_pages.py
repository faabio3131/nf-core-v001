"""T09 real-byte provenance must reject governmental maintenance/access pages.

A correct SHA-256 by itself proves integrity of bytes, not that those bytes
contain a normative act. These regressions protect real-world blocked portals.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from runpy import run_path

import pytest

_SCRIPT = run_path(
    str(Path(__file__).resolve().parents[2]
        / "scripts" / "nfcore_state_benefits_import_reviewed.py"),
)
verify_reviewed_source_bytes = _SCRIPT["verify_reviewed_source_bytes"]
SOURCE_MANIFEST_SCHEMA = _SCRIPT["SOURCE_MANIFEST_SCHEMA"]
URL = "https://portal.sefaz.example.gov.br/legislacao/lei-123"


def _packet(tmp_path: Path, raw: bytes) -> tuple[dict[str, object], Path]:
    (tmp_path / "fonte.html").write_bytes(raw)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "sources": [{"source_url": URL, "relative_path": "fonte.html"}],
    }), encoding="utf-8")
    return {
        "legal_citations": [{
            "source_url": URL,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        }],
    }, manifest


@pytest.mark.parametrize(
    "page",
    [
        "<!doctype html><html><body><h1>Site em manutenção</h1></body></html>",
        "<html><body>Manutenção em andamento — SEFAZ Alagoas</body></html>",
        "<html><body><h1>Site em manuten&ccedil;&atilde;o</h1></body></html>",
        "<html><body>Se você recebeu uma mensagem de bloqueio</body></html>",
        ("<html><body>Serviço de segurança bloqueia acessos provenientes "
         "desses endereços IP</body></html>"),
        "<html><body><h1>Página não encontrada</h1></body></html>",
    ],
)
def test_official_portal_error_html_is_not_legal_evidence(tmp_path, page):
    policy, manifest = _packet(tmp_path, page.encode("utf-8"))
    with pytest.raises(ValueError, match="HTML access/error page"):
        verify_reviewed_source_bytes(policy, manifest)


def test_normal_html_still_requires_exact_digest(tmp_path):
    page = (
        "<!doctype html><html><body>"
        "<h1>Decreto nº 123, de 2026</h1><p>Art. 1º</p>"
        "</body></html>"
    ).encode()
    policy, manifest = _packet(tmp_path, page)
    assert verify_reviewed_source_bytes(policy, manifest) == 1
    policy["legal_citations"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        verify_reviewed_source_bytes(policy, manifest)
