"""P05 tests for staging binding and egress administration without live credentials."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.runtime.api_staging_gsm_probe import staging_probe_verifier
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.web.staging_gsm_binding_admin import create_staging_gsm_binding_router
from kordena_fiscal.web.staging_webhook_approval import create_staging_webhook_egress_router

COOKIES = {"nfcore_session": "signed-cookie", "nfcore_csrf": "csrf-proof"}
HEADERS = {"X-CSRF-Token": "csrf-proof"}


@dataclass
class _Account:
    account_id: str = "pilot-admin"
    tenant_id: str = "nfcore-staging-e2e"
    enabled: bool = True
    is_platform_admin: bool = True

    @property
    def platform_admin(self) -> bool:
        return self.is_platform_admin


class _Actor:
    def __init__(self, admin: bool = True, allow_integration: bool = True) -> None:
        self.account = _Account(is_platform_admin=admin)
        self.allow_integration = allow_integration

    def assert_permission(self, permission: object, *, unit_id: str | None = None) -> None:
        if not self.allow_integration or unit_id != "pilot-gsm-staging":
            raise ValueError("permission denied")


class _Identity:
    def __init__(self, actor: _Actor) -> None:
        self.actor = actor

    def authenticate_session(self, *, session_token: str, now: object) -> _Actor:
        assert session_token == "signed-cookie"
        return self.actor

    def assert_csrf(self, actor: _Actor, token: str) -> None:
        assert actor is self.actor and token == "csrf-proof"


class _BindingAdmin:
    def __init__(self) -> None:
        self.bound: list[Any] = []

    def current_binding(self, reference_id: str) -> Any | None:
        return next((b for b in reversed(self.bound) if b.reference_id == reference_id), None)

    def put(
        self, *, actor: _Actor, binding: Any, expected_revision: int, correlation_id: str
    ) -> None:
        assert actor.account.is_platform_admin
        previous = self.current_binding(binding.reference_id)
        if previous == binding:
            return
        assert expected_revision == (previous.revision if previous is not None else 0)
        assert correlation_id
        if previous != binding:
            self.bound.append(binding)


def _client(router: object) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_binding_requires_session_and_platform_admin() -> None:
    administration = _BindingAdmin()
    client = _client(create_staging_gsm_binding_router(_Identity(_Actor()), administration))
    assert client.post("/internal/staging/gsm-binding").status_code == 401
    client.cookies.update(COOKIES)
    assert client.post("/internal/staging/gsm-binding").status_code == 403
    response = client.post("/internal/staging/gsm-binding", headers=HEADERS)
    assert response.status_code == 200
    assert {b.workload_id for b in administration.bound} == {"nfcore-worker", "nfcore-api"}
    assert {b.workload_id: b.cloud_version for b in administration.bound} == {
        "nfcore-worker": "3", "nfcore-api": "2"
    }
    assert all(
        b.resource.endswith("nfcore-stg-pilot-webhook-signing")
        for b in administration.bound
    )



def test_binding_upgrades_existing_api_version_with_revision_and_replay() -> None:
    administration = _BindingAdmin()
    client = _client(create_staging_gsm_binding_router(_Identity(_Actor()), administration))
    client.cookies.update(COOKIES)
    assert client.post("/internal/staging/gsm-binding", headers=HEADERS).status_code == 200
    worker = administration.current_binding("sec_nfcore_staging_pilot_gsm_signing_01")
    assert worker.cloud_version == "3"
    administration.bound[0] = replace(worker, cloud_version="1")
    verifier = administration.current_binding("sec_nfcore_staging_pilot_gsm_verify_01")
    assert verifier.cloud_version == "2"
    administration.bound[-1] = replace(verifier, cloud_version="1")
    assert client.post("/internal/staging/gsm-binding", headers=HEADERS).status_code == 200
    upgraded_worker = administration.current_binding(worker.reference_id)
    assert upgraded_worker.cloud_version == "3"
    assert upgraded_worker.revision == 2
    upgraded = administration.current_binding(verifier.reference_id)
    assert upgraded.cloud_version == "2"
    assert upgraded.revision == 2
    count = len(administration.bound)
    assert client.post("/internal/staging/gsm-binding", headers=HEADERS).status_code == 200
    assert len(administration.bound) == count


def test_binding_rejects_non_platform_admin() -> None:
    administration = _BindingAdmin()
    client = _client(
        create_staging_gsm_binding_router(_Identity(_Actor(admin=False)), administration)
    )
    client.cookies.update(COOKIES)
    assert client.post("/internal/staging/gsm-binding", headers=HEADERS).status_code == 403
    assert not administration.bound


class _FrozenClock(datetime):
    """The pilot binding hard-codes not_after=2026-11-17; freeze time before it."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return datetime(2026, 11, 16, tzinfo=tz)


def test_commercial_trial_binding_denied_after_its_expiry() -> None:
    administration = _BindingAdmin()
    client = _client(create_staging_gsm_binding_router(_Identity(_Actor()), administration))
    client.cookies.update(COOKIES)
    response = client.post("/internal/staging/commercial-trial-binding", headers=HEADERS)
    if datetime.now(UTC) >= datetime(2026, 11, 17, tzinfo=UTC):
        assert response.status_code == 409
        assert not administration.bound


def test_commercial_trial_binding_is_platform_only_and_replay_safe(monkeypatch) -> None:
    from kordena_fiscal.web import staging_gsm_binding_admin as module

    monkeypatch.setattr(module, "datetime", _FrozenClock)
    administration = _BindingAdmin()
    client = _client(create_staging_gsm_binding_router(_Identity(_Actor()), administration))
    url = "/internal/staging/commercial-trial-binding"
    assert client.post(url).status_code == 401
    client.cookies.update(COOKIES)
    assert client.post(url).status_code == 403
    assert client.post(url, headers=HEADERS, json={"tenant_id": "attacker"}).status_code == 400
    response = client.post(url, headers=HEADERS)
    assert response.status_code == 200
    assert len(administration.bound) == 1
    bound = administration.bound[0]
    assert bound.reference_id == "sec_nfcore_commercial_trial_staging_01"
    assert bound.tenant_id == "nfcore-platform" and bound.unit_id is None
    assert bound.purpose == "commercial-trial-ingress"
    assert bound.workload_id == "nfcore-api"
    assert bound.cloud_version == "1"
    assert bound.resource.endswith("nfcore-commercial-trial-stg")
    assert bound.not_after is not None
    assert client.post(url, headers=HEADERS).status_code == 200
    assert len(administration.bound) == 1


def test_commercial_trial_binding_cannot_be_approved_by_tenant_owner() -> None:
    admin = _BindingAdmin()
    client = _client(create_staging_gsm_binding_router(_Identity(_Actor(admin=False)), admin))
    client.cookies.update(COOKIES)
    denied = client.post("/internal/staging/commercial-trial-binding", headers=HEADERS)
    assert denied.status_code == 403
    assert not admin.bound


class _Store:
    def __init__(self) -> None:
        self.version = 0
        self.record: dict[str, Any] | None = None
        self.audits: list[Any] = []
        self.committed = False

    def configuration_version(self, scope: Any, surface: str, destination: str) -> int:
        assert surface == "webhooks"
        return self.version

    def put_webhook_destination(self, destination: Any) -> Any:
        self.record = {"url": destination.url, "enabled": True, "approval_status": "pending",
                       "requested_by": "", "approved_by": None}
        return destination

    def advance_configuration_version(
        self, scope: Any, surface: str, destination: str, expected: int
    ) -> int:
        assert expected == self.version
        self.version += 1
        return self.version

    def record_webhook_approval(
        self, scope: Any, destination: str, *, status: str, version: int | None,
        expires_at: str | None, url_sha256: str | None,
        requested_by: str | None = None, approved_by: str | None = None
    ) -> None:
        assert self.record is not None
        self.record.update({"approval_status": status, "approved_version": version,
                            "approved_until": expires_at, "approved_url_sha256": url_sha256,
                            "approved_by": approved_by})
        if requested_by is not None:
            self.record["requested_by"] = requested_by

    def webhook_approval(self, scope: Any, destination: str) -> dict[str, Any] | None:
        return self.record


class _Uow:
    def __init__(self, store: _Store) -> None:
        self.control_plane = self
        self.commercial = store
        self.store = store

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_unit(self, tenant: str, unit: str) -> SimpleNamespace:
        return SimpleNamespace(
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION})
        )

    def append_audit(self, event: Any) -> None:
        self.store.audits.append(event)

    def commit(self) -> None:
        self.store.committed = True


def test_egress_request_requires_integration_permission_and_admin_approval() -> None:
    store = _Store()
    actor = _Actor()
    client = _client(create_staging_webhook_egress_router(
        _Identity(actor), lambda: _Uow(store)
    ))
    client.cookies.update(COOKIES)
    assert client.post("/internal/staging/webhook-destination/request").status_code == 403
    first = client.post("/internal/staging/webhook-destination/request", headers=HEADERS)
    assert first.status_code == 200
    assert first.json()["status"] == "pending"
    assert store.record is not None
    assert store.record["approved_by"] is None
    second = client.post("/internal/staging/webhook-destination/approve", headers=HEADERS)
    assert second.status_code == 200
    assert second.json()["status"] == "approved"
    assert store.record["approved_by"] == "pilot-admin"
    assert len(store.audits) == 2
    assert store.committed
    assert client.post(
        "/internal/staging/webhook-destination/approve", headers=HEADERS
    ).status_code == 409


def test_staging_verifier_refuses_wrong_environment_and_incomplete_identity() -> None:
    assert staging_probe_verifier(None, {}) is None
    import pytest

    with pytest.raises(RuntimeConfigurationError):
        staging_probe_verifier(None, {"NFCORE_API_GSM_MODE": "scoped-staging-sa-v1",
                                      "NFCORE_ENVIRONMENT": "production"})
    with pytest.raises(RuntimeConfigurationError):
        staging_probe_verifier(None, {"NFCORE_API_GSM_MODE": "scoped-staging-sa-v1",
                                      "NFCORE_ENVIRONMENT": "staging"})


def test_staging_gsm_diagnostics_are_bounded_and_do_not_leak_errors() -> None:
    import pytest

    class _FailedDatabase:
        def __call__(self) -> None:
            raise RuntimeError("PRIVATE_KEY=must-not-leak")

    env = {
        "NFCORE_API_GSM_MODE": "scoped-staging-sa-v1",
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_API_GSM_KEY_ID": "0" * 40,
        "NFCORE_API_GSM_KEY_CREATED_AT": "2026-10-14T08:00:00+00:00",
        "NFCORE_API_GSM_KEY_NOT_AFTER": "2026-11-10T08:00:00+00:00",
        "NFCORE_API_GSM_CREDENTIAL_JSON": "private-sensitive-value",
    }
    with pytest.raises(RuntimeConfigurationError, match="\\[DATABASE_READ\\]") as exc:
        staging_probe_verifier(_FailedDatabase(), env)
    assert "must-not-leak" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_staging_gsm_diagnostic_reports_binding_contract_without_contents() -> None:
    import pytest

    class _Uow:
        secret_bindings = SimpleNamespace(get=lambda reference: None)

        def __enter__(self) -> _Uow:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    env = {
        "NFCORE_API_GSM_MODE": "scoped-staging-sa-v1",
        "NFCORE_ENVIRONMENT": "staging",
        "NFCORE_API_GSM_KEY_ID": "0" * 40,
        "NFCORE_API_GSM_KEY_CREATED_AT": "2026-10-14T08:00:00+00:00",
        "NFCORE_API_GSM_KEY_NOT_AFTER": "2026-11-10T08:00:00+00:00",
        "NFCORE_API_GSM_CREDENTIAL_JSON": "private-sensitive-value",
    }
    with pytest.raises(RuntimeConfigurationError, match="\\[BINDING_CONTRACT\\]"):
        staging_probe_verifier(lambda: _Uow(), env)
