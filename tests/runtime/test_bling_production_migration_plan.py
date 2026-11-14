"""Bling 19→21 controlled plan: read-only, exact schema and Cakto authority."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nfcore_bling_production_plan",
    Path(__file__).resolve().parents[2] / "scripts/ci/migration_guard.py",
)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class _Rows:
    def __init__(self, values: tuple[tuple[object, ...], ...]) -> None:
        self.values = values

    def fetchone(self) -> tuple[object, ...] | None:
        return self.values[0] if self.values else None

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self.values


class _Database:
    def __init__(
        self,
        installed: tuple[int, ...],
        cakto: tuple[int, ...] | None = (1, 2, 3),
    ) -> None:
        self.installed = installed
        self.cakto = cakto
        self.queries: list[str] = []
        self.schema_checks: list[bool] = []
        self.closed = False

    def applied_migrations(self) -> tuple[int, ...]:
        return self.installed

    def require_current_schema(self, *, require_bling: bool = False) -> tuple[int, ...]:
        self.schema_checks.append(require_bling)
        return self.installed

    @contextmanager
    def connection(self):
        yield self

    def execute(self, sql: str) -> _Rows:
        self.queries.append(sql)
        if sql.startswith("SELECT to_regclass"):
            return _Rows(((None if self.cakto is None else "fm_cakto_schema_migrations",),))
        if sql.startswith("SELECT version FROM fm_cakto_schema_migrations"):
            return _Rows(tuple((version,) for version in self.cakto or ()))
        raise AssertionError("unexpected read-only query or DDL")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch):
    # The tested subject is the read-only guard, not global migration metadata.
    # Keep the policy validation itself covered by the canonical CI check.
    # The database factory below is a fake and has no class-level version fields.
    monkeypatch.setattr(guard, "validate_policy", lambda: tuple(range(1, 23)))
    monkeypatch.setenv("NFCORE_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/nfcore")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    monkeypatch.delenv("NFCORE_SCHEMA_MIGRATION_APPROVED", raising=False)
    monkeypatch.delenv("NFCORE_PRODUCTION_APPROVAL", raising=False)

    def set_database(
        installed: tuple[int, ...], cakto: tuple[int, ...] | None = (1, 2, 3),
    ) -> _Database:
        db = _Database(installed, cakto)
        monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: db)
        return db

    return set_database


@pytest.mark.parametrize(
    ("installed", "pending", "requires_bling"),
    [
        (tuple(range(1, 20)), "20,21,22", False),
        (tuple(range(1, 22)), "22", True),
        ((*range(1, 20), 22), "20,21", False),
        (tuple(range(1, 23)), "NONE", True),
    ],
)
def test_plan_accepts_only_certified_boundaries_without_writes(
    setup, capsys: pytest.CaptureFixture[str],
    installed: tuple[int, ...], pending: str, requires_bling: bool,
) -> None:
    db = setup(installed)
    guard.plan_production_bling()
    text = capsys.readouterr().out
    assert "PASS READ_ONLY" in text
    assert f"pending={pending}" in text
    assert "approval_required=true; no DDL executed" in text
    assert db.schema_checks == [requires_bling]
    assert db.closed
    assert db.queries
    assert all(query.startswith("SELECT ") for query in db.queries)


@pytest.mark.parametrize(
    "installed",
    [
        (),
        tuple(range(1, 19)),
        tuple(range(1, 21)),  # partial migration 20 is NEVER a ready baseline
        (1, *range(3, 20)),
        tuple(range(1, 24)),
        (*range(1, 21), 22),  # partial Bling 20 with DPS 22 is not ready
    ],
)
def test_plan_rejects_drift_and_partial_schema_before_catalog_access(
    setup, installed: tuple[int, ...],
) -> None:
    db = setup(installed)
    with pytest.raises(RuntimeError, match="drift or partial"):
        guard.plan_production_bling()
    assert db.closed
    assert db.schema_checks == []
    assert db.queries == []


@pytest.mark.parametrize("cakto", [None, (), (1,), (1, 3), (1, 2, 3, 4)])
def test_plan_rejects_missing_or_drifted_cakto_schema(setup, cakto) -> None:
    db = setup(tuple(range(1, 20)), cakto)
    with pytest.raises(RuntimeError, match="Cakto"):
        guard.plan_production_bling()
    assert db.closed
    assert all(query.startswith("SELECT ") for query in db.queries)


@pytest.mark.parametrize("environment", ["", "staging", "development"])
def test_plan_rejects_nonproduction_before_connecting(
    setup, monkeypatch: pytest.MonkeyPatch, environment: str,
) -> None:
    setup(tuple(range(1, 20)))
    monkeypatch.setenv("NFCORE_ENVIRONMENT", environment)
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("db opened"))
    with pytest.raises(RuntimeError, match="production environment"):
        guard.plan_production_bling()


def test_plan_rejects_service_startup_before_connecting(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup(tuple(range(1, 20)))
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "service")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("db opened"))
    with pytest.raises(RuntimeError, match="outside service startup"):
        guard.plan_production_bling()


def test_plan_rejects_missing_database_url_before_connecting(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup(tuple(range(1, 20)))
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("db opened"))
    with pytest.raises(RuntimeError, match="requires DATABASE_URL"):
        guard.plan_production_bling()


def test_plan_refuses_unexpected_migration_policy(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup(tuple(range(1, 20)))
    monkeypatch.setattr(guard, "validate_policy", lambda: tuple(range(1, 20)))
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("db opened"))
    with pytest.raises(RuntimeError, match="policy changed unexpectedly"):
        guard.plan_production_bling()


@pytest.mark.parametrize(
    "installed",
    [(), tuple(range(1, 19)), tuple(range(1, 21)),
     (*range(1, 21), 22), (1, *range(3, 23))],
)
def test_approved_production_apply_never_repairs_partial_or_drifted_schema(
    setup, monkeypatch: pytest.MonkeyPatch, installed: tuple[int, ...],
) -> None:
    db = setup(installed)
    monkeypatch.setenv("NFCORE_SCHEMA_MIGRATION_APPROVED", "true")
    monkeypatch.setenv("NFCORE_PRODUCTION_APPROVAL", "PRODUCTION_APPROVED")
    monkeypatch.setenv("NFCORE_BLING_INSTALLATIONS_ENABLED", "true")
    monkeypatch.setattr(
        db, "initialize", lambda **_kwargs: pytest.fail("executed unexpected DDL"),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="partial or drifted schema"):
        guard.apply()
    assert db.closed
    assert db.queries == []
    assert db.schema_checks == []


def test_production_apply_requires_cakto_consistency_before_any_ddl(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = setup(tuple(range(1, 20)), None)
    monkeypatch.setenv("NFCORE_SCHEMA_MIGRATION_APPROVED", "true")
    monkeypatch.setenv("NFCORE_PRODUCTION_APPROVAL", "PRODUCTION_APPROVED")
    monkeypatch.setenv("NFCORE_BLING_INSTALLATIONS_ENABLED", "true")
    monkeypatch.setattr(
        db, "initialize", lambda **_kwargs: pytest.fail("executed unexpected DDL"),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="Cakto"):
        guard.apply()
    assert db.closed
    assert db.schema_checks == [False]
    assert all(query.startswith("SELECT ") for query in db.queries)


def test_production_apply_without_approval_never_opens_database(
    setup, monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup(tuple(range(1, 20)))
    monkeypatch.setenv("NFCORE_BLING_INSTALLATIONS_ENABLED", "true")
    monkeypatch.setattr(guard, "PostgresFiscalDatabase", lambda _: pytest.fail("db opened"))
    with pytest.raises(RuntimeError, match="migration blocked"):
        guard.apply()
