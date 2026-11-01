"""COG-02: exercise real SQL counters with simultaneous reservation attempts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kordena_fiscal.cognitive.commercial_quotas import allowance_for_subscription
from kordena_fiscal.cognitive.durable_usage import DurableTokenQuotaStore, QuotaDenied
from kordena_fiscal.persistence.cognitive_quota_schema import COGNITIVE_QUOTA_SCHEMA


@pytest.fixture
def quota_db(tmp_path: Path) -> tuple[Path, datetime]:
    path = tmp_path / "commercial.sqlite"
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE fm_commercial_subscriptions (
                subscription_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                plan_id TEXT NOT NULL, status TEXT NOT NULL,
                period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                last_event_at TEXT NOT NULL
            )"""
        )
        for ddl in COGNITIVE_QUOTA_SCHEMA:
            db.execute(ddl)
        for tenant, plan, status in (
            ("tenant-a", "essencial", "active"),
            ("tenant-b", "crescimento", "active"),
            ("tenant-trial", "anything", "trial"),
            ("tenant-suspended", "escala", "suspended"),
        ):
            db.execute(
                "INSERT INTO fm_commercial_subscriptions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"sub-{tenant}", tenant, plan, status,
                    (now - timedelta(days=1)).isoformat(),
                    (now + timedelta(days=29)).isoformat(),
                    now.isoformat(),
                ),
            )
    return path, now


def store(db: tuple[Path, datetime]) -> DurableTokenQuotaStore:
    path, now = db

    @contextmanager
    def acquire() -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(path, timeout=20)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    return DurableTokenQuotaStore(acquire, clock=lambda: now)


def test_approved_allowances_and_unknown_plan() -> None:
    for plan_id, status, expected in (
        ("any", "trial", (750_000, 210_000)),
        ("essencial", "active", (1_000_000, 300_000)),
        ("crescimento", "active", (3_000_000, 900_000)),
        ("escala", "active", (8_000_000, 2_400_000)),
    ):
        allowance = allowance_for_subscription(plan_id=plan_id, status=status)
        assert allowance is not None
        assert (allowance.input_tokens, allowance.output_tokens) == expected
    assert allowance_for_subscription(plan_id="unknown", status="active") is None
    assert allowance_for_subscription(plan_id="escala", status="suspended") is None


def test_reserve_replay_settle_and_exact_limit(quota_db: tuple[Path, datetime]) -> None:
    quota = store(quota_db)
    first = quota.reserve(
        tenant_id="tenant-a", request_id="request-1",
        max_input_tokens=700_000, max_output_tokens=200_000,
    )
    assert first.created
    replay = quota.reserve(
        tenant_id="tenant-a", request_id="request-1",
        max_input_tokens=700_000, max_output_tokens=200_000,
    )
    assert not replay.created
    with pytest.raises(QuotaDenied, match="idempotency"):
        quota.reserve(
            tenant_id="tenant-a", request_id="request-1",
            max_input_tokens=1, max_output_tokens=1,
        )
    with pytest.raises(QuotaDenied, match="exhausted"):
        quota.reserve(
            tenant_id="tenant-a", request_id="request-2",
            max_input_tokens=300_001, max_output_tokens=1,
        )
    assert quota.settle(
        tenant_id="tenant-a", request_id="request-1",
        input_tokens=600_000, output_tokens=120_000,
    )
    assert not quota.settle(
        tenant_id="tenant-a", request_id="request-1",
        input_tokens=600_000, output_tokens=120_000,
    )
    balance = quota.balance(tenant_id="tenant-a")
    assert (balance.used_input, balance.used_output) == (600_000, 120_000)
    assert quota.reserve(
        tenant_id="tenant-a", request_id="request-2",
        max_input_tokens=400_000, max_output_tokens=180_000,
    ).created
    with pytest.raises(QuotaDenied, match="exhausted"):
        quota.reserve(
            tenant_id="tenant-a", request_id="request-3",
            max_input_tokens=1, max_output_tokens=1,
        )


def test_tenant_isolation_expiry_and_suspended(quota_db: tuple[Path, datetime]) -> None:
    quota = store(quota_db)
    quota.reserve(
        tenant_id="tenant-a", request_id="same-key",
        max_input_tokens=1_000_000, max_output_tokens=300_000,
    )
    assert quota.reserve(
        tenant_id="tenant-b", request_id="same-key",
        max_input_tokens=3_000_000, max_output_tokens=900_000,
    ).created
    with pytest.raises(QuotaDenied, match="cannot consume"):
        quota.reserve(
            tenant_id="tenant-suspended", request_id="req",
            max_input_tokens=1, max_output_tokens=1,
        )
    with pytest.raises(QuotaDenied, match="unavailable"):
        quota.balance(tenant_id="tenant-unknown")
    with pytest.raises(QuotaDenied, match="exhausted"):
        quota.reserve(
            tenant_id="tenant-trial", request_id="too-large",
            max_input_tokens=750_001, max_output_tokens=1,
        )
    path, now = quota_db
    expired = DurableTokenQuotaStore(
        lambda: _acquire_sqlite(path), clock=lambda: now + timedelta(days=32)
    )
    with pytest.raises(QuotaDenied, match="expired"):
        expired.balance(tenant_id="tenant-trial")


@contextmanager
def _acquire_sqlite(path: Path) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def test_concurrent_reservations_never_overdraw(quota_db: tuple[Path, datetime]) -> None:
    quota = store(quota_db)

    def attempt(index: int) -> bool:
        try:
            return quota.reserve(
                tenant_id="tenant-a", request_id=f"parallel-{index}",
                max_input_tokens=300_000, max_output_tokens=100_000,
            ).created
        except QuotaDenied:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(results) == 3
    balance = quota.balance(tenant_id="tenant-a")
    assert (balance.used_input, balance.used_output) == (900_000, 300_000)


def test_unknown_provider_usage_keeps_reservation(quota_db: tuple[Path, datetime]) -> None:
    quota = store(quota_db)
    quota.reserve(
        tenant_id="tenant-a", request_id="timeout",
        max_input_tokens=50_000, max_output_tokens=700,
    )
    assert quota.balance(tenant_id="tenant-a").used_input == 50_000
    with pytest.raises(QuotaDenied, match="exceeded"):
        quota.settle(
            tenant_id="tenant-a", request_id="timeout",
            input_tokens=50_001, output_tokens=1,
        )
    assert quota.balance(tenant_id="tenant-a").used_input == 50_000


def test_paid_allowance_renews_monthly_inside_annual_contract(
    quota_db: tuple[Path, datetime],
) -> None:
    path, _ = quota_db
    start = datetime(2026, 1, 31, 12, tzinfo=UTC)
    with sqlite3.connect(path) as db:
        db.execute(
            """UPDATE fm_commercial_subscriptions
               SET period_start = ?, period_end = ?
               WHERE tenant_id = 'tenant-b'""",
            (start.isoformat(), datetime(2027, 1, 31, 12, tzinfo=UTC).isoformat()),
        )
    first = DurableTokenQuotaStore(
        lambda: _acquire_sqlite(path),
        clock=lambda: datetime(2026, 2, 20, 12, tzinfo=UTC),
    )
    first.reserve(
        tenant_id="tenant-b", request_id="january-period",
        max_input_tokens=3_000_000, max_output_tokens=900_000,
    )
    assert first.balance(tenant_id="tenant-b").used_input == 3_000_000
    second = DurableTokenQuotaStore(
        lambda: _acquire_sqlite(path),
        clock=lambda: datetime(2026, 3, 1, 12, tzinfo=UTC),
    )
    assert second.balance(tenant_id="tenant-b").used_input == 0
    assert second.reserve(
        tenant_id="tenant-b", request_id="february-period",
        max_input_tokens=3_000_000, max_output_tokens=900_000,
    ).created
    # Anchored to Jan 31: Feb's monthly window ends Mar 31.
    assert second.balance(tenant_id="tenant-b").period_end == datetime(
        2026, 3, 31, 12, tzinfo=UTC
    )


def test_no_trial_token_reset_after_thirty_days(
    quota_db: tuple[Path, datetime],
) -> None:
    path, now = quota_db
    with sqlite3.connect(path) as db:
        db.execute(
            """UPDATE fm_commercial_subscriptions
               SET period_end = ?
               WHERE tenant_id = 'tenant-trial'""",
            ((now + timedelta(days=80)).isoformat(),),
        )
    after_trial = DurableTokenQuotaStore(
        lambda: _acquire_sqlite(path),
        clock=lambda: now + timedelta(days=30),
    )
    with pytest.raises(QuotaDenied, match="expired"):
        after_trial.reserve(
            tenant_id="tenant-trial", request_id="too-late",
            max_input_tokens=1, max_output_tokens=1,
        )
