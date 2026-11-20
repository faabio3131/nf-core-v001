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

    def search_runner(authority, unit_id, environment, snapshot, version):
        assert authority.tenant_id == "tenant-authoritative"
        assert (unit_id, environment.value, snapshot, version) == (
            "unit-a", "homologation", "federal-facts", 1,
        )
        return {
            "status": "advisory", "advisory_only": True, "issuance_authorized": False,
            "complete_national_coverage": False, "counts": {"potential": 1},
            "results": [{"benefit_id": "lei-do-bem", "status": "potential"}],
        }

    router = build_cognitive_router(
        ident, executor, {"NFCORE_COGNITIVE_ENABLED": "true"},
        federal_benefit_runner=runner if configured else None,
        federal_benefit_search_runner=search_runner if configured else None,
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


def test_registry_index_is_read_only_and_requires_authorized_session():
    web = _web()
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    url = "/v1/portal/cognitive/economy/federal-programs?unit_id=unit-a"
    assert anonymous.get(url).status_code == 401
    response = web.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_only"] is True
    assert body["complete_national_coverage"] is False
    assert len(body["programs"]) == 8
    assert all(row["requires_reviewed_policy"] for row in body["programs"])
    assert web.get(url.replace("unit-a", "unit-b")).status_code == 403
    operator = _web(role=PortalRole.OPERATOR)
    assert operator.get(url).status_code == 403



def test_federal_search_uses_scoped_snapshot_not_browser_tax_rules():
    web = _web()
    url = "/v1/portal/cognitive/economy/federal-benefit-search"
    body = {key: BODY[key] for key in (
        "unit_id", "environment", "snapshot_id", "snapshot_version",
    )}
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.post(url, json=body).status_code == 401
    assert web.post(url, json=body).status_code == 403
    output = web.post(url, json=body, headers=_csrf_header(web))
    assert output.status_code == 200
    assert output.json()["status"] == "advisory"
    assert output.json()["complete_national_coverage"] is False
    assert output.json()["results"][0]["status"] == "potential"
    for forbidden in ("tenant_id", "cnae", "ncm", "program_code", "tax_code",
                      "benefit_content", "legal_citations", "approved_cents"):
        assert web.post(url, json={**body, forbidden: "spoofed"},
                        headers=_csrf_header(web)).status_code == 400
    assert web.post(url, json={**body, "snapshot_version": True},
                    headers=_csrf_header(web)).status_code == 400
    assert web.post(url, json={**body, "unit_id": "foreign"},
                    headers=_csrf_header(web)).status_code == 403
    assert web.post(url, json={**body, "environment": "invalid"},
                    headers=_csrf_header(web)).status_code == 400


def test_federal_search_no_runner_or_unauthorized_role_fails_closed():
    url = "/v1/portal/cognitive/economy/federal-benefit-search"
    body = {key: BODY[key] for key in (
        "unit_id", "environment", "snapshot_id", "snapshot_version",
    )}
    off = _web(configured=False)
    assert off.post(url, json=body, headers=_csrf_header(off)).status_code == 503
    operator = _web(role=PortalRole.OPERATOR)
    assert operator.post(url, json=body,
                         headers=_csrf_header(operator)).status_code == 403
