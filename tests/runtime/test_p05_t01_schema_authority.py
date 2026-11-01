"""P05-T01: service startup is read-only; only the orchestrator may migrate."""

from __future__ import annotations

import runpy
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from kordena_fiscal.persistence.cakto import (
    CaktoStateConflictError,
    SqliteCaktoCommercialDatabase,
)
from kordena_fiscal.persistence.ports import PersistenceStateError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime import api as runtime_api
from kordena_fiscal.runtime import worker_main
from kordena_fiscal.runtime.config import RuntimeSettings


def _staging_settings() -> RuntimeSettings:
    return RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://example.invalid/nfcore",
        "NFCORE_SECRET_BACKEND": "external",
        "NFCORE_REQUIRE_HTTPS": "true",
    })


@pytest.mark.parametrize(
    ("versions", "should_pass"),
    [
        (tuple(range(1, 20)), True),
        ((), False),
        (tuple(range(1, 17)), False),
        (tuple(range(1, 20)), False),
        ((1, 3, *range(4, 19)), False),
    ],
)
def test_schema_guard_is_read_only_and_requires_exact_version_set(
    monkeypatch: pytest.MonkeyPatch, versions: tuple[int, ...], should_pass: bool,
) -> None:
    database = object.__new__(PostgresFiscalDatabase)
    monkeypatch.setattr(
        PostgresFiscalDatabase, "applied_migrations", lambda _self: versions
    )
    if should_pass:
        assert database.require_current_schema() == versions
    else:
        with pytest.raises(PersistenceStateError, match="certified migration version"):
            database.require_current_schema()


def test_api_staging_boot_checks_existing_schema_without_initialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Database:
        def __init__(self, _dsn: str) -> None:
            calls.append("construct")

        def require_current_schema(self) -> tuple[int, ...]:
            calls.append("verify")
            return tuple(range(1, 20))

        def initialize(self) -> None:
            raise AssertionError("API must not apply migrations at service startup")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(runtime_api, "PostgresFiscalDatabase", Database)
    monkeypatch.setattr(
        runtime_api, "build_postgres_runtime_composition",
        lambda *_args, **_kwargs: object(),
    )
    runtime = runtime_api.RuntimeApi(_staging_settings())
    assert runtime.database is not None
    assert runtime.composition is not None
    assert calls == ["construct", "verify"]
    runtime.close()
    assert calls == ["construct", "verify", "close"]


def test_api_refuses_stale_schema_and_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Database:
        def __init__(self, _dsn: str) -> None:
            calls.append("construct")

        def require_current_schema(self) -> None:
            calls.append("verify")
            raise PersistenceStateError("outdated schema")

        def initialize(self) -> None:
            raise AssertionError("no startup schema mutation")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(runtime_api, "PostgresFiscalDatabase", Database)
    runtime = runtime_api.RuntimeApi(_staging_settings())
    assert runtime.database is None
    assert runtime.ready() == (False, "database_unavailable")
    assert calls == ["construct", "verify", "close"]


@pytest.mark.parametrize("schema_ok", [True, False])
def test_worker_staging_boot_never_applies_migrations(
    monkeypatch: pytest.MonkeyPatch, tmp_path, schema_ok: bool,
) -> None:
    calls: list[str] = []

    class Connection:
        def execute(self, statement: str) -> Connection:
            assert statement == "SELECT 1"
            calls.append("sql-read")
            return self

        def fetchone(self) -> tuple[int]:
            return (1,)

    class Database:
        def __init__(self, _dsn: str) -> None:
            calls.append("construct")

        def initialize(self) -> None:
            raise AssertionError("Worker must not migrate at startup")

        def require_current_schema(self) -> None:
            calls.append("verify")
            if not schema_ok:
                raise PersistenceStateError("schema missing")

        @contextmanager
        def connection(self):
            yield Connection()

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(worker_main, "PostgresFiscalDatabase", Database)
    monkeypatch.setattr(
        worker_main.RuntimeSettings, "from_environ", _staging_settings
    )
    monkeypatch.setenv("NFCORE_WORKER_ONESHOT", "true")
    if schema_ok:
        assert worker_main.run(health_path=tmp_path / "health") == 0
        assert calls == ["construct", "verify", "sql-read", "close"]
    else:
        with pytest.raises(PersistenceStateError, match="schema missing"):
            worker_main.run(health_path=tmp_path / "health")
        assert calls == ["construct", "verify", "close"]


@pytest.mark.parametrize("env", ["staging", "production"])
def test_railway_service_predeploy_cannot_apply_migrations(
    monkeypatch: pytest.MonkeyPatch, env: str,
) -> None:
    monkeypatch.setenv("NFCORE_ENVIRONMENT", env)
    monkeypatch.setenv("NFCORE_SCHEMA_MIGRATION_APPROVED", "true")
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "railway-service-internal")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/db")
    apply = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/ci/migration_guard.py")
    )["apply"]
    with pytest.raises(RuntimeError, match="Railway service preDeploy"):
        apply()


def test_cakto_schema_guard_is_read_only(tmp_path) -> None:
    path = tmp_path / "cakto-schema.sqlite3"
    database = SqliteCaktoCommercialDatabase(path)
    with pytest.raises(CaktoStateConflictError, match="certified migration version"):
        database.require_current_schema()
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='fm_cakto_schema_migrations'"
        ).fetchall()
    assert rows == [], "read-only guard must not initialize missing schema"

    assert database.initialize() is True
    assert database.require_current_schema() == (1, 2)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM fm_cakto_schema_migrations WHERE version = 2")
    with pytest.raises(CaktoStateConflictError, match="certified migration version"):
        database.require_current_schema()
