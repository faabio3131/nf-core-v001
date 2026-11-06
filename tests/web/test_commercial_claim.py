"""HTTP boundary proofs for the self-service commercial claim route."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.application.commercial_claim import CommercialClaimService
from kordena_fiscal.product.commercial_fulfillment import (
    CommercialFulfillmentError,
    CommercialPurchaseState,
)
from kordena_fiscal.security.human_identity import InMemoryHumanAccountRepository
from kordena_fiscal.security.human_recovery import IssuedPasswordReset
from kordena_fiscal.web.commercial_claim import create_commercial_claim_router
from tests.application.test_cl11_secure_commercial_claim import (
    MemoryClaimDatabase,
    purchase,
)

NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)


class FakeActivation:
    """Stub around CommercialCustomerActivationService.provision()."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def provision(self, *, purchase_id: str, now: datetime) -> Any:
        self.calls.append(purchase_id)
        if self.fail:
            raise CommercialFulfillmentError("not ready for provisioning")

        class _Result:
            def __init__(self) -> None:
                self.purchase = purchase(
                    state=CommercialPurchaseState.ACTIVATION_PENDING,
                )
                self.activation_reset = IssuedPasswordReset(
                    reset_token="synthetic-reset-token",  # noqa: S106
                    account_id="acct-synthetic",
                    expires_at=now,
                )

        return _Result()


class FakeDelivery:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail = fail

    def deliver(self, *, email: str, reset: object) -> None:
        if self.fail:
            raise RuntimeError("synthetic-delivery-private-material")
        self.calls.append((email, reset))


def _issue_token(database: MemoryClaimDatabase) -> tuple[str, CommercialClaimService]:
    database.store.purchases[purchase().purchase_id] = purchase()
    service = CommercialClaimService(
        unit_of_work_factory=database,
        accounts=InMemoryHumanAccountRepository(),
    )
    issued = service.issue(purchase_id=purchase().purchase_id, now=NOW)
    return issued.claim_token, service


def _client(
    service: CommercialClaimService,
    activation: FakeActivation,
    delivery: FakeDelivery,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_commercial_claim_router(
            service,
            activation=activation,
            delivery=delivery,
            now=lambda: NOW,
        )
    )
    return TestClient(app)


def test_claim_completion_provisions_and_delivers_credentials() -> None:
    database = MemoryClaimDatabase()
    token, service = _issue_token(database)
    activation = FakeActivation()
    delivery = FakeDelivery()

    response = _client(service, activation, delivery).post(
        "/v1/commercial/claim",
        json={"claim_token": token, "legal_name": "Synthetic Claim LTDA"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "activated"
    assert activation.calls == [purchase().purchase_id]
    assert len(delivery.calls) == 1
    assert delivery.calls[0][0] == purchase().buyer_email


def test_invalid_or_reused_token_never_leaks_which_reason() -> None:
    database = MemoryClaimDatabase()
    token, service = _issue_token(database)
    activation = FakeActivation()
    delivery = FakeDelivery()
    client = _client(service, activation, delivery)

    first = client.post(
        "/v1/commercial/claim",
        json={"claim_token": token, "legal_name": "Synthetic Claim LTDA"},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/commercial/claim",
        json={"claim_token": token, "legal_name": "Synthetic Claim LTDA"},
    )
    assert second.status_code == 409
    assert second.json() == {"detail": "claim unavailable"}

    garbage = client.post(
        "/v1/commercial/claim",
        json={"claim_token": "not-a-real-token", "legal_name": "Synthetic Claim LTDA"},
    )
    assert garbage.status_code == 409
    assert garbage.json() == {"detail": "claim unavailable"}


def test_manual_review_never_calls_activation_or_delivery() -> None:
    database = MemoryClaimDatabase()
    database.store.purchases[purchase().purchase_id] = purchase()
    accounts = InMemoryHumanAccountRepository()
    service = CommercialClaimService(unit_of_work_factory=database, accounts=accounts)
    issued = service.issue(purchase_id=purchase().purchase_id, now=NOW)

    from kordena_fiscal.security.human_identity import HumanAccount, PortalRole

    accounts.save(
        HumanAccount(
            account_id="acct-existing",
            email=purchase().buyer_email,
            password_hash="x" * 32,
            tenant_id="tenant-existing",
            role=PortalRole.OWNER,
        )
    )

    activation = FakeActivation()
    delivery = FakeDelivery()
    response = _client(service, activation, delivery).post(
        "/v1/commercial/claim",
        json={"claim_token": issued.claim_token, "legal_name": "Synthetic Claim LTDA"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "manual_review"
    assert activation.calls == []
    assert delivery.calls == []


def test_rejects_non_json_and_malformed_payloads() -> None:
    database = MemoryClaimDatabase()
    token, service = _issue_token(database)
    client = _client(service, FakeActivation(), FakeDelivery())

    wrong_content_type = client.post(
        "/v1/commercial/claim",
        data=b"not json",
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_content_type.status_code == 415

    missing_field = client.post(
        "/v1/commercial/claim",
        json={"claim_token": token},
    )
    assert missing_field.status_code == 400

    authenticated = client.post(
        "/v1/commercial/claim",
        json={"claim_token": token, "legal_name": "Synthetic Claim LTDA"},
        headers={"Authorization": "Bearer x"},
    )
    assert authenticated.status_code == 403


def test_activation_failure_surfaces_as_conflict_without_losing_claim_consumption() -> None:
    database = MemoryClaimDatabase()
    token, service = _issue_token(database)
    activation = FakeActivation(fail=True)
    delivery = FakeDelivery()

    response = _client(service, activation, delivery).post(
        "/v1/commercial/claim",
        json={"claim_token": token, "legal_name": "Synthetic Claim LTDA"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "activation unavailable"}
    assert delivery.calls == []
