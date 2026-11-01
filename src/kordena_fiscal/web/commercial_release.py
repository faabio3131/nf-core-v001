"""Public and platform-admin HTTP surfaces for commercial release governance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, Response, status

from kordena_fiscal.control_plane.commercial_release import (
    CommercialReleaseAdministrationService,
)
from kordena_fiscal.control_plane.pricing_admin import (
    CommercialPricingAdministrationService,
)
from kordena_fiscal.product.checkout import (
    CommercialCheckoutProjector,
    unconfigured_checkout_projection,
)
from kordena_fiscal.product.commercial_readiness import (
    CommercialDeliveryPathReadiness,
    commercial_purchase_ready,
)
from kordena_fiscal.product.commercial_release import (
    CommercialReleaseDecision,
    CommercialReleaseError,
)
from kordena_fiscal.runtime.observability import MetricsRegistry
from kordena_fiscal.security.human_identity import HumanIdentityService
from kordena_fiscal.web.portal_api import _csrf
from kordena_fiscal.web.pricing_admin import _platform_actor, _public_catalog


def create_commercial_release_router(
    identity: HumanIdentityService,
    pricing: CommercialPricingAdministrationService,
    release: CommercialReleaseAdministrationService,
    checkout: CommercialCheckoutProjector | None = None,
    *,
    checkout_processing_configured: bool = False,
    trial_ingress_configured: bool = False,
    trial_site_channel_configured: bool = False,
    public_trial_configured: bool = False,
    delivery_readiness: CommercialDeliveryPathReadiness | None = None,
    operational_readiness: Callable[[], bool] | None = None,
    trial_operational_readiness: Callable[[], bool] | None = None,
    runtime_metrics: MetricsRegistry | None = None,
) -> APIRouter:
    router = APIRouter(tags=["commercial-release"])
    resolved_delivery_readiness = delivery_readiness or CommercialDeliveryPathReadiness()

    @router.get("/v1/commercial/offer")
    async def public_offer(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        try:
            pricing_current = pricing.current
            release_current = release.current
            checkout_projection = (
                unconfigured_checkout_projection()
                if checkout is None
                else checkout.project(pricing_current)
            )
        except Exception:
            # Loss of a canonical reader must not expose a cached charge URL.
            pricing_current = None
            release_current = None
            checkout_projection = unconfigured_checkout_projection()
        pricing_payload: dict[str, object]
        if pricing_current is None:
            pricing_payload = {
                "status": "unpriced",
                "catalog": None,
            }
        else:
            pricing_payload = {
                "status": "published",
                "catalog": _public_catalog(pricing_current),
            }

        release_payload: dict[str, object] = {
            "status": "unavailable",
            "version": None,
            "public_message": None,
            "commercially_approved": False,
        }
        if release_current is not None:
            release_payload = {
                "status": release_current.status.value,
                "version": release_current.version,
                "public_message": release_current.public_message,
                "commercially_approved": release_current.commercially_approved,
            }

        processing_configured = (
            checkout is not None and checkout_processing_configured
            and checkout_projection.provider == checkout.provider_id
        )
        purchase_enabled = commercial_purchase_ready(
            release=release_current,
            pricing=pricing_current,
            checkout=checkout_projection,
            checkout_processing_configured=processing_configured,
            delivery=resolved_delivery_readiness,
            operational_readiness=operational_readiness,
        )
        # Public trial and signed site-to-site trial are distinct authorized
        # channels. Only the signed channel requires remote HMAC attestation;
        # the browser channel requires explicit Origin and shared PG admission.
        trial_channel_ready = public_trial_configured or (
            trial_ingress_configured and trial_site_channel_configured
        )
        trial_enabled = bool(
            release_current is not None
            and release_current.commercially_approved
            and pricing_current is not None
            and any(
                plan.enabled and plan.trial_days > 0
                and any(
                    price.enabled and price.price_id in plan.price_ids
                    for price in pricing_current.prices
                )
                for plan in pricing_current.plans
            )
            and trial_channel_ready
            and resolved_delivery_readiness.ready
        )
        if trial_enabled:
            # A trial may be issued without a payment processor; it must still
            # prove durable state, activation delivery and rate gate readiness.
            # The existing signed acquisition channel retains its old gate.
            readiness = (
                trial_operational_readiness
                if public_trial_configured
                else operational_readiness
            )
            if readiness is not None:
                try:
                    trial_enabled = readiness() is True
                except Exception:
                    trial_enabled = False
        checkout_payload = checkout_projection.to_public_mapping(
            processing_configured=processing_configured,
            expose_urls=purchase_enabled,
        )
        if runtime_metrics is not None:
            try:
                runtime_metrics.increment(
                    "nfcore_commercial_offer_observed_total",
                    outcome="available" if purchase_enabled else "blocked",
                )
            except Exception:
                pass  # Metrics are not commercial approval authority.

        return {
            "product_id": "nfcore",
            "pricing": pricing_payload,
            "release": release_payload,
            "checkout": checkout_payload,
            "purchase_enabled": purchase_enabled,
            # Neither trial_days nor signer configuration alone grants public release.
            "trial_enabled": trial_enabled,
        }

    @router.get("/v1/admin/commercial-release")
    async def admin_release(request: Request) -> dict[str, object]:
        _authority, _actor = _platform_actor(request, identity)
        current = release.current
        history = release.history()
        return {
            "current": None if current is None else current.to_mapping(),
            "history": [
                {
                    "version": publication.decision.version,
                    "status": publication.decision.status.value,
                    "public_message": publication.decision.public_message,
                    "human_decision_reference": (
                        publication.decision.human_decision_reference
                    ),
                    "actor_id": publication.actor_id,
                    "correlation_id": publication.correlation_id,
                    "published_at": publication.published_at.isoformat(),
                }
                for publication in history
            ],
        }

    @router.post("/v1/admin/commercial-release")
    async def publish_release(
        request: Request,
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, object]:
        authority, actor = _platform_actor(request, identity)
        _csrf(request, identity, authority)
        raw_decision = payload.get("decision")
        expected_version = payload.get("expected_version")
        if not isinstance(raw_decision, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_COMMERCIAL_RELEASE",
                    "message": "decision must be an object",
                },
            )
        if expected_version is not None and (
            not isinstance(expected_version, int) or isinstance(expected_version, bool)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_EXPECTED_VERSION",
                    "message": "expected_version must be integer or null",
                },
            )
        try:
            decision = CommercialReleaseDecision.from_mapping(raw_decision)
            published = release.publish(
                actor=actor,
                decision=decision,
                expected_version=expected_version,
                correlation_id=request.headers.get("X-Correlation-Id", "").strip()
                or uuid4().hex,
            )
        except CommercialReleaseError as exc:
            code = (
                status.HTTP_409_CONFLICT
                if "version" in str(exc).casefold()
                else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(
                status_code=code,
                detail={
                    "code": "COMMERCIAL_RELEASE_REJECTED",
                    "message": str(exc),
                },
            ) from exc
        return {"decision": published.to_mapping()}

    return router
