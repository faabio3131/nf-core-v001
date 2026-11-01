from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from kordena_fiscal.persistence.commercial_fulfillment import (
    postgres_canonical_commercial_database,
)
from kordena_fiscal.persistence.postgres import (
    _COMMERCIAL_RELEASE_SCHEMA,
    _HUMAN_SCHEMA,
    _PRICING_SCHEMA,
    PostgresFiscalDatabase,
    _translate_ddl,
)
from kordena_fiscal.persistence.sqlite import _MIGRATIONS
from kordena_fiscal.product.billing import (
    CommercialPlan,
    CommercialSubscription,
    SubscriptionStatus,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CommercialAcquisitionRecord,
    CommercialClaimRecord,
    CommercialEventReceipt,
    CommercialEventType,
    CommercialFulfillmentError,
    CommercialPurchaseRecord,
    CommercialPurchaseState,
    DurableCommercialSubscription,
    commercial_purchase_id,
)

DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"
NOW = datetime(2026, 9, 28, 1, 45, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is required for PostgreSQL commercial certification")
    return value


@pytest.fixture
def database() -> PostgresFiscalDatabase:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    database = PostgresFiscalDatabase(dsn)
    assert database.initialize() == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18)
    try:
        yield database
    finally:
        database.close()


def _receipt(provider: str, event_id: str, order_id: str) -> CommercialEventReceipt:
    return CommercialEventReceipt(
        provider_id=provider,
        event_id=event_id,
        event_type=CommercialEventType.SALE_CONFIRMED,
        external_order_id=order_id,
        purchase_id=commercial_purchase_id(provider, order_id),
        occurred_at=NOW,
        received_at=NOW,
    )


def _purchase(provider: str, order_id: str) -> CommercialPurchaseRecord:
    return CommercialPurchaseRecord(
        purchase_id=commercial_purchase_id(provider, order_id),
        provider_id=provider,
        external_order_id=order_id,
        plan_id="growth",
        price_id="growth-monthly",
        state=CommercialPurchaseState.UNCLAIMED,
        created_at=NOW,
        updated_at=NOW,
        last_event_at=NOW,
        last_event_id=f"evt-{provider}-{order_id}",
        buyer_email=f"owner-{provider}@example.com",
        external_customer_id=f"customer-{provider}",
    )


def test_event_receipts_are_idempotent_and_replay_mismatch_fails_closed(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    receipt = _receipt("cakto", "evt-1", "order-1")

    with commercial() as uow:
        stored, replay = uow.commercial.receive_event(receipt)
        assert stored == receipt
        assert replay is False
        uow.commit()

    with commercial() as uow:
        stored, replay = uow.commercial.receive_event(receipt)
        assert stored == receipt
        assert replay is True
        uow.commit()

    forged = _receipt("cakto", "evt-1", "different-order")
    with pytest.raises(CommercialFulfillmentError, match="different content"):
        with commercial() as uow:
            uow.commercial.receive_event(forged)


def test_same_external_order_is_isolated_by_provider(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    cakto = _purchase("cakto", "shared-order")
    hotmart = _purchase("hotmart", "shared-order")

    with commercial() as uow:
        uow.commercial.put_purchase(cakto)
        uow.commercial.put_purchase(hotmart)
        uow.commit()

    with commercial() as uow:
        assert (
            uow.commercial.get_purchase_by_external_order("cakto", "shared-order")
            == cakto
        )
        assert (
            uow.commercial.get_purchase_by_external_order("hotmart", "shared-order")
            == hotmart
        )


def test_canonical_purchase_rejects_tenant_rewrite_and_stale_event(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    original = _purchase("cakto", "order-tenant")
    bound = replace(
        original,
        state=CommercialPurchaseState.PROVISIONED,
        tenant_id="tenant-a",
        account_id="owner-a",
        updated_at=NOW + timedelta(seconds=1),
        last_event_at=NOW + timedelta(seconds=1),
        last_event_id="evt-bound",
    )

    with commercial() as uow:
        uow.commercial.put_purchase(original)
        uow.commercial.put_purchase(bound)
        uow.commit()

    rewritten = replace(
        bound,
        tenant_id="tenant-b",
        updated_at=NOW + timedelta(seconds=2),
        last_event_at=NOW + timedelta(seconds=2),
        last_event_id="evt-rewrite",
    )
    with pytest.raises(CommercialFulfillmentError, match="tenant cannot change"):
        with commercial() as uow:
            uow.commercial.put_purchase(rewritten)

    stale = replace(
        bound,
        updated_at=NOW,
        last_event_at=NOW,
        last_event_id="evt-stale",
    )
    with pytest.raises(CommercialFulfillmentError, match="stale"):
        with commercial() as uow:
            uow.commercial.put_purchase(stale)


def test_subscription_snapshot_is_durable_and_tenant_scoped(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    purchase = _purchase("hotmart", "order-subscription")

    with database.connection() as connection:
        connection.execute(
            "INSERT INTO fm_control_plane_organizations (tenant_id, legal_name) VALUES (?, ?)",
            ("tenant-a", "Tenant A"),
        )
        connection.commit()

    with commercial() as uow:
        uow.commercial.put_purchase(
            replace(
                purchase,
                state=CommercialPurchaseState.PROVISIONED,
                tenant_id="tenant-a",
                account_id="owner-a",
                updated_at=NOW + timedelta(seconds=1),
                last_event_at=NOW + timedelta(seconds=1),
                last_event_id="evt-provisioned",
            )
        )
        uow.commit()

    start = NOW
    subscription = CommercialSubscription(
        tenant_id="tenant-a",
        plan=CommercialPlan(
            "growth",
            ("documents.issue", "documents.query"),
        ),
        status=SubscriptionStatus.ACTIVE,
        period_start=start,
        period_end=start + timedelta(days=30),
    )
    durable = DurableCommercialSubscription(
        subscription_id="subscription-hotmart-a",
        purchase_id=purchase.purchase_id,
        checkpoint=subscription.checkpoint(),
        provider_id="hotmart",
        external_subscription_id="hotmart-sub-a",
        last_event_id="evt-active",
        last_event_at=NOW + timedelta(seconds=2),
    )

    with commercial() as uow:
        uow.commercial.put_subscription(durable)
        uow.commit()

    with commercial() as uow:
        assert uow.commercial.get_subscription(durable.subscription_id) == durable
        assert (
            uow.commercial.get_subscription_by_external_reference(
                "hotmart", "hotmart-sub-a"
            )
            == durable
        )
        assert uow.commercial.get_subscription_for_tenant("tenant-a") == durable
        assert uow.commercial.get_subscription_for_tenant("tenant-b") is None


def test_migration_9_upgrades_an_existing_version_8_database() -> None:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
        connection.execute(
            """
            CREATE TABLE fm_schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for version in range(1, 9):
            connection.execute(
                """
                INSERT INTO fm_schema_migrations (version, name, applied_at)
                VALUES (%s, %s, %s)
                """,
                (version, f"existing-{version}", NOW.isoformat()),
            )
        for migration in _MIGRATIONS:
            for statement in migration.statements:
                connection.execute(_translate_ddl(statement))
        for schema in (_HUMAN_SCHEMA, _PRICING_SCHEMA, _COMMERCIAL_RELEASE_SCHEMA):
            for statement in schema:
                connection.execute(statement)
        connection.execute(
            "INSERT INTO fm_fiscal_lifecycle VALUES (%s, %s, %s, %s, %s)",
            ("legacy-v8", "draft", 0, NOW.isoformat(), "[]"),
        )

    database = PostgresFiscalDatabase(dsn)
    try:
        assert database.initialize() == (9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
        assert database.applied_migrations() == tuple(range(1, 20))
        with database.connection() as connection:
            assert connection.execute(
                "SELECT document_id, tenant_id, unit_id FROM fm_fiscal_lifecycle"
            ).fetchone() == ("legacy-v8", None, None)
        with database.connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM fm_commercial_purchases"
            ).fetchone() == (0,)
    finally:
        database.close()


def test_commercial_claim_rotates_digest_and_consumes_once(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    candidate = _purchase("hotmart", "order-claim")

    with commercial() as uow:
        uow.commercial.put_purchase(candidate)
        first = CommercialClaimRecord(
            claim_id="claim-first",
            purchase_id=candidate.purchase_id,
            token_sha256="a" * 64,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        uow.commercial.put_claim(first)
        uow.commit()

    with commercial() as uow:
        assert uow.commercial.get_claim_by_digest("a" * 64) == first
        rotated = CommercialClaimRecord(
            claim_id="claim-second",
            purchase_id=candidate.purchase_id,
            token_sha256="b" * 64,
            created_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1, minutes=1),
        )
        uow.commercial.put_claim(rotated)
        uow.commit()

    with commercial() as uow:
        assert uow.commercial.get_claim_by_digest("a" * 64) is None
        assert uow.commercial.get_claim_by_digest("b" * 64) == rotated
        assert uow.commercial.consume_claim(
            rotated.claim_id,
            NOW + timedelta(minutes=2),
        )
        assert not uow.commercial.consume_claim(
            rotated.claim_id,
            NOW + timedelta(minutes=3),
        )
        uow.commit()

    with commercial() as uow:
        used = uow.commercial.get_claim_for_purchase(candidate.purchase_id)
        assert used is not None
        assert used.used_at == NOW + timedelta(minutes=2)


def test_legal_name_becomes_immutable_after_claim_identity_resolution(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    original = _purchase("cakto", "order-legal-name")
    resolved = replace(
        original,
        legal_name="ACME Tecnologia LTDA",
        tenant_id="tenant-internal-1",
        state=CommercialPurchaseState.READY_TO_PROVISION,
        updated_at=NOW + timedelta(minutes=1),
    )

    with commercial() as uow:
        uow.commercial.put_purchase(original)
        uow.commercial.put_purchase(resolved)
        uow.commit()

    conflicting = replace(
        resolved,
        legal_name="Outra Empresa LTDA",
        updated_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(CommercialFulfillmentError, match="legal name cannot change"):
        with commercial() as uow:
            uow.commercial.put_purchase(conflicting)


def test_migration_10_upgrades_existing_version_9_state() -> None:
    dsn = _dsn()
    database = PostgresFiscalDatabase(dsn)
    try:
        database.initialize()
    finally:
        database.close()

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM fm_schema_migrations WHERE version = 10")
        connection.execute("DROP TABLE IF EXISTS fm_commercial_claims")
        connection.execute("ALTER TABLE fm_commercial_purchases DROP COLUMN IF EXISTS legal_name")

    database = PostgresFiscalDatabase(dsn)
    try:
        assert database.initialize() == (10,)
        assert database.applied_migrations() == tuple(range(1, 20))
        with database.connection() as connection:
            columns = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'fm_commercial_purchases'
                """
            ).fetchall()
            assert ("legal_name",) in columns
            assert connection.execute(
                "SELECT COUNT(*) FROM fm_commercial_claims"
            ).fetchone() == (0,)
    finally:
        database.close()


def test_first_party_acquisition_is_durable_and_idempotency_is_hashed(
    database: PostgresFiscalDatabase,
) -> None:
    commercial = postgres_canonical_commercial_database(database)
    acquisition = CommercialAcquisitionRecord(
        acquisition_id="acq-0123456789abcdef0123456789abcdef",
        idempotency_sha256="c" * 64,
        request_sha256="d" * 64,
        provider_id="synthetic",
        plan_id="growth",
        price_id="growth-monthly",
        buyer_email="owner@example.com",
        legal_name="ACME Tecnologia LTDA",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )

    with commercial() as uow:
        uow.commercial.put_acquisition(acquisition)
        uow.commit()

    with commercial() as uow:
        assert uow.commercial.get_acquisition(acquisition.acquisition_id) == acquisition
        assert (
            uow.commercial.get_acquisition_by_idempotency("c" * 64)
            == acquisition
        )

    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT idempotency_sha256, request_sha256
            FROM fm_commercial_acquisitions
            WHERE acquisition_id = ?
            """,
            (acquisition.acquisition_id,),
        ).fetchone()
    assert row == ("c" * 64, "d" * 64)


def test_migration_11_upgrades_existing_version_10_state() -> None:
    dsn = _dsn()
    database = PostgresFiscalDatabase(dsn)
    try:
        database.initialize()
    finally:
        database.close()

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM fm_schema_migrations WHERE version = 11")
        connection.execute("DROP TABLE IF EXISTS fm_commercial_acquisitions")

    database = PostgresFiscalDatabase(dsn)
    try:
        assert database.initialize() == (11,)
        assert database.applied_migrations() == tuple(range(1, 20))
        with database.connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM fm_commercial_acquisitions"
            ).fetchone() == (0,)
    finally:
        database.close()


def test_migration_12_upgrades_existing_version_11_state() -> None:
    dsn = _dsn()
    database = PostgresFiscalDatabase(dsn)
    try:
        database.initialize()
    finally:
        database.close()

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM fm_schema_migrations WHERE version = 12")
        connection.execute(
            "ALTER TABLE fm_commercial_purchases DROP COLUMN IF EXISTS billing_status"
        )
        connection.execute(
            "DROP INDEX IF EXISTS fm_commercial_purchases_subscription_idx"
        )

    database = PostgresFiscalDatabase(dsn)
    try:
        assert database.initialize() == (12,)
        assert database.applied_migrations() == tuple(range(1, 20))
        with database.connection() as connection:
            columns = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'fm_commercial_purchases'
                """
            ).fetchall()
            assert ("billing_status",) in columns
    finally:
        database.close()
