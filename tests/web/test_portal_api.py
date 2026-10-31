from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

PASSWORD = "correct-horse-nfcore-2026"


class RecordingPortalExecutor:
    def __init__(self) -> None:
        self.snapshot_authority: AuthenticatedHuman | None = None
        self.surface_authority: AuthenticatedHuman | None = None
        self.operation_authority: AuthenticatedHuman | None = None
        self.operation_payload: Mapping[str, Any] | None = None
        self.operation_key: str | None = None

    def snapshot(self, *, authority: AuthenticatedHuman) -> Mapping[str, Any]:
        self.snapshot_authority = authority
        return {"production_state": "BLOCKED_EXTERNAL", "readiness": "EVIDENCE_REQUIRED"}

    def surface(
        self,
        *,
        surface_id: str,
        authority: AuthenticatedHuman,
        unit_id: str | None = None,
        environment: object = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Mapping[str, Any]]:
        self.surface_authority = authority
        return ({"document_id": "DOC-1", "status": "AUTHORIZED"},)

    def execute(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        self.operation_authority = authority
        self.operation_payload = payload
        self.operation_key = idempotency_key
        return {"operation_id": operation_id, "status": "ACCEPTED"}


class SecretLeakingExecutor(RecordingPortalExecutor):
    def snapshot(self, *, authority: AuthenticatedHuman) -> Mapping[str, Any]:
        return {"session_token": "must-never-leak"}


def identity(role: PortalRole = PortalRole.OWNER) -> HumanIdentityService:
    hasher = ScryptPasswordHasher()
    account = HumanAccount(
        account_id=f"account-{role.value}",
        email=f"{role.value}@example.com",
        password_hash=hasher.hash(PASSWORD),
        tenant_id="tenant-authoritative",
        role=role,
        unit_ids=frozenset({"unit-a"}),
    )
    return HumanIdentityService(
        accounts=InMemoryHumanAccountRepository((account,)),
        sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
        session_ttl=timedelta(hours=8),
    )


def logged_client(
    executor: RecordingPortalExecutor | None,
    *,
    role: PortalRole = PortalRole.OWNER,
) -> TestClient:
    web = TestClient(
        create_app(human_identity=identity(role), portal_executor=executor),
        base_url="https://nfcore.test",
    )
    login = web.post(
        "/v1/auth/login",
        json={"email": f"{role.value}@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    return web


def test_portal_is_not_exposed_without_human_identity() -> None:
    anonymous = TestClient(create_app(), base_url="https://nfcore.test")
    assert anonymous.get("/v1/portal/bootstrap").status_code == 404


def test_bootstrap_derives_tenant_from_session_not_headers() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor)

    response = web.get(
        "/v1/portal/bootstrap",
        headers={"X-FM-Tenant-Id": "attacker-tenant", "X-FM-Unit-Id": "attacker-unit"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-authoritative"
    assert body["unit_ids"] == ["unit-a"]
    assert body["projection"]["production_state"] == "BLOCKED_EXTERNAL"
    assert executor.snapshot_authority is not None
    assert executor.snapshot_authority.account.tenant_id == "tenant-authoritative"


def test_portal_fails_closed_when_product_executor_is_missing() -> None:
    web = logged_client(None)

    response = web.get("/v1/portal/bootstrap")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "PORTAL_RUNTIME_NOT_READY"


def test_surface_enforces_role_and_unit_scope() -> None:
    executor = RecordingPortalExecutor()
    operator = logged_client(executor, role=PortalRole.OPERATOR)

    allowed = operator.get("/v1/portal/surfaces/documents?unit_id=unit-a")
    forbidden_admin = operator.get("/v1/portal/surfaces/certificates?unit_id=unit-a")
    forbidden_unit = operator.get("/v1/portal/surfaces/documents?unit_id=unit-b")

    assert allowed.status_code == 200
    assert allowed.json()["rows"][0]["document_id"] == "DOC-1"
    assert forbidden_admin.status_code == 403
    assert forbidden_unit.status_code == 403


def test_mutation_requires_csrf_and_idempotency() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor)

    no_csrf = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json={"unit_id": "unit-a"},
        headers={"Idempotency-Key": "idem-1"},
    )
    assert no_csrf.status_code == 403

    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    no_key = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json={"unit_id": "unit-a"},
        headers={CSRF_HEADER: csrf},
    )
    assert no_key.status_code == 400
    assert no_key.json()["detail"]["code"] == "MISSING_IDEMPOTENCY_KEY"

    accepted = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json={"unit_id": "unit-a", "document": {"model": "55"}},
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "idem-2"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    assert executor.operation_authority is not None
    assert executor.operation_authority.account.tenant_id == "tenant-authoritative"
    assert executor.operation_payload == {"unit_id": "unit-a", "document": {"model": "55"}}
    assert executor.operation_key == "idem-2"


def test_browser_cannot_mass_assign_tenant_or_other_authority_fields() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor)
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf

    response = web.post(
        "/v1/portal/operations/issueFiscalDocument",
        json={"unit_id": "unit-a", "tenant_id": "attacker-tenant"},
        headers={CSRF_HEADER: csrf, "Idempotency-Key": "idem-spoof"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BROWSER_AUTHORITY_REJECTED"
    assert executor.operation_authority is None


def test_query_operation_does_not_require_idempotency_key() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor, role=PortalRole.AUDITOR)
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf

    response = web.post(
        "/v1/portal/operations/queryFiscalDocument",
        json={"unit_id": "unit-a", "document_id": "DOC-1"},
        headers={CSRF_HEADER: csrf},
    )

    assert response.status_code == 200
    assert executor.operation_key is None


def test_portal_projection_rejects_secret_material() -> None:
    web = logged_client(SecretLeakingExecutor())

    response = web.get("/v1/portal/bootstrap")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "PORTAL_SECRET_BOUNDARY_VIOLATION"


def test_unknown_surface_and_operation_are_not_routable_authority() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor)

    assert web.get("/v1/portal/surfaces/not-real").status_code == 404
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf
    unknown = web.post(
        "/v1/portal/operations/not-real",
        json={},
        headers={CSRF_HEADER: csrf},
    )
    assert unknown.status_code == 404


def test_archive_reference_query_uses_existing_portal_role_and_scope() -> None:
    executor = RecordingPortalExecutor()
    web = logged_client(executor, role=PortalRole.AUDITOR)
    csrf = web.cookies.get(CSRF_COOKIE)
    assert csrf

    allowed = web.post(
        "/v1/portal/operations/queryArchiveReference",
        json={"unit_id": "unit-a", "document_reference": "document-1"},
        headers={CSRF_HEADER: csrf},
    )
    other_unit = web.post(
        "/v1/portal/operations/queryArchiveReference",
        json={"unit_id": "unit-b", "document_reference": "document-1"},
        headers={CSRF_HEADER: csrf},
    )
    assert allowed.status_code == 200
    assert executor.operation_key is None
    assert executor.operation_authority is not None
    assert executor.operation_authority.account.tenant_id == "tenant-authoritative"
    assert other_unit.status_code == 403


def test_tax_reform_surface_uses_existing_session_rbac_and_unit_isolation() -> None:
    executor = RecordingPortalExecutor()
    owner = logged_client(executor, role=PortalRole.OWNER)
    permitted = owner.get(
        "/v1/portal/surfaces/tax-reform?unit_id=unit-a&environment=homologation",
        headers={"X-FM-Tenant-Id": "spoofed-tenant"},
    )
    assert permitted.status_code == 200
    assert executor.surface_authority is not None
    assert executor.surface_authority.tenant_id == "tenant-authoritative"
    assert owner.get("/v1/portal/surfaces/tax-reform?unit_id=unit-b").status_code == 403
    assert owner.get(
        "/v1/portal/surfaces/tax-reform?unit_id=unit-a&environment=invalid"
    ).status_code == 400


def test_profile_registration_denies_operator_and_cross_unit_before_executor() -> None:
    executor = RecordingPortalExecutor()
    operator = logged_client(executor, role=PortalRole.OPERATOR)
    token = operator.cookies.get(CSRF_COOKIE)
    assert token
    headers = {CSRF_HEADER: token, "Idempotency-Key": "fiscal-registration-negative"}
    blocked = operator.post(
        "/v1/portal/operations/registerFiscalProfile",
        json={"unit_id": "unit-a"}, headers=headers,
    )
    assert blocked.status_code == 403
    owner = logged_client(executor, role=PortalRole.OWNER)
    token = owner.cookies.get(CSRF_COOKIE)
    assert token
    cross_unit = owner.post(
        "/v1/portal/operations/registerFiscalProfile",
        json={"unit_id": "unit-b"},
        headers={CSRF_HEADER: token, "Idempotency-Key": "cross-unit-attempt"},
    )
    assert cross_unit.status_code == 403
    assert executor.operation_authority is None
