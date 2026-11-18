"""A-03 acceptance: exact partition claims, per-unit policy and fail-closed worker."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest

from kordena_fiscal.application.bling_orders import PROCESS_ORDER
from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.contingency import (
    FiscalDispatchResult,
    FiscalDispatchStatus,
    FiscalOutboxService,
    FiscalOutboxStatus,
)
from kordena_fiscal.contingency.outbox import OutboxClaimSelection
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalEnvironment,
    FiscalUnitId,
    FiscalValidationError,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.integrations.bling_contracts import BlingInstallationState
from kordena_fiscal.persistence.bling_installations import BlingInstallationRepository
from kordena_fiscal.persistence.ports import PersistenceConflictError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.persistence.sqlite import SqliteFiscalDatabase
from kordena_fiscal.runtime.bling_multi_worker import BlingMultiTenantWorkerComposition
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.runtime.worker_composition import build_production_worker_runtime


@contextmanager
def database_fixture(tmp_path: Path, backend: str):
    if backend == "sqlite":
        db = SqliteFiscalDatabase(tmp_path / "bling-a03.sqlite")
        db.initialize(enable_bling=True)
        yield db
        return

    import psycopg
    from psycopg.sql import SQL, Identifier

    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("isolated PostgreSQL is provided by CI")
    schema = "bling_a03_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    parsed = urlsplit(dsn)
    query = dict(parse_qsl(parsed.query))
    query["options"] = f"-c search_path={schema}"
    isolated = urlunsplit(parsed._replace(query=urlencode(query, quote_via=quote)))
    db = None
    try:
        db = PostgresFiscalDatabase(isolated, min_pool_size=1, max_pool_size=4)
        db.initialize(enable_bling=True)
        assert db.applied_migrations() == (*range(1, 22), 22, 23)
        yield db
    finally:
        if db is not None:
            db.close()
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))


def setup_installations(db):
    with db() as uow:
        for tenant in ("a", "b"):
            for unit in ("1", "2"):
                uow.bindings.add(FiscalAccountBinding(
                    binding_id=f"bind-{tenant}-{unit}",
                    host_scope=HostScope(HostNamespace("bling"), tenant, unit),
                    fiscal_account_id=FiscalAccountId(f"fiscal-{tenant}"),
                    fiscal_unit_id=FiscalUnitId(f"fiscal-{unit}"),
                ))
        uow.commit()
    store = BlingInstallationRepository(db)
    result = []
    for tenant in ("a", "b"):
        for unit in ("1", "2"):
            host = HostScope(HostNamespace("bling"), tenant, unit)
            created = store.create(
                host_scope=host,
                company_id=f"company-{tenant}-{unit}",
                environment=FiscalEnvironment.HOMOLOGATION,
            )
            scope = FiscalApplicationService(db).resolve_scope(
                host, environment=FiscalEnvironment.HOMOLOGATION,
                correlation_id="bling-a03",
            )
            connected = store.transition(
                scope, created.installation_id, expected_revision=1,
                state=BlingInstallationState.CONNECTED,
            )
            ready = store.configure_status_mapping(
                scope, connected.installation_id, expected_revision=2,
                authorized_status_id=100 + len(result),
                rejected_status_id=200 + len(result),
            )
            result.append((ready, scope))
    return store, result


class Succeed:
    def __init__(self, scope: ExecutionScope, observed: list[str]):
        self.scope = scope
        self.observed = observed

    def dispatch(self, job):
        assert job.scope.identity_partition_key == self.scope.identity_partition_key
        self.observed.append(job.entry_id)
        return FiscalDispatchResult(
            FiscalDispatchStatus.SUCCEEDED, reference="synthetic-durable-confirmation",
        )


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_worker_claims_four_partitions_exactly_once(tmp_path: Path, backend: str) -> None:
    with database_fixture(tmp_path, backend) as db:
        store, views = setup_installations(db)
        observed: list[str] = []
        for index, (_, scope) in enumerate(views):
            with db() as uow:
                FiscalOutboxService(uow.outbox).enqueue(
                    scope=scope, operation=PROCESS_ORDER,
                    deduplication_key=f"a03-job-{index}",
                    payload=f"payload-{index}".encode(),
                    created_at=datetime.now(UTC),
                )
                uow.commit()

        comp = BlingMultiTenantWorkerComposition(db, store, oauth=object())
        def scoped_factory(view):
            scope = comp._scope(view)
            return build_production_worker_runtime(
                uow_factory=db,
                handlers={PROCESS_ORDER: Succeed(scope, observed)},
                environment="production",
                batch_size=1,
                claim_selection=OutboxClaimSelection(
                    scope=scope, operations=frozenset({PROCESS_ORDER}),
                ),
            )
        comp._scoped_factory = scoped_factory
        outcome = comp.run_cycle()
        assert (outcome.claimed, outcome.succeeded, outcome.retry_wait) == (4, 4, 0)
        assert len(observed) == len(set(observed)) == 4
        assert comp.run_cycle().claimed == 0
        with db() as uow:
            assert uow.outbox.counts_by_status()[FiscalOutboxStatus.SUCCEEDED] == 4


def test_one_active_company_per_canonical_outbox_partition(tmp_path: Path) -> None:
    with database_fixture(tmp_path, "sqlite") as db:
        store, views = setup_installations(db)
        first, scope = views[0]
        second = store.create(
            host_scope=HostScope(HostNamespace("bling"), "a", "1"),
            company_id="different-company",
            environment=FiscalEnvironment.HOMOLOGATION,
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.transition(
                scope, second.installation_id, expected_revision=1,
                state=BlingInstallationState.CONNECTED,
            )
        assert (
            store.get_for_scope(scope, first.installation_id).state
            is BlingInstallationState.CONNECTED
        )
        assert (
            store.get_for_scope(scope, second.installation_id).state
            is BlingInstallationState.NOT_CONFIGURED
        )


def test_status_config_fails_closed_on_cross_tenant_and_stale_cas(tmp_path: Path) -> None:
    with database_fixture(tmp_path, "sqlite") as db:
        store, views = setup_installations(db)
        first, scope = views[0]
        other_scope = views[2][1]
        assert store.status_mapping_for_scope(scope, first.installation_id) == (100, 200)
        assert store.status_mapping_for_scope(other_scope, first.installation_id) is None
        with pytest.raises(PersistenceConflictError):
            store.configure_status_mapping(
                other_scope, first.installation_id, expected_revision=first.revision,
                authorized_status_id=300, rejected_status_id=400,
            )
        with pytest.raises(FiscalValidationError):
            store.configure_status_mapping(
                scope, first.installation_id, expected_revision=first.revision,
                authorized_status_id=True, rejected_status_id=400,
            )


def test_worker_rejects_missing_mapping_and_stale_binding(tmp_path: Path) -> None:
    with database_fixture(tmp_path, "sqlite") as db:
        store, views = setup_installations(db)
        view, scope = views[0]
        with db.connection() as connection:
            connection.execute(
                "UPDATE fm_bling_installations SET authorized_status_id = NULL "
                "WHERE installation_id = ?", (view.installation_id,),
            )
            connection.commit()
        comp = BlingMultiTenantWorkerComposition(db, store, oauth=object())
        with pytest.raises(RuntimeConfigurationError):
            comp._scoped_worker(view)
        with db.connection() as connection:
            connection.execute(
                "UPDATE fm_fiscal_bindings SET fiscal_account_id = 'drifted' "
                "WHERE external_tenant_id = 'a' AND external_unit_id = '1' "
                "AND host_namespace = 'bling'"
            )
            connection.commit()
        with pytest.raises(RuntimeConfigurationError):
            comp._scope(view)
        assert scope.tenant_id != "drifted"


def test_oauth_unavailable_leaves_fiscal_outbox_unclaimed(tmp_path: Path) -> None:
    with database_fixture(tmp_path, "sqlite") as db:
        store, views = setup_installations(db)
        _, scope = views[0]
        with db() as uow:
            FiscalOutboxService(uow.outbox).enqueue(
                scope=scope, operation=PROCESS_ORDER,
                deduplication_key="oauth-recovery-preserve",
                payload=b"oauth-recovery", created_at=datetime.now(UTC),
            )
            uow.commit()

        class UnavailableOAuth:
            def access_token(self, scope: ExecutionScope, installation_id: str) -> str:
                raise RuntimeError("provider unavailable - do not claim")

        worker = BlingMultiTenantWorkerComposition(db, store, oauth=UnavailableOAuth())
        assert worker.run_cycle().claimed == 0
        with db() as uow:
            counts = uow.outbox.counts_by_status()
            entries = uow.outbox.list_for_scope(scope)
        assert counts[FiscalOutboxStatus.PENDING] == 1
        assert entries[0].attempt_count == 0


def test_worker_registry_cursor_and_pause(tmp_path: Path) -> None:
    with database_fixture(tmp_path, "sqlite") as db:
        store, views = setup_installations(db)
        ids = []
        cursor = ""
        while True:
            page, cursor = store.list_connected_for_worker(after=cursor, limit=1)
            ids.extend(v.installation_id for v in page)
            if cursor is None:
                break
        assert len(ids) == len(set(ids)) == 4
        view, scope = views[0]
        store.transition(
            scope, view.installation_id, expected_revision=view.revision,
            state=BlingInstallationState.PAUSED,
        )
        active, _ = store.list_connected_for_worker()
        assert len(active) == 3
        assert all(v.installation_id != view.installation_id for v in active)
