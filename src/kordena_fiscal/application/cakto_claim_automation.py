"""Automatic post-payment claim issuance for Cakto.

This module connects a reconciled Cakto payment to the existing, already-governed
claim/redeem flow (``CommercialClaimService`` / ``POST /v1/commercial/claim``). It
deliberately does NOT provision or activate an account by itself, and it does NOT
treat anything Cakto reports (order id, customer id, customer email) as proof of
identity -- it only uses a Cakto-reported email as a best-effort delivery address
for the same one-time claim link an operator would otherwise have to issue by hand.

Why not call ``CommercialCustomerActivationService.provision()`` directly, the way
``CommandCommercialReceiver`` does for the Command provider? Command already
collects and verifies the buyer's email through NFCore's own first-party checkout
flow (a ``CommercialAcquisitionRecord``) before redirecting to Command, so the
email on the resulting purchase is already trustworthy identity, not just a
delivery hint. Cakto's own checkout page is not operated by NFCore, so an email it
reports in a webhook is never elevated past "where to send the claim link" --
exactly the boundary ``CommercialClaimService`` already enforces for every
provider ("without trusting external customer identity"). Skipping the claim step
for Cakto would mean inventing a new, weaker identity-assurance rule for one
provider, which AGENTS.md Rule 8 (adapters cannot invent business rules) forbids.

Idempotency: at most one automatic claim is ever issued per purchase. This is
enforced by checking ``get_claim_for_purchase`` before issuing -- a purchase that
already has any claim record (active, expired, or consumed) is left alone.
Re-sending a fresh claim for an already-claimed purchase is a deliberate,
individually-authorized operator action (e.g. a "resend claim" admin tool), not a
silent side effect of webhook reprocessing, because a second automatic issue would
silently invalidate a link the customer may already be holding or using.

Fail-closed: no delivery adapter configured means no claim is minted at all (an
undeliverable claim token is worse than none), and any claim-issuance precondition
that is not met (purchase missing, not in a claimable state, no usable email) is
reported back as a non-issuing outcome rather than raised, so a single purchase's
claim-automation gap never blocks or retries the webhook's own successful
commercial reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from kordena_fiscal.application.commercial_claim import (
    CommercialClaimService,
    IssuedCommercialClaim,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CanonicalCommercialUnitOfWorkFactory,
    CommercialFulfillmentError,
    CommercialPurchaseState,
)


class CaktoClaimDeliveryError(RuntimeError):
    """Claim delivery failed without exposing provider/token details."""


@runtime_checkable
class CaktoClaimDelivery(Protocol):
    """External delivery port for the automatic post-payment claim email.

    Production implementations enqueue an email/SMS send. The protocol never
    receives the claim's purchase_id or any Cakto identifiers -- only the
    delivery address and the opaque issued claim -- so a delivery adapter
    cannot become a second source of commercial business logic.
    """

    def deliver(self, *, email: str, claim: IssuedCommercialClaim) -> None: ...


# Deterministic, non-sensitive reasons a caller can branch on or log; never a
# message string that could embed an identifier, email or token.
_ISSUED = "issued"
_ISSUED_DELIVERY_FAILED = "issued_delivery_failed"
_NOT_OPENING_EVENT = "not_opening_event"
_DELIVERY_NOT_CONFIGURED = "delivery_not_configured"
_PURCHASE_NOT_FOUND = "purchase_not_found"
_NOT_CLAIMABLE = "not_claimable"
_NO_DELIVERY_EMAIL = "no_delivery_email"
_CLAIM_ALREADY_ISSUED = "claim_already_issued"


@dataclass(frozen=True, slots=True)
class CaktoClaimAutomationOutcome:
    """Observable, non-sensitive result of one automation attempt."""

    purchase_id: str
    issued: bool
    reason: str


class CaktoClaimAutomationService:
    """Issue and deliver the customer claim link right after a Cakto payment is
    reconciled into a new canonical purchase, without skipping identity proof.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: CanonicalCommercialUnitOfWorkFactory,
        claims: CommercialClaimService,
        delivery: CaktoClaimDelivery | None,
    ) -> None:
        if not isinstance(claims, CommercialClaimService):
            raise ValueError("claims must be a CommercialClaimService")
        self._unit_of_work_factory = unit_of_work_factory
        self._claims = claims
        self._delivery = delivery

    def after_canonical_change(
        self,
        *,
        purchase_id: str,
        opening: bool,
        now: datetime,
    ) -> CaktoClaimAutomationOutcome:
        """Issue/deliver a claim only for a brand-new, opening-event purchase.

        Safe to call for every processed Cakto event: continuing (non-opening)
        events and purchases that are not freshly claimable are simply reported
        as non-issuing outcomes, never raised.
        """

        if not opening:
            return CaktoClaimAutomationOutcome(purchase_id, False, _NOT_OPENING_EVENT)
        # Do not mint an undeliverable claim.
        if self._delivery is None:
            return CaktoClaimAutomationOutcome(
                purchase_id, False, _DELIVERY_NOT_CONFIGURED
            )

        with self._unit_of_work_factory() as uow:
            purchase = uow.commercial.get_purchase(purchase_id)
            if purchase is None:
                return CaktoClaimAutomationOutcome(
                    purchase_id, False, _PURCHASE_NOT_FOUND
                )
            if purchase.state not in {
                CommercialPurchaseState.UNCLAIMED,
                CommercialPurchaseState.IDENTITY_REQUIRED,
            }:
                return CaktoClaimAutomationOutcome(purchase_id, False, _NOT_CLAIMABLE)
            if purchase.buyer_email is None:
                return CaktoClaimAutomationOutcome(
                    purchase_id, False, _NO_DELIVERY_EMAIL
                )
            existing_claim = uow.commercial.get_claim_for_purchase(purchase_id)
        if existing_claim is not None:
            return CaktoClaimAutomationOutcome(
                purchase_id, False, _CLAIM_ALREADY_ISSUED
            )

        try:
            issued = self._claims.issue(purchase_id=purchase_id, now=now)
        except CommercialFulfillmentError:
            # Coverage/eligibility may have changed between the read above and
            # the issue() call; report as not-claimable rather than raise.
            return CaktoClaimAutomationOutcome(purchase_id, False, _NOT_CLAIMABLE)

        try:
            self._delivery.deliver(email=issued.delivery_email, claim=issued)
        except Exception:
            # The claim is already durably persisted; delivery health belongs to
            # the external adapter/observability boundary (same pattern as
            # password-reset delivery). It must not be retried automatically --
            # a second automatic issue would invalidate the first token.
            return CaktoClaimAutomationOutcome(
                purchase_id, True, _ISSUED_DELIVERY_FAILED
            )
        return CaktoClaimAutomationOutcome(purchase_id, True, _ISSUED)


__all__ = [
    "CaktoClaimAutomationOutcome",
    "CaktoClaimAutomationService",
    "CaktoClaimDelivery",
    "CaktoClaimDeliveryError",
]
