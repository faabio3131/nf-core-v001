"""Opt-in public trial intake backed by the existing governed commercial service.

No S2S secret in browsers, no authority from client-supplied tenant fields.
Deployment requires explicit allowlisted origin, activation delivery and an
external shared anti-abuse gate; never automatically enabled in runtime.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.application.commercial_trial import GovernedTrialService, TrialPricingReader
from kordena_fiscal.product.commercial_fulfillment import CommercialFulfillmentError
from kordena_fiscal.web.human_recovery import PasswordResetDelivery


class PublicTrialAbuseGate(Protocol):
    """Atomically decide trial admission across all application replicas."""

    def allow(self, identity: str, now: datetime) -> bool: ...


def create_public_trial_router(
    service: GovernedTrialService,
    *,
    pricing: TrialPricingReader,
    allowed_origins: tuple[str, ...],
    rate_limiter: PublicTrialAbuseGate,
    delivery: PasswordResetDelivery,
    commercially_authorized: Callable[[], bool] | None = None,
) -> APIRouter:
    """Produce first-party trial ingress without modifying the signed S2S route."""
    if not allowed_origins or any(
        urlsplit(value).scheme != "https"
        or not urlsplit(value).netloc
        or urlsplit(value).username is not None
        or urlsplit(value).password is not None
        or urlsplit(value).path not in ("", "/")
        or urlsplit(value).query
        or urlsplit(value).fragment
        or value.rstrip("/") != value
        for value in allowed_origins
    ):
        raise ValueError("public trial requires explicit HTTPS origins")

    router = APIRouter(tags=["public-commercial-trial"])

    def release_allowed() -> bool:
        # The production composition binds the existing human-approved release.
        # A failed/absent release reader is never interpreted as approval.
        if commercially_authorized is None:
            return False
        try:
            return commercially_authorized() is True
        except Exception:
            return False

    # Same-origin browser POST supplies Origin without weakening the allowlist.
    @router.post("/v1/public/trial-plans")
    @router.get("/v1/public/trial-plans")
    async def published_trial_plans(request: Request) -> JSONResponse:
        origin = request.headers.get("origin", "")
        if origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "origin denied"})
        headers = {
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
        }
        if not release_allowed():
            return JSONResponse(
                status_code=503,
                content={"detail": "trial offers not released"},
                headers=headers,
            )
        try:
            catalog = pricing.current
            if catalog is None:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "trial plans not published"},
                    headers=headers,
                )
            entries = []
            for plan in catalog.plans:
                if not plan.enabled or plan.trial_days < 1:
                    continue
                for price_id in plan.price_ids:
                    price = catalog.price(price_id)
                    if price.enabled:
                        entries.append({
                            "plan_id": plan.plan_id,
                            "price_id": price.price_id,
                            "display_name": plan.display_name,
                            "trial_days": plan.trial_days,
                            "currency": price.currency,
                            "billing_cadence": price.cadence.value,
                            "base_amount": str(price.base_amount),
                        })
        except Exception:
            # The pricing authority is unavailable: never synthesize public offers.
            return JSONResponse(
                status_code=503,
                content={"detail": "trial plans temporarily unavailable"},
                headers=headers,
            )
        return JSONResponse(
            status_code=200,
            content={"plans": entries},
            headers=headers,
        )

    @router.options("/v1/public/trials")
    async def public_trial_preflight(request: Request) -> JSONResponse:
        origin = request.headers.get("origin", "")
        if origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "origin denied"})
        requested = {
            item.strip().lower()
            for item in request.headers.get("access-control-request-headers", "").split(",")
            if item.strip()
        }
        if request.headers.get("access-control-request-method", "") != "POST" or not (
            requested <= {"content-type", "idempotency-key"}
        ):
            return JSONResponse(status_code=403, content={"detail": "preflight denied"})
        return JSONResponse(
            status_code=200,
            content={},
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key",
                "Access-Control-Max-Age": "600",
                "Cache-Control": "no-store",
                "Vary": "Origin",
            },
        )

    def _strict_trial_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Reject ambiguous JSON objects at every nesting level."""
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    @router.post("/v1/public/trials")
    async def public_trial(request: Request) -> JSONResponse:
        origin = request.headers.get("origin", "")
        headers = {"Cache-Control": "no-store, max-age=0"}
        if origin not in allowed_origins:
            return JSONResponse(
                status_code=403,
                content={"detail": "origin denied"},
                headers=headers,
            )
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
        if not release_allowed():
            return JSONResponse(
                status_code=503,
                content={"detail": "trial not released"},
                headers=headers,
            )
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(
                status_code=415,
                content={"detail": "JSON required"},
                headers=headers,
            )
        if request.headers.get("cookie") or request.headers.get("authorization"):
            return JSONResponse(
                status_code=403,
                content={"detail": "anonymous request required"},
                headers=headers,
            )
        identity = request.client.host if request.client is not None else "unknown"
        if not rate_limiter.allow(f"public-trial:{identity}", datetime.now(UTC)):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limited"},
                headers=headers,
            )
        key = request.headers.get("Idempotency-Key", "").strip()
        if not (16 <= len(key) <= 128 and key.isascii() and key.isprintable()):
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid idempotency key"},
                headers=headers,
            )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 4096:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "payload too large"},
                    headers=headers,
                )
            body.extend(chunk)
        try:
            payload = json.loads(bytes(body), object_pairs_hook=_strict_trial_json_pairs)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid JSON"},
                headers=headers,
            )
        fields = {"plan_id", "price_id", "buyer_email", "legal_name"}
        if not isinstance(payload, dict) or set(payload) != fields or not all(
            isinstance(payload[field], str) for field in fields
        ):
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid trial fields"},
                headers=headers,
            )
        now = datetime.now(UTC)
        try:
            started = service.begin(
                plan_id=payload["plan_id"],
                price_id=payload["price_id"],
                buyer_email=payload["buyer_email"],
                legal_name=payload["legal_name"],
                idempotency_key=key,
                now=now,
            )
        except CommercialFulfillmentError:
            return JSONResponse(
                status_code=409,
                content={"detail": "trial unavailable"},
                headers=headers,
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "trial temporarily unavailable"},
                headers=headers,
            )
        if started.activation_reset is not None:
            try:
                delivery.deliver(
                    email=payload["buyer_email"].strip().casefold(),
                    reset=started.activation_reset,
                )
            except Exception:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "activation delivery unavailable"},
                    headers=headers,
                )
        return JSONResponse(
            status_code=200 if started.replay else 201,
            content={
                "status": "trial_activation_pending",
                "trial_expires_at": started.expires_at.isoformat(),
                "replay": started.replay,
            },
            headers=headers,
        )

    return router
