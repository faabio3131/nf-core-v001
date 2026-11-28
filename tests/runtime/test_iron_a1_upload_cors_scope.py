"""Global portal CORS must not intercept the router-owned IRON A1 upload contract."""
from __future__ import annotations

from fastapi.testclient import TestClient

from kordena_fiscal.runtime.config import RuntimeEnvironment, RuntimeSettings
from kordena_fiscal.runtime.security import configure_edge_security
from kordena_fiscal.web import create_app

PORTAL = "https://app.nfcore.com.br"
IRON = "https://app.ironfitcore.com.br"


def _client() -> TestClient:
    app = create_app(iron_a1_allowed_origin=IRON)
    configure_edge_security(app, RuntimeSettings(
        environment=RuntimeEnvironment.TEST, persistence_backend="sqlite",
        database_url=None, secret_backend="none", require_https=False, port=8080,
        allowed_origins=(PORTAL,), trusted_hosts=("testserver",),
    ))
    return TestClient(app)


def _preflight(client: TestClient, path: str, origin: str):
    return client.options(path, headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_iron_origin_preflight_reaches_the_a1_router_without_credentials() -> None:
    response = _preflight(_client(), "/v1/iron/a1/upload", IRON)
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == IRON
    assert response.headers["access-control-allow-methods"] == "POST, OPTIONS"
    assert "access-control-allow-credentials" not in response.headers


def test_portal_origin_cannot_use_the_a1_upload() -> None:
    response = _preflight(_client(), "/v1/iron/a1/upload", PORTAL)
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_iron_origin_gains_no_access_to_other_routes() -> None:
    client = _client()
    for path in ("/v1/iron/a1/delegations", "/v1/portal/certificates/a1", "/v1/auth/login"):
        response = _preflight(client, path, IRON)
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


def test_portal_origin_keeps_global_credentialed_cors() -> None:
    response = _preflight(_client(), "/v1/auth/login", PORTAL)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PORTAL
    assert response.headers["access-control-allow-credentials"] == "true"
