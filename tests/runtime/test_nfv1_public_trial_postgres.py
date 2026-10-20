"""Real PostgreSQL verification of the canonical shared trial admission gate.

CI-only ephemeral PostgreSQL. The same canonical migrations initialize the
database before requests. No secrets, pricing changes, or deployment activity.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime.public_trial_abuse import PostgresPublicTrialAbuseGate


def test_real_postgres_trial_gate_is_atomic_and_denies_missing_schema() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("NFCORE_TEST_POSTGRES_DSN required for PostgreSQL test")

    # Existing PostgreSQL test suite uses an isolated disposable CI database.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    database = PostgresFiscalDatabase(dsn, min_pool_size=1, max_pool_size=12)
    try:
        assert database.initialize() == tuple(range(1, 19))
        gate_a = PostgresPublicTrialAbuseGate(
            database.connection, max_requests=3, window_seconds=3600
        )
        gate_b = PostgresPublicTrialAbuseGate(
            database.connection, max_requests=3, window_seconds=3600
        )
        now = datetime(2026, 10, 20, 15, tzinfo=UTC)

        # Separate gateway instances must share one committed limit.
        def attempt(index: int) -> bool:
            gate = gate_a if index % 2 else gate_b
            return gate.allow("198.51.100.24", now)

        with ThreadPoolExecutor(max_workers=8) as pool:
            admissions = list(pool.map(attempt, range(12)))
        assert admissions.count(True) == 3
        assert admissions.count(False) == 9

        with database.connection() as conn:
            records = conn.execute(
                "SELECT scope_key, window_start, hits "
                "FROM fm_public_trial_rate_windows"
            ).fetchall()
        assert len(records) == 1
        assert records[0][2] == 3
        assert "198.51.100.24" not in str(records)
        assert gate_a.allow("198.51.100.25", now)
        assert gate_b.allow("198.51.100.24", now + timedelta(hours=1))

        # A missing persistence authority may never downgrade to memory.
        with database.connection() as conn:
            conn.execute("DROP TABLE fm_public_trial_rate_windows")
        assert not gate_a.allow("198.51.100.24", now)
    finally:
        database.close()
