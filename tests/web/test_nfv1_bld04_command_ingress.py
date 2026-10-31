"""BLD-04: HTTP ingress Command, synthetic transport only."""

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.product.commercial_fulfillment import CommercialFulfillmentError
from kordena_fiscal.security.s2s import FixedWindowRateLimiter, WebhookSignature
from kordena_fiscal.web.command_commercial import create_command_commercial_router


class Receiver:
    def __init__(self):
        self.auth_count = 0
        self.effects = 0
        self.reject_auth = False
        self.reject_event = False
        self.fail = False
        self.replay = False

    def authenticate(self, body, signature, now):
        assert body and now.tzinfo is not None
        self.auth_count += 1
        if self.reject_auth or signature.key_id != "synthetic-command":
            raise CommercialFulfillmentError("synthetic auth denied")
        return SimpleNamespace(binding_id="synthetic-binding")

    def receive(self, *, event, binding, now):
        assert event.product_id == "nfcore"
        assert binding.binding_id == "synthetic-binding"
        assert now.tzinfo is not None
        self.effects += 1
        if self.reject_event:
            raise CommercialFulfillmentError("synthetic transition denied")
        if self.fail:
            raise RuntimeError("synthetic storage unavailable")
        return SimpleNamespace(purchase_id="purchase-synthetic", replay=self.replay)


def _client(receiver, *, limit=10):
    app = FastAPI()
    app.include_router(
        create_command_commercial_router(
            receiver,  # type: ignore[arg-type]
            rate_limiter=FixedWindowRateLimiter(max_requests=limit, window_seconds=3600),
        )
    )
    return TestClient(app)


def _headers():
    return {
        "X-NFCore-Signature": WebhookSignature(
            key_id="synthetic-command",
            timestamp=int(datetime.now(UTC).timestamp()),
            digest="a" * 64,
        ).header_value,
    }


def _event():
    return {
        "version": 1,
        "event_id": "event_synthetic",
        "event_type": "sale_confirmed",
        "occurred_at": datetime.now(UTC).isoformat(),
        "product_id": "nfcore",
        "environment": "test",
        "command_customer_id": "customer_synthetic",
        "command_subscription_id": "subscription_synthetic",
        "command_invoice_id": "invoice_synthetic",
        "acquisition_id": "acquisition_synthetic",
        "plan_id": "plan_synthetic",
        "price_id": "price_synthetic",
    }


def test_denies_unsigned_and_untrusted_events_before_effect():
    receiver = Receiver()
    client = _client(receiver)
    assert client.post("/v1/commercial/command/events", json=_event()).status_code == 401
    receiver.reject_auth = True
    denied = client.post("/v1/commercial/command/events", json=_event(), headers=_headers())
    assert denied.status_code == 401
    assert receiver.effects == 0


def test_invalid_envelope_returns_400_without_effect():
    receiver = Receiver()
    response = _client(receiver).post(
        "/v1/commercial/command/events",
        content=b'{"unexpected":1}',
        headers=_headers(),
    )
    assert response.status_code == 400
    assert receiver.auth_count == 1
    assert receiver.effects == 0


def test_success_and_replay_have_distinct_receipts():
    receiver = Receiver()
    client = _client(receiver)
    first = client.post("/v1/commercial/command/events", json=_event(), headers=_headers())
    assert first.status_code == 202
    assert first.json() == {
        "status": "processed", "purchase_id": "purchase-synthetic", "replay": False,
    }
    assert first.headers["cache-control"] == "no-store, max-age=0"
    receiver.replay = True
    again = client.post("/v1/commercial/command/events", json=_event(), headers=_headers())
    assert again.status_code == 200
    assert again.json()["replay"] is True


def test_rate_limit_is_scoped_after_authentication():
    receiver = Receiver()
    client = _client(receiver, limit=1)
    path = "/v1/commercial/command/events"
    assert client.post(path, json=_event(), headers=_headers()).status_code == 202
    assert client.post(path, json=_event(), headers=_headers()).status_code == 429
    assert receiver.effects == 1


def test_oversized_body_fails_before_authentication():
    receiver = Receiver()
    result = _client(receiver).post(
        "/v1/commercial/command/events",
        content=b"x" * (64 * 1024 + 1),
        headers=_headers(),
    )
    assert result.status_code == 413
    assert receiver.auth_count == 0


def test_rejected_transition_and_storage_error_do_not_claim_success():
    receiver = Receiver()
    client = _client(receiver)
    receiver.reject_event = True
    path = "/v1/commercial/command/events"
    assert client.post(path, json=_event(), headers=_headers()).status_code == 409
    receiver.reject_event = False
    receiver.fail = True
    assert client.post(path, json=_event(), headers=_headers()).status_code == 503
