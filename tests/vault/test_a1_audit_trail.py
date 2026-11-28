"""A1 operations leave a durable, chained, secret-free audit trail; fail closed."""
from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pytest

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.vault.a1_audit import (
    AUDIT_FILENAME,
    A1AuditUnavailable,
    verify_a1_audit_chain,
)
from kordena_fiscal.vault.encrypted_a1 import A1VaultUnavailable, EncryptedA1Vault

_UPLOAD_TESTS = Path(__file__).resolve().parents[1] / "web/test_portal_a1_upload_errors.py"
_helpers = run_path(str(_UPLOAD_TESTS))
_pfx, _CNPJ, _PASSWORD = _helpers["_pfx"], _helpers["_CNPJ"], _helpers["_PASSWORD"]
SCOPE = ExecutionScope("tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION, "c", "fm-nfcore")


def _events(directory: Path) -> list[dict]:
    return [json.loads(x) for x in (directory / AUDIT_FILENAME).read_text().splitlines()]


def test_full_lifecycle_is_audited_once_per_public_call(tmp_path) -> None:
    vault = EncryptedA1Vault(directory=tmp_path, master_key=b"k" * 32)
    vault.provision(scope=SCOPE, issuer_cnpj=_CNPJ, pkcs12_bytes=_pfx(),
                    password=_PASSWORD, actor="acct-1")
    assert vault.inspect(scope=SCOPE, issuer_cnpj=_CNPJ) is not None
    vault.resolve(scope=SCOPE, issuer_cnpj=_CNPJ)
    vault.withdraw(scope=SCOPE, issuer_cnpj=_CNPJ, actor="acct-1")
    with pytest.raises(A1VaultUnavailable):
        vault.resolve(scope=SCOPE, issuer_cnpj=_CNPJ)
    events = _events(tmp_path)
    assert [(e["event"], e["outcome"]) for e in events] == [
        ("provision", "ok"), ("inspect", "ok"), ("resolve", "ok"),
        ("withdraw", "ok"), ("resolve", "failed"),
    ]
    assert events[-1]["error"] == "A1VaultUnavailable"
    fingerprints = {e.get("fingerprint_sha256") for e in events[:3]}
    assert len(fingerprints) == 1 and None not in fingerprints
    assert all(e["tenant_id"] == "tenant-a" and e["unit_id"] == "unit-a" for e in events)
    assert verify_a1_audit_chain(tmp_path / AUDIT_FILENAME) == 5
    raw = (tmp_path / AUDIT_FILENAME).read_bytes()
    assert _PASSWORD not in raw and b"pfx" not in raw


def test_edited_or_removed_line_breaks_the_chain(tmp_path) -> None:
    vault = EncryptedA1Vault(directory=tmp_path, master_key=b"k" * 32)
    for _ in range(3):
        with pytest.raises(A1VaultUnavailable):
            vault.resolve(scope=SCOPE, issuer_cnpj=_CNPJ)
    trail = tmp_path / AUDIT_FILENAME
    lines = trail.read_text().splitlines()
    trail.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(A1AuditUnavailable, match="broken"):
        verify_a1_audit_chain(trail)
    edited = lines[1].replace('"failed"', '"ok"')
    trail.write_text("\n".join([lines[0], edited, lines[2]]) + "\n")
    with pytest.raises(A1AuditUnavailable, match="broken"):
        verify_a1_audit_chain(trail)


def test_unwritable_audit_trail_fails_the_operation_closed(tmp_path) -> None:
    vault = EncryptedA1Vault(directory=tmp_path, master_key=b"k" * 32)
    (tmp_path / AUDIT_FILENAME).symlink_to(tmp_path / "elsewhere.jsonl")
    with pytest.raises(A1AuditUnavailable):
        vault.provision(scope=SCOPE, issuer_cnpj=_CNPJ, pkcs12_bytes=_pfx(),
                        password=_PASSWORD)
    assert not (tmp_path / "elsewhere.jsonl").exists()
    # Nothing was stored without an audit record.
    assert not list(tmp_path.glob("*.a1.enc"))


def test_audit_file_is_private(tmp_path) -> None:
    vault = EncryptedA1Vault(directory=tmp_path, master_key=b"k" * 32)
    with pytest.raises(A1VaultUnavailable):
        vault.resolve(scope=SCOPE, issuer_cnpj=_CNPJ)
    assert (tmp_path / AUDIT_FILENAME).stat().st_mode & 0o077 == 0


def _ops(monkeypatch, vault_dir: Path):
    import importlib.util
    import os

    script = Path(__file__).resolve().parents[2] / "deploy/contabo/a1-vault-ops.py"
    spec = importlib.util.spec_from_file_location("a1_ops_audit", script)
    assert spec is not None and spec.loader is not None
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    monkeypatch.setenv("NFCORE_A1_VAULT_HOST_DIR", str(vault_dir))
    monkeypatch.setattr(ops, "_VAULT_UID", os.getuid())
    return ops


def test_backup_tooling_accepts_only_the_audit_trail_besides_records(
    tmp_path, monkeypatch,
) -> None:
    vault_dir = tmp_path / "vault"
    vault = EncryptedA1Vault(directory=vault_dir, master_key=b"k" * 32)
    vault.provision(scope=SCOPE, issuer_cnpj=_CNPJ, pkcs12_bytes=_pfx(), password=_PASSWORD)
    ops = _ops(monkeypatch, vault_dir)
    _, records = ops._vault_records()
    assert len(records) == 1 and AUDIT_FILENAME not in records
    stray = vault_dir / "notes.txt"
    stray.write_text("x")
    stray.chmod(0o600)
    with pytest.raises(ops.VaultOpsError):
        ops._vault_records()
    stray.unlink()
    (vault_dir / AUDIT_FILENAME).unlink()
    (vault_dir / AUDIT_FILENAME).symlink_to(vault_dir / "elsewhere")
    with pytest.raises(ops.VaultOpsError):
        ops._vault_records()
