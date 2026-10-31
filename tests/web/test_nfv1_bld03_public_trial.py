"""Public trial ingress: explicit origin and canonical service without browser HMAC."""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.control_plane.commercial_release import (
    CommercialReleaseAdministrationService,
    InMemoryCommercialReleaseCatalog,
)
from kordena_fiscal.control_plane.models import AdminPrincipal, ControlPlanePermission
from kordena_fiscal.product.commercial_release import (
    CommercialReleaseDecision,
    CommercialReleaseStatus,
)
from kordena_fiscal.security.s2s import FixedWindowRateLimiter
from kordena_fiscal.web.public_trial import create_public_trial_router


class Trial:
    def __init__(self) -> None:
        self.calls = []

    def begin(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            replay=False,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            activation_reset=None,
        )


class Delivery:
    def deliver(self, **kwargs):
        raise AssertionError("no activation reset was issued")


def client(service: Trial, *, commercially_authorized=lambda: True) -> TestClient:
    app = FastAPI()
    app.include_router(create_public_trial_router(
        service,  # type: ignore[arg-type]
        pricing=SimpleNamespace(current=None),  # type: ignore[arg-type]
        allowed_origins=("https://fmtecnologia.com.br",),
        rate_limiter=FixedWindowRateLimiter(max_requests=3, window_seconds=3600),
        delivery=Delivery(),  # type: ignore[arg-type]
        commercially_authorized=commercially_authorized,
    ))
    return TestClient(app)


def test_public_trial_requires_approved_origin_and_rejects_authority_fields() -> None:
    service = Trial()
    c = client(service)
    body = {"plan_id": "p", "price_id": "price", "buyer_email": "a@example.com",
            "legal_name": "ACME"}
    headers = {"Origin": "https://fmtecnologia.com.br", "Idempotency-Key": "public-trial-0001"}
    assert c.post("/v1/public/trials", json=body).status_code == 403
    assert c.post("/v1/public/trials", json={**body, "tenant_id": "spoof"},
                  headers=headers).status_code == 400
    response = c.post("/v1/public/trials", json=body, headers=headers)
    assert response.status_code == 201
    assert response.json()["status"] == "trial_activation_pending"
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    assert "reset_token" not in response.text
    assert len(service.calls) == 1


def test_public_trial_rejects_unsigned_browser_authority_and_large_payload() -> None:
    service = Trial()
    c = client(service)
    headers = {"Origin": "https://fmtecnologia.com.br", "Idempotency-Key": "public-trial-0002"}
    assert c.post("/v1/public/trials", json={}, headers={**headers,
        "Authorization": "Bearer forged"}).status_code == 403
    assert c.post("/v1/public/trials", content=json.dumps({"x": "a" * 5000}),
                  headers={**headers, "Content-Type": "application/json"}).status_code == 413
    assert service.calls == []


def test_public_trial_requires_explicit_https_origin() -> None:
    with pytest.raises(ValueError):
        create_public_trial_router(
            Trial(),  # type: ignore[arg-type]
            pricing=SimpleNamespace(current=None),  # type: ignore[arg-type]
            allowed_origins=("http://fmtecnologia.com.br",),
            rate_limiter=FixedWindowRateLimiter(max_requests=1, window_seconds=60),
            delivery=Delivery(),  # type: ignore[arg-type]
            commercially_authorized=lambda: True,
        )


def test_public_trial_cors_preflight_requires_origin_and_restricted_headers() -> None:
    service = Trial()
    c = client(service)
    good = {
        "Origin": "https://fmtecnologia.com.br",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key",
    }
    response = c.options("/v1/public/trials", headers=good)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == good["Origin"]
    denied = c.options(
        "/v1/public/trials",
        headers={**good, "Access-Control-Request-Headers": "authorization"},
    )
    assert denied.status_code == 403
    assert c.options("/v1/public/trials", headers={
        **good, "Origin": "https://attacker.example"
    }).status_code == 403
    assert service.calls == []


def test_unpublished_pricing_does_not_invent_trial_offers() -> None:
    service = Trial()
    response = client(service).get(
        "/v1/public/trial-plans",
        headers={"Origin": "https://fmtecnologia.com.br"},
    )
    assert response.status_code == 503
    assert "plans" not in response.json()
    assert service.calls == []


@pytest.mark.parametrize("origin", (None, "null", "https://attacker.example"))
def test_browser_catalog_post_preserves_origin_gate(origin) -> None:
    service = Trial()
    response = client(service).post(
        "/v1/public/trial-plans", headers={"Origin": origin} if origin else {},
    )
    assert response.status_code == 403
    assert service.calls == []


def test_browser_catalog_post_uses_same_publication_authority() -> None:
    service = Trial()
    response = client(service).post(
        "/v1/public/trial-plans", headers={"Origin": "https://fmtecnologia.com.br"},
    )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == []


@pytest.mark.parametrize(
    "release_reader",
    (
        lambda: False,
        lambda: None,
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    ),
)
def test_public_trial_denies_catalog_and_submission_without_canonical_release(
    release_reader,
) -> None:
    service = Trial()
    c = client(service, commercially_authorized=release_reader)
    origin = {"Origin": "https://fmtecnologia.com.br"}
    catalog = c.post("/v1/public/trial-plans", headers=origin)
    assert catalog.status_code == 503
    assert "plans" not in catalog.json()
    body = {
        "plan_id": "p",
        "price_id": "price",
        "buyer_email": "a@example.com",
        "legal_name": "ACME",
    }
    submission = c.post(
        "/v1/public/trials",
        json=body,
        headers={**origin, "Idempotency-Key": "trial-gated-0001"},
    )
    assert submission.status_code == 503
    assert submission.headers["cache-control"] == "no-store, max-age=0"
    assert service.calls == []


def test_approved_release_preserves_public_trial_submission_contract() -> None:
    service = Trial()
    c = client(service, commercially_authorized=lambda: True)
    body = {
        "plan_id": "p",
        "price_id": "price",
        "buyer_email": "a@example.com",
        "legal_name": "ACME",
    }
    response = c.post(
        "/v1/public/trials",
        json=body,
        headers={
            "Origin": "https://fmtecnologia.com.br",
            "Idempotency-Key": "trial-approved-0001",
        },
    )
    assert response.status_code == 201
    assert len(service.calls) == 1


def test_missing_release_reader_fails_closed() -> None:
    service = Trial()
    app = FastAPI()
    app.include_router(
        create_public_trial_router(
            service,  # type: ignore[arg-type]
            pricing=SimpleNamespace(current=None),  # type: ignore[arg-type]
            allowed_origins=("https://fmtecnologia.com.br",),
            rate_limiter=FixedWindowRateLimiter(max_requests=3, window_seconds=3600),
            delivery=Delivery(),  # type: ignore[arg-type]
        )
    )
    c = TestClient(app)
    origin = {"Origin": "https://fmtecnologia.com.br"}
    assert c.post("/v1/public/trial-plans", headers=origin).status_code == 503
    assert c.post(
        "/v1/public/trials",
        json={
            "plan_id": "p",
            "price_id": "price",
            "buyer_email": "a@example.com",
            "legal_name": "ACME",
        },
        headers={**origin, "Idempotency-Key": "trial-missing-release"},
    ).status_code == 503
    assert service.calls == []


def test_trial_intake_tracks_governed_release_approval_and_revocation() -> None:
    release = CommercialReleaseAdministrationService(InMemoryCommercialReleaseCatalog())
    actor = AdminPrincipal(
        actor_id="synthetic-platform-admin",
        global_scope=True,
        permissions=frozenset({ControlPlanePermission.COMMERCIAL_CONFIG_WRITE}),
    )
    service = Trial()
    c = client(
        service,
        commercially_authorized=lambda: (
            release.current is not None and release.current.commercially_approved
        ),
    )
    headers = {
        "Origin": "https://fmtecnologia.com.br",
        "Idempotency-Key": "governed-release-0001",
    }
    body = {
        "plan_id": "p",
        "price_id": "price",
        "buyer_email": "a@example.com",
        "legal_name": "ACME",
    }
    assert c.post("/v1/public/trials", json=body, headers=headers).status_code == 503
    release.publish(
        actor=actor,
        expected_version=None,
        decision=CommercialReleaseDecision(
            version=1,
            status=CommercialReleaseStatus.INTERNAL_ONLY,
        ),
    )
    assert c.post("/v1/public/trials", json=body, headers=headers).status_code == 503
    release.publish(
        actor=actor,
        expected_version=1,
        decision=CommercialReleaseDecision(
            version=2,
            status=CommercialReleaseStatus.COMMERCIAL_APPROVED,
            human_decision_reference="synthetic-approval-reference",
        ),
    )
    assert c.post("/v1/public/trials", json=body, headers=headers).status_code == 201
    release.publish(
        actor=actor,
        expected_version=2,
        decision=CommercialReleaseDecision(
            version=3,
            status=CommercialReleaseStatus.INTERNAL_ONLY,
        ),
    )
    assert c.post("/v1/public/trials", json=body, headers=headers).status_code == 503
    assert len(service.calls) == 1


@pytest.mark.parametrize(
    "raw",
    (
        b'{"plan_id":"p","plan_id":"forged","price_id":"price","buyer_email":"a@example.com","legal_name":"ACME"}',
        b'{"plan_id":"p","price_id":"price","buyer_email":"a@example.com","legal_name":"ACME","legal_name":"forged"}',
        b'{"plan_id":"p","price_id":"price","buyer_email":"a@example.com","legal_name":"ACME","extra":{"key":1,"key":2}}',
    ),
)
def test_public_trial_rejects_duplicate_json_fields_before_service(raw: bytes) -> None:
    service = Trial()
    response = client(service).post(
        "/v1/public/trials",
        content=raw,
        headers={
            "Origin": "https://fmtecnologia.com.br",
            "Content-Type": "application/json",
            "Idempotency-Key": "trial-duplicate-rejection",
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid JSON"}
    assert service.calls == []



@pytest.mark.parametrize("failure", ["read", "malformed-catalog"])
def test_public_trial_catalog_failure_is_503_without_offer_leak(failure: str) -> None:
    class UnavailablePricing:
        @property
        def current(self):
            if failure == "read":
                raise RuntimeError("synthetic-internal-pricing-error")
            return SimpleNamespace(plans=[SimpleNamespace(
                enabled=True, trial_days=7, price_ids=["missing"],
            )], price=lambda _id: (_ for _ in ()).throw(
                RuntimeError("synthetic-internal-price-error")
            ))

    service = Trial()
    app = FastAPI()
    app.include_router(create_public_trial_router(
        service,  # type: ignore[arg-type]
        pricing=UnavailablePricing(),  # type: ignore[arg-type]
        allowed_origins=("https://fmtecnologia.com.br",),
        rate_limiter=FixedWindowRateLimiter(max_requests=3, window_seconds=3600),
        delivery=Delivery(),  # type: ignore[arg-type]
        commercially_authorized=lambda: True,
    ))
    response = TestClient(app).get(
        "/v1/public/trial-plans",
        headers={"Origin": "https://fmtecnologia.com.br"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "trial plans temporarily unavailable"}
    assert "synthetic-internal" not in response.text
    assert "plans" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == []


@pytest.mark.parametrize("key", ("short-key", " " * 7 + "abcdefgh", " " * 16))
def test_public_trial_rejects_key_shorter_than_canonical_minimum(key: str) -> None:
    service = Trial()
    response = client(service).post(
        "/v1/public/trials",
        json={
            "plan_id": "p", "price_id": "price",
            "buyer_email": "a@example.com", "legal_name": "ACME",
        },
        headers={
            "Origin": "https://fmtecnologia.com.br",
            "Idempotency-Key": key,
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid idempotency key"}
    assert service.calls == []


def test_public_trial_streamed_payload_is_bounded_before_parsing() -> None:
    service = Trial()
    response = client(service).post(
        "/v1/public/trials",
        content=iter((b'{"plan_id":"p","padding":"', b"x" * 4096, b'"}')),
        headers={
            "Origin": "https://fmtecnologia.com.br",
            "Content-Type": "application/json",
            "Idempotency-Key": "trial-stream-overflow-key",
        },
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "payload too large"}
    assert service.calls == []
