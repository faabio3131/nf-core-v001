"""Legacy COG-02 bridge production guard: no DDL, exact 18 or verified 19."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest

from kordena_fiscal.persistence.ports import PersistenceStateError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "nfcore_legacy_bridge_guard", ROOT / "scripts" / "ci" / "migration_guard.py"
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


class Database:
    def __init__(
        self, versions: tuple[int, ...], cakto: tuple[int, ...] | None,
    ) -> None:
        self.versions = versions
        self.cakto = cakto
        self.queries: list[str] = []
        self.closed = False

    def require_current_schema(self) -> tuple[int, ...]:
        if self.versions not in (tuple(range(1, 19)), tuple(range(1, 20))):
            raise PersistenceStateError("PostgreSQL schema is not certified")
        return self.versions

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql: str) -> Cursor:
        self.queries.append(sql)
        if sql.startswith("SELECT to_regclass"):
            name = None if self.cakto is None else "fm_cakto_schema_migrations"
            return Cursor(((name,),))
        if sql.startswith("SELECT version FROM fm_cakto_schema_migrations"):
            return Cursor(tuple((version,) for version in self.cakto or ()))
        raise AssertionError("production gate must not issue DDL or DML")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(guard, "validate_policy", lambda: tuple(range(1, 19)))
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/bridge")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)

    def set_database(versions: tuple[int, ...], cakto: tuple[int, ...] | None):
        database = Database(versions, cakto)
        monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: database)
        return database

    return set_database


@pytest.mark.parametrize("version", [18, 19])
def test_bridge_deploy_gate_accepts_exact_18_or_19_without_write(
    setup, capsys: pytest.CaptureFixture[str], version: int,
) -> None:
    database = setup(tuple(range(1, version + 1)), (1, 2))
    guard.assert_current_production()
    assert "PASS READ_ONLY" in capsys.readouterr().out
    assert database.closed
    assert database.queries
    assert all(sql.startswith("SELECT") for sql in database.queries)


@pytest.mark.parametrize(
    ("fiscal", "cakto"),
    [
        (tuple(range(1, 18)), (1, 2)),
        (tuple(range(1, 21)), (1, 2)),
        (tuple(range(1, 19)), None),
        (tuple(range(1, 20)), (1,)),
        (tuple(range(1, 19)), (1, 2, 3)),
    ],
)
def test_bridge_deploy_gate_rejects_schema_drift(
    setup, fiscal: tuple[int, ...], cakto: tuple[int, ...] | None,
) -> None:
    database = setup(fiscal, cakto)
    with pytest.raises((RuntimeError, PersistenceStateError)):
        guard.assert_current_production()
    assert database.closed
    assert all(sql.startswith("SELECT") for sql in database.queries)


@pytest.mark.parametrize("environment", ["", "staging", "development"])
def test_bridge_gate_requires_production_before_db_access(
    setup, monkeypatch: pytest.MonkeyPatch, environment: str,
) -> None:
    monkeypatch.setenv("NFCORE_ENVIRONMENT", environment)
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("DB opened"))
    with pytest.raises(RuntimeError, match="production environment"):
        guard.assert_current_production()


def test_bridge_gate_rejects_legacy_service_startup(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "legacy")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("DB opened"))
    with pytest.raises(RuntimeError, match="service startup"):
        guard.assert_current_production()
