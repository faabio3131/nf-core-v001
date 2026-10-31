"""Fail-closed read-only production schema gate for code-only Contabo deploys."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "nfcore_production_migration_guard", ROOT / "scripts" / "ci" / "migration_guard.py"
)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class Cursor:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self.rows


class ReadOnlyDb:
    def __init__(self, fiscal: tuple[int, ...], cakto: tuple[int, ...] | None) -> None:
        self.fiscal = fiscal
        self.cakto = cakto
        self.sql: list[str] = []
        self.closed = False

    def applied_migrations(self) -> tuple[int, ...]:
        return self.fiscal

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql: str) -> Cursor:
        self.sql.append(sql)
        if sql.startswith("SELECT to_regclass"):
            return Cursor(((None if self.cakto is None else "fm_cakto_schema_migrations",),))
        if sql.startswith("SELECT version FROM fm_cakto_schema_migrations"):
            return Cursor(tuple((v,) for v in self.cakto or ()))
        raise AssertionError("read-only gate must not run DDL/DML")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(guard, "validate_policy", lambda: tuple(range(1, 19)))
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/test")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    monkeypatch.delenv("NFCORE_PRODUCTION_APPROVAL", raising=False)
    monkeypatch.delenv("NFCORE_SCHEMA_MIGRATION_APPROVED", raising=False)

    def set_db(fiscal: tuple[int, ...], cakto: tuple[int, ...] | None) -> ReadOnlyDb:
        db = ReadOnlyDb(fiscal, cakto)
        monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: db)
        return db

    return set_db


def test_production_exact_schema_permits_code_only_without_approval(setup, capsys):
    db = setup(tuple(range(1, 19)), tuple(range(1, guard.CAKTO_SCHEMA_VERSION + 1)))
    guard.assert_current_production()
    assert "PASS READ_ONLY CURRENT" in capsys.readouterr().out
    assert db.closed
    assert db.sql
    assert all(sql.startswith("SELECT") for sql in db.sql)


@pytest.mark.parametrize(
    ("fiscal", "cakto", "reason"),
    [
        (tuple(range(1, 18)), (1, 2), "fiscal"),
        ((1, 3), (1, 2), "fiscal"),
        (tuple(range(1, 20)), (1, 2), "fiscal"),
        (tuple(range(1, 19)), None, "Cakto"),
        (tuple(range(1, 19)), (1,), "Cakto"),
        (tuple(range(1, 19)), (2,), "Cakto"),
        (tuple(range(1, 19)), (1, 2, 3), "Cakto"),
    ],
)
def test_production_schema_mismatch_blocks_without_write(setup, fiscal, cakto, reason):
    db = setup(fiscal, cakto)
    with pytest.raises(RuntimeError, match=reason):
        guard.assert_current_production()
    assert db.closed
    assert all(sql.startswith("SELECT") for sql in db.sql)


@pytest.mark.parametrize("environment", ["staging", "development", ""])
def test_assertion_rejects_wrong_environment_without_db(setup, monkeypatch, environment):
    monkeypatch.setenv("NFCORE_ENVIRONMENT", environment)
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("DB opened"))
    with pytest.raises(RuntimeError, match="production environment"):
        guard.assert_current_production()


def test_assertion_needs_database_url_without_db(setup, monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("DB opened"))
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        guard.assert_current_production()


def test_assertion_rejects_service_startup_without_db(setup, monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "legacy")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("DB opened"))
    with pytest.raises(RuntimeError, match="outside service startup"):
        guard.assert_current_production()
