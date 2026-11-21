"""T09 primary-source capture is evidence collection, NOT tax authorization."""
from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

SCRIPT = run_path(
    str(Path(__file__).resolve().parents[2]
        / "scripts" / "nfcore_t09_capture_public_evidence.py"),
)
official_url = SCRIPT["official_url"]
inspect_bytes = SCRIPT["inspect_bytes"]
capture_one = SCRIPT["capture_one"]


@pytest.mark.parametrize(
    "url",
    [
        "http://legislacao.fazenda.sp.gov.br/Paginas/lei",
        "https://gov.br.evil.example/lei",
        "https://evil-leg.br/lei",
        "https://evilgov.br/lei",
        "https://user:password@gov.br/lei",
        "https://www.gov.br:8080/lei",
    ],
)
def test_capture_rejects_unofficial_address(url):
    assert not official_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://legislacao.fazenda.sp.gov.br/Paginas/lei",
        "https://www.al.to.leg.br/arquivo/65595",
        "https://gov.br/norma",
    ],
)
def test_capture_permits_official_domains(url):
    assert official_url(url)


@pytest.mark.parametrize(
    "page",
    [
        b"<html><body>Site em manutenÃ§Ã£o</body></html>",
        b"<html><body>403 Forbidden</body></html>",
        b"<html><body>Access denied</body></html>",
        b"<html><body>PÃ¡gina temporariamente indisponÃ­vel</body></html>",
        b"<html><body>Se vocÃª recebeu mensagem de bloqueio de IP</body></html>",
    ],
)
def test_capture_rejects_invalid_official_html(page):
    with pytest.raises(ValueError, match="HTML maintenance/access/error page"):
        inspect_bytes(page)


def test_capture_rejects_truncated_pdf():
    with pytest.raises(ValueError, match="incomplete PDF"):
        inspect_bytes(b"%PDF-1.7\n/Type /Catalog\n")


def test_valid_synthetic_html_is_only_a_capture_not_review(tmp_path, monkeypatch):
    body = (
        b"<!doctype html><html><body>"
        + b"Lei estadual de exemplo sem validade fiscal real. " * 15
        + b"</body></html>"
    )

    class FakeResponse:
        status = 200
        url = "https://www.legislacao.sp.gov.br/norma"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            assert size > len(body)
            return body

        @property
        def headers(self):
            return {"Content-Type": "text/html"}

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    monkeypatch.setattr(
        SCRIPT["urllib"].request, "build_opener", lambda *args: FakeOpener(),
    )
    row = {
        "uf": "SP",
        "candidate_id": "synthetic-sp-for-test",
        "state_official_source_url": "https://www.legislacao.sp.gov.br/norma",
    }
    result = capture_one(row, tmp_path, 3)
    assert result["status"] == "captured_unreviewed"
    assert result["approved_for_import"] is False
    assert result["legal_consolidation_verified"] is False
    assert result["taxpayer_concession_verified"] is False
    assert result["independent_fiscal_review"] is False
    evidence = tmp_path / result["relative_path"]
    assert evidence.read_bytes() == body
