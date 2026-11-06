"""Post-payment customer claim/activation HTTP boundary.

Lets a paying customer, who has received a one-time claim link by email after an
upstream checkout provider (e.g. Cakto) confirms payment, self-activate their
canonical commercial purchase without ever disclosing account existence, trusting
a client-supplied tenant/identity, or exposing a raw reset/activation token to any
caller other than the delivery adapter.

This router is provider-neutral: it never talks to Cakto, Command or any other
checkout provider directly. It only consumes the already-certified
``CommercialClaimService`` (token issuance/consumption) and
``CommercialCustomerActivationService`` (canonical provisioning) boundaries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.application.commercial_activation import (
    CommercialCustomerActivationService,
)
from kordena_fiscal.application.commercial_claim import CommercialClaimService
from kordena_fiscal.product.commercial_fulfillment import CommercialFulfillmentError
from kordena_fiscal.web.human_recovery import PasswordResetDelivery

_MAX_BODY_BYTES = 4096


def create_commercial_claim_router(
    claim: CommercialClaimService,
    *,
    activation: CommercialCustomerActivationService,
    delivery: PasswordResetDelivery,
    now: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Expose claim completion without leaking tokens, emails or account existence."""

    now_provider = now or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["public-commercial-claim"])

    @router.post("/v1/commercial/claim")
    async def complete_commercial_claim(request: Request) -> JSONResponse:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(status_code=415, content={"detail": "JSON required"})
        if request.headers.get("cookie") or request.headers.get("authorization"):
            return JSONResponse(
                status_code=403,
                content={"detail": "anonymous request required"},
            )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > _MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "payload too large"})
            body.extend(chunk)
        try:
            payload = json.loads(bytes(body))
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(status_code=400, content={"detail": "invalid JSON"})
        fields = {"claim_token", "legal_name"}
        if not isinstance(payload, dict) or set(payload) != fields or not all(
            isinstance(payload[field], str) for field in fields
        ):
            return JSONResponse(status_code=400, content={"detail": "invalid claim fields"})

        now = now_provider()
        try:
            completion = claim.complete(
                claim_token=payload["claim_token"],
                legal_name=payload["legal_name"],
                now=now,
            )
        except CommercialFulfillmentError:
            # Never distinguish "not found", "expired" and "already used" to a
            # caller who only has a token: all are indistinguishable misuse.
            return JSONResponse(status_code=409, content={"detail": "claim unavailable"})
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "claim temporarily unavailable"},
            )

        if completion.manual_review:
            return JSONResponse(
                status_code=202,
                content={"status": "manual_review", "purchase_id": completion.purchase.purchase_id},
            )

        try:
            provisioned = activation.provision(
                purchase_id=completion.purchase.purchase_id,
                now=now,
            )
        except CommercialFulfillmentError:
            return JSONResponse(status_code=409, content={"detail": "activation unavailable"})
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "activation temporarily unavailable"},
            )

        buyer_email = provisioned.purchase.buyer_email
        if buyer_email is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "activation temporarily unavailable"},
            )
        try:
            delivery.deliver(email=buyer_email, reset=provisioned.activation_reset)
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"detail": "activation delivery unavailable"},
            )

        return JSONResponse(
            status_code=200,
            content={
                "status": "activated",
                "purchase_id": provisioned.purchase.purchase_id,
                "tenant_id": provisioned.purchase.tenant_id,
            },
        )

    return router


__all__ = ["create_commercial_claim_router"]
