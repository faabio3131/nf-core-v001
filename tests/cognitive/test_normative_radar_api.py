"""T03 session, RBAC and canonical unit authority on the existing portal route."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.compliance.normative_watch import poll_normative_sources
from kordena_fiscal.security.human_identity import PortalRole
from kordena_fiscal.web import create_app

from .test_api import PASSWORD, Executor, identity

ROUTE = "/v1/portal/cognitive/economy/normative-alerts"


def _web(state, rows, role=PortalRole.OWNER):
    ident = identity(role)
    executor = Executor({"units": rows})
    router = build_cognitive_router(ident, executor, {
        "NFCORE_COGNITIVE_ENABLED": "true",
        "NFCORE_NORMATIVE_RADAR_ENABLED": "true",
        "NFCORE_NORMATIVE_RADAR_STATE": str(state),
    })
    web = TestClient(
        create_app(human_identity=ident, portal_executor=executor, cognitive_router=router),
        base_url="https://nfcore.test",
    )
    assert web.post("/v1/auth/login", json={
        "email": f"{role.value}@example.com", "password": PASSWORD,
    }).status_code == 200
    return web


def test_normative_api_session_rbac_scope_and_replay(tmp_path: Path):
    state = tmp_path / "state.json"
    poll_normative_sources(
        state_path=state, fetch=lambda url: b"<a href='/edital'>Edital REFIS</a>", economy=True,
    )
    rows = [{"unit_id": "unit-a", "enabled_environments": ["homologation"]}]
    web = _web(state, rows)
    query = {"unit_id": "unit-a"}
    anonymous = TestClient(web.app, base_url="https://nfcore.test")
    assert anonymous.get(ROUTE, params=query).status_code == 401
    result = web.get(ROUTE, params=query)
    assert result.status_code == 200
    data = result.json()
    assert data["tenant_id"] == "tenant-authoritative"
    assert data["unit_id"] == "unit-a"
    assert any(x["category"] == "refis" for x in data["alerts"])
    assert web.get(ROUTE, params=query).json() == data
    assert web.get(ROUTE, params={"unit_id": "unit-b"}).status_code == 403
    assert web.get(ROUTE, params={**query, "environment": "production"}).status_code == 403
    assert _web(state, rows, PortalRole.OPERATOR).get(ROUTE, params=query).status_code == 403
    foreign = [{"unit_id": "unit-a", "tenant_id": "attacker",
                "enabled_environments": ["homologation"]}]
    assert _web(state, foreign).get(ROUTE, params=query).status_code == 403
    assert _web(state, []).get(ROUTE, params=query).status_code == 403
    assert web.get(ROUTE, params={**query, "tenant_id": "attacker"}).json() == data
    assert web.post(ROUTE, json=query).status_code == 405
    state.write_text("{}")
    assert web.get(ROUTE, params=query).status_code == 503
