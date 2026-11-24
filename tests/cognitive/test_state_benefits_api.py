"""T09 state catalog HTTP must preserve session, RBAC, CSRF and scoped IDs."""
import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.security.human_identity import PortalRole
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

from .test_api import PASSWORD, Executor, identity

PREFIX = "/v1/portal/cognitive/economy"
BODY = {
    "unit_id": "unit-a", "environment": "homologation",
    "snapshot_id": "t09-reviewed", "snapshot_version": 1,
    "benefit_id": "t09-rule", "benefit_version": 1,
}


def _web(role=PortalRole.OWNER, *, configured=True):
    ident = identity(role)
    executor = Executor()

    def runner(auth, unit, env, snapshot, snapshot_version, rule, rule_version):
        assert auth.tenant_id == "tenant-authoritative"
        assert (unit, env.value, snapshot, snapshot_version, rule, rule_version) == (
            "unit-a", "homologation", "t09-reviewed", 1, "t09-rule", 1,
        )
        return {
            "status": "potential", "uf": "SP", "advisory_only": True,
            "issuance_authorized": False, "estimated_cents": None,
        }

    def search_runner(auth, unit, env, snapshot, snapshot_version):
        assert auth.tenant_id == "tenant-authoritative"
        assert (unit, env.value, snapshot, snapshot_version) == (
            "unit-a", "homologation", "t09-reviewed", 1,
        )
        return {
            "status": "advisory", "uf": "SP",
            "complete_state_benefit_coverage": False, "results": [{
                "status": "potential", "benefit_id": "t09-rule",
            }],
        }

    router = build_cognitive_router(
        ident, executor, {"NFCORE_COGNITIVE_ENABLED": "true"},
        state_benefit_runner=runner if configured else None,
        state_search_runner=search_runner if configured else None,
    )
    web = TestClient(
        create_app(human_identity=ident, portal_executor=executor, cognitive_router=router),
        base_url="https://nfcore.test",
    )
    assert web.post("/v1/auth/login", json={
        "email": f"{role.value}@example.com", "password": PASSWORD,
    }).status_code == 200
    return web


def csrf(web):
    return {CSRF_HEADER: web.cookies.get(CSRF_COOKIE) or ""}


def test_state_index_requires_session_and_lists_all_states_without_false_homologation():
    web = _web()
    url = PREFIX + "/state-jurisdictions?unit_id=unit-a"
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.get(url).status_code == 401
    index = web.get(url)
    assert index.status_code == 200
    assert len(index.json()["uf"]) == 27
    assert index.json()["homologated_state_count"] == 0
    assert index.json()["complete_state_benefit_coverage"] is False
    assert index.json()["issuance_authorized"] is False
    assert web.get(url.replace("unit-a", "unit-b")).status_code == 403


def test_state_search_requires_csrf_scope_and_only_ids_from_browser():
    web = _web()
    url = PREFIX + "/state-benefit-search"
    body = {key: BODY[key] for key in (
        "unit_id", "environment", "snapshot_id", "snapshot_version",
    )}
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.post(url, json=body).status_code == 401
    assert web.post(url, json=body).status_code == 403
    result = web.post(url, json=body, headers=csrf(web))
    assert result.status_code == 200
    assert result.json()["uf"] == "SP"
    assert result.json()["complete_state_benefit_coverage"] is False
    for field in (
        "uf", "tenant_id", "cnae", "ncm", "cfop", "legal_citations",
        "allowed_regimes", "benefit_kind", "state_normative_reference",
    ):
        assert web.post(url, json={**body, field: "forged"},
                        headers=csrf(web)).status_code == 400
    assert web.post(url, json={**body, "snapshot_version": True},
                    headers=csrf(web)).status_code == 400
    assert web.post(url, json={**body, "unit_id": "unit-b"},
                    headers=csrf(web)).status_code == 403
    assert web.post(url, json={**body, "environment": "invalid"},
                    headers=csrf(web)).status_code == 400


def test_state_benefit_evaluation_requires_session_and_explicit_version():
    web = _web()
    url = PREFIX + "/state-benefit"
    assert web.post(url, json=BODY, headers=csrf(web)).status_code == 200
    assert web.post(url, json={**BODY, "benefit_version": True},
                    headers=csrf(web)).status_code == 400
    assert web.post(url, json={**BODY, "uf": "RJ"},
                    headers=csrf(web)).status_code == 400
    assert web.post(url, json={**BODY, "unit_id": "unit-b"},
                    headers=csrf(web)).status_code == 403


def test_state_api_fails_closed_when_unconfigured_or_unauthorized():
    disabled = _web(configured=False)
    body = {key: BODY[key] for key in (
        "unit_id", "environment", "snapshot_id", "snapshot_version",
    )}
    assert disabled.post(
        PREFIX + "/state-benefit", json=BODY, headers=csrf(disabled),
    ).status_code == 503
    assert disabled.post(
        PREFIX + "/state-benefit-search", json=body, headers=csrf(disabled),
    ).status_code == 503
    operator = _web(role=PortalRole.OPERATOR)
    assert operator.get(
        PREFIX + "/state-jurisdictions?unit_id=unit-a",
    ).status_code == 403
    assert operator.post(
        PREFIX + "/state-benefit-search", json=body, headers=csrf(operator),
    ).status_code == 403


@pytest.mark.parametrize("path", ["opportunity-radar", "quarterly-simulation", "annual-regime-comparison"])
def test_economy_unit_csrf_and_month_authority(path):
    calls = []

    def scan(auth, unit, env, month):
        calls.append((auth.tenant_id, unit, env.value, month.isoformat()))
        return {"opportunities": []}

    ident = identity(PortalRole.OWNER)
    executor = Executor()
    router = build_cognitive_router(ident, executor, {"NFCORE_COGNITIVE_ENABLED": "true"},
                                    opportunity_runner=scan, simulation_runner=scan,
                                    annual_comparison_runner=scan)
    web = TestClient(create_app(human_identity=ident, portal_executor=executor,
                                cognitive_router=router), base_url="https://nfcore.test")
    url = PREFIX + "/" + path
    body = {"unit_id": "unit-a", "environment": "homologation", "competence": "2026-11-01"}
    assert web.post(url, json=body).status_code == 401
    assert web.post("/v1/auth/login", json={"email": "owner@example.com",
                                            "password": PASSWORD}).status_code == 200
    assert web.post(url, json=body).status_code == 403
    for change, expected in (({"unit_id": "unit-b"}, 403), ({"tenant_id": "fake"}, 400),
                             ({"competence": "2026-11-02"}, 400), ({"estimated_cents": 1}, 400)):
        assert web.post(url, json={**body, **change}, headers=csrf(web)).status_code == expected
    assert web.post(url, json=body, headers=csrf(web)).status_code == 200
    assert calls == [("tenant-authoritative", "unit-a", "homologation", "2026-11-01")]
