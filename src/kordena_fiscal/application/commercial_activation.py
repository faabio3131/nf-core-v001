"""Canonical paid-customer provisioning and activation for FM NFCORE."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from kordena_fiscal.product.billing import (
    CommercialPlan,
    CommercialSubscription,
    SubscriptionStatus,
    UsagePeriodCheckpoint,
    UsageQuota,
)
from kordena_fiscal.cognitive.commercial_quotas import (
    APPROVED_TOKEN_ALLOWANCES,
    INPUT_QUOTA_METRIC,
    OUTPUT_QUOTA_METRIC,
    TokenQuotaPlan,
)
from kordena_fiscal.product.catalog import DEFAULT_COMMERCIAL_CATALOG, CommercialCatalog
from kordena_fiscal.product.commercial_fulfillment import (
    CanonicalCommercialUnitOfWorkFactory,
    CommercialFulfillmentError,
    CommercialPurchaseRecord,
    CommercialPurchaseState,
    DurableCommercialSubscription,
)
from kordena_fiscal.product.commercial_lifecycle import (
    CommercialContract,
    PaidCommercialPeriod,
    period_end,
)
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    CommercialPricingError,
)
from kordena_fiscal.runtime.commercial_provisioning import (
    CommercialCustomerProvisioningService,
)
from kordena_fiscal.security.human_recovery import (
    IssuedPasswordReset,
    PasswordRecoveryService,
)


class CommercialPricingPublicationReader(Protocol):
    @property
    def configuration(self) -> CommercialPricingConfiguration: ...

    @property
    def published_at(self) -> datetime: ...


class CommercialPricingReader(Protocol):
    def history(self) -> tuple[CommercialPricingPublicationReader, ...]: ...


@dataclass(frozen=True, slots=True)
class CommercialActivationProvisioningResult:
    purchase: CommercialPurchaseRecord
    subscription: DurableCommercialSubscription
    activation_reset: IssuedPasswordReset

    def __repr__(self) -> str:
        return (
            "CommercialActivationProvisioningResult("
            f"purchase={self.purchase.purchase_id!r}, "
            f"subscription={self.subscription.subscription_id!r}, "
            "activation_reset=<redacted>)"
        )


class CommercialCustomerActivationService:
    """Provision canonical customer identity and subscription after a secure claim."""

    def __init__(
        self,
        *,
        unit_of_work_factory: CanonicalCommercialUnitOfWorkFactory,
        provisioning: CommercialCustomerProvisioningService,
        password_recovery: PasswordRecoveryService,
        pricing: CommercialPricingReader,
        catalog: CommercialCatalog = DEFAULT_COMMERCIAL_CATALOG,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._provisioning = provisioning
        self._password_recovery = password_recovery
        self._pricing = pricing
        self._catalog = catalog

    def provision(
        self,
        *,
        purchase_id: str,
        now: datetime,
    ) -> CommercialActivationProvisioningResult:
        self._aware(now, "now")
        with self._unit_of_work_factory() as uow:
            purchase = uow.commercial.get_purchase(purchase_id)
        if purchase is None:
            raise CommercialFulfillmentError("commercial purchase was not found")

        if purchase.state is CommercialPurchaseState.ACTIVATION_PENDING:
            return self._retry_activation(purchase, now)

        if purchase.state is not CommercialPurchaseState.READY_TO_PROVISION:
            raise CommercialFulfillmentError("commercial purchase is not ready for provisioning")
        if (
            purchase.tenant_id is None
            or purchase.legal_name is None
            or purchase.buyer_email is None
        ):
            raise CommercialFulfillmentError("commercial purchase canonical identity is incomplete")

        plan, cadence, trial_days = self._resolve_plan(purchase)
        subscription = self._subscription(
            purchase=purchase, plan=plan, cadence=cadence, trial_days=trial_days
        )
        self._require_coverage(subscription, now)
        provisioned = self._provisioning.provision(
            tenant_id=purchase.tenant_id,
            legal_name=purchase.legal_name,
            owner_email=purchase.buyer_email,
            correlation_id=f"commercial-provision-{purchase.purchase_id}",
            now=now,
        )
        reset = provisioned.activation_reset
        if reset is None:
            reset = self._password_recovery.request_reset(
                email=purchase.buyer_email,
                now=now,
            )
        if reset is None:
            raise CommercialFulfillmentError("commercial owner did not produce an activation reset")

        updated = replace(
            purchase,
            state=CommercialPurchaseState.ACTIVATION_PENDING,
            account_id=provisioned.account_id,
            updated_at=now,
        )

        with self._unit_of_work_factory() as uow:
            current = uow.commercial.get_purchase(purchase.purchase_id)
            if current is None:
                raise CommercialFulfillmentError(
                    "commercial purchase disappeared during provisioning"
                )
            if current.state not in {
                CommercialPurchaseState.READY_TO_PROVISION,
                CommercialPurchaseState.ACTIVATION_PENDING,
            }:
                raise CommercialFulfillmentError("commercial purchase changed during provisioning")
            if (
                current.last_event_id != purchase.last_event_id
                or current.billing_status != purchase.billing_status
            ):
                raise CommercialFulfillmentError("commercial lifecycle changed during provisioning")
            if current.tenant_id != purchase.tenant_id:
                raise CommercialFulfillmentError("canonical tenant changed during provisioning")
            uow.commercial.put_subscription(subscription)
            uow.commercial.put_purchase(updated)
            uow.commit()

        return CommercialActivationProvisioningResult(
            purchase=updated,
            subscription=subscription,
            activation_reset=reset,
        )

    def mark_active(
        self,
        *,
        account_id: str,
        now: datetime,
    ) -> CommercialPurchaseRecord | None:
        self._aware(now, "now")
        normalized_account = account_id.strip().lower()
        if not normalized_account:
            raise CommercialFulfillmentError("account_id is required")
        with self._unit_of_work_factory() as uow:
            purchase = uow.commercial.get_purchase_by_account(normalized_account)
            if purchase is None:
                return None
            if purchase.state is CommercialPurchaseState.ACTIVE:
                return purchase
            if purchase.state is not CommercialPurchaseState.ACTIVATION_PENDING:
                raise CommercialFulfillmentError("commercial purchase is not awaiting activation")
            subscription = uow.commercial.get_subscription_for_purchase(purchase.purchase_id)
            if subscription is None:
                raise CommercialFulfillmentError("activation requires canonical subscription")
            self._require_coverage(subscription, now)
            updated = replace(
                purchase,
                state=CommercialPurchaseState.ACTIVE,
                updated_at=now,
            )
            uow.commercial.put_purchase(updated)
            uow.commit()
            return updated

    def _retry_activation(
        self,
        purchase: CommercialPurchaseRecord,
        now: datetime,
    ) -> CommercialActivationProvisioningResult:
        if (
            purchase.tenant_id is None
            or purchase.account_id is None
            or purchase.buyer_email is None
        ):
            raise CommercialFulfillmentError("activation-pending purchase identity is incomplete")
        subscription_id = self._subscription_id(purchase.purchase_id)
        with self._unit_of_work_factory() as uow:
            subscription = uow.commercial.get_subscription(subscription_id)
        if subscription is None:
            raise CommercialFulfillmentError(
                "activation-pending purchase has no canonical subscription"
            )
        self._require_coverage(subscription, now)
        reset = self._password_recovery.request_reset(
            email=purchase.buyer_email,
            now=now,
        )
        if reset is None:
            raise CommercialFulfillmentError("commercial owner did not produce an activation reset")
        return CommercialActivationProvisioningResult(
            purchase=purchase,
            subscription=subscription,
            activation_reset=reset,
        )

    def _resolve_plan(
        self,
        purchase: CommercialPurchaseRecord,
    ) -> tuple[CommercialPlan, BillingCadence, int]:
        pricing = self._pricing_at_purchase(purchase)
        plan_definition = next(
            (plan for plan in pricing.plans if plan.plan_id == purchase.plan_id and plan.enabled),
            None,
        )
        if plan_definition is None:
            raise CommercialFulfillmentError("commercial plan was not available at purchase time")
        if purchase.price_id is None or purchase.price_id not in plan_definition.price_ids:
            raise CommercialFulfillmentError(
                "commercial purchase price does not belong to its plan"
            )
        try:
            price = pricing.price(purchase.price_id)
            edition = self._catalog.edition(plan_definition.edition_id)
        except (CommercialPricingError, ValueError) as exc:
            raise CommercialFulfillmentError(
                "commercial plan cannot resolve canonical pricing/catalog"
            ) from exc
        if not price.enabled:
            raise CommercialFulfillmentError("commercial price was not enabled at purchase time")
        return (
            CommercialPlan(
                plan_id=plan_definition.plan_id,
                entitlement_ids=edition.entitlement_ids,
                quotas=plan_definition.periodic_quotas,
            ),
            price.cadence,
            plan_definition.trial_days,
        )

    def _pricing_at_purchase(
        self,
        purchase: CommercialPurchaseRecord,
    ) -> CommercialPricingConfiguration:
        history = self._pricing.history()
        if not history:
            raise CommercialFulfillmentError("commercial pricing is not published")
        publication = max(
            (
                item
                for item in history
                if item.published_at <= purchase.created_at
            ),
            key=lambda item: (item.published_at, item.configuration.version),
            default=None,
        )
        if publication is None:
            raise CommercialFulfillmentError(
                "commercial pricing snapshot is unavailable for purchase"
            )
        return publication.configuration

    def contract_for(
        self, purchase: CommercialPurchaseRecord, start: datetime, invoice_id: str
    ) -> CommercialContract:
        plan, cadence, _ = self._resolve_plan(purchase)
        pricing = self._pricing_at_purchase(purchase)
        definition = next(p for p in pricing.plans if p.plan_id == purchase.plan_id)
        return CommercialContract(
            purchase_id=purchase.purchase_id,
            plan=plan,
            cadence=cadence,
            grace_days=definition.grace_days,
            pricing_configuration_id=pricing.configuration_id,
            pricing_version=pricing.version,
            periods=(
                PaidCommercialPeriod(
                    invoice_id=invoice_id,
                    paid_at=start,
                    start=start,
                    end=period_end(start, cadence),
                ),
            ),
        )

    @staticmethod
    def _require_coverage(subscription: DurableCommercialSubscription, now: datetime) -> None:
        if not CommercialSubscription.restore(subscription.checkpoint).accepts_operations_at(now):
            raise CommercialFulfillmentError("commercial subscription coverage blocks activation")

    def _subscription(
        self,
        *,
        purchase: CommercialPurchaseRecord,
        plan: CommercialPlan,
        cadence: BillingCadence,
        trial_days: int,
    ) -> DurableCommercialSubscription:
        assert purchase.tenant_id is not None
        start = purchase.last_event_at
        if purchase.billing_status is SubscriptionStatus.TRIAL:
            if trial_days < 1:
                raise CommercialFulfillmentError("commercial plan is not eligible for trial")
            end = start + timedelta(days=trial_days)
        else:
            end = self._period_end(start, cadence)
        with self._unit_of_work_factory() as uow:
            contract = uow.commercial.get_contract(purchase.purchase_id)
        if contract is not None:
            plan = contract.plan
            start, end = contract.periods[-1].start, contract.periods[-1].end
        if purchase.billing_status is SubscriptionStatus.TRIAL and contract is None:
            # Preserve the canonical plan and all non-AI entitlements/quotas;
            # override only the approved trial AI allowance in its durable snapshot.
            trial = APPROVED_TOKEN_ALLOWANCES[TokenQuotaPlan.TRIAL]
            plan = CommercialPlan(
                plan_id=plan.plan_id,
                entitlement_ids=plan.entitlement_ids,
                quotas=tuple(
                    quota for quota in plan.quotas
                    if quota.metric_id not in {INPUT_QUOTA_METRIC, OUTPUT_QUOTA_METRIC}
                ) + (
                    UsageQuota(INPUT_QUOTA_METRIC, trial.input_tokens),
                    UsageQuota(OUTPUT_QUOTA_METRIC, trial.output_tokens),
                ),
            )
        subscription = CommercialSubscription(
            tenant_id=purchase.tenant_id,
            plan=plan,
            status=purchase.billing_status or SubscriptionStatus.ACTIVE,
            period_start=start,
            period_end=end,
            grace_days=0 if contract is None else contract.grace_days,
            previous_periods=()
            if contract is None
            else tuple(
                UsagePeriodCheckpoint(p.start, p.end, p.usage) for p in contract.periods[:-1]
            ),
        )
        return DurableCommercialSubscription(
            subscription_id=self._subscription_id(purchase.purchase_id),
            purchase_id=purchase.purchase_id,
            checkpoint=subscription.checkpoint(),
            provider_id=purchase.provider_id,
            external_subscription_id=purchase.external_subscription_id,
            last_event_id=purchase.last_event_id,
            last_event_at=purchase.last_event_at,
        )

    @staticmethod
    def _subscription_id(purchase_id: str) -> str:
        digest = hashlib.sha256(purchase_id.encode()).hexdigest()
        return f"commercial-subscription-{digest[:32]}"

    @staticmethod
    def _period_end(start: datetime, cadence: BillingCadence) -> datetime:
        return period_end(start, cadence)

    @staticmethod
    def _aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise CommercialFulfillmentError(f"{field_name} must be timezone-aware")


__all__ = [
    "CommercialActivationProvisioningResult",
    "CommercialCustomerActivationService",
    "CommercialPricingPublicationReader",
    "CommercialPricingReader",
]
