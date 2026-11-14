"""A1 root-owned Plan B preflight proof, independent of the Vault deployment."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "contabo"
    / "audit-a1-vault-readonly.py"
)

def _module():
    spec = importlib.util.spec_from_file_location("a1_host_preflight", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_invalid_production_pin_does_not_inspect_docker(tmp_path, monkeypatch, capsys):
    audit = _module()
    marker = tmp_path / ".deployed"
    correct_sha = "a" * 40
    marker.write_text(f"SHA={correct_sha}\n", encoding="ascii")
    monkeypatch.setattr(audit, "_DEPLOY_MARKER", marker)
    assert audit._pinned_production_sha(correct_sha)
    assert not audit._pinned_production_sha("b" * 40)
    assert not audit._pinned_production_sha(correct_sha + ";id")
    marker.write_text("SHA=" + "b" * 40 + "\n", encoding="ascii")

    def forbidden_docker(*_args):
        raise AssertionError("Docker inspection not allowed with wrong production SHA")

    monkeypatch.setattr(audit, "_docker", forbidden_docker)
    assert audit.main(correct_sha) == 2
    assert capsys.readouterr().out == "DEPLOY_SHA_EXACT=BLOCKED\n"

def test_missing_production_pin_fails_closed(tmp_path, monkeypatch):
    audit = _module()
    monkeypatch.setattr(audit, "_DEPLOY_MARKER", tmp_path / "missing-marker")
    assert audit.main("a" * 40) == 2
