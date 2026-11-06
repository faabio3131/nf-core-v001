from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest

from kordena_fiscal.persistence.cakto import postgres_cakto_commercial_database
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.product.cakto import (
    CaktoInboxStatus,
    CaktoPlanBinding,
    CaktoWebhookEvent,
    CaktoWebhookInboxEntry,
)

DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"
NOW = datetime(2026, 9, 15, 20, 15, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is required for real PostgreSQL certification")
    return value


def test_cakto_schema_and_plan_mapping_are_durable_on_postgres() -> None:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    core = PostgresFiscalDatabase(dsn)
    try:
        core.initialize()
        cakto = postgres_cakto_commercial_database(core)
        assert cakto.initialize() is True
        assert cakto.initialize() is False
        binding = CaktoPlanBinding(
            external_product_id="product-postgres",
            external_offer_id="offer-postgres",
            plan_id="pro",
            entitlement_ids=("portal",),
        )
        with cakto() as uow:
            uow.commercial.put_cakto_plan_binding(binding)
            uow.commit()
        with cakto() as uow:
            restored = uow.commercial.resolve_cakto_plan_binding(
                "product-postgres", "offer-postgres"
            )
            listed = uow.commercial.list_cakto_plan_bindings()
        assert restored == binding
        assert listed == (binding,)
    finally:
        core.close()


def test_cakto_schema_v2_persists_only_opaque_correlation_metadata() -> None:
    dsn = _dsn()
    core = PostgresFiscalDatabase(dsn)
    try:
        core.initialize()
        cakto = postgres_cakto_commercial_database(core)
        cakto.initialize()
        entry = CaktoWebhookInboxEntry(
            event_key="purchase_approved:order-v2",
            event_type=CaktoWebhookEvent.PURCHASE_APPROVED,
            order_id="order-v2",
            external_product_id="product-postgres",
            external_offer_id="offer-postgres",
            external_customer_id="customer-481920",
            order_status="paid",
            occurred_at=NOW,
            payload_sha256="a" * 64,
            received_at=NOW,
            callback_token="acq-0123456789abcdef0123456789abcdef",
            external_subscription_id="sub-postgres-1",
            status=CaktoInboxStatus.RECEIVED,
        )
        with cakto() as uow:
            uow.commercial.receive_cakto_event(entry)
            uow.commit()
        with cakto() as uow:
            restored = uow.commercial.get_cakto_event(entry.event_key)
        assert restored == entry
        assert restored is not None
        assert restored.callback_token == entry.callback_token
        assert restored.external_subscription_id == "sub-postgres-1"
    finally:
        core.close()


def test_cakto_schema_upgrades_existing_v1_to_v2_without_dropping_history() -> None:
    dsn = _dsn()
    core = PostgresFiscalDatabase(dsn)
    try:
        core.initialize()
        cakto = postgres_cakto_commercial_database(core)
        cakto.initialize()
        with core.connection() as connection:
            connection.execute(
                "DELETE FROM fm_cakto_schema_migrations WHERE version = 2"
            )
            connection.execute(
                "ALTER TABLE fm_cakto_webhook_inbox DROP COLUMN IF EXISTS callback_token"
            )
            connection.execute(
                "ALTER TABLE fm_cakto_webhook_inbox DROP COLUMN IF EXISTS external_subscription_id"
            )
            connection.commit()

        upgraded = postgres_cakto_commercial_database(core)
        assert upgraded.initialize() is True
        assert upgraded.initialize() is False
        with core.connection() as connection:
            versions = connection.execute(
                "SELECT version FROM fm_cakto_schema_migrations ORDER BY version"
            ).fetchall()
            columns = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'fm_cakto_webhook_inbox'
                """
            ).fetchall()
        assert tuple(versions) == ((1,), (2,), (3,))
        assert ("callback_token",) in columns
        assert ("external_subscription_id",) in columns
    finally:
        core.close()
