"""T07 HTTP authorization and request-shape regression."""
from fastapi.testclient import TestClient

from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.security.human_identity import PortalRole
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

from .test_api import PASSWORD, Executor, identity

ROUTE = "/v1/portal/cognitive/economy/simples-assessment"
BODY = {"unit_id": "unit-a", "environment": "homologation", "snapshot_id": "s",
        "snapshot_version": 1, "rule_id": "r", "rule_version": 1}


def _web(role=PortalRole.OWNER):
    ident = identity(role)
    executor = Executor()

    def run(authority, unit, environment, snapshot, version, rule, rule_version):
        assert authority.tenant_id == "tenant-authoritative"
        assert (unit, environment.value, snapshot, version, rule, rule_version) == (
            "unit-a", "homologation", "s", 1, "r", 1,
        )
        return {"advisory_only": True}

    router = build_cognitive_router(
        ident, executor, {"NFCORE_COGNITIVE_ENABLED": "true"}, assessment_runner=run,
    )
    web = TestClient(
        create_app(human_identity=ident, portal_executor=executor, cognitive_router=router),
        base_url="https://nfcore.test",
    )
    assert web.post("/v1/auth/login", json={
        "email": f"{role.value}@example.com", "password": PASSWORD,
    }).status_code == 200
    return web


def test_t07_route_authority():
    web = _web()
    headers = {CSRF_HEADER: web.cookies.get(CSRF_COOKIE) or ""}
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.post(ROUTE, json=BODY).status_code == 401
    assert web.post(ROUTE, json=BODY).status_code == 403
    assert web.post(ROUTE, json=BODY, headers=headers).json() == {"advisory_only": True}
    for extra in ("tenant_id", "payroll_cents", "legal_citations", "estimated_cents",
                  "ibs_cbs_election", "rtc_projection", "nominal_rates"):
        assert web.post(ROUTE, json={**BODY, extra: "forged"}, headers=headers).status_code == 400
    invalid = web.post(ROUTE, json={**BODY, "snapshot_version": True}, headers=headers)
    assert invalid.status_code == 400
    assert web.post(ROUTE, json={**BODY, "unit_id": "unit-b"}, headers=headers).status_code == 403
    operator = _web(PortalRole.OPERATOR)
    assert operator.post(ROUTE, json=BODY, headers={
        CSRF_HEADER: operator.cookies.get(CSRF_COOKIE) or "",
    }).status_code == 403
