"""P05 read-only preflight: inspect installed schema without granting DDL authority."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "nfcore_migration_guard", ROOT / "scripts" / "ci" / "migration_guard.py"
)
assert SPEC is not None and SPEC.loader is not None
migration_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration_guard)


@pytest.fixture(autouse=True)
def _approved_migration_versions(monkeypatch) -> None:
    # Policy itself is exercised separately by check-policy in the CI.
    # Keep this suite focused on SELECT-only preflight and drift handling.
    monkeypatch.setattr(
        migration_guard, "validate_policy", lambda: tuple(range(1, 19))
    )


class _Cursor:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class _Db:
    def __init__(self, installed: tuple[int, ...], cakto: tuple[int, ...] | None) -> None:
        self.installed, self.cakto = installed, cakto
        self.queries: list[str] = []
        self.closed = False

    def applied_migrations(self) -> tuple[int, ...]:
        return self.installed

    @contextmanager
    def connection(self):
        yield self

    def execute(self, statement: str) -> _Cursor:
        self.queries.append(statement)
        if statement.startswith("SELECT to_regclass"):
            return _Cursor(((None if self.cakto is None else "fm_cakto_schema_migrations",),))
        if statement.startswith("SELECT version FROM fm_cakto_schema_migrations"):
            return _Cursor(tuple((i,) for i in self.cakto or ()))
        raise AssertionError("preflight must never execute DDL or unknown SQL")

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("installed", "cakto", "expected_missing"),
    [
        (tuple(range(1, 13)), None, "fiscal_pending=(13, 14, 15, 16, 17, 18)"),
        (tuple(range(1, 19)), (1, 2), "fiscal_pending=()"),
        (tuple(range(1, 15)), (1,), "cakto_pending=(2, 3)"),
    ],
)
def test_preflight_is_read_only(
    monkeypatch, capsys, installed: tuple[int, ...], cakto: tuple[int, ...] | None,
    expected_missing: str,
) -> None:
    db = _Db(installed, cakto)
    monkeypatch.setattr(migration_guard, "PostgresFiscalDatabase", lambda _: db)
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/not-used")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    monkeypatch.delenv("NFCORE_SCHEMA_MIGRATION_APPROVED", raising=False)
    migration_guard.plan_staging()
    assert expected_missing in capsys.readouterr().out
    assert db.closed
    assert all(q.startswith("SELECT") for q in db.queries)


@pytest.mark.parametrize(
    ("installed", "cakto"),
    [
        ((1, 3), None),
        (tuple(range(1, 20)), None),
        (tuple(range(1, 13)), (2,)),
        (tuple(range(1, 13)), (1, 2, 3, 4)),
    ],
)
def test_schema_drift_blocks_preflight(monkeypatch, installed, cakto) -> None:
    db = _Db(installed, cakto)
    monkeypatch.setattr(migration_guard, "PostgresFiscalDatabase", lambda _: db)
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/not-used")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    with pytest.raises(RuntimeError, match="unexpected.*migration sequence"):
        migration_guard.plan_staging()
    assert db.closed


@pytest.mark.parametrize("env", ["production", "development"])
def test_preflight_rejects_other_environments_without_db(monkeypatch, env) -> None:
    monkeypatch.setenv("NFCORE_ENVIRONMENT", env)
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/not-used")
    monkeypatch.setattr(
        migration_guard, "PostgresFiscalDatabase", lambda _: pytest.fail("opened DB")
    )
    with pytest.raises(RuntimeError, match="restricted to staging"):
        migration_guard.plan_staging()


def test_preflight_rejects_service_startup_without_db(monkeypatch) -> None:
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic/not-used")
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "service")
    monkeypatch.setattr(
        migration_guard, "PostgresFiscalDatabase", lambda _: pytest.fail("opened DB")
    )
    with pytest.raises(RuntimeError, match="outside service startup"):
        migration_guard.plan_staging()
