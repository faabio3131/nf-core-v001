from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from kordena_fiscal.control_plane.models import AdminPrincipal, ControlPlanePermission
from kordena_fiscal.control_plane.pricing_admin import CommercialPricingAdministrationService
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    CommercialPricingError,
    PlanDefinition,
    PriceDefinition,
)
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    PortalRole,
    ScryptPasswordHasher,
)

DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"
NOW = datetime(2026, 9, 27, 18, 30, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is required for PostgreSQL pricing certification")
    return value


@pytest.fixture
def database() -> PostgresFiscalDatabase:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    database = PostgresFiscalDatabase(dsn)
    assert database.initialize() == tuple(range(1, 20))
    try:
        yield database
    finally:
        database.close()


def _configuration(version: int) -> CommercialPricingConfiguration:
    price = PriceDefinition(
        price_id="synthetic-durable-monthly",
        currency="BRL",
        cadence=BillingCadence.MONTHLY,
        base_amount=Decimal("321.00"),
    )
    return CommercialPricingConfiguration(
        configuration_id="synthetic-durable-pricing",
        version=version,
        prices=(price,),
        plans=(
            PlanDefinition(
                plan_id="synthetic-durable-plan",
                display_name="Synthetic Durable Plan",
                edition_id="synthetic",
                price_ids=(price.price_id,),
            ),
        ),
    )


def _actor() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="fm-pricing-platform-admin",
        permissions=frozenset({ControlPlanePermission.COMMERCIAL_CONFIG_WRITE}),
        global_scope=True,
    )


def test_pricing_catalog_is_durable_versioned_and_audited(
    database: PostgresFiscalDatabase,
) -> None:
    first_service = CommercialPricingAdministrationService(database.pricing_catalog())
    first_service.publish(
        actor=_actor(),
        configuration=_configuration(1),
        expected_version=None,
        correlation_id="pricing-durable-v1",
        published_at=NOW,
    )

    reloaded = CommercialPricingAdministrationService(database.pricing_catalog())
    assert reloaded.current == _configuration(1)
    assert reloaded.history()[0].actor_id == "fm-pricing-platform-admin"
    assert reloaded.history()[0].correlation_id == "pricing-durable-v1"

    second = reloaded.publish(
        actor=_actor(),
        configuration=_configuration(2),
        expected_version=1,
        correlation_id="pricing-durable-v2",
        published_at=NOW,
    )
    assert second.version == 2
    assert [item.configuration.version for item in reloaded.history()] == [2, 1]

    with pytest.raises(CommercialPricingError, match="version conflict"):
        reloaded.publish(
            actor=_actor(),
            configuration=_configuration(3),
            expected_version=1,
            correlation_id="stale-writer",
            published_at=NOW,
        )


def test_platform_admin_authority_survives_postgres_reload(
    database: PostgresFiscalDatabase,
) -> None:
    hasher = ScryptPasswordHasher()
    account = HumanAccount(
        account_id="fm-platform-operator",
        email="platform-operator@example.com",
        password_hash=hasher.hash("platform-operator-password-2026"),
        tenant_id="fm-platform",
        role=PortalRole.OWNER,
        platform_admin=True,
    )

    database.human_accounts().save(account)
    loaded = database.human_accounts().by_id(account.account_id)

    assert loaded is not None
    assert loaded.platform_admin is True
    assert loaded.is_platform_admin is True
