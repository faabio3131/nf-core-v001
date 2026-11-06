"""Unit coverage (no Postgres required) for CaktoCanonicalCommercialBridgeService wiring.

tests/application/test_cl11_cakto_reconciliation.py already certifies this class end to end
against a real Postgres-backed canonical commercial database, but that file skips entirely
without NFCORE_TEST_POSTGRES_DSN. This file adds a fast, portable, in-memory-backed unit test
for the two behaviors introduced for Cakto claim automation that deserve coverage even when
Postgres is unavailable:

1. buyer_email priority on a newly-opened purchase: a first-party CommercialAcquisitionRecord
   (verified by NFCore's own pre-checkout flow) always outranks whatever Cakto's webhook
   self-reports in entry.external_customer_email, and the self-reported email is used only
   when there is no usable acquisition at all.
2. CaktoClaimAutomationService.after_canonical_change() is invoked exactly once, with
   opening=True, only on the branch that just created a brand-new purchase (existing is None)
   -- never on a continuing/non-opening event for an already-known purchase.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from kordena_fiscal.application.cakto_reconciliation import (
    CaktoCanonicalCommercialBridgeService,
    PricingPublicationReader,
)
from kordena_fiscal.application.commercial_fulfillment import CommercialFulfillmentService
from kordena_fiscal.product.cakto import (
    CaktoPlanBinding,
    CaktoWebhookEvent,
    CaktoWebhookInboxEntry,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CommercialAcquisitionRecord,
    CommercialEventReceipt,
    CommercialFulfillmentError,
    CommercialPurchaseRecord,
)
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    PlanDefinition,
    PriceDefinition,
)

NOW = datetime(2026, 9, 28, 16, 0, tzinfo=UTC)


class MemoryBridgeStore:
    """Minimal in-memory double covering only what this file's scenarios exercise.

    CommercialFulfillmentService._resolve_acquisition/_sync_subscription_status/
    _contract_for_event all probe for optional store methods (get_contract,
    get_subscription_for_purchase, put_subscription, get_first_event) via getattr(...,
    default=None) and silently no-op when absent, so this double deliberately omits them
    rather than stubbing them out: the real production store implements all of
    CanonicalCommercialStore, this one only needs what SALE_CONFIRMED actually touches.
    """

    def __init__(self) -> None:
        self.acquisitions: dict[str, CommercialAcquisitionRecord] = {}
        self.events: dict[tuple[str, str], CommercialEventReceipt] = {}
        self.purchases: dict[str, CommercialPurchaseRecord] = {}

    def get_acquisition(self, acquisition_id: str) -> CommercialAcquisitionRecord | None:
        return self.acquisitions.get(acquisition_id)

    def put_acquisition(
        self, acquisition: CommercialAcquisitionRecord
    ) -> CommercialAcquisitionRecord:
        self.acquisitions[acquisition.acquisition_id] = acquisition
        return acquisition

    def receive_event(
        self, receipt: CommercialEventReceipt
    ) -> tuple[CommercialEventReceipt, bool]:
        key = (receipt.provider_id, receipt.event_id)
        current = self.events.get(key)
        if current is not None:
            if current != receipt:
                raise CommercialFulfillmentError(
                    "commercial event identity was replayed with different content"
                )
            return current, True
        self.events[key] = receipt
        return receipt, False

    def get_purchase(self, purchase_id: str) -> CommercialPurchaseRecord | None:
        return self.purchases.get(purchase_id)

    def get_purchase_by_external_order(
        self, provider_id: str, external_order_id: str
    ) -> CommercialPurchaseRecord | None:
        return next(
            (
                item
                for item in self.purchases.values()
                if item.provider_id == provider_id
                and item.external_order_id == external_order_id
            ),
            None,
        )

    def get_purchase_by_external_subscription(
        self, provider_id: str, external_subscription_id: str
    ) -> CommercialPurchaseRecord | None:
        return next(
            (
                item
                for item in self.purchases.values()
                if item.provider_id == provider_id
                and item.external_subscription_id == external_subscription_id
            ),
            None,
        )

    def put_purchase(self, purchase: CommercialPurchaseRecord) -> CommercialPurchaseRecord:
        self.purchases[purchase.purchase_id] = purchase
        return purchase


class MemoryBridgeUow:
    def __init__(self, store: MemoryBridgeStore) -> None:
        self.commercial = store
        self._snapshot: tuple[object, object, object] | None = None
        self._committed = False

    def __enter__(self) -> MemoryBridgeUow:
        self._snapshot = (
            deepcopy(self.commercial.acquisitions),
            deepcopy(self.commercial.events),
            deepcopy(self.commercial.purchases),
        )
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            assert self._snapshot is not None
            acquisitions, events, purchases = self._snapshot
            self.commercial.acquisitions = acquisitions  # type: ignore[assignment]
            self.commercial.events = events  # type: ignore[assignment]
            self.commercial.purchases = purchases  # type: ignore[assignment]

    def commit(self) -> None:
        self._committed = True


class MemoryBridgeDatabase:
    def __init__(self) -> None:
        self.store = MemoryBridgeStore()

    def __call__(self) -> MemoryBridgeUow:
        return MemoryBridgeUow(self.store)


class FixedPricingPublication:
    def __init__(self, configuration: CommercialPricingConfiguration) -> None:
        self.configuration = configuration
        self.published_at = NOW - timedelta(days=1)


class FixedPricing:
    """One published configuration resolving binding growth/product-1/offer-1 to one price.

    Only used for scenarios that go through CaktoCanonicalCommercialBridgeService's own
    price lookup (no usable acquisition supplies a price_id directly).
    """

    def __init__(self) -> None:
        price = PriceDefinition(
            price_id="growth-monthly",
            currency="BRL",
            cadence=BillingCadence.MONTHLY,
            base_amount=Decimal("199.00"),
            external_price_reference="cakto://product-1/offer-1",
        )
        plan = PlanDefinition(
            plan_id="growth",
            display_name="Growth",
            edition_id="growth-edition",
            price_ids=("growth-monthly",),
        )
        configuration = CommercialPricingConfiguration(
            configuration_id="cfg-1",
            version=1,
            prices=(price,),
            plans=(plan,),
        )
        self._publication = FixedPricingPublication(configuration)

    def history(self) -> tuple[PricingPublicationReader, ...]:
        return (self._publication,)  # type: ignore[return-value]


class RecordingClaimAutomation:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def after_canonical_change(
        self, *, purchase_id: str, opening: bool, now: datetime
    ) -> None:
        self.calls.append({"purchase_id": purchase_id, "opening": opening, "now": now})


def _binding() -> CaktoPlanBinding:
    return CaktoPlanBinding(
        external_product_id="product-1",
        external_offer_id="offer-1",
        plan_id="growth",
        entitlement_ids=("documents.issue",),
    )


def _entry(
    *,
    order_id: str = "order-1",
    callback_token: str | None = None,
    external_customer_email: str | None = "cakto-reported@example.com",
) -> CaktoWebhookInboxEntry:
    return CaktoWebhookInboxEntry(
        event_key="evt-1",
        event_type=CaktoWebhookEvent.PURCHASE_APPROVED,
        order_id=order_id,
        external_product_id="product-1",
        external_offer_id="offer-1",
        external_customer_id="customer-1",
        order_status="paid",
        occurred_at=NOW,
        payload_sha256="a" * 64,
        received_at=NOW,
        callback_token=callback_token,
        external_customer_email=external_customer_email,
    )


def _bridge(
    database: MemoryBridgeDatabase,
    *,
    claim_automation: RecordingClaimAutomation | None = None,
) -> CaktoCanonicalCommercialBridgeService:
    return CaktoCanonicalCommercialBridgeService(
        unit_of_work_factory=database,
        fulfillment=CommercialFulfillmentService(database),
        pricing=FixedPricing(),
        claim_automation=claim_automation,
    )


def test_new_purchase_without_acquisition_uses_cakto_reported_email() -> None:
    database = MemoryBridgeDatabase()
    bridge = _bridge(database)

    outcome = bridge.process(_entry(), _binding())

    assert outcome.startswith("canonical_purchase:")
    purchase = next(iter(database.store.purchases.values()))
    assert purchase.buyer_email == "cakto-reported@example.com"


def test_new_purchase_with_acquisition_prefers_first_party_email_over_cakto_report() -> None:
    database = MemoryBridgeDatabase()
    acquisition = CommercialAcquisitionRecord(
        acquisition_id="acq-0123456789abcdef0123456789abcdef",
        idempotency_sha256="b" * 64,
        request_sha256="c" * 64,
        provider_id="cakto",
        plan_id="growth",
        price_id="growth-monthly",
        buyer_email="first-party@example.com",
        legal_name="Acme Ltda",
        created_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )
    database.store.put_acquisition(acquisition)
    bridge = _bridge(database)

    outcome = bridge.process(
        _entry(
            callback_token=acquisition.acquisition_id,
            external_customer_email="cakto-reported@example.com",
        ),
        _binding(),
    )

    assert outcome.startswith("canonical_purchase:")
    purchase = next(iter(database.store.purchases.values()))
    # The first-party, pre-checkout-verified email wins even though Cakto's webhook
    # also reported a (different, unverified) email for the same event.
    assert purchase.buyer_email == "first-party@example.com"


def test_claim_automation_invoked_once_on_new_opening_purchase() -> None:
    database = MemoryBridgeDatabase()
    claim_automation = RecordingClaimAutomation()
    bridge = _bridge(database, claim_automation=claim_automation)

    outcome = bridge.process(_entry(), _binding())

    assert outcome.startswith("canonical_purchase:")
    assert len(claim_automation.calls) == 1
    call = claim_automation.calls[0]
    assert call["opening"] is True
    purchase = next(iter(database.store.purchases.values()))
    assert call["purchase_id"] == purchase.purchase_id


def test_claim_automation_not_invoked_again_on_continuing_event_for_same_purchase() -> None:
    database = MemoryBridgeDatabase()
    claim_automation = RecordingClaimAutomation()
    bridge = _bridge(database, claim_automation=claim_automation)

    bridge.process(_entry(), _binding())
    assert len(claim_automation.calls) == 1

    # SUBSCRIPTION_PAUSED (not an opening event) needs no contract_factory, unlike
    # SUBSCRIPTION_RENEWED -- the point here is only that it's a continuing event for
    # an already-known purchase, so it must never re-trigger claim automation.
    continuing_entry = CaktoWebhookInboxEntry(
        event_key="evt-2",
        event_type=CaktoWebhookEvent.SUBSCRIPTION_PAUSED,
        order_id="order-1",
        external_product_id="product-1",
        external_offer_id="offer-1",
        external_customer_id="customer-1",
        order_status=None,
        occurred_at=NOW + timedelta(days=30),
        payload_sha256="d" * 64,
        received_at=NOW + timedelta(days=30),
        external_customer_email="cakto-reported@example.com",
    )
    bridge.process(continuing_entry, _binding())

    # A continuing event for an already-known purchase must never trigger a second
    # (automatic, unauthorized) claim issuance.
    assert len(claim_automation.calls) == 1


def test_claim_automation_not_invoked_when_none_is_configured() -> None:
    database = MemoryBridgeDatabase()
    bridge = _bridge(database, claim_automation=None)

    outcome = bridge.process(_entry(), _binding())

    assert outcome.startswith("canonical_purchase:")
