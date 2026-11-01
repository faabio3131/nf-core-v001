"""Signed server-to-server HTTP boundary for first-party NFCore acquisitions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.application.commercial_acquisition import (
    CommercialAcquisitionService,
)
from kordena_fiscal.product.commercial_fulfillment import CommercialFulfillmentError
from kordena_fiscal.security.s2s import (
    FixedWindowRateLimiter,
    WebhookSecurity,
    WebhookSignature,
    WebhookSignatureError,
)

MAX_ACQUISITION_BODY_BYTES = 64 * 1024


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def create_commercial_acquisition_router(
    service: CommercialAcquisitionService,
    *,
    security: WebhookSecurity,
    rate_limiter: FixedWindowRateLimiter,
) -> APIRouter:
    router = APIRouter(tags=["commercial-acquisition"])

    @router.post("/v1/commercial/acquisitions")
    async def begin_acquisition(request: Request) -> JSONResponse:
        now = datetime.now(UTC)
        # Bound untrusted bodies before signature verification or JSON parsing.
        # Reading the complete request here permits unbounded memory allocation.
        body_buffer = bytearray()
        async for chunk in request.stream():
            if len(body_buffer) + len(chunk) > MAX_ACQUISITION_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "commercial acquisition body too large"},
                )
            body_buffer.extend(chunk)
        body = bytes(body_buffer)
        raw_signature = request.headers.get("X-NFCore-Signature", "").strip()
        if not raw_signature:
            return JSONResponse(
                status_code=401,
                content={"detail": "commercial workload authentication is required"},
            )
        try:
            signature = WebhookSignature.parse(raw_signature)
            security.verify(body, signature, now=now)
        except (WebhookSignatureError, ValueError):
            return JSONResponse(
                status_code=401,
                content={"detail": "commercial workload authentication failed"},
            )
        if not rate_limiter.allow(signature.key_id, now):
            return JSONResponse(
                status_code=429,
                content={"detail": "commercial acquisition rate limit exceeded"},
            )

        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency-Key is required"},
            )
        if not (
            16 <= len(idempotency_key) <= 128
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            return JSONResponse(
                status_code=400,
                content={"detail": "Idempotency-Key is invalid"},
            )
        try:
            payload = json.loads(body, object_pairs_hook=_unique_json_pairs)
        except (UnicodeDecodeError, ValueError):
            return JSONResponse(
                status_code=400,
                content={"detail": "commercial acquisition body must be valid JSON"},
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                status_code=400,
                content={"detail": "commercial acquisition body must be an object"},
            )
        required = {"plan_id", "price_id", "buyer_email", "legal_name"}
        if set(payload) != required or not all(
            isinstance(payload.get(field), str) for field in required
        ):
            return JSONResponse(
                status_code=400,
                content={"detail": "commercial acquisition fields are invalid"},
            )

        try:
            started = service.begin(
                plan_id=payload["plan_id"],
                price_id=payload["price_id"],
                buyer_email=payload["buyer_email"],
                legal_name=payload["legal_name"],
                idempotency_key=idempotency_key,
                now=now,
            )
        except CommercialFulfillmentError as exc:
            message = str(exc)
            not_ready = "not operationally ready" in message
            return JSONResponse(
                status_code=503 if not_ready else 409,
                content={
                    "detail": (
                        "commercial purchase path is unavailable"
                        if not_ready
                        else "commercial acquisition could not be created"
                    )
                },
            )

        return JSONResponse(
            status_code=200 if started.replay else 201,
            content={
                "acquisition_reference": started.acquisition_reference,
                "provider": started.provider_id,
                "checkout_url": started.checkout_url,
                "expires_at": started.expires_at.isoformat(),
                "replay": started.replay,
            },
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    return router


__all__ = ["create_commercial_acquisition_router"]
