"""Cross-worker quota contention on a disposable PostgreSQL schema in CI."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from kordena_fiscal.cognitive.durable_usage import DurableTokenQuotaStore, QuotaDenied
from kordena_fiscal.persistence.cognitive_quota_schema import COGNITIVE_QUOTA_SCHEMA
from kordena_fiscal.persistence.postgres import _PostgresCompatConnection


def test_atomic_reservations_across_postgres_connections() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable CI PostgreSQL is not configured")
    schema = f"nfcore_cogtest_{uuid4().hex}"
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    # All objects are isolated under a unique test schema in an ephemeral CI DB.
    # Never touch public, production schemas or real subscriptions.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}")
        conn.execute(
            """CREATE TABLE fm_commercial_subscriptions (
                subscription_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                plan_id TEXT NOT NULL, status TEXT NOT NULL,
                period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                last_event_at TEXT NOT NULL
            )"""
        )
        for ddl in COGNITIVE_QUOTA_SCHEMA:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO fm_commercial_subscriptions VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                "sub-a", "tenant-a", "essencial", "active",
                (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(days=30)).isoformat(),
                now.isoformat(),
            ),
        )

    @contextmanager
    def acquire() -> Iterator[_PostgresCompatConnection]:
        with psycopg.connect(dsn, options=f"-c search_path={schema}") as raw:
            yield _PostgresCompatConnection(raw)

    quotas = DurableTokenQuotaStore(acquire, clock=lambda: now)

    def reserve(index: int) -> bool:
        try:
            return quotas.reserve(
                tenant_id="tenant-a",
                request_id=f"postgres-concurrent-{index}",
                max_input_tokens=250_000,
                max_output_tokens=75_000,
            ).created
        except QuotaDenied:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(results) == 4
    balance = quotas.balance(tenant_id="tenant-a")
    assert (balance.used_input, balance.used_output) == (1_000_000, 300_000)
    with pytest.raises(QuotaDenied, match="exhausted"):
        quotas.reserve(
            tenant_id="tenant-a", request_id="overdraw",
            max_input_tokens=1, max_output_tokens=1,
        )
