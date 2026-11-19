"""Regression: A1 upload extension filter must accept real .pfx/.p12 names."""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "portal" / "app.js"


def test_a1_extension_regex_is_not_double_escaped() -> None:
    source = _APP.read_text(encoding="utf-8")
    # `\\.` in a JS regex literal means "backslash + any char": no real file matches.
    assert r"/\\.(pfx|p12)$/i" not in source
    assert source.count(r"/\.(pfx|p12)$/i.test(chosen.name)") == 1
