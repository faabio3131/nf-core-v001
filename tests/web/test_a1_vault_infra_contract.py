"""N3 A1 infrastructure contract tests — synthetic ciphertext, no external services."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "contabo" / "a1-vault-ops.py"
_OVERLAY = _SCRIPT.with_name("compose.a1-vault.opt-in.yml")


def _module():
    spec = importlib.util.spec_from_file_location("a1_vault_ops", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure(tmp_path, monkeypatch):
    vault = tmp_path / "a1-vault"
    vault.mkdir(mode=0o700)
    vault.chmod(0o700)
    ciphertext = vault / ("a" * 64 + ".a1.enc")
    ciphertext.write_bytes(b"NFA1\x01" + b"synthetic-encrypted-only")
    ciphertext.chmod(0o600)
    pass_file = tmp_path / "restic-password"
    pass_file.write_text("CI-DUMMY-NOT-A-REAL-PASSWORD", encoding="utf-8")
    pass_file.chmod(0o600)
    monkeypatch.setenv("NFCORE_A1_VAULT_HOST_DIR", str(vault))
    monkeypatch.setenv("RESTIC_REPOSITORY", "sftp:backup@example.invalid:/nfcore-test")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", str(pass_file))
    mod = _module()
    monkeypatch.setattr(mod, "_VAULT_UID", os.getuid())
    return mod, vault, ciphertext, pass_file


def test_overlay_is_explicit_persistent_private_bind_with_no_implicit_host_creation():
    source = _OVERLAY.read_text(encoding="utf-8")
    assert "NFCORE_A1_VAULT_HOST_DIR:?" in source
    assert "create_host_path: false" in source
    assert "NFCORE_A1_VAULT_DIR: /var/lib/nfcore/vault" in source
    assert "Never add a different target mount" in source
    assert "read_only: false" in source
    assert "nfcore-api:" in source
    # Never silently modify the production compose or introduce another vault authority.
    canonical = _OVERLAY.with_name("compose.prod.yml").read_text(encoding="utf-8")
    assert "compose.a1-vault.opt-in.yml" not in canonical
    assert "source: /var/lib/nfcore/vault" in canonical
    assert "target: /var/lib/nfcore/vault" in canonical
    assert "create_host_path: false" in canonical


def test_offsite_backup_requires_remote_repository_private_password_and_private_vault(
    tmp_path, monkeypatch,
):
    mod, vault, ciphertext, pass_file = _configure(tmp_path, monkeypatch)
    invocations = []
    monkeypatch.setattr(mod, "_restic", lambda *args: invocations.append(args))
    assert mod.backup() == 0
    assert invocations == [
        ("backup", "--quiet", "--tag", "nfcore-a1-vault", str(vault)),
        ("check", "--quiet"),
    ]

    monkeypatch.setenv("RESTIC_REPOSITORY", str(tmp_path / "local-backup"))
    with pytest.raises(mod.VaultOpsError):
        mod.backup()
    monkeypatch.setenv("RESTIC_REPOSITORY", "sftp:backup@example.invalid:/nfcore-test")
    pass_file.chmod(0o644)
    with pytest.raises(mod.VaultOpsError):
        mod.backup()
    pass_file.chmod(0o600)
    ciphertext.chmod(0o644)
    with pytest.raises(mod.VaultOpsError):
        mod.backup()
    ciphertext.chmod(0o600)
    vault.chmod(0o755)
    with pytest.raises(mod.VaultOpsError):
        mod.backup()


def test_restore_rehearsal_matches_ciphertext_without_touching_live_vault(
    tmp_path, monkeypatch,
):
    mod, vault, ciphertext, _ = _configure(tmp_path, monkeypatch)
    original = ciphertext.read_bytes()

    def fake_restic(*args):
        assert args[:2] == ("restore", "latest")
        target = Path(args[args.index("--target") + 1])
        destination = target / vault.relative_to("/")
        destination.mkdir(parents=True)
        (destination / ciphertext.name).write_bytes(original)

    monkeypatch.setattr(mod, "_restic", fake_restic)
    assert mod.restore_rehearsal() == 0
    assert ciphertext.read_bytes() == original


def test_restore_rehearsal_detects_mismatch_and_symlinks(
    tmp_path, monkeypatch,
):
    mod, vault, ciphertext, _ = _configure(tmp_path, monkeypatch)

    def fake_corrupt(*args):
        target = Path(args[args.index("--target") + 1])
        destination = target / vault.relative_to("/")
        destination.mkdir(parents=True)
        (destination / ciphertext.name).write_bytes(b"bad-ciphertext")

    monkeypatch.setattr(mod, "_restic", fake_corrupt)
    with pytest.raises(mod.VaultOpsError):
        mod.restore_rehearsal()
    ciphertext.unlink()
    ciphertext.symlink_to(tmp_path / "other")
    with pytest.raises(mod.VaultOpsError):
        mod.backup()


def test_backup_refuses_unexpected_files_even_if_private(tmp_path, monkeypatch):
    mod, vault, _, _ = _configure(tmp_path, monkeypatch)
    (vault / "password.txt").write_text("unsafe", encoding="utf-8")
    with pytest.raises(mod.VaultOpsError):
        mod.backup()


def test_docker_compose_overlay_effective_mount_is_correct_and_requires_host_source(
    tmp_path, monkeypatch,
):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose executable unavailable")
    src = _OVERLAY.with_name("compose.prod.yml")
    base = tmp_path / "compose.prod.yml"
    overlay = tmp_path / "compose.a1-vault.opt-in.yml"
    base.write_bytes(src.read_bytes())
    overlay.write_bytes(_OVERLAY.read_bytes())
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=synthetic\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    host_vault = tmp_path / "vault"
    host_vault.mkdir(mode=0o700)
    env = {**os.environ, "POSTGRES_PASSWORD": "synthetic",
           "NFCORE_A1_VAULT_HOST_DIR": str(host_vault)}
    # The canonical production Compose must preserve the existing Contabo Vault
    # even WITHOUT the optional overlay. Do not create an alternative authority.
    base_result = subprocess.run(
        ["docker", "compose", "-f", str(base), "config", "--format", "json"],
        capture_output=True, text=True, env=env, check=False, timeout=30,
    )
    assert base_result.returncode == 0, "invalid canonical A1 production Compose"
    base_mounts = json.loads(base_result.stdout)["services"]["nfcore-api"]["volumes"]
    canonical_vault = [m for m in base_mounts if m["target"] == "/var/lib/nfcore/vault"]
    assert len(canonical_vault) == 1
    assert canonical_vault[0]["type"] == "bind"
    assert canonical_vault[0]["source"] == "/var/lib/nfcore/vault"
    assert canonical_vault[0].get("bind", {}).get("create_host_path", False) is False

    args = ["docker", "compose", "-f", str(base), "-f", str(overlay), "config"]
    result = subprocess.run(args + ["--format", "json"], capture_output=True,
                            text=True, env=env, check=False, timeout=30)
    assert result.returncode == 0, "invalid A1 Compose overlay"
    api = json.loads(result.stdout)["services"]["nfcore-api"]
    assert api["environment"]["NFCORE_A1_VAULT_DIR"] == "/var/lib/nfcore/vault"
    mounts = [v for v in api["volumes"] if v["target"] == "/var/lib/nfcore/vault"]
    assert len(mounts) == 1
    assert mounts[0]["type"] == "bind"
    assert mounts[0]["source"] == str(host_vault)
    # Compose may omit false booleans from normalized JSON; source assertion above
    # independently proves the explicit create_host_path: false contract.
    assert mounts[0].get("bind", {}).get("create_host_path", False) is False

    env.pop("NFCORE_A1_VAULT_HOST_DIR")
    invalid = subprocess.run(args + ["--quiet"], capture_output=True,
                             text=True, env=env, check=False, timeout=30)
    assert invalid.returncode != 0, "missing persistent host source accepted"


def test_a1_audit_requires_exact_deployed_production_sha_before_docker(
    tmp_path, monkeypatch, capsys,
):
    audit_script = _OVERLAY.with_name("audit-a1-vault-readonly.py")
    spec = importlib.util.spec_from_file_location("a1_host_preflight", audit_script)
    assert spec is not None and spec.loader is not None
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    marker = tmp_path / ".deployed"
    sha = "a" * 40
    marker.write_text(f"SHA={sha}\n", encoding="ascii")
    monkeypatch.setattr(audit, "_DEPLOY_MARKER", marker)
    assert audit._pinned_production_sha(sha) is True
    assert audit._pinned_production_sha("b" * 40) is False
    assert audit._pinned_production_sha(sha + ";id") is False
    marker.write_text("SHA=" + "b" * 40 + "\n", encoding="ascii")
    monkeypatch.setattr(
        audit, "_docker", lambda _: pytest.fail("Docker must not run for invalid release pin")
    )
    assert audit.main(sha) == 2
    assert capsys.readouterr().out == "DEPLOY_SHA_EXACT=BLOCKED\n"
