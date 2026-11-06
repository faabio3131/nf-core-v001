"""Production Cakto webhook GSM ingress: opt-in and durable source-of-truth tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kordena_fiscal.runtime import production_cakto_ingress as candidate
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.security.secret_binding import SecretBinding

REF = "sec_caktowebhookprodkey_0001"
RESOURCE = "projects/example-project/secrets/nfcore-cakto-webhook-prod"


def settings() -> dict[str, str]:
    return {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_API_GSM_MODE": "scoped-production-sa-v1",
        "NFCORE_PRODUCTION_CAKTO_WEBHOOK_MODE": "scoped-production-cakto-webhook-gsm-v1",
        "NFCORE_PRODUCTION_CAKTO_WEBHOOK_REFERENCE": REF,
        "NFCORE_PRODUCTION_CAKTO_WEBHOOK_VERSION": "1",
    }


def canonical_secret() -> SecretBinding:
    return SecretBinding(
        reference_id=REF,
        tenant_id="nfcore-platform",
        unit_id=None,
        purpose="commercial-cakto-webhook",
        runtime_environment="production",
        fiscal_environment=None,
        provider_id="google-secret-manager",
        workload_id="nfcore-api",
        kind="signature",
        canonical_version=1,
        resource=RESOURCE,
        cloud_version="1",
    )


class FakeDatabase:
    def __init__(self, secret: SecretBinding | None) -> None:
        self.secret = secret

    def connection(self):
        return None

    @contextmanager
    def __call__(self):
        yield SimpleNamespace(secret_bindings=SimpleNamespace(get=lambda _id: self.secret))


def _binding_fixture(monkeypatch, secret: SecretBinding | None) -> FakeDatabase:
    monkeypatch.setattr(
        candidate, "production_config",
        lambda _source, role: SimpleNamespace(
            role=role, project="example-project", project_number="123456"
        ),
    )
    return FakeDatabase(secret)


def test_partial_cakto_webhook_identity_fails_closed_before_database() -> None:
    with pytest.raises(RuntimeConfigurationError, match="identity denied"):
        candidate.production_cakto_webhook_secret(
            object(),  # type: ignore[arg-type]
            {
                "NFCORE_ENVIRONMENT": "production",
                "NFCORE_PRODUCTION_CAKTO_WEBHOOK_REFERENCE": REF,
            },
        )


def test_disabled_cakto_webhook_ingress_never_touches_database() -> None:
    assert candidate.production_cakto_webhook_secret(
        object(), {"NFCORE_ENVIRONMENT": "production"}  # type: ignore[arg-type]
    ) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"NFCORE_PRODUCTION_CAKTO_WEBHOOK_MODE": "unknown"},
        {"NFCORE_ENVIRONMENT": "staging"},
        {"NFCORE_API_GSM_MODE": "scoped-staging-sa-v1"},
    ],
)
def test_invalid_optin_fails_before_secret_or_database_access(changes) -> None:
    config = {**settings(), **changes}
    with pytest.raises(RuntimeConfigurationError, match="identity denied"):
        candidate.production_cakto_webhook_secret(object(), config)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "variant",
    [
        "missing-secret", "secret-revoked", "wrong-tenant", "wrong-purpose",
        "wrong-resource", "wrong-provider", "wrong-version", "wrong-workload",
        "expired-secret",
    ],
)
def test_bad_canonical_bindings_never_attempt_external_secret_access(
    monkeypatch, variant: str
) -> None:
    secret: SecretBinding | None = canonical_secret()
    if variant == "missing-secret":
        secret = None
    elif variant == "secret-revoked":
        secret = replace(secret, state="revoked")
    elif variant == "wrong-tenant":
        secret = replace(secret, tenant_id="other-tenant")
    elif variant == "wrong-purpose":
        secret = replace(secret, purpose="some.other-purpose")
    elif variant == "wrong-resource":
        secret = replace(
            secret, resource="projects/other-project/secrets/nfcore-cakto-webhook-prod"
        )
    elif variant == "wrong-provider":
        secret = replace(secret, provider_id="other-provider")
    elif variant == "wrong-version":
        secret = replace(secret, canonical_version=2)
    elif variant == "wrong-workload":
        secret = replace(secret, workload_id="other-api")
    elif variant == "expired-secret":
        secret = replace(secret, not_after=datetime.now(UTC) - timedelta(seconds=1))
    db = _binding_fixture(monkeypatch, secret)
    monkeypatch.setattr(
        candidate, "production_credentials",
        lambda *_args: pytest.fail("should not try external credentials"),
    )
    with pytest.raises(RuntimeConfigurationError, match="binding unavailable"):
        candidate.production_cakto_webhook_secret(db, settings())  # type: ignore[arg-type]


def test_valid_canonical_binding_resolves_pinned_production_gsm_only(monkeypatch) -> None:
    secret = canonical_secret()
    db = _binding_fixture(monkeypatch, secret)
    called = []
    monkeypatch.setattr(
        candidate, "production_credentials",
        lambda *_args: ("approved-credential", datetime.now(UTC) + timedelta(hours=1)),
    )
    monkeypatch.setattr(
        candidate.secretmanager_v1,
        "SecretManagerServiceClient",
        lambda **kwargs: called.append(("client", kwargs)) or object(),
    )
    monkeypatch.setattr(candidate, "GoogleSdkSecretAccess", lambda *_args, **_kw: object())
    monkeypatch.setattr(
        candidate, "DurableGsmReader",
        lambda **kwargs: called.append(("reader", kwargs)) or object(),
    )
    monkeypatch.setattr(candidate, "GoogleSignatureSecretBackend", lambda *_args, **_kw: object())

    class Resolver:
        def __init__(self, _backend, *, environment):
            assert environment == "production"

        @contextmanager
        def resolve(self, reference, *, scope):
            assert reference.reference_id == REF
            assert scope.purpose == "commercial-cakto-webhook"
            yield SimpleNamespace(reveal=lambda: b"x" * 32)

    monkeypatch.setattr(candidate, "SecretResolver", Resolver)
    result = candidate.production_cakto_webhook_secret(db, settings())  # type: ignore[arg-type]
    assert result == b"x" * 32
    assert called[0][0] == "client"
    assert called[1][1]["allowed_resources"] == frozenset({RESOURCE})
    assert called[1][1]["environment"] == "production"
    assert called[1][1]["workload_id"] == "nfcore-api"


def test_weak_material_fails_closed_without_secret_echo(monkeypatch) -> None:
    secret = canonical_secret()
    db = _binding_fixture(monkeypatch, secret)
    monkeypatch.setattr(
        candidate, "production_credentials",
        lambda *_a: ("creds", datetime.now(UTC)),
    )
    monkeypatch.setattr(
        candidate.secretmanager_v1, "SecretManagerServiceClient",
        lambda **_kw: object(),
    )
    monkeypatch.setattr(candidate, "GoogleSdkSecretAccess", lambda *_a, **_kw: object())
    monkeypatch.setattr(candidate, "DurableGsmReader", lambda **_kw: object())
    monkeypatch.setattr(candidate, "GoogleSignatureSecretBackend", lambda *_a, **_kw: object())

    class WeakResolver:
        def __init__(self, *_a, **_kw):
            pass

        @contextmanager
        def resolve(self, _reference, *, scope):
            del scope
            yield SimpleNamespace(reveal=lambda: b"short")

    monkeypatch.setattr(candidate, "SecretResolver", WeakResolver)
    with pytest.raises(RuntimeConfigurationError, match="GSM material unavailable"):
        candidate.production_cakto_webhook_secret(db, settings())  # type: ignore[arg-type]
