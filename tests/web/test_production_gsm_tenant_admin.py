"""Governed dynamic GSM metadata administration uses canonical RBAC/CSRF."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.security.secret_binding import SecretBinding
from kordena_fiscal.web import production_gsm_tenant_admin as admin

PROJECT = "fm-core-live"


def _binding() -> SecretBinding:
    return SecretBinding(
        reference_id="sec_nfcore_academy_a_main_signing",
        tenant_id="academy-a",
        unit_id="main",
        purpose="webhook-signing",
        runtime_environment="production",
        fiscal_environment=None,
        provider_id="google-secret-manager",
        workload_id="nfcore-worker",
        kind="signature",
        canonical_version=1,
        resource=f"projects/{PROJECT}/secrets/academy-a-main",
        cloud_version="1",
    )


class Db:
    @contextmanager
    def __call__(self):
        yield SimpleNamespace(
            control_plane=SimpleNamespace(
                get_unit=lambda tenant, unit: (
                    SimpleNamespace(
                        enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION})
                    )
                    if (tenant, unit) == ("academy-a", "main")
                    else None
                )
            ),
            secret_bindings=SimpleNamespace(list_active_signatures=lambda **_: ()),
        )


class BindingAdmin:
    def __init__(self):
        self.stored: SecretBinding | None = None
        self.events: list[tuple[SecretBinding, int]] = []

    def current_binding(self, reference_id):
        if self.stored is not None and self.stored.reference_id == reference_id:
            return self.stored
        return None

    def put(self, *, actor, binding, expected_revision, correlation_id):
        self.events.append((binding, expected_revision))
        self.stored = binding


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch):
    source = {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_PRODUCTION_GSM_TENANT_ADMIN": "platform-admin-v1",
        "NFCORE_GSM_PROJECT_ID": PROJECT,
        "NFCORE_GSM_PROJECT_NUMBER": "123456789012",
        "NFCORE_GSM_ALLOWED_PROJECTS": PROJECT,
        "NFCORE_GSM_API_SERVICE_ACCOUNT": f"nfcore-api@{PROJECT}.iam.gserviceaccount.com",
        "NFCORE_GSM_WORKER_SERVICE_ACCOUNT": f"nfcore-worker@{PROJECT}.iam.gserviceaccount.com",
    }
    monkeypatch.setattr(admin, "_platform_actor", lambda *_: (object(), object()))
    monkeypatch.setattr(admin, "_csrf", lambda *_: None)
    authority = BindingAdmin()
    app = FastAPI()
    app.include_router(
        admin.create_production_gsm_tenant_router(
            object(),
            authority,
            Db(),
            environ=source,
        )
    )
    with TestClient(app) as client:
        yield client, authority, source


def test_admin_can_register_then_revoke_exact_tenant_metadata(portal):
    client, authority, _ = portal
    binding = _binding()
    response = client.post(
        "/internal/production/gsm-tenant-bindings",
        json={
            "binding": binding.metadata(),
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "bound",
        "reference_id": binding.reference_id,
        "revision": 1,
    }
    revoked = replace(binding, state="revoked", revision=2)
    response = client.post(
        "/internal/production/gsm-tenant-bindings",
        json={
            "binding": revoked.metadata(),
            "expected_revision": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert [revision for _, revision in authority.events] == [0, 1]


def test_admin_rejects_cross_project_missing_unit_and_secret_material(portal):
    client, authority, _ = portal
    binding = _binding()
    for override in [
        {"resource": "projects/other-project/secrets/leak"},
        {"tenant_id": "academy-b"},
        {"workload_id": "nfcore-api"},
        {"runtime_environment": "staging"},
    ]:
        record = binding.metadata() | override
        response = client.post(
            "/internal/production/gsm-tenant-bindings",
            json={
                "binding": record,
                "expected_revision": 0,
            },
        )
        assert response.status_code == 409
    record = binding.metadata() | {"private_key": "never"}
    response = client.post(
        "/internal/production/gsm-tenant-bindings",
        json={
            "binding": record,
            "expected_revision": 0,
        },
    )
    assert response.status_code == 409
    assert authority.events == []


def test_admin_requires_global_enablement_and_platform_auth(portal, monkeypatch):
    client, authority, source = portal
    binding = _binding()
    source["NFCORE_ENVIRONMENT"] = "staging"
    assert (
        client.post(
            "/internal/production/gsm-tenant-bindings",
            json={
                "binding": binding.metadata(),
                "expected_revision": 0,
            },
        ).status_code
        == 403
    )
    source["NFCORE_ENVIRONMENT"] = "production"
    monkeypatch.setattr(
        admin,
        "_platform_actor",
        lambda *_: (_ for _ in ()).throw(HTTPException(403, "PLATFORM_ADMIN_REQUIRED")),
    )
    assert (
        client.post(
            "/internal/production/gsm-tenant-bindings",
            json={
                "binding": binding.metadata(),
                "expected_revision": 0,
            },
        ).status_code
        == 403
    )
    assert authority.events == []
