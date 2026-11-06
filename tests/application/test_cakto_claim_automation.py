from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.application.cakto_claim_automation import (
    CaktoClaimAutomationService,
    CaktoClaimDeliveryError,
)
from kordena_fiscal.application.commercial_claim import (
    CommercialClaimService,
    IssuedCommercialClaim,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CommercialClaimRecord,
    CommercialPurchaseRecord,
    CommercialPurchaseState,
)
from kordena_fiscal.security.human_identity import InMemoryHumanAccountRepository

NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
PURCHASE_ID = "commercial-purchase-0123456789abcdef0123456789abcdef"


class MemoryClaimStore:
    def __init__(self) -> None:
        self.purchases: dict[str, CommercialPurchaseRecord] = {}
        self.claims_by_purchase: dict[str, CommercialClaimRecord] = {}
        self.claims_by_digest: dict[str, CommercialClaimRecord] = {}

    def get_purchase(self, purchase_id: str) -> CommercialPurchaseRecord | None:
        return self.purchases.get(purchase_id)

    def put_purchase(self, purchase: CommercialPurchaseRecord) -> CommercialPurchaseRecord:
        self.purchases[purchase.purchase_id] = purchase
        return purchase

    def get_claim_by_digest(self, token_sha256: str) -> CommercialClaimRecord | None:
        return self.claims_by_digest.get(token_sha256)

    def get_claim_for_purchase(self, purchase_id: str) -> CommercialClaimRecord | None:
        return self.claims_by_purchase.get(purchase_id)

    def put_claim(self, claim: CommercialClaimRecord) -> CommercialClaimRecord:
        self.claims_by_purchase[claim.purchase_id] = claim
        self.claims_by_digest[claim.token_sha256] = claim
        return claim

    def consume_claim(self, claim_id: str, used_at: datetime) -> bool:
        return False


class MemoryClaimUow:
    def __init__(self, store: MemoryClaimStore) -> None:
        self.commercial = store
        self._snapshot: tuple[object, object, object] | None = None
        self._committed = False

    def __enter__(self) -> MemoryClaimUow:
        self._snapshot = (
            deepcopy(self.commercial.purchases),
            deepcopy(self.commercial.claims_by_purchase),
            deepcopy(self.commercial.claims_by_digest),
        )
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            assert self._snapshot is not None
            purchases, claims_by_purchase, claims_by_digest = self._snapshot
            self.commercial.purchases = purchases  # type: ignore[assignment]
            self.commercial.claims_by_purchase = claims_by_purchase  # type: ignore[assignment]
            self.commercial.claims_by_digest = claims_by_digest  # type: ignore[assignment]

    def commit(self) -> None:
        self._committed = True


class MemoryClaimDatabase:
    def __init__(self) -> None:
        self.store = MemoryClaimStore()

    def __call__(self) -> MemoryClaimUow:
        return MemoryClaimUow(self.store)


class RecordingDelivery:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, IssuedCommercialClaim]] = []
        self._fail = fail

    def deliver(self, *, email: str, claim: IssuedCommercialClaim) -> None:
        if self._fail:
            raise CaktoClaimDeliveryError("transport failed")
        self.calls.append((email, claim))


def _purchase(
    *,
    state: CommercialPurchaseState = CommercialPurchaseState.UNCLAIMED,
    email: str | None = "buyer@example.com",
) -> CommercialPurchaseRecord:
    return CommercialPurchaseRecord(
        purchase_id=PURCHASE_ID,
        provider_id="cakto",
        external_order_id="cakto-order-1",
        plan_id="growth",
        price_id="growth-monthly",
        state=state,
        created_at=NOW,
        updated_at=NOW,
        last_event_at=NOW,
        last_event_id="evt-sale",
        buyer_email=email,
        external_customer_id="cakto-customer-1",
    )


def _service(database: MemoryClaimDatabase, delivery: RecordingDelivery | None) -> (
    CaktoClaimAutomationService
):
    claims = CommercialClaimService(
        unit_of_work_factory=database,
        accounts=InMemoryHumanAccountRepository(),
    )
    return CaktoClaimAutomationService(
        unit_of_work_factory=database,
        claims=claims,
        delivery=delivery,
    )


def test_issues_and_delivers_claim_for_new_unclaimed_purchase() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase()
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is True
    assert outcome.reason == "issued"
    assert len(delivery.calls) == 1
    email, claim = delivery.calls[0]
    assert email == "buyer@example.com"
    assert claim.purchase_id == PURCHASE_ID
    assert database.store.get_claim_for_purchase(PURCHASE_ID) is not None


def test_identity_required_with_email_is_also_claimable() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase(
        state=CommercialPurchaseState.IDENTITY_REQUIRED
    )
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is True


def test_is_idempotent_across_repeated_invocations() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase()
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    first = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )
    second = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW + timedelta(minutes=5)
    )

    assert first.issued is True
    assert second.issued is False
    assert second.reason == "claim_already_issued"
    assert len(delivery.calls) == 1


def test_skips_non_opening_events() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase()
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=False, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "not_opening_event"
    assert delivery.calls == []


def test_fails_closed_without_configured_delivery() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase()
    automation = _service(database, None)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "delivery_not_configured"
    assert database.store.get_claim_for_purchase(PURCHASE_ID) is None


def test_skips_when_purchase_is_missing() -> None:
    database = MemoryClaimDatabase()
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "purchase_not_found"


@pytest.mark.parametrize(
    "state",
    [
        CommercialPurchaseState.READY_TO_PROVISION,
        CommercialPurchaseState.PROVISIONED,
        CommercialPurchaseState.ACTIVE,
        CommercialPurchaseState.MANUAL_REVIEW,
        CommercialPurchaseState.CANCELED,
    ],
)
def test_skips_purchases_that_are_not_freshly_claimable(
    state: CommercialPurchaseState,
) -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase(state=state)
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "not_claimable"
    assert delivery.calls == []


def test_skips_when_no_delivery_email_is_known() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase(
        state=CommercialPurchaseState.IDENTITY_REQUIRED, email=None
    )
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "no_delivery_email"
    assert delivery.calls == []


def test_claim_persists_even_when_delivery_transport_fails() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[PURCHASE_ID] = _purchase()
    delivery = RecordingDelivery(fail=True)
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is True
    assert outcome.reason == "issued_delivery_failed"
    # A second call must not re-issue -- the already-persisted claim governs.
    second = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW + timedelta(minutes=1)
    )
    assert second.issued is False
    assert second.reason == "claim_already_issued"


def test_rejects_non_commercial_claim_service_dependency() -> None:
    database = MemoryClaimDatabase()
    with pytest.raises(ValueError, match="CommercialClaimService"):
        CaktoClaimAutomationService(
            unit_of_work_factory=database,
            claims=object(),  # type: ignore[arg-type]
            delivery=None,
        )


def test_never_raises_even_when_issue_rejects_the_purchase() -> None:
    database = MemoryClaimDatabase()
    # tenant_id already set makes the purchase not-claimable at issue() time,
    # even though the initial state check above might pass for a stale read.
    purchase = _purchase()
    purchase = CommercialPurchaseRecord(
        purchase_id=purchase.purchase_id,
        provider_id=purchase.provider_id,
        external_order_id=purchase.external_order_id,
        plan_id=purchase.plan_id,
        price_id=purchase.price_id,
        state=purchase.state,
        created_at=purchase.created_at,
        updated_at=purchase.updated_at,
        last_event_at=purchase.last_event_at,
        last_event_id=purchase.last_event_id,
        buyer_email=purchase.buyer_email,
        external_customer_id=purchase.external_customer_id,
        tenant_id="tenant-already-assigned-0123456789ab",
    )
    database.store.purchases[PURCHASE_ID] = purchase
    delivery = RecordingDelivery()
    automation = _service(database, delivery)

    outcome = automation.after_canonical_change(
        purchase_id=PURCHASE_ID, opening=True, now=NOW
    )

    assert outcome.issued is False
    assert outcome.reason == "not_claimable"
    assert delivery.calls == []
