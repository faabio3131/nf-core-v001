"""Migration 19 additive rehearsal on a disposable PostgreSQL schema.

This is NOT a restoration of a real production backup. It verifies the 18->19
ledger transition, transaction rollback, and preservation of existing rows.
"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from kordena_fiscal.persistence.cognitive_quota_schema import (
    COGNITIVE_QUOTA_SCHEMA,
    COGNITIVE_QUOTA_VERSION,
)


def test_migration19_preserves_legacy_rows_and_rolls_back_atomically() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable CI PostgreSQL is not configured")

    schema = f"nfcore_cog02_upgrade_{uuid4().hex}"
    # This test uses its own generated schema in CI; never change public or
    # the running NFCore database. Names contain only fixed text and UUID hex.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        try:
            conn.execute(f"SET search_path TO {schema}")
            conn.execute(
                "CREATE TABLE fm_schema_migrations ("
                "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO fm_schema_migrations "
                "SELECT version, 'legacy', '2026-11-01' FROM generate_series(1, 18) AS version"
            )
            conn.execute(
                "CREATE TABLE fm_legacy_customer_sentinel "
                "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO fm_legacy_customer_sentinel VALUES (1, 'preserved')"
            )
            # An interrupted schema change must roll back before recording 19.
            with pytest.raises(psycopg.errors.UndefinedTable):
                with conn.transaction():
                    conn.execute(COGNITIVE_QUOTA_SCHEMA[0])
                    conn.execute("SELECT * FROM fm_cog02_missing_test_table")
            assert conn.execute(
                "SELECT to_regclass('fm_cognitive_token_counters')"
            ).fetchone() == (None,)
            assert conn.execute(
                "SELECT COUNT(*) FROM fm_schema_migrations"
            ).fetchone() == (18,)

            # The approved canonical additive SQL and ledger insertion are
            # transactional, not separate independently committed operations.
            with conn.transaction():
                for statement in COGNITIVE_QUOTA_SCHEMA:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO fm_schema_migrations VALUES (%s, %s, %s)",
                    (COGNITIVE_QUOTA_VERSION, "cognitive_token_reservations", "2026-11-01"),
                )

            assert tuple(row[0] for row in conn.execute(
                "SELECT version FROM fm_schema_migrations ORDER BY version"
            ).fetchall()) == tuple(range(1, 20))
            assert conn.execute(
                "SELECT payload FROM fm_legacy_customer_sentinel WHERE id=1"
            ).fetchone() == ("preserved",)
            assert conn.execute(
                "SELECT to_regclass('fm_cognitive_token_counters'), "
                "to_regclass('fm_cognitive_token_reservations')"
            ).fetchone() == (
                "fm_cognitive_token_counters",
                "fm_cognitive_token_reservations",
            )
        finally:
            conn.execute("RESET search_path")
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
