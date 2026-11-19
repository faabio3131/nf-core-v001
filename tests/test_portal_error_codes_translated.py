"""Every error code the Portal API can return has a Portuguese message in app.js.

A missing entry made the browser show raw "Falha HTTP 400" to the accountant.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "src/kordena_fiscal/web/portal_api.py",
    "src/kordena_fiscal/web/portal_runtime.py",
    "src/kordena_fiscal/web/native_nfse_preparation.py",
)
_CODE = re.compile(
    r'"code":\s*"([A-Z][A-Z0-9_]{4,})"'
    r'|_error\(\d+,\s*"([A-Z][A-Z0-9_]{4,})"\)'
    r'|return "(A1_[A-Z0-9_]{4,})"'
)


def _emitted_codes() -> set[str]:
    codes: set[str] = set()
    for name in SOURCES:
        text = (ROOT / name).read_text(encoding="utf-8")
        codes.update(next(group for group in match if group) for match in _CODE.findall(text))
    return codes


def test_portal_error_codes_have_portuguese_messages() -> None:
    portal = (ROOT / "portal/app.js").read_text(encoding="utf-8")
    codes = _emitted_codes()
    assert {"NATIVE_NFSE_INVALID_FISCAL_FACTS", "A1_CNPJ_MISMATCH"} <= codes
    missing = sorted(code for code in codes if f"{code}:" not in portal)
    assert not missing, f"Portal API codes without app.js message: {missing}"
