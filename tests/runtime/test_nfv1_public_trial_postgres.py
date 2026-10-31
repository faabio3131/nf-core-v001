"""BLD-03 shared admission proof, adapted from #237 into an isolated schema."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime.public_trial_abuse import PostgresPublicTrialAbuseGate


def test_real_postgres_trial_gate_is_atomic_and_denies_missing_schema() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("NFCORE_TEST_POSTGRES_DSN required for PostgreSQL test")
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost", "::1"}
    schema = "bld03_admission_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    uri = urlsplit(dsn)
    query = dict(parse_qsl(uri.query, keep_blank_values=True))
    query["options"] = f"-c search_path={schema}"
    isolated_dsn = urlunsplit(uri._replace(query=urlencode(query, quote_via=quote)))
    database = None
    try:
        database = PostgresFiscalDatabase(
            isolated_dsn, min_pool_size=1, max_pool_size=12,
        )
        database.initialize()
        database.require_current_schema()
        gate_a = PostgresPublicTrialAbuseGate(database.connection, max_requests=3)
        gate_b = PostgresPublicTrialAbuseGate(database.connection, max_requests=3)
        now = datetime(2026, 10, 27, 15, tzinfo=UTC)

        def attempt(index: int) -> bool:
            return (gate_a if index % 2 else gate_b).allow("198.51.100.24", now)

        with ThreadPoolExecutor(max_workers=8) as pool:
            admissions = list(pool.map(attempt, range(12)))
        assert admissions.count(True) == 3
        assert admissions.count(False) == 9
        with database.connection() as connection:
            records = connection.execute(
                "SELECT scope_key, window_start, hits FROM fm_public_trial_rate_windows"
            ).fetchall()
        assert len(records) == 1
        assert records[0][2] == 3
        assert "198.51.100.24" not in str(records)
        assert gate_a.allow("198.51.100.25", now)
        assert gate_b.allow("198.51.100.24", now + timedelta(hours=1))
        with database.connection() as connection:
            connection.execute("DROP TABLE fm_public_trial_rate_windows")
        assert not gate_a.allow("198.51.100.24", now)
    finally:
        if database is not None:
            database.close()
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
