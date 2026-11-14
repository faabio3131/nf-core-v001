"""Contract tests: production release is code-only and DDL needs separate N3."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _sandbox(tmp_path: Path) -> tuple[dict[str, str], Path]:
    ci = tmp_path / "scripts/ci"
    driver = tmp_path / "scripts/deploy/drivers"
    bin_path = tmp_path / "bin"
    for folder in (ci, driver, bin_path):
        folder.mkdir(parents=True, exist_ok=True)
    for name in ("run_production_promotion.sh", "production_preflight.sh"):
        shutil.copyfile(_ROOT / "scripts/ci" / name, ci / name)
    (ci / "production_smoke.sh").write_text(
        '#!/bin/sh\nexit "$SIMULATE_SMOKE_CODE"\n', encoding="utf-8"
    )
    (bin_path / "python").write_text(
        '#!/bin/sh\n'
        'printf "python:%s\\n" "$*" >> "$NFCORE_TEST_AUDIT"\n'
        'case "$*" in\n'
        '  *--apply*) exit 99 ;;\n'
        '  *--assert-current-production*) '
        '[ "$SIMULATE_SCHEMA_CURRENT" = true ] || exit 42 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    (driver / "mock.sh").write_text(
        '#!/bin/sh\n'
        'printf "driver:%s\\n" "$1" >> "$NFCORE_TEST_AUDIT"\n',
        encoding="utf-8",
    )
    (bin_path / "python").chmod(0o755)
    audit = tmp_path / "audit.log"
    env = {
        **os.environ,
        "PATH": str(bin_path) + os.pathsep + os.environ.get("PATH", ""),
        "NFCORE_TEST_AUDIT": str(audit),
        "DATABASE_URL": "postgresql://unused.invalid/nfcore_test",
        "SIMULATE_SMOKE_CODE": "0",
        "SIMULATE_SCHEMA_CURRENT": "true",
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "NFCORE_SECRET_BACKEND": "external",
        "NFCORE_REQUIRE_HTTPS": "true",
        "NFCORE_PRODUCTION_BASE_URL": "https://example.invalid",
        "NFCORE_PRODUCTION_DEPLOY_DRIVER": "scripts/deploy/drivers/mock.sh",
        "NFCORE_DEPLOY_REVISION": "a" * 40,
        "NFCORE_PRODUCTION_APPROVAL": "PRODUCTION_APPROVED",
    }
    return env, audit


def _run(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "scripts/ci/run_production_promotion.sh"],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )


def test_production_promotion_is_code_only(tmp_path: Path) -> None:
    env, audit = _sandbox(tmp_path)
    result = _run(tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    log = audit.read_text(encoding="utf-8")
    assert "python:scripts/ci/migration_guard.py --assert-current-production" in log
    assert "--apply" not in log
    assert "driver:deploy" in log
    assert "driver:rollback" not in log


def test_schema_drift_prevents_any_deploy(tmp_path: Path) -> None:
    env, audit = _sandbox(tmp_path)
    env["SIMULATE_SCHEMA_CURRENT"] = "false"
    result = _run(tmp_path, env)
    assert result.returncode == 42
    log = audit.read_text(encoding="utf-8")
    assert "--assert-current-production" in log
    assert "driver:deploy" not in log
    assert "--apply" not in log


@pytest.mark.parametrize("invalid_sha", ["main", "", "g" * 40, "a" * 39])
def test_production_preflight_requires_immutable_sha(
    tmp_path: Path, invalid_sha: str,
) -> None:
    env, audit = _sandbox(tmp_path)
    env["NFCORE_DEPLOY_REVISION"] = invalid_sha
    result = _run(tmp_path, env)
    assert result.returncode != 0
    assert "source revision" in result.stdout or "NFCORE_DEPLOY_REVISION" in result.stdout
    assert not audit.exists()


def test_smoke_failure_rolls_back_application_without_ddl(tmp_path: Path) -> None:
    env, audit = _sandbox(tmp_path)
    env["SIMULATE_SMOKE_CODE"] = "1"
    result = _run(tmp_path, env)
    assert result.returncode != 0
    log = audit.read_text(encoding="utf-8")
    assert "driver:deploy" in log
    assert "driver:rollback" in log
    assert "--apply" not in log


def test_even_legacy_implicit_schema_flag_never_applies_ddl(
    tmp_path: Path,
) -> None:
    env, audit = _sandbox(tmp_path)
    env["NFCORE_SCHEMA_MIGRATION_APPROVED"] = "true"
    result = _run(tmp_path, env)
    assert result.returncode == 0
    log = audit.read_text(encoding="utf-8")
    assert "--assert-current-production" in log
    assert "--apply" not in log
