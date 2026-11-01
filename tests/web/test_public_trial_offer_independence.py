"""BLD-03: public trial readiness does not implicitly enable paid checkout."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.product.commercial_readiness import CommercialDeliveryPathReadiness
from kordena_fiscal.product.commercial_release import (
    CommercialReleaseDecision,
    CommercialReleaseStatus,
)
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    PlanDefinition,
    PriceDefinition,
)
from kordena_fiscal.security.human_identity import HumanIdentityService
from kordena_fiscal.web.commercial_release import create_commercial_release_router


def offer(
    *,
    public: bool = False,
    signed: bool = False,
    site_channel: bool = False,
    ready: bool = True,
    approve: bool = True,
    days: int = 7,
) -> dict[str, object]:
    price = PriceDefinition(
        price_id="synthetic-monthly",
        currency="BRL",
        cadence=BillingCadence.MONTHLY,
        base_amount=Decimal("50.00"),
    )
    pricing = CommercialPricingConfiguration(
        configuration_id="synthetic-offer",
        version=1,
        prices=(price,),
        plans=(
            PlanDefinition(
                plan_id="synthetic-plan",
                display_name="Synthetic",
                edition_id="synthetic",
                price_ids=(price.price_id,),
                trial_days=days,
            ),
        ),
    )
    release = (
        CommercialReleaseDecision(
            version=1,
            status=CommercialReleaseStatus.COMMERCIAL_APPROVED,
            human_decision_reference="human-approved-synthetic",
        )
        if approve else None
    )
    app = FastAPI()
    app.include_router(
        create_commercial_release_router(
            cast(HumanIdentityService, object()),
            SimpleNamespace(current=pricing),  # type: ignore[arg-type]
            SimpleNamespace(current=release),  # type: ignore[arg-type]
            trial_ingress_configured=signed,
            trial_site_channel_configured=site_channel,
            public_trial_configured=public,
            checkout=None,
            delivery_readiness=CommercialDeliveryPathReadiness(
                canonical_commercial_persistence=True,
                fulfillment=True,
                provisioning=True,
                activation_delivery=True,
            ),
            # Command checkout readiness remains separate and unavailable.
            operational_readiness=lambda: False,
            trial_operational_readiness=lambda: ready,
        )
    )
    response = TestClient(app).get("/v1/commercial/offer")
    assert response.status_code == 200
    return response.json()


def test_approved_public_trial_can_be_ready_without_paid_checkout() -> None:
    result = offer(public=True)
    assert result["trial_enabled"] is True
    assert result["purchase_enabled"] is False
    assert result["checkout"]["status"] == "unconfigured"


@pytest.mark.parametrize(
    ("case", "options"),
    [
        ("not-configured", {}),
        ("no-human-release", {"public": True, "approve": False}),
        ("missing-admission", {"public": True, "ready": False}),
        ("no-trial-days", {"public": True, "days": 0}),
        ("signed-without-site", {"signed": True}),
        ("signed-site-without-checkout", {"signed": True, "site_channel": True}),
    ],
)
def test_unready_or_unapproved_trial_never_gets_public_release(
    case: str, options: dict[str, object]
) -> None:
    assert case
    result = offer(**options)  # type: ignore[arg-type]
    assert result["trial_enabled"] is False
    assert result["purchase_enabled"] is False


def test_signed_only_trial_keeps_existing_readiness_requirement() -> None:
    assert offer(signed=True, site_channel=True, ready=True)["trial_enabled"] is False
