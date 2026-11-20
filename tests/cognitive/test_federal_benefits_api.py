"""T08 Portal: same session, CSRF, RBAC and unit-authority gates as T05–T07."""
from fastapi.testclient import TestClient

from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.security.human_identity import PortalRole
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

from .test_api import PASSWORD, Executor, identity

ROUTE = "/v1/portal/cognitive/economy/federal-benefit"
BODY = {
    "unit_id": "unit-a", "environment": "homologation",
    "snapshot_id": "federal-facts", "snapshot_version": 1,
    "benefit_id": "lei-do-bem", "benefit_version": 1,
}


def _web(role=PortalRole.OWNER, *, configured=True):
    ident = identity(role)
    executor = Executor()

    def runner(authority, unit_id, environment, snapshot, version, benefit, benefit_ver):
        assert authority.tenant_id == "tenant-authoritative"
        assert (unit_id, environment.value, snapshot, version, benefit, benefit_ver) == (
            "unit-a", "homologation", "federal-facts", 1, "lei-do-bem", 1,
        )
        return {
            "status": "potential", "advisory_only": True,
            "issuance_authorized": False, "estimated_cents": None,
        }

    router = build_cognitive_router(
        ident, executor, {"NFCORE_COGNITIVE_ENABLED": "true"},
        federal_benefit_runner=runner if configured else None,
    )
    web = TestClient(
        create_app(human_identity=ident, portal_executor=executor, cognitive_router=router),
        base_url="https://nfcore.test",
    )
    assert web.post("/v1/auth/login", json={
        "email": f"{role.value}@example.com", "password": PASSWORD,
    }).status_code == 200
    return web


def _csrf_header(web):
    return {CSRF_HEADER: web.cookies.get(CSRF_COOKIE) or ""}


def test_federal_catalog_requires_session_permission_and_csrf():
    web = _web()
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.post(ROUTE, json=BODY).status_code == 401
    assert web.post(ROUTE, json=BODY).status_code == 403
    output = web.post(ROUTE, json=BODY, headers=_csrf_header(web))
    assert output.status_code == 200
    assert output.json()["status"] == "potential"
    assert output.json()["issuance_authorized"] is False
    assert output.json()["estimated_cents"] is None


def test_federal_catalog_rejects_browser_rule_forgery_and_cross_unit():
    web = _web()
    headers = _csrf_header(web)
    for key in (
        "tenant_id", "cnae", "ncm", "allowed_regimes", "legal_citations",
        "benefit_content", "tax_code", "estimated_cents", "review_status",
    ):
        assert web.post(ROUTE, json={**BODY, key: "forged"},
                        headers=headers).status_code == 400
    assert web.post(ROUTE, json={**BODY, "snapshot_version": True},
                    headers=headers).status_code == 400
    assert web.post(ROUTE, json={**BODY, "unit_id": "unit-b"},
                    headers=headers).status_code == 403
    assert web.post(ROUTE, json={**BODY, "environment": "invalid"},
                    headers=headers).status_code == 400


def test_federal_catalog_fails_closed_for_unconfigured_or_insufficient_role():
    web = _web(configured=False)
    assert web.post(ROUTE, json=BODY, headers=_csrf_header(web)).status_code == 503
    operator = _web(role=PortalRole.OPERATOR)
    assert operator.post(ROUTE, json=BODY,
                         headers=_csrf_header(operator)).status_code == 403
