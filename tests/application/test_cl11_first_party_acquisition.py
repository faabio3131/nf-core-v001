from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.application.commercial_acquisition import CommercialAcquisitionService
from kordena_fiscal.product.checkout import (
    CommercialCheckoutItem,
    CommercialCheckoutProjection,
    CommercialCheckoutStatus,
)
from kordena_fiscal.product.commercial_fulfillment import (
    CommercialAcquisitionRecord,
    CommercialFulfillmentError,
)
from kordena_fiscal.product.commercial_readiness import CommercialDeliveryPathReadiness
from kordena_fiscal.product.commercial_release import (
    CommercialReleaseDecision,
    CommercialReleaseStatus,
)
from kordena_fiscal.product.pricing import (
    BillingCadence,
    CommercialPricingConfiguration,
    PlanDefinition,
    PriceDefinition,
)
from kordena_fiscal.security.s2s import (
    FixedWindowRateLimiter,
    InMemoryWebhookKeyRing,
    WebhookSecurity,
)
from kordena_fiscal.web.commercial_acquisition import (
    MAX_ACQUISITION_BODY_BYTES,
    create_commercial_acquisition_router,
)

NOW = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
SECRET = b"first-party-site-secret-key-material-2026"
KEY_ID = "site-fm-v1"


class MemoryAcquisitionStore:
    def __init__(self) -> None:
        self.acquisitions: dict[str, CommercialAcquisitionRecord] = {}

    def get_acquisition(
        self,
        acquisition_id: str,
    ) -> CommercialAcquisitionRecord | None:
        return self.acquisitions.get(acquisition_id)

    def get_acquisition_by_idempotency(
        self,
        idempotency_sha256: str,
    ) -> CommercialAcquisitionRecord | None:
        return next(
            (
                item
                for item in self.acquisitions.values()
                if item.idempotency_sha256 == idempotency_sha256
            ),
            None,
        )

    def put_acquisition(
        self,
        acquisition: CommercialAcquisitionRecord,
    ) -> CommercialAcquisitionRecord:
        self.acquisitions[acquisition.acquisition_id] = acquisition
        return acquisition


class MemoryAcquisitionUow:
    def __init__(self, store: MemoryAcquisitionStore) -> None:
        self.commercial = store
        self._snapshot: dict[str, CommercialAcquisitionRecord] | None = None
        self._committed = False

    def __enter__(self) -> MemoryAcquisitionUow:
        self._snapshot = deepcopy(self.commercial.acquisitions)
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            assert self._snapshot is not None
            self.commercial.acquisitions = self._snapshot

    def commit(self) -> None:
        self._committed = True


class MemoryAcquisitionDatabase:
    def __init__(self) -> None:
        self.store = MemoryAcquisitionStore()

    def __call__(self) -> MemoryAcquisitionUow:
        return MemoryAcquisitionUow(self.store)


class PricingReader:
    def __init__(self, current: CommercialPricingConfiguration | None) -> None:
        self.current = current


class ReleaseReader:
    def __init__(self, current: CommercialReleaseDecision | None) -> None:
        self.current = current


class SyntheticCheckout:
    provider_id = "synthetic"

    def project(
        self,
        pricing: CommercialPricingConfiguration | None,
    ) -> CommercialCheckoutProjection:
        if pricing is None:
            return CommercialCheckoutProjection(
                status=CommercialCheckoutStatus.UNCONFIGURED,
                provider=self.provider_id,
                expected_count=0,
                configured_count=0,
                items=(),
            )
        return CommercialCheckoutProjection(
            status=CommercialCheckoutStatus.CONFIGURED,
            provider=self.provider_id,
            expected_count=1,
            configured_count=1,
            items=(
                CommercialCheckoutItem(
                    plan_id="growth",
                    price_id="growth-monthly",
                    provider=self.provider_id,
                    checkout_url="https://payments.example/checkout",
                ),
            ),
        )

    def start_checkout(
        self,
        *,
        item: CommercialCheckoutItem,
        acquisition_reference: str,
    ) -> str:
        assert item.provider == self.provider_id
        return (
            "https://payments.example/checkout"
            f"?acquisition_reference={acquisition_reference}"
        )


def pricing() -> CommercialPricingConfiguration:
    price = PriceDefinition(
        price_id="growth-monthly",
        currency="BRL",
        cadence=BillingCadence.MONTHLY,
        base_amount=Decimal("199.00"),
    )
    return CommercialPricingConfiguration(
        configuration_id="cl11-first-party",
        version=1,
        prices=(price,),
        plans=(
            PlanDefinition(
                plan_id="growth",
                display_name="Growth",
                edition_id="growth",
                price_ids=(price.price_id,),
            ),
        ),
    )


def approved_release() -> CommercialReleaseDecision:
    return CommercialReleaseDecision(
        version=1,
        status=CommercialReleaseStatus.COMMERCIAL_APPROVED,
        human_decision_reference="cl11-first-party-test",
    )


def readiness(*, activation_delivery: bool = True) -> CommercialDeliveryPathReadiness:
    return CommercialDeliveryPathReadiness(
        canonical_commercial_persistence=True,
        fulfillment=True,
        provisioning=True,
        activation_delivery=activation_delivery,
    )


def service(
    database: MemoryAcquisitionDatabase,
    *,
    release: CommercialReleaseDecision | None = None,
    delivery: CommercialDeliveryPathReadiness | None = None,
) -> CommercialAcquisitionService:
    checkout = SyntheticCheckout()
    return CommercialAcquisitionService(
        unit_of_work_factory=database,
        pricing=PricingReader(pricing()),
        release=ReleaseReader(release or approved_release()),
        checkout=checkout,
        checkout_starter=checkout,
        checkout_processing_configured=True,
        delivery_readiness=delivery or readiness(),
    )


def test_begin_creates_nfcore_reference_and_hashes_idempotency() -> None:
    database = MemoryAcquisitionDatabase()
    acquisitions = service(database)

    started = acquisitions.begin(
        plan_id="growth",
        price_id="growth-monthly",
        buyer_email=" Owner@Example.com ",
        legal_name=" ACME Tecnologia LTDA ",
        idempotency_key="first-party-idempotency-0001",
        now=NOW,
    )

    assert started.replay is False
    assert started.acquisition_reference.startswith("acq-")
    assert started.provider_id == "synthetic"
    assert started.acquisition_reference in started.checkout_url

    record = database.store.acquisitions[started.acquisition_reference]
    assert record.buyer_email == "owner@example.com"
    assert record.legal_name == "ACME Tecnologia LTDA"
    assert record.idempotency_sha256 != "first-party-idempotency-0001"
    assert len(record.idempotency_sha256) == 64
    assert "owner@example.com" not in repr(record)
    assert "ACME Tecnologia LTDA" not in repr(record)


def test_idempotent_replay_returns_same_reference_and_conflict_fails_closed() -> None:
    database = MemoryAcquisitionDatabase()
    acquisitions = service(database)
    first = acquisitions.begin(
        plan_id="growth",
        price_id="growth-monthly",
        buyer_email="owner@example.com",
        legal_name="ACME LTDA",
        idempotency_key="first-party-idempotency-0002",
        now=NOW,
    )
    replay = acquisitions.begin(
        plan_id="growth",
        price_id="growth-monthly",
        buyer_email="owner@example.com",
        legal_name="ACME LTDA",
        idempotency_key="first-party-idempotency-0002",
        now=NOW + timedelta(seconds=1),
    )

    assert replay.replay is True
    assert replay.acquisition_reference == first.acquisition_reference
    assert len(database.store.acquisitions) == 1

    with pytest.raises(CommercialFulfillmentError, match="different acquisition"):
        acquisitions.begin(
            plan_id="growth",
            price_id="growth-monthly",
            buyer_email="attacker@example.com",
            legal_name="ACME LTDA",
            idempotency_key="first-party-idempotency-0002",
            now=NOW + timedelta(seconds=2),
        )


def test_purchase_gate_and_selected_plan_fail_closed() -> None:
    database = MemoryAcquisitionDatabase()
    blocked = service(
        database,
        delivery=readiness(activation_delivery=False),
    )
    with pytest.raises(CommercialFulfillmentError, match="not operationally ready"):
        blocked.begin(
            plan_id="growth",
            price_id="growth-monthly",
            buyer_email="owner@example.com",
            legal_name="ACME LTDA",
            idempotency_key="first-party-idempotency-0003",
            now=NOW,
        )

    ready = service(database)
    with pytest.raises(CommercialFulfillmentError, match="not available"):
        ready.begin(
            plan_id="enterprise",
            price_id="enterprise-monthly",
            buyer_email="owner@example.com",
            legal_name="ACME LTDA",
            idempotency_key="first-party-idempotency-0004",
            now=NOW,
        )


def signed_client(
    database: MemoryAcquisitionDatabase,
    *,
    max_requests: int = 10,
) -> tuple[TestClient, WebhookSecurity]:
    security = WebhookSecurity(
        key_resolver=InMemoryWebhookKeyRing(
            active_key_id=KEY_ID,
            keys={KEY_ID: SECRET},
        ),
        signing_key_id=KEY_ID,
        max_age_seconds=300,
        max_future_skew_seconds=30,
    )
    app = FastAPI()
    app.include_router(
        create_commercial_acquisition_router(
            service(database),
            security=security,
            rate_limiter=FixedWindowRateLimiter(
                max_requests=max_requests,
                window_seconds=60,
            ),
        )
    )
    return TestClient(app), security


def acquisition_body() -> bytes:
    return json.dumps(
        {
            "plan_id": "growth",
            "price_id": "growth-monthly",
            "buyer_email": "owner@example.com",
            "legal_name": "ACME LTDA",
        },
        separators=(",", ":"),
    ).encode()


def test_http_boundary_requires_valid_signature_and_rejects_extra_authority() -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database)
    body = acquisition_body()

    unsigned = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={"Idempotency-Key": "first-party-http-000001"},
    )
    assert unsigned.status_code == 401

    signature = security.sign(body, now=datetime.now(UTC))
    created = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "first-party-http-000001",
            "X-NFCore-Signature": signature.header_value,
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["acquisition_reference"].startswith("acq-")
    assert payload["checkout_url"].startswith("https://payments.example/")
    assert "buyer_email" not in payload
    assert "legal_name" not in payload

    tampered = body.replace(b"ACME LTDA", b"EVIL LTDA")
    rejected = client.post(
        "/v1/commercial/acquisitions",
        content=tampered,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "first-party-http-000002",
            "X-NFCore-Signature": signature.header_value,
        },
    )
    assert rejected.status_code == 401

    privileged = json.loads(body)
    privileged["payment_success"] = True
    privileged_body = json.dumps(privileged, separators=(",", ":")).encode()
    privileged_signature = security.sign(privileged_body, now=datetime.now(UTC))
    rejected_authority = client.post(
        "/v1/commercial/acquisitions",
        content=privileged_body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "first-party-http-000003",
            "X-NFCore-Signature": privileged_signature.header_value,
        },
    )
    assert rejected_authority.status_code == 400


def test_http_boundary_rate_limits_authenticated_site_key() -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database, max_requests=1)
    body = acquisition_body()

    first_signature = security.sign(body, now=datetime.now(UTC))
    first = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "first-party-rate-limit-01",
            "X-NFCore-Signature": first_signature.header_value,
        },
    )
    assert first.status_code == 201

    second_signature = security.sign(body, now=datetime.now(UTC))
    second = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "first-party-rate-limit-02",
            "X-NFCore-Signature": second_signature.header_value,
        },
    )
    assert second.status_code == 429


@pytest.mark.parametrize("authenticated", [False, True])
def test_acquisition_http_rejects_oversized_body_before_authentication_or_effect(
    authenticated: bool,
) -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database)
    body = b"x" * (MAX_ACQUISITION_BODY_BYTES + 1)
    headers = {"Idempotency-Key": "oversized-acquisition-test-0001"}
    if authenticated:
        headers["X-NFCore-Signature"] = security.sign(
            body, now=datetime.now(UTC)
        ).header_value
    response = client.post(
        "/v1/commercial/acquisitions", content=body, headers=headers,
    )
    assert response.status_code == 413
    assert database.store.acquisitions == {}


def test_acquisition_http_accepts_normal_signed_body_after_bounding() -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database)
    body = acquisition_body()
    assert len(body) < MAX_ACQUISITION_BODY_BYTES
    response = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Idempotency-Key": "normal-acquisition-bounded-0001",
            "X-NFCore-Signature": security.sign(
                body, now=datetime.now(UTC)
            ).header_value,
        },
    )
    assert response.status_code == 201
    assert len(database.store.acquisitions) == 1


@pytest.mark.parametrize(
    "body",
    (
        b'{"plan_id":"growth","plan_id":"forged","price_id":"growth-monthly","buyer_email":"owner@example.com","legal_name":"ACME"}',
        b'{"plan_id":"growth","price_id":"growth-monthly","buyer_email":"owner@example.com","legal_name":"ACME","extra":{"id":"a","id":"b"}}',
    ),
)
def test_signed_acquisition_duplicate_json_is_denied_without_side_effect(
    body: bytes,
) -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database)
    response = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "signed-duplicate-json-0001",
            "X-NFCore-Signature": security.sign(
                body, now=datetime.now(UTC)
            ).header_value,
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": "commercial acquisition body must be valid JSON"
    }
    assert database.store.acquisitions == {}


@pytest.mark.parametrize("idempotency_key", ("short", " " * 16, "a" * 129, "abc" + "\\t" + "0" * 20))
def test_signed_acquisition_invalid_idempotency_denied_before_mutation(
    idempotency_key: str,
) -> None:
    database = MemoryAcquisitionDatabase()
    client, security = signed_client(database)
    body = acquisition_body()
    response = client.post(
        "/v1/commercial/acquisitions",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-NFCore-Signature": security.sign(
                body, now=datetime.now(UTC)
            ).header_value,
        },
    )
    assert response.status_code == 400
    assert database.store.acquisitions == {}
