"""Loopback-only browser proof with a unique disposable PostgreSQL schema.

Only activation email transport is replaced. Domain, provisioning, identity,
pricing, subscription, recovery and admission persistence are canonical.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from fastapi import FastAPI
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from kordena_fiscal.control_plane.models import AdminPrincipal, ControlPlanePermission
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    PlanDefinition,
    PriceDefinition,
)
from kordena_fiscal.runtime.composition import build_postgres_runtime_composition
from kordena_fiscal.runtime.public_trial_abuse import PostgresPublicTrialAbuseGate
from kordena_fiscal.web import create_app
from kordena_fiscal.web.public_trial import create_public_trial_router


class TestMailbox:
    def __init__(self):
        self.reset = None
        self.deliveries = 0

    def deliver(self, *, email, reset):
        assert email.endswith("@example.test")
        self.reset = reset
        self.deliveries += 1


def build_trial_app():
    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        app = FastAPI()

        @app.get("/__test/health")
        def unavailable():
            return {"postgres_configured": False}

        return app
    # The harness must never initialize a shared remote database.
    if conninfo_to_dict(dsn).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("trial browser fixture requires disposable loopback PostgreSQL")
    schema = "bld03_browser_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    uri = urlsplit(dsn)
    query = dict(parse_qsl(uri.query, keep_blank_values=True))
    query["options"] = f"-c search_path={schema}"
    isolated_dsn = urlunsplit(uri._replace(query=urlencode(query, quote_via=quote)))
    database = PostgresFiscalDatabase(isolated_dsn)
    database.initialize()
    composition = build_postgres_runtime_composition(database)
    mailbox = TestMailbox()
    now = datetime.now(UTC)
    composition.pricing_administration.publish(
        actor=AdminPrincipal(
            actor_id="synthetic-browser-admin", global_scope=True,
            permissions=frozenset({ControlPlanePermission.COMMERCIAL_CONFIG_WRITE}),
        ),
        configuration=CommercialPricingConfiguration(
            configuration_id="synthetic-browser-trial", version=1,
            prices=(PriceDefinition(
                price_id="growth-monthly", currency="BRL", cadence=BillingCadence.MONTHLY,
                base_amount=Decimal("199.00"),
            ),),
            plans=(PlanDefinition(
                plan_id="growth", display_name="Oferta sintética", edition_id="growth",
                price_ids=("growth-monthly",), trial_days=7,
            ),),
        ),
        expected_version=None, correlation_id="synthetic-browser-trial", published_at=now,
    )
    def activated(account_id, at):
        composition.commercial_activation.mark_active(account_id=account_id, now=at)

    app = create_app(
        human_identity=composition.human_identity,
        portal_executor=composition.portal_executor,
        human_login_completed=activated,
        password_reset_completed=activated,
        password_recovery=composition.password_recovery,
        password_reset_delivery=mailbox,
    )
    app.include_router(create_public_trial_router(
        composition.commercial_trial,
        pricing=composition.pricing_administration,
        allowed_origins=("https://127.0.0.1:4176",),
        rate_limiter=PostgresPublicTrialAbuseGate(database.connection),
        delivery=mailbox,
        commercially_authorized=lambda: True,  # Synthetic browser harness only.
    ))

    @app.get("/__test/health")
    def health():
        return {"postgres_configured": True}

    @app.get("/__test/trial-proof")
    def proof():
        with database.connection() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "fm_commercial_purchases", "fm_commercial_subscriptions",
                    "fm_human_accounts", "fm_control_plane_organizations",
                )
            }
            subscription = connection.execute(
                "SELECT subscription_id, status, period_start, period_end "
                "FROM fm_commercial_subscriptions"
            ).fetchone()
        owner = database.human_accounts().by_email("browser-owner@example.test")
        # Synthetic mailbox is visible only in this loopback test harness.
        return {
            "counts": counts, "deliveries": mailbox.deliveries,
            "subscription_id": subscription[0] if subscription else None,
            "subscription_status": subscription[1] if subscription else None,
            "period_start": subscription[2] if subscription else None,
            "period_end": subscription[3] if subscription else None,
            "owner_role": owner.role.value if owner else None,
            "reset_token": mailbox.reset.reset_token if mailbox.reset else None,
        }

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            database.close()
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    app.router.lifespan_context = lifespan
    return app
