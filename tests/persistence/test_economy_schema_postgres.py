"""PostgreSQL T01 schema rehearsal: real SQL, RLS and immutable rows."""
import os
from datetime import date
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_schema import ECONOMY_VERSION, TABLES
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase


def _scope(tenant="tenant-a", unit="unit-a", host="fm-nfcore"):
    return ExecutionScope(tenant, unit, FiscalEnvironment.HOMOLOGATION, "test", host)


def test_real_postgres_economy_schema_scope_and_immutability(monkeypatch):
    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL required for T01")
    suffix = uuid4().hex
    schema_name = "economy_test_" + suffix
    role_name = "economy_role_" + suffix
    # Existing CI database role is responsible for sandbox DDL only.
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
            sql.Identifier(role_name)
        ))
        database = None
        try:
            uri = urlsplit(dsn)
            query = dict(parse_qsl(uri.query, keep_blank_values=True))
            query["options"] = f"-c search_path={schema_name}"
            database = PostgresFiscalDatabase(
                urlunsplit(uri._replace(query=urlencode(query, quote_via=quote)))
            )
            assert ECONOMY_VERSION not in database.initialize()
            assert database.initialize(
                enable_economy=True, economy_runtime_role=role_name,
            ) == (ECONOMY_VERSION,)
            assert database.initialize(enable_economy=True) == ()
            assert database.applied_migrations()[-1] == ECONOMY_VERSION
            monkeypatch.setenv("NFCORE_ECONOMY_ENABLED", "true")
            monkeypatch.setenv("NFCORE_ECONOMY_RUNTIME_ROLE", role_name)
            with database.economy(_scope(tenant="tenant-migration")) as scoped:
                scoped.append_snapshot(
                    record_id="migration-proof", version=1, competence=date(2026, 11, 1),
                    issuer=Cnpj("12345678000195"), content={"revenue_cents": 10},
                )
            with database.economy(_scope(tenant="tenant-b")) as scoped:
                assert scoped.snapshot("migration-proof", 1) is None
            with database.economy(_scope(tenant="tenant-migration")) as scoped:
                assert scoped.snapshot("migration-proof", 1) == {"revenue_cents": 10}
            with database.economy(_scope(tenant="tenant-c")) as scoped:
                scoped.append_snapshot(
                    record_id="migration-proof", version=1, competence=date(2026, 11, 1),
                    issuer=Cnpj("12345678000195"), content={"revenue_cents": 20},
                )
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            # Explicitly add DML permissions only in this sandbox to prove
            # that the RLS policies, not solely GRANTs, deny mutation.
            for table in TABLES:
                admin.execute(sql.SQL("GRANT UPDATE, DELETE ON {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(role_name),
                ))
            # Keep the subsequent original tests in a distinct partition.
            with psycopg.connect(dsn, autocommit=True) as runtime:
                runtime.execute(sql.SQL("SET search_path TO {}").format(
                    sql.Identifier(schema_name)
                ))
                with pytest.raises(FiscalValidationError, match="bypass RLS"):
                    with EconomyStore.transaction(runtime, _scope()):
                        pass
                runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role_name)))
                with EconomyStore.transaction(runtime, _scope()) as store:
                    digest = store.append_snapshot(
                        record_id="s", version=1, competence=date(2026, 11, 1),
                        issuer=Cnpj("12345678000195"), content={"revenue_cents": 100},
                    )
                    assert len(digest) == 64
                    assert store.snapshot("s", 1) == {"revenue_cents": 100}
                    store.append_benefit(
                        record_id="b", version=1, tax_code="ICMS", jurisdiction="SP",
                        normative_reference="synthetic-only", valid_from=date(2026, 1, 1),
                        valid_until=date(2027, 1, 1), content={"eligible": False},
                    )
                    store.append_opportunity(
                        record_id="o", version=1, snapshot_id="s", snapshot_version=1,
                        benefit_id="b", benefit_version=1, estimated_cents=10,
                        content={"status": "potential"},
                    )
                    store.append_credit_entry(
                        record_id="credit", opportunity_id="o", opportunity_version=1,
                        tax_code="ICMS", competence=date(2026, 11, 1),
                        movement="identified", amount_cents=10,
                        evidence_reference="synthetic-only",
                    )
                    store.append_dossier(
                        record_id="d", version=1, opportunity_id="o", opportunity_version=1,
                        archive_reference="synthetic-only", digest=digest,
                    )
                    for table in TABLES:
                        assert len(store.records(table)) == 1
                    assert runtime.execute(
                        "UPDATE fm_economy_snapshots SET version=2"
                    ).rowcount == 0
                    assert runtime.execute("DELETE FROM fm_economy_snapshots").rowcount == 0
                with pytest.raises(FiscalValidationError, match="active scoped transaction"):
                    store.records("fm_economy_snapshots")
                with pytest.raises(FiscalValidationError, match="active scoped transaction"):
                    EconomyStore(runtime, _scope()).snapshot("s", 1)
                assert runtime.execute(
                    "SELECT count(*) FROM fm_economy_snapshots"
                ).fetchone() == (0,)
                with pytest.raises(RuntimeError, match="force rollback"):
                    with EconomyStore.transaction(runtime, _scope()) as rollback_store:
                        rollback_store.append_snapshot(
                            record_id="rolled-back", version=1, competence=date(2026, 11, 1),
                            issuer=Cnpj("12345678000195"), content={"revenue_cents": 100},
                        )
                        raise RuntimeError("force rollback")
                with EconomyStore.transaction(runtime, _scope()) as rollback_store:
                    assert rollback_store.snapshot("rolled-back", 1) is None
                for scope in (
                    _scope(tenant="tenant-b"), _scope(unit="unit-b"), _scope(host="other"),
                ):
                    with EconomyStore.transaction(runtime, scope) as store:
                        assert store.snapshot("s", 1) is None
                        for table in TABLES:
                            assert store.records(table) == ()
                        assert runtime.execute(
                            "SELECT count(*) FROM fm_economy_snapshots"
                        ).fetchone() == (0,)
                with EconomyStore.transaction(runtime, _scope()) as store:
                    assert store.snapshot("s", 1) == {"revenue_cents": 100}
                    with pytest.raises(psycopg.errors.UniqueViolation):
                        with runtime.transaction():
                            store.append_snapshot(
                                record_id="s", version=1, competence=date(2026, 11, 1),
                                issuer=Cnpj("12345678000195"), content={"revenue_cents": 999},
                            )
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    with EconomyStore.transaction(runtime, _scope(tenant="tenant-b")) as store:
                        store.append_opportunity(
                            record_id="foreign", version=1, snapshot_id="s", snapshot_version=1,
                            benefit_id=None, benefit_version=None, estimated_cents=1, content={},
                        )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with EconomyStore.transaction(runtime, _scope()):
                        runtime.execute(
                            """INSERT INTO fm_economy_snapshots
                            SELECT host_namespace, 'tenant-b', unit_id, environment, record_id,
                                version, competence, issuer_cnpj, content, digest, created_at
                            FROM fm_economy_snapshots"""
                        )
        finally:
            if database is not None:
                database.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
