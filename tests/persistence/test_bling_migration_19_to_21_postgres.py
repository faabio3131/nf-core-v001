"""Real 19→21 additive Bling schema rehearsal on an isolated CI PostgreSQL schema.

This is NOT a production backup restoration. No production database is accessed.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.sql import SQL, Identifier

from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase


def test_bling_upgrade_19_to_21_keeps_existing_data_and_partition_lock() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN", "")
    if not dsn:
        pytest.skip("disposable PostgreSQL is supplied by CI")
    schema = "bling_upgrade_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))

    parsed = urlsplit(dsn)
    query = dict(parse_qsl(parsed.query))
    query["options"] = f"-c search_path={schema}"
    isolated_dsn = urlunsplit(parsed._replace(query=urlencode(query, quote_via=quote)))
    database = None
    try:
        with psycopg.connect(isolated_dsn) as initial:
            initial.execute(
                "CREATE TABLE fm_schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            initial.execute(
                "INSERT INTO fm_schema_migrations "
                "SELECT version, 'historical', '2026-11-01' "
                "FROM generate_series(1, 19) AS version"
            )
            initial.execute(
                "CREATE TABLE legacy_sentinel (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            initial.execute("INSERT INTO legacy_sentinel VALUES (1, 'do-not-delete')")
        database = PostgresFiscalDatabase(
            isolated_dsn, min_pool_size=1, max_pool_size=4,
        )
        assert database.applied_migrations() == tuple(range(1, 20))
        assert database.initialize(enable_bling=True) == (20, 21, 22, 23)
        assert database.applied_migrations() == tuple(range(1, 24))
        # Second invocation must be idempotent; no schema rewrite or drop.
        assert database.initialize(enable_bling=True) == ()

        with database.connection() as connection:
            assert connection.execute(
                "SELECT payload FROM legacy_sentinel WHERE id = 1"
            ).fetchone() == ("do-not-delete",)
            assert connection.execute(
                "SELECT to_regclass('fm_bling_installations'), "
                "to_regclass('fm_bling_oauth_flows'), "
                "to_regclass('fm_bling_credentials'), "
                "to_regclass('fm_bling_active_partition_unique')"
            ).fetchone() == (
                "fm_bling_installations",
                "fm_bling_oauth_flows",
                "fm_bling_credentials",
                "fm_bling_active_partition_unique",
            )
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'fm_bling_installations' "
                "AND column_name IN ('authorized_status_id','rejected_status_id')",
                (schema,),
            ).fetchall()
            assert {row[0] for row in columns} == {
                "authorized_status_id", "rejected_status_id",
            }
        # One connected company per canonical fiscal tenant/unit/environment.
        with psycopg.connect(isolated_dsn) as connection:
            insert = (
                "INSERT INTO fm_bling_installations("
                "installation_id, company_id, external_tenant_id, external_unit_id,"
                "tenant_id, unit_id, environment, state, revision, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            )
            connection.execute(
                insert,
                ("one", "company-1", "ext1", "ext-u", "tenant", "unit",
                 "homologation", "connected", 1, "now", "now"),
            )
        with pytest.raises(psycopg.errors.UniqueViolation):
            with psycopg.connect(isolated_dsn) as connection:
                connection.execute(
                    insert,
                    ("two", "company-2", "ext2", "ext-u", "tenant", "unit",
                     "homologation", "connected", 1, "now", "now"),
                )
    finally:
        if database is not None:
            database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))
