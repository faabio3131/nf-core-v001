"""Runtime composition and HTTP adapter for the Cakto commercial boundary.

The runtime deliberately accepts webhook secret material only by injection. Secret
resolution belongs to the external secret boundary; this module never reads secrets
from environment variables, persists them, or grants fiscal production authority.

Operational note -- claim automation logic exists; its trigger is NOT yet scheduled
-------------------------------------------------------------------------------------
``CaktoWebhookReceiver.receive()`` (built here) persists accepted Cakto events
into the canonical commercial inbox. ``CaktoCommercialProcessor.process_due()``
(also built here) later reconciles due inbox entries against canonical
purchase/subscription state via ``CaktoCanonicalCommercialBridge``.

As of this revision, ``CaktoCanonicalCommercialBridgeService``
(``application/cakto_reconciliation.py``) DOES call
``CommercialClaimService.issue()`` (via ``CaktoClaimAutomationService``,
``application/cakto_claim_automation.py``) immediately after it reconciles a
brand-new, opening Cakto payment into a canonical purchase -- idempotently
(at most one automatic claim per purchase, ever) and fail-closed (no delivery
adapter configured means no claim is minted). The issued claim is delivered to
the buyer's email (first-party acquisition email when one exists, otherwise
Cakto's self-reported webhook email as a best-effort delivery hint only --
never trusted as identity) via ``SecureCaktoClaimEmailDelivery``
(``application/cakto_claim_email.py``), wired here from
``build_cakto_claim_delivery_from_environ()`` when
``NFCORE_ACTIVATION_EMAIL_PROVIDER`` and ``NFCORE_CAKTO_CLAIM_BASE_URL`` are
both configured. Composed in ``runtime/composition.py`` as
``RuntimeComposition.cakto_canonical_bridge`` and injected into
``compose_postgres_cakto_commercial_runtime(..., canonical_bridge=...)`` by
``runtime/api.py``.

The customer still has to open the delivered link and confirm their legal
name at ``POST /v1/commercial/claim`` -- this never skips the identity-proof
step ``CommercialClaimService.complete()`` already enforces; it only removes
the manual step of starting that flow.

Remaining gap: nothing in the current runtime composition (API or Worker)
actually calls ``CaktoCommercialProcessor.process_due()`` on a schedule. Until
a worker job is wired to drain due Cakto inbox entries, an accepted webhook
sits in the inbox and the claim-automation logic above never runs for it.
Operations must still treat every Cakto webhook as requiring a manual
``process_due()`` invocation (or the pending worker wiring) until that
scheduling gap is closed. Do not read the mere existence of the webhook
route, the canonical bridge, or the claim-automation service as proof that
payments are reconciled end to end today.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request, status

from kordena_fiscal.persistence.cakto import (
    CaktoCommercialDatabase,
    postgres_cakto_commercial_database,
)
from kordena_fiscal.product.cakto import (
    CaktoAuthenticationError,
    CaktoCanonicalCommercialBridge,
    CaktoCommercialProcessor,
    CaktoMetricSink,
    CaktoPayloadError,
    CaktoStateConflictError,
    CaktoWebhookReceiver,
    CaktoWebhookVerifier,
    utc_now,
)

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CaktoCommercialRuntime:
    """Canonical commercial runtime assembled around one durable database."""

    database: CaktoCommercialDatabase
    receiver: CaktoWebhookReceiver
    processor: CaktoCommercialProcessor


def compose_cakto_commercial_runtime(
    *,
    database: CaktoCommercialDatabase,
    webhook_secret: bytes,
    metrics: CaktoMetricSink | None = None,
    canonical_bridge: CaktoCanonicalCommercialBridge | None = None,
    initialize_schema: bool = True,
) -> CaktoCommercialRuntime:
    """Compose Cakto ingestion and processing without resolving secret material here.

    ``webhook_secret`` must already have been resolved by the governed external secret
    boundary. Keeping that resolution outside this function prevents a second secret
    architecture and makes rotation observable on the next composition/reload.
    """

    if not isinstance(database, CaktoCommercialDatabase):
        raise CaktoStateConflictError("Cakto commercial database is required")
    if initialize_schema:
        database.initialize()
    verifier = CaktoWebhookVerifier(webhook_secret)
    receiver = CaktoWebhookReceiver(
        verifier=verifier,
        unit_of_work_factory=database,
        metrics=metrics,
    )
    processor = CaktoCommercialProcessor(
        unit_of_work_factory=database,
        canonical_bridge=canonical_bridge,
        metrics=metrics,
    )
    return CaktoCommercialRuntime(
        database=database,
        receiver=receiver,
        processor=processor,
    )


def compose_postgres_cakto_commercial_runtime(
    *,
    fiscal_database: object,
    webhook_secret: bytes,
    metrics: CaktoMetricSink | None = None,
    canonical_bridge: CaktoCanonicalCommercialBridge | None = None,
) -> CaktoCommercialRuntime:
    """Bind the commercial runtime to the canonical PostgreSQL connection boundary."""

    database = postgres_cakto_commercial_database(fiscal_database)
    return compose_cakto_commercial_runtime(
        database=database,
        webhook_secret=webhook_secret,
        metrics=metrics,
        canonical_bridge=canonical_bridge,
        initialize_schema=True,
    )


def build_cakto_webhook_router(
    receiver: CaktoWebhookReceiver,
    *,
    clock: Clock = utc_now,
) -> APIRouter:
    """Build a router only when a real externally-sourced webhook secret is injected."""

    router = APIRouter(tags=["commercial-cakto"])

    @router.post(
        "/webhooks/cakto",
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    async def receive_cakto_webhook(
        request: Request,
        x_cakto_timestamp: str | None = Header(default=None, alias="X-Cakto-Timestamp"),
        x_cakto_signature: str | None = Header(default=None, alias="X-Cakto-Signature"),
    ) -> dict[str, int | str]:
        if x_cakto_timestamp is None or x_cakto_signature is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cakto signature headers are required",
            )
        raw_body = await request.body()
        try:
            entries = receiver.receive(
                raw_body=raw_body,
                timestamp_header=x_cakto_timestamp,
                signature_header=x_cakto_signature,
                received_at=clock(),
            )
        except CaktoAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cakto webhook authentication failed",
            ) from exc
        except CaktoPayloadError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cakto webhook payload rejected",
            ) from exc
        except CaktoStateConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cakto webhook state conflict",
            ) from exc
        return {"status": "accepted", "accepted": len(entries)}

    return router
