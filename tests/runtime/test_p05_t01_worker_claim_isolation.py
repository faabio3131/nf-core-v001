"""Exact partition claims on real stores; no GSM/cloud or staging certification."""

import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from types import SimpleNamespace
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from kordena_fiscal.application import DurableFiscalOutboxWorker
from kordena_fiscal.contingency import (
    FiscalDispatchResult,
    FiscalDispatchStatus,
    FiscalOutboxService,
    FiscalOutboxStatus,
    InMemoryFiscalOutboxStore,
    OutboxStateError,
)
from kordena_fiscal.contingency.outbox import OutboxClaimSelection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.persistence.sqlite_outbox_archive import SqliteFiscalOutboxStore
from kordena_fiscal.runtime import worker_main
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.runtime.worker_composition import (
    ScopedWorkerHandlerComposition,
    build_production_worker_runtime,
)

NOW = datetime(2026, 10, 12, tzinfo=UTC)
SCOPE = ExecutionScope("tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION, "claim", "nfcore")
SELECTION = OutboxClaimSelection(SCOPE, frozenset({"deliver_webhook"}))


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    dsn = ""
    schema = ""
    db = None
    if request.param == "postgres":
        dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN", "").strip()
        if not dsn:
            pytest.skip("NFCORE_TEST_POSTGRES_DSN required for PostgreSQL proof")
        info = conninfo_to_dict(dsn)
        if (
            info.get("host") not in {"127.0.0.1", "localhost", "::1"}
            or not info.get("dbname", "").endswith("_test")
        ):
            pytest.fail("worker claim PostgreSQL test requires local *_test database")
        schema = "worker_claim_" + uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        url = urlsplit(dsn)
        args = dict(parse_qsl(url.query, keep_blank_values=True))
        args["options"] = f"-c search_path={schema}"
        isolated = urlunsplit(url._replace(query=urlencode(args, quote_via=quote)))
        db = PostgresFiscalDatabase(isolated)
    else:
        db = SqliteFiscalDatabase(tmp_path / "isolated.sqlite3")
    try:
        db.initialize()
        yield db
    finally:
        if isinstance(db, PostgresFiscalDatabase):
            db.close()
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def enqueue(store, key, scope=SCOPE, operation="deliver_webhook", created=NOW):
    return FiscalOutboxService(store).enqueue(
        scope=scope, operation=operation, deduplication_key=key,
        payload=b'{"synthetic":"no external delivery"}', created_at=created,
    ).entry


def snapshot(db, entry):
    with db() as uow:
        return uow.outbox.get(entry.entry_id), uow.delivery_audit.list_for_entry(entry.entry_id)


class Handler:
    def __init__(self):
        self.calls = []

    def dispatch(self, entry):
        self.calls.append(entry)
        return FiscalDispatchResult(FiscalDispatchStatus.SUCCEEDED, reference="internal-test")


@pytest.mark.parametrize("foreign", [
    {"tenant_id": "tenant-b"}, {"unit_id": "unit-b"},
    {"environment": FiscalEnvironment.PRODUCTION}, {"host_namespace": "other-host"},
    {"host_namespace": None},
])
def test_foreign_partition_is_untouched_before_limit_and_audit(database, foreign):
    with database() as uow:
        other = enqueue(uow.outbox, "foreign", replace(SCOPE, **foreign),
                        created=NOW - timedelta(minutes=1))
        own = enqueue(uow.outbox, "own")
        uow.commit()
    before = snapshot(database, other)
    handler = Handler()
    worker = DurableFiscalOutboxWorker(
        uow_factory=database, handler=handler, claim_selection=SELECTION,
    )
    outcomes = worker.run_once(now=NOW, limit=1)
    assert [item.entry_id for item in outcomes] == [own.entry_id]
    assert snapshot(database, other) == before
    assert [entry.entry_id for entry in handler.calls] == [own.entry_id]
    assert worker.run_once(now=NOW, limit=1) == ()
    assert snapshot(database, other) == before


def test_unknown_operation_and_expired_foreign_lease_are_not_consumed(database):
    foreign_scope = replace(SCOPE, tenant_id="tenant-b")
    foreign_selection = OutboxClaimSelection(foreign_scope, SELECTION.operations)
    with database() as uow:
        expired = enqueue(uow.outbox, "expired", foreign_scope)
        uow.outbox.claim_due(now=NOW, limit=1, lease_duration=timedelta(seconds=1),
                             selection=foreign_selection)
        foreign = uow.outbox.get(expired.entry_id)
        uow.delivery_audit.start(foreign, started_at=NOW)
        unknown = enqueue(uow.outbox, "unsupported", operation="issue_document")
        own = enqueue(uow.outbox, "own")
        uow.commit()
    before = snapshot(database, expired), snapshot(database, unknown)
    handler = Handler()
    composition = build_production_worker_runtime(
        uow_factory=database, handlers={"deliver_webhook": handler},
        environment="staging", claim_selection=SELECTION,
    )
    with database() as uow:
        counts = uow.outbox.counts_by_status(selection=SELECTION)
        assert counts[FiscalOutboxStatus.PENDING] == 1
        assert counts[FiscalOutboxStatus.IN_FLIGHT] == 0
    result = composition.runtime.run_cycle()
    assert result.claimed == result.succeeded == 1
    assert [entry.entry_id for entry in handler.calls] == [own.entry_id]
    assert (snapshot(database, expired), snapshot(database, unknown)) == before
    assert next(
        sample.value for sample in composition.metrics.snapshot()
        if sample.name == "nfcore_worker_backlog_jobs"
    ) == 0


def test_store_scope_violation_rolls_back_before_io_or_audit(database, monkeypatch):
    with database() as uow:
        foreign = enqueue(uow.outbox, "foreign", replace(SCOPE, tenant_id="tenant-b"))
        uow.commit()
    before = snapshot(database, foreign)
    original = SqliteFiscalOutboxStore.claim_due

    def corrupted(store, *, selection=None, **kwargs):
        return original(store, **kwargs)  # Deliberately violate the repository contract.

    monkeypatch.setattr(SqliteFiscalOutboxStore, "claim_due", corrupted)
    handler = Handler()
    worker = DurableFiscalOutboxWorker(
        uow_factory=database, handler=handler, claim_selection=SELECTION,
    )
    with pytest.raises(OutboxStateError, match="unauthorized partition"):
        worker.run_once(now=NOW)
    assert handler.calls == []
    assert snapshot(database, foreign) == before


def test_postgres_workers_claim_independent_partitions(database):
    if not isinstance(database, PostgresFiscalDatabase):
        return  # SQLite isolation is certified above; concurrent case requires PostgreSQL.
    other = replace(SCOPE, tenant_id="tenant-b")
    with database() as uow:
        enqueue(uow.outbox, "a")
        enqueue(uow.outbox, "b", other)
        uow.commit()
    barrier = Barrier(2)
    handlers = [Handler(), Handler()]
    errors = []

    def run(index, scope):
        try:
            barrier.wait(timeout=5)
            worker = DurableFiscalOutboxWorker(
                uow_factory=database, handler=handlers[index],
                claim_selection=OutboxClaimSelection(scope, SELECTION.operations),
            )
            worker.run_once(now=NOW, limit=1)
        except Exception as exc:
            errors.append(exc)

    threads = [Thread(target=run, args=(i, scope)) for i, scope in enumerate((SCOPE, other))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert errors == []
    assert [entry.scope.tenant_id for entry in handlers[0].calls] == ["tenant-a"]
    assert [entry.scope.tenant_id for entry in handlers[1].calls] == ["tenant-b"]


def test_memory_store_uses_same_partition_contract():
    store = InMemoryFiscalOutboxStore()
    foreign = enqueue(store, "foreign", replace(SCOPE, tenant_id="tenant-b"))
    own = enqueue(store, "own", replace(SCOPE, correlation_id="job-correlation"))
    assert store.counts_by_status(selection=SELECTION)[FiscalOutboxStatus.PENDING] == 1
    claimed = store.claim_due(now=NOW, limit=1, lease_duration=timedelta(seconds=10),
                              selection=SELECTION)
    assert claimed[0].entry_id == own.entry_id
    assert store.get(foreign.entry_id) == foreign


@pytest.mark.parametrize("operations", [
    frozenset(), frozenset({"*"}), frozenset({" bad "}), frozenset({"DELIVER_WEBHOOK"}),
])
def test_empty_or_wildcard_operations_fail_closed(operations):
    with pytest.raises(FiscalValidationError):
        OutboxClaimSelection(SCOPE, operations)


def test_handler_registry_cannot_silently_widen_selection():
    handler = Handler()
    with pytest.raises(RuntimeConfigurationError, match="disagree"):
        ScopedWorkerHandlerComposition({"issue_document": handler}, SELECTION)
    with pytest.raises(RuntimeConfigurationError, match="disagree"):
        build_production_worker_runtime(
            uow_factory=lambda: pytest.fail("must not open DB"),
            handlers={"issue_document": handler}, environment="staging", claim_selection=SELECTION,
        )


def test_entrypoint_keeps_scoped_factory_claim_authority(monkeypatch, tmp_path):
    handler = Handler()
    scoped = ScopedWorkerHandlerComposition({"deliver_webhook": handler}, SELECTION)
    captured = {}

    class ProbeDatabase:
        def require_current_schema(self):
            pass

        @contextmanager
        def connection(self):
            yield SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: (1,)))

        def close(self):
            captured["closed"] = True

    def compose(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            health=lambda: None, runtime=SimpleNamespace(run_forever=lambda stop: None),
        )

    for key, value in {
        "NFCORE_ENVIRONMENT": "staging", "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://synthetic/not-connected",
        "NFCORE_SECRET_BACKEND": "external", "NFCORE_REQUIRE_HTTPS": "true",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NFCORE_WORKER_ONESHOT", raising=False)
    monkeypatch.setattr(worker_main, "PostgresFiscalDatabase", lambda _: ProbeDatabase())
    monkeypatch.setattr(worker_main, "build_production_worker_runtime", compose)
    assert worker_main.run(
        handler_factory=lambda _db, _settings: scoped, health_path=tmp_path / "worker-health.json",
    ) == 0
    assert captured["claim_selection"] is SELECTION
    assert captured["handlers"] == scoped.handlers
    assert captured["closed"]
