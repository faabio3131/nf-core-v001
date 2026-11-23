"""Legal-source capture allowlist: exact official publishers, no wildcard."""
from __future__ import annotations

from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).resolve().parents[2]
check = run_path(str(ROOT / "scripts/nfcore_t09_capture_public_evidence.py"))
official_url = check["official_url"]


def test_narrow_legal_source_allowlist_for_stf_and_para_diario():
    assert official_url("https://portal.stf.jus.br/peticaoInicial/") is True
    assert official_url("https://www.ioepa.com.br/pages/2018/DOE.pdf") is True
    assert official_url("https://diofe.portal.ap.gov.br/portal/edicoes/") is True
    assert official_url("https://aleselegis.al.se.leg.br/") is True


def test_spoofed_publishers_must_remain_forbidden():
    for url in (
        "https://attacker.ioepa.com.br/pages/DOE.pdf",
        "https://ioepa.com.br.evil.invalid/pages/DOE.pdf",
        "https://fake.portal.stf.jus.br.evil.invalid/processo",
        "https://attacker.stf.jus.br/processo",
        "https://portal.stf.jus.br@evil.example/processo",
        "https://www.ioepa.com.br:444/pages/DOE.pdf",
        "http://www.ioepa.com.br/pages/DOE.pdf",
        "https://www.ioepa.com.br/pages/DOE.pdf#fragment",
    ):
        assert official_url(url) is False, url
