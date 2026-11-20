"""PostgreSQL T01 schema rehearsal: real SQL, RLS and immutable rows."""
import os
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_schema import ECONOMY_SCHEMA, TABLES
from kordena_fiscal.persistence.economy_store import EconomyStore


def _scope(tenant="tenant-a", unit="unit-a", host="fm-nfcore"):
    return ExecutionScope(tenant, unit, FiscalEnvironment.HOMOLOGATION, "test", host)


def test_real_postgres_economy_schema_scope_and_immutability():
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
        try:
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            with admin.transaction():
                for statement in ECONOMY_SCHEMA:
                    admin.execute(statement)
                admin.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema_name), sql.Identifier(role_name),
                ))
                for table in TABLES:
                    admin.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(
                        sql.Identifier(table), sql.Identifier(role_name),
                    ))
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
                    assert runtime.execute("UPDATE fm_economy_snapshots SET version=2").rowcount == 0
                    assert runtime.execute("DELETE FROM fm_economy_snapshots").rowcount == 0
                assert runtime.execute("SELECT count(*) FROM fm_economy_snapshots").fetchone() == (0,)
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
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
