"""Translate authenticated Cakto adapter facts into canonical commercial state."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from kordena_fiscal.application.cakto_claim_automation import CaktoClaimAutomationService
from kordena_fiscal.application.commercial_fulfillment import CommercialFulfillmentService
from kordena_fiscal.product.billing import SubscriptionStatus
from kordena_fiscal.product.cakto import (
    CaktoCanonicalCommercialBridge,
    CaktoExternalSubscriptionStatus,
    CaktoPermanentProcessingError,
    CaktoPlanBinding,
    CaktoReconciliationResult,
    CaktoReconciliationSnapshot,
    CaktoTransientProcessingError,
    CaktoWebhookEvent,
    CaktoWebhookInboxEntry,
    utc_now,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CanonicalCommercialUnitOfWorkFactory,
    CommercialAcquisitionRecord,
    CommercialEventType,
    CommercialFulfillmentError,
    CommercialPurchaseRecord,
    ValidatedCommercialEvent,
)
from kordena_fiscal.product.pricing import CommercialPricingConfiguration

_ACQUISITION = re.compile(r"^acq-[a-z0-9][a-z0-9._-]{0,127}$")


class PricingPublicationReader(Protocol):
    @property
    def configuration(self) -> CommercialPricingConfiguration: ...

    @property
    def published_at(self) -> datetime: ...


class PricingHistoryReader(Protocol):
    def history(self) -> tuple[PricingPublicationReader, ...]: ...


class CaktoCanonicalCommercialBridgeService(CaktoCanonicalCommercialBridge):
    """Keep Cakto provider-specific while canonical commercial state owns authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: CanonicalCommercialUnitOfWorkFactory,
        fulfillment: CommercialFulfillmentService,
        pricing: PricingHistoryReader,
        claim_automation: CaktoClaimAutomationService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._fulfillment = fulfillment
        self._pricing = pricing
        self._claim_automation = claim_automation
        self._clock = clock

    def process(
        self,
        entry: CaktoWebhookInboxEntry,
        binding: CaktoPlanBinding,
    ) -> str:
        mapped = self._event_type(entry)
        if mapped is None:
            return "canonical_no_commercial_change"

        opening = mapped in {
            CommercialEventType.SALE_CONFIRMED,
            CommercialEventType.SUBSCRIPTION_ACTIVATED,
        }
        if opening and entry.order_status != "paid":
            return "canonical_unpaid_no_activation"
        if entry.order_id is None:
            raise CaktoPermanentProcessingError(
                "commercial Cakto event is missing order identity"
            )

        existing = self._existing_purchase(entry)
        if existing is not None and existing.plan_id != binding.plan_id:
            raise CaktoPermanentProcessingError(
                "Cakto binding conflicts with canonical purchase plan"
            )
        if existing is None and not opening:
            raise CaktoTransientProcessingError(
                "canonical purchase for Cakto lifecycle event is not available"
            )

        acquisition = self._usable_acquisition(
            entry,
            binding=binding,
            existing=existing,
        )
        price_id: str | None
        if existing is None:
            plan_id = binding.plan_id
            price_id = (
                acquisition.price_id
                if acquisition is not None
                else self._price_id_at_event(entry, binding)
            )
            external_order_id = entry.order_id
            # A first-party acquisition's email was verified by NFCore's own
            # checkout flow before the Cakto redirect, so it always outranks
            # whatever Cakto reports in the webhook. Only fall back to Cakto's
            # self-reported email when there is no first-party acquisition at
            # all; either way this is a delivery address, never proof of
            # identity (see CaktoClaimAutomationService module docstring).
            buyer_email = (
                acquisition.buyer_email
                if acquisition is not None
                else entry.external_customer_email
            )
        else:
            plan_id = existing.plan_id
            price_id = existing.price_id
            external_order_id = existing.external_order_id
            buyer_email = None

        if price_id is None:
            raise CaktoTransientProcessingError(
                "canonical price mapping for Cakto event is unavailable"
            )

        event = ValidatedCommercialEvent(
            provider_id="cakto",
            event_id=entry.event_key,
            event_type=mapped,
            external_order_id=external_order_id,
            plan_id=plan_id,
            price_id=price_id,
            external_subscription_id=(
                entry.external_subscription_id
                or (None if existing is None else existing.external_subscription_id)
            ),
            external_customer_id=entry.external_customer_id,
            buyer_email=buyer_email,
            acquisition_id=(
                None if acquisition is None or not opening else acquisition.acquisition_id
            ),
            occurred_at=entry.occurred_at,
        )
        try:
            result = self._fulfillment.process(
                event=event,
                received_at=entry.received_at,
            )
        except CommercialFulfillmentError as exc:
            message = str(exc)
            if "stale" in message:
                return "ignored_stale"
            if "was not found" in message or "cannot create" in message:
                raise CaktoTransientProcessingError(message) from exc
            raise CaktoPermanentProcessingError(message) from exc
        if opening and existing is None and self._claim_automation is not None:
            # Best-effort, non-authoritative side effect: a claim-automation
            # failure must never undo or block the canonical commercial
            # reconciliation above, which has already committed.
            try:
                self._claim_automation.after_canonical_change(
                    purchase_id=result.purchase.purchase_id,
                    opening=True,
                    now=self._clock(),
                )
            except Exception:
                pass
        return (
            f"canonical_purchase:{result.purchase.purchase_id}:"
            f"{result.purchase.state.value}"
        )

    def reconcile(
        self,
        snapshot: CaktoReconciliationSnapshot,
        binding: CaktoPlanBinding,
    ) -> CaktoReconciliationResult:
        purchase = self._purchase_for_reconciliation(snapshot)
        if purchase is None:
            return CaktoReconciliationResult(
                canonical_purchase_id=None,
                external_status=snapshot.status,
                canonical_status=None,
                drift=True,
            )
        if purchase.plan_id != binding.plan_id:
            raise CaktoPermanentProcessingError(
                "Cakto reconciliation binding conflicts with canonical purchase"
            )

        canonical_status = purchase.billing_status
        with self._unit_of_work_factory() as uow:
            durable = uow.commercial.get_subscription_for_purchase(
                purchase.purchase_id
            )
        if durable is not None:
            canonical_status = durable.checkpoint.status

        expected = self._expected_status(snapshot.status)
        return CaktoReconciliationResult(
            canonical_purchase_id=purchase.purchase_id,
            external_status=snapshot.status,
            canonical_status=(
                None if canonical_status is None else canonical_status.value
            ),
            drift=canonical_status is not expected,
        )

    def _existing_purchase(
        self,
        entry: CaktoWebhookInboxEntry,
    ) -> CommercialPurchaseRecord | None:
        with self._unit_of_work_factory() as uow:
            if entry.external_subscription_id is not None:
                purchase = uow.commercial.get_purchase_by_external_subscription(
                    "cakto",
                    entry.external_subscription_id,
                )
                if purchase is not None:
                    return purchase
            if entry.order_id is None:
                return None
            return uow.commercial.get_purchase_by_external_order(
                "cakto",
                entry.order_id,
            )

    def _purchase_for_reconciliation(
        self,
        snapshot: CaktoReconciliationSnapshot,
    ) -> CommercialPurchaseRecord | None:
        with self._unit_of_work_factory() as uow:
            if snapshot.external_subscription_id is not None:
                purchase = uow.commercial.get_purchase_by_external_subscription(
                    "cakto",
                    snapshot.external_subscription_id,
                )
                if purchase is not None:
                    return purchase
            if snapshot.external_order_id is None:
                return None
            return uow.commercial.get_purchase_by_external_order(
                "cakto",
                snapshot.external_order_id,
            )

    def _usable_acquisition(
        self,
        entry: CaktoWebhookInboxEntry,
        *,
        binding: CaktoPlanBinding,
        existing: CommercialPurchaseRecord | None,
    ) -> CommercialAcquisitionRecord | None:
        callback = entry.callback_token
        if (
            existing is not None
            or callback is None
            or _ACQUISITION.fullmatch(callback.lower()) is None
        ):
            return None
        with self._unit_of_work_factory() as uow:
            acquisition = uow.commercial.get_acquisition(callback.lower())
        if acquisition is None or entry.received_at >= acquisition.expires_at:
            return None
        if (
            acquisition.provider_id != "cakto"
            or acquisition.plan_id != binding.plan_id
        ):
            return None
        return acquisition

    def _price_id_at_event(
        self,
        entry: CaktoWebhookInboxEntry,
        binding: CaktoPlanBinding,
    ) -> str:
        if entry.external_offer_id is None:
            raise CaktoTransientProcessingError(
                "Cakto event has no offer for canonical price resolution"
            )
        reference = (
            f"cakto://{entry.external_product_id}/{entry.external_offer_id}"
        )
        publication = max(
            (
                item
                for item in self._pricing.history()
                if item.published_at <= entry.occurred_at
            ),
            key=lambda item: (
                item.published_at,
                item.configuration.version,
            ),
            default=None,
        )
        if publication is None:
            raise CaktoTransientProcessingError(
                "canonical pricing snapshot is unavailable for Cakto event"
            )
        matching = tuple(
            price
            for price in publication.configuration.prices
            if price.enabled
            and price.external_price_reference == reference
        )
        plan = next(
            (
                item
                for item in publication.configuration.plans
                if item.plan_id == binding.plan_id and item.enabled
            ),
            None,
        )
        if (
            plan is None
            or len(matching) != 1
            or matching[0].price_id not in plan.price_ids
        ):
            raise CaktoTransientProcessingError(
                "Cakto product/offer does not resolve one canonical price"
            )
        return matching[0].price_id

    @staticmethod
    def _event_type(
        entry: CaktoWebhookInboxEntry,
    ) -> CommercialEventType | None:
        mapping = {
            CaktoWebhookEvent.PURCHASE_APPROVED:
                CommercialEventType.SALE_CONFIRMED,
            CaktoWebhookEvent.SUBSCRIPTION_CREATED:
                CommercialEventType.SUBSCRIPTION_ACTIVATED,
            CaktoWebhookEvent.SUBSCRIPTION_RENEWED:
                CommercialEventType.SUBSCRIPTION_RENEWED,
            CaktoWebhookEvent.SUBSCRIPTION_RENEWAL_REFUSED:
                CommercialEventType.SUBSCRIPTION_PAYMENT_LATE,
            CaktoWebhookEvent.SUBSCRIPTION_LATE:
                CommercialEventType.SUBSCRIPTION_PAYMENT_LATE,
            CaktoWebhookEvent.SUBSCRIPTION_PAUSED:
                CommercialEventType.SUBSCRIPTION_PAUSED,
            CaktoWebhookEvent.SUBSCRIPTION_RESUMED:
                CommercialEventType.SUBSCRIPTION_RECOVERED,
            CaktoWebhookEvent.SUBSCRIPTION_LATE_RECOVERED:
                CommercialEventType.SUBSCRIPTION_RECOVERED,
            CaktoWebhookEvent.SUBSCRIPTION_CANCELED:
                CommercialEventType.SUBSCRIPTION_CANCELED,
            CaktoWebhookEvent.REFUND:
                CommercialEventType.REFUND_CONFIRMED,
            CaktoWebhookEvent.CHARGEBACK:
                CommercialEventType.CHARGEBACK_CONFIRMED,
        }
        return mapping.get(entry.event_type)

    @staticmethod
    def _expected_status(
        status: CaktoExternalSubscriptionStatus,
    ) -> SubscriptionStatus:
        if status is CaktoExternalSubscriptionStatus.ACTIVE:
            return SubscriptionStatus.ACTIVE
        if status is CaktoExternalSubscriptionStatus.PAUSED:
            return SubscriptionStatus.SUSPENDED
        return SubscriptionStatus.CANCELED


__all__ = [
    "CaktoCanonicalCommercialBridgeService",
    "PricingHistoryReader",
    "PricingPublicationReader",
]
