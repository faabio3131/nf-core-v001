"""Production Command GSM ingress: opt-in and durable source-of-truth tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kordena_fiscal.product.command_commercial import CommandBinding
from kordena_fiscal.runtime import production_command_ingress as candidate
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.security.secret_binding import SecretBinding

REF = "sec_commandproductionkey_0001"
KEY = "command-production-001"
RESOURCE = "projects/example-project/secrets/nfcore-command-prod"


def settings() -> dict[str, str]:
    return {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_API_GSM_MODE": "scoped-production-sa-v1",
        "NFCORE_PRODUCTION_COMMAND_MODE": "scoped-production-command-gsm-v1",
        "NFCORE_PRODUCTION_COMMAND_KEY_ID": KEY,
    }


def canonical() -> tuple[CommandBinding, SecretBinding]:
    command = CommandBinding(
        key_id=KEY,
        binding_id="nfcore-command",
        product_id="nfcore",
        environment="production",
        secret_reference=REF,
        secret_version=1,
        not_after=datetime.now(UTC) + timedelta(days=30),
    )
    scope = command.scope
    secret = SecretBinding(
        reference_id=REF,
        tenant_id=scope.tenant_id,
        unit_id=scope.unit_id,
        purpose=scope.purpose,
        runtime_environment="production",
        fiscal_environment=None,
        provider_id="google-secret-manager",
        workload_id="nfcore-api",
        kind="signature",
        canonical_version=1,
        resource=RESOURCE,
        cloud_version="1",
    )
    return command, secret


class FakeDatabase:
    def __init__(self, secret: SecretBinding | None) -> None:
        self.secret = secret

    def connection(self):
        return None

    @contextmanager
    def __call__(self):
        yield SimpleNamespace(secret_bindings=SimpleNamespace(get=lambda _id: self.secret))


def _binding_fixture(monkeypatch, command: CommandBinding | None, secret: SecretBinding | None):
    monkeypatch.setattr(
        candidate, "production_config",
        lambda _source, role: SimpleNamespace(
            role=role, project="example-project", project_number="123456"
        ),
    )
    monkeypatch.setattr(
        candidate, "CommandCommercialStore",
        lambda _: SimpleNamespace(binding=lambda _key: None if command is None else (command, 1)),
    )
    return FakeDatabase(secret)


def test_partial_command_identity_fails_closed_before_database() -> None:
    with pytest.raises(RuntimeConfigurationError, match="mode missing"):
        candidate.production_command_resolver(
            object(),  # type: ignore[arg-type]
            {
                "NFCORE_ENVIRONMENT": "production",
                "NFCORE_PRODUCTION_COMMAND_KEY_ID": KEY,
            },
        )


def test_disabled_command_ingress_never_touches_database() -> None:
    assert candidate.production_command_resolver(
        object(), {"NFCORE_ENVIRONMENT": "production"}  # type: ignore[arg-type]
    ) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"NFCORE_PRODUCTION_COMMAND_MODE": "unknown"},
        {"NFCORE_ENVIRONMENT": "staging"},
        {"NFCORE_API_GSM_MODE": "scoped-staging-sa-v1"},
    ],
)
def test_invalid_optin_fails_before_secret_or_database_access(changes) -> None:
    config = {**settings(), **changes}
    with pytest.raises(RuntimeConfigurationError, match="identity denied"):
        candidate.production_command_resolver(object(), config)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "variant",
    [
        "missing-command", "command-disabled", "wrong-product", "expired-command",
        "missing-secret", "secret-revoked", "wrong-purpose", "wrong-resource",
        "wrong-provider", "wrong-version", "wrong-workload",
    ],
)
def test_bad_canonical_bindings_never_attempt_external_secret_access(
    monkeypatch, variant: str
) -> None:
    cmd, secret = canonical()
    if variant == "missing-command":
        cmd = None  # type: ignore[assignment]
    elif variant == "command-disabled":
        cmd = replace(cmd, enabled=False)
    elif variant == "wrong-product":
        cmd = replace(cmd, product_id="other")
    elif variant == "expired-command":
        cmd = replace(cmd, not_after=datetime.now(UTC) - timedelta(seconds=1))
    elif variant == "missing-secret":
        secret = None  # type: ignore[assignment]
    elif variant == "secret-revoked":
        secret = replace(secret, state="revoked")
    elif variant == "wrong-purpose":
        secret = replace(secret, purpose="some.other-purpose")
    elif variant == "wrong-resource":
        secret = replace(secret, resource="projects/other-project/secrets/nfcore-command-prod")
    elif variant == "wrong-provider":
        secret = replace(secret, provider_id="other-provider")
    elif variant == "wrong-version":
        secret = replace(secret, canonical_version=2)
    elif variant == "wrong-workload":
        secret = replace(secret, workload_id="other-api")
    db = _binding_fixture(monkeypatch, cmd, secret)
    monkeypatch.setattr(
        candidate, "production_credentials",
        lambda *_args: pytest.fail("should not try external credentials"),
    )
    with pytest.raises(RuntimeConfigurationError, match="binding unavailable"):
        candidate.production_command_resolver(db, settings())  # type: ignore[arg-type]


def test_valid_canonical_binding_resolves_pinned_production_gsm_only(
    monkeypatch
) -> None:
    cmd, secret = canonical()
    db = _binding_fixture(monkeypatch, cmd, secret)
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
    monkeypatch.setattr(
        candidate, "GoogleSignatureSecretBackend",
        lambda *_args, **_kw: object(),
    )

    class Resolver:
        def __init__(self, _backend, *, environment):
            assert environment == "production"

        @contextmanager
        def resolve(self, reference, *, scope):
            assert reference.reference_id == REF
            assert scope == cmd.scope
            yield SimpleNamespace(reveal=lambda: b"x" * 32)

    monkeypatch.setattr(candidate, "SecretResolver", Resolver)
    result = candidate.production_command_resolver(db, settings())  # type: ignore[arg-type]
    assert isinstance(result, Resolver)
    assert called[0][0] == "client"
    assert called[1][1]["allowed_resources"] == frozenset({RESOURCE})
    assert called[1][1]["environment"] == "production"
    assert called[1][1]["workload_id"] == "nfcore-api"


def test_weak_material_fails_closed_without_secret_echo(monkeypatch) -> None:
    cmd, secret = canonical()
    db = _binding_fixture(monkeypatch, cmd, secret)
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
        def resolve(self, *_a, **_kw):
            yield SimpleNamespace(reveal=lambda: b"weak")

    monkeypatch.setattr(candidate, "SecretResolver", WeakResolver)
    with pytest.raises(RuntimeConfigurationError, match="GSM material unavailable"):
        candidate.production_command_resolver(db, settings())  # type: ignore[arg-type]
