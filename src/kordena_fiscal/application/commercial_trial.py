"""Governed first-party trial lifecycle for FM NFCORE.

Trials are canonical NFCore commercial state. They never grant fiscal production
readiness and never derive tenant identity from an external provider.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from kordena_fiscal.application.commercial_activation import (
    CommercialCustomerActivationService,
)
from kordena_fiscal.product.billing import CommercialSubscription, SubscriptionStatus
from kordena_fiscal.product.commercial_fulfillment import (
    CanonicalCommercialUnitOfWorkFactory,
    CommercialFulfillmentError,
    CommercialPurchaseRecord,
    CommercialPurchaseState,
    DurableCommercialSubscription,
    commercial_purchase_id,
)
from kordena_fiscal.product.pricing import CommercialPricingConfiguration
from kordena_fiscal.security.human_identity import HumanAccountRepository
from kordena_fiscal.security.human_recovery import IssuedPasswordReset


class TrialPricingReader(Protocol):
    @property
    def current(self) -> CommercialPricingConfiguration | None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class GovernedTrialStart:
    purchase: CommercialPurchaseRecord
    subscription: DurableCommercialSubscription
    activation_reset: IssuedPasswordReset | None
    replay: bool

    @property
    def expires_at(self) -> datetime:
        return self.subscription.checkpoint.period_end


class GovernedTrialService:
    """Create, expire and internally convert one canonical trial."""

    _PROVIDER_ID = "nfcore-trial"

    def __init__(
        self,
        *,
        unit_of_work_factory: CanonicalCommercialUnitOfWorkFactory,
        activation: CommercialCustomerActivationService,
        pricing: TrialPricingReader,
        accounts: HumanAccountRepository,
        request_guard: Callable[[tuple[str, ...]], AbstractContextManager[None]],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._activation = activation
        self._pricing = pricing
        self._accounts = accounts
        self._request_guard = request_guard

    def begin(
        self,
        *,
        plan_id: str,
        price_id: str,
        buyer_email: str,
        legal_name: str,
        idempotency_key: str,
        now: datetime,
    ) -> GovernedTrialStart:
        self._aware(now)
        plan_id = self._token(plan_id, "plan_id")
        price_id = self._token(price_id, "price_id")
        buyer_email = self._email(buyer_email)
        legal_name = self._legal_name(legal_name)
        digest = self._idempotency_digest(idempotency_key)

        # Serialize the existing email/idempotency invariants across replicas.
        # Raw email and idempotency material never become lock identities.
        identities = tuple(
            sorted(
                (
                    f"trial-request:{digest}",
                    f"trial-owner:{hashlib.sha256(buyer_email.encode()).hexdigest()}",
                )
            )
        )
        with self._request_guard(identities):
            return self._begin_guarded(
                plan_id=plan_id,
                price_id=price_id,
                buyer_email=buyer_email,
                legal_name=legal_name,
                digest=digest,
                now=now,
            )

    def _begin_guarded(
        self,
        *,
        plan_id: str,
        price_id: str,
        buyer_email: str,
        legal_name: str,
        digest: str,
        now: datetime,
    ) -> GovernedTrialStart:

        pricing = self._pricing.current
        if pricing is None:
            raise CommercialFulfillmentError("commercial pricing is not published")
        plan = next(
            (
                item
                for item in pricing.plans
                if item.plan_id == plan_id and item.enabled
            ),
            None,
        )
        if plan is None or plan.trial_days < 1:
            raise CommercialFulfillmentError("selected plan is not eligible for trial")
        if price_id not in plan.price_ids:
            raise CommercialFulfillmentError("selected trial price does not belong to plan")
        if not pricing.price(price_id).enabled:
            raise CommercialFulfillmentError("selected trial price is disabled")

        existing_account = self._accounts.by_email(buyer_email)
        external_order_id = f"trial-{digest[:48]}"
        purchase_id = commercial_purchase_id(self._PROVIDER_ID, external_order_id)
        replay = False

        with self._unit_of_work_factory() as uow:
            current = uow.commercial.get_purchase(purchase_id)
            if current is not None:
                self._assert_replay(
                    current,
                    plan_id=plan_id,
                    price_id=price_id,
                    buyer_email=buyer_email,
                    legal_name=legal_name,
                )
                replay = True
                purchase = current
                # A request can reach the lock first but acquire it second.
                # Its captured ingress time may precede the committed reservation.
                # The held guard proves that reservation already exists at this
                # decision; floor the replay clock to creation, never to a future
                # paid period or a new expiry. The original trial dates remain fixed.
                now = max(now, current.created_at)
            else:
                if (
                    existing_account is not None
                    or uow.commercial.get_trial_for_email(buyer_email) is not None
                ):
                    raise CommercialFulfillmentError(
                        "trial is not available for an existing account or trial reservation"
                    )
                purchase = CommercialPurchaseRecord(
                    purchase_id=purchase_id,
                    provider_id=self._PROVIDER_ID,
                    external_order_id=external_order_id,
                    plan_id=plan_id,
                    price_id=price_id,
                    state=CommercialPurchaseState.READY_TO_PROVISION,
                    created_at=now,
                    updated_at=now,
                    last_event_at=now,
                    last_event_id=f"trial-start-{digest[:40]}",
                    buyer_email=buyer_email,
                    legal_name=legal_name,
                    tenant_id=f"tenant-{secrets.token_hex(16)}",
                    billing_status=SubscriptionStatus.TRIAL,
                )
                uow.commercial.put_purchase(purchase)
                uow.commit()

        if purchase.state is CommercialPurchaseState.ACTIVE:
            with self._unit_of_work_factory() as uow:
                subscription = uow.commercial.get_subscription_for_purchase(
                    purchase.purchase_id
                )
            if subscription is None:
                raise CommercialFulfillmentError(
                    "active trial has no canonical subscription"
                )
            return GovernedTrialStart(
                purchase=purchase,
                subscription=subscription,
                activation_reset=None,
                replay=True,
            )

        activation = self._activation.provision(
            purchase_id=purchase.purchase_id,
            now=now,
        )
        return GovernedTrialStart(
            purchase=activation.purchase,
            subscription=activation.subscription,
            activation_reset=activation.activation_reset,
            replay=replay,
        )

    def expire(
        self,
        *,
        purchase_id: str,
        now: datetime,
    ) -> DurableCommercialSubscription:
        self._aware(now)
        with self._unit_of_work_factory() as uow:
            purchase = uow.commercial.get_purchase(purchase_id)
            if purchase is None:
                raise CommercialFulfillmentError("trial purchase was not found")
            subscription = uow.commercial.get_subscription_for_purchase(purchase_id)
            if subscription is None:
                raise CommercialFulfillmentError("trial subscription was not found")
            if subscription.checkpoint.status is not SubscriptionStatus.TRIAL:
                return subscription
            if now < subscription.checkpoint.period_end:
                raise CommercialFulfillmentError("trial has not expired")

            current = CommercialSubscription.restore(subscription.checkpoint)
            current.transition(SubscriptionStatus.SUSPENDED)
            event_id = f"trial-expired-{hashlib.sha256(purchase_id.encode()).hexdigest()[:32]}"
            updated_subscription = replace(
                subscription,
                checkpoint=current.checkpoint(),
                last_event_id=event_id,
                last_event_at=now,
            )
            updated_purchase = replace(
                purchase,
                billing_status=SubscriptionStatus.SUSPENDED,
                updated_at=now,
                last_event_id=event_id,
                last_event_at=now,
            )
            uow.commercial.put_subscription(updated_subscription)
            uow.commercial.put_purchase(updated_purchase)
            uow.commit()
            return updated_subscription

    def convert(
        self,
        *,
        purchase_id: str,
        conversion_reference: str,
        now: datetime,
    ) -> DurableCommercialSubscription:
        """Convert a trial only from a trusted internal commercial authority call.

        This method is intentionally not exposed by the public trial HTTP router.
        Provider adapters/commercial orchestration must first validate payment and
        then invoke this boundary with an opaque canonical conversion reference.
        """

        self._aware(now)
        reference = self._token(conversion_reference, "conversion_reference")
        with self._unit_of_work_factory() as uow:
            purchase = uow.commercial.get_purchase(purchase_id)
            if purchase is None:
                raise CommercialFulfillmentError("trial purchase was not found")
            subscription = uow.commercial.get_subscription_for_purchase(purchase_id)
            if subscription is None:
                raise CommercialFulfillmentError("trial subscription was not found")
            if subscription.checkpoint.status is SubscriptionStatus.ACTIVE:
                return subscription
            if subscription.checkpoint.status is not SubscriptionStatus.TRIAL:
                raise CommercialFulfillmentError("trial is not convertible")

            current = CommercialSubscription.restore(subscription.checkpoint)
            current.transition(SubscriptionStatus.ACTIVE)
            # A paid conversion must not inherit the 30-day AI trial allowance.
            # Resolve the paid plan from the original governed pricing publication.
            paid_plan = self._activation.paid_plan_for_purchase(purchase)
            event_id = f"trial-converted-{hashlib.sha256(reference.encode()).hexdigest()[:32]}"
            updated_subscription = replace(
                subscription,
                checkpoint=replace(current.checkpoint(), plan=paid_plan),
                last_event_id=event_id,
                last_event_at=now,
            )
            updated_purchase = replace(
                purchase,
                billing_status=SubscriptionStatus.ACTIVE,
                updated_at=now,
                last_event_id=event_id,
                last_event_at=now,
            )
            uow.commercial.put_subscription(updated_subscription)
            uow.commercial.put_purchase(updated_purchase)
            uow.commit()
            return updated_subscription

    @staticmethod
    def _assert_replay(
        purchase: CommercialPurchaseRecord,
        *,
        plan_id: str,
        price_id: str,
        buyer_email: str,
        legal_name: str,
    ) -> None:
        expected = (
            GovernedTrialService._PROVIDER_ID,
            plan_id,
            price_id,
            buyer_email,
            legal_name,
            SubscriptionStatus.TRIAL,
        )
        current = (
            purchase.provider_id,
            purchase.plan_id,
            purchase.price_id,
            purchase.buyer_email,
            purchase.legal_name,
            purchase.billing_status,
        )
        if current != expected:
            raise CommercialFulfillmentError(
                "trial idempotency key was reused with different data"
            )

    @staticmethod
    def _aware(now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise CommercialFulfillmentError("now must be timezone-aware")

    @staticmethod
    def _token(value: str, field_name: str) -> str:
        normalized = value.strip().lower()
        if not normalized or len(normalized) > 128:
            raise CommercialFulfillmentError(
                f"{field_name} must be non-blank and <= 128 chars"
            )
        return normalized

    @staticmethod
    def _email(value: str) -> str:
        normalized = value.strip().casefold()
        if (
            not normalized
            or len(normalized) > 320
            or normalized.count("@") != 1
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            raise CommercialFulfillmentError("buyer_email is invalid")
        return normalized

    @staticmethod
    def _legal_name(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 256:
            raise CommercialFulfillmentError(
                "legal_name must be non-blank and <= 256 chars"
            )
        return normalized

    @staticmethod
    def _idempotency_digest(value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 16 or len(normalized) > 256:
            raise CommercialFulfillmentError(
                "idempotency key must contain between 16 and 256 characters"
            )
        return hashlib.sha256(normalized.encode()).hexdigest()


__all__ = ["GovernedTrialService", "GovernedTrialStart", "TrialPricingReader"]
