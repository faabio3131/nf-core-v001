"""A1 delegated onboarding: canonical authority, single-use, scope, CORS and secrets."""
from __future__ import annotations

import base64
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.iron_a1_delegation import (
    IRON_A1_DELEGATION_SCHEMA,
    IronA1DelegationStore,
)
from kordena_fiscal.web.app import AuthorizedBridgeContext, BridgeHttpContext, HttpContractError
from kordena_fiscal.web.iron_a1_delegation import (
    create_iron_a1_router,
    trusted_iron_origin,
)

_CNPJ = "11222333000181"
_ORIGIN = "https://app.ironfitcore.com.br"

class _Database:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        for statement in IRON_A1_DELEGATION_SCHEMA:
            self.db.execute(statement)
        self.db.commit()
        self.cnpj = _CNPJ

    @contextmanager
    def connection(self):
        yield self.db

    @contextmanager
    def __call__(self):
        database = self
        class ControlPlane:
            def resolve_profile(self, *, host_namespace, tenant_id, unit_id, environment, instant):
                if (host_namespace, tenant_id, unit_id, environment) != (
                    "fm.iron", "tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION
                ):
                    return None
                return SimpleNamespace(cnpj=SimpleNamespace(value=database.cnpj))
        yield SimpleNamespace(control_plane=ControlPlane())

class _Vault:
    def __init__(self):
        self.calls = []
        self.evidence = None

    def provision(self, *, scope, issuer_cnpj, pkcs12_bytes, password):
        self.calls.append((scope, issuer_cnpj, pkcs12_bytes, password))
        self.evidence = SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(days=7))
        return self.evidence

    def inspect(self, *, scope, issuer_cnpj):
        assert scope.host_namespace == "fm.iron"
        assert scope.tenant_id == "tenant-a"
        assert issuer_cnpj == _CNPJ
        return self.evidence

class _Security:
    def __init__(self, *, environment=FiscalEnvironment.HOMOLOGATION):
        self.environment = environment
        self.calls = []

    def authorize(self, *, operation_id, context):
        self.calls.append(operation_id)
        if operation_id not in {"prepareIronA1Delegation", "readIronA1Status"}:
            raise HttpContractError(
                403,"WORKLOAD_CAPABILITY_DENIED","not allowed", context.correlation_id,
            )
        if context.credential_id != "iron-credential" or context.presented_secret != "test-secret":
            raise HttpContractError(
                401,"WORKLOAD_AUTHENTICATION_FAILED","not allowed", context.correlation_id,
            )
        return AuthorizedBridgeContext(
            authority=SimpleNamespace(scope=ExecutionScope(
                host_namespace=context.host_namespace, tenant_id="tenant-a",
                unit_id="unit-a", environment=self.environment,
                correlation_id=context.correlation_id,
            )),
            correlation_id=context.correlation_id,
        )

def _context(request):
    h = request.headers
    return BridgeHttpContext(
        host_namespace=h.get("x-fm-host-namespace", ""),
        tenant_id="tenant-a", unit_id="unit-a", environment="homologation",
        correlation_id="test-correlation", causation_id=None,
        credential_id=h.get("x-fm-workload-credential-id",""),
        presented_secret=h.get("authorization","").removeprefix("Bearer "),
        idempotency_key=None,
    )

def _fixture(*, environment=FiscalEnvironment.HOMOLOGATION, origin=_ORIGIN, vault_available=True):
    db = _Database()
    vault = _Vault()
    security = _Security(environment=environment)
    app = FastAPI()
    app.include_router(create_iron_a1_router(
        security=security, database=db, vault=vault if vault_available else None,
        allowed_origin=origin, context_from_request=_context,
    ))
    @app.exception_handler(HttpContractError)
    async def errors(_request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"code":exc.code})
    return TestClient(app), db, vault, security

def _workload_headers(host="fm.iron"):
    return {"X-FM-Host-Namespace": host, "X-FM-Workload-Credential-Id": "iron-credential",
            "Authorization": "Bearer test-secret", "Content-Type": "application/json"}

def _prepare(client, cnpj=_CNPJ):
    return client.post("/v1/iron/a1/delegations",
                       headers=_workload_headers(),
                       json={"issuer_cnpj":cnpj,"actor_user_id":"user-owner-1"})

def test_canonical_workload_direct_upload_and_status_without_credential_leaks():
    client, db, vault, security = _fixture()
    response = _prepare(client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING_UPLOAD"
    assert body["upload_path"] == "/v1/iron/a1/upload"
    token = body["delegation_token"]
    assert len(token) >= 40
    assert token not in str(db.db.execute("SELECT * FROM fm_iron_a1_delegations").fetchall())
    assert db.db.execute("SELECT COUNT(*) FROM fm_iron_a1_delegations").fetchone()[0] == 1

    uploaded = client.post("/v1/iron/a1/upload",
                           headers={"Origin":_ORIGIN, "Content-Type":"application/json"},
                           json={"delegation_token":token,
                                 "pfx_base64":base64.b64encode(b"synthetic-pfx").decode(),
                                 "password":"sample-only"})
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "STORED"
    assert uploaded.json()["official_homologation"] == "NOT_VERIFIED"
    assert uploaded.headers["access-control-allow-origin"] == _ORIGIN
    assert uploaded.headers["cache-control"] == "no-store"
    assert len(vault.calls) == 1
    assert vault.calls[0][0].host_namespace == "fm.iron"
    assert vault.calls[0][1:] == (_CNPJ, b"synthetic-pfx", b"sample-only")
    assert "synthetic-pfx" not in uploaded.text and "sample-only" not in uploaded.text

    replay = client.post("/v1/iron/a1/upload",
                         headers={"Origin":_ORIGIN},
                         json={"delegation_token":token,
                               "pfx_base64":base64.b64encode(b"synthetic-pfx").decode(),
                               "password":"sample-only"})
    assert replay.status_code == 409
    assert len(vault.calls) == 1
    readback = client.post("/v1/iron/a1/status",headers=_workload_headers(),
                           json={"issuer_cnpj":_CNPJ})
    assert readback.status_code == 200
    assert readback.json()["status"] == "STORED"
    assert "password" not in readback.text and "pfx" not in readback.text
    assert security.calls == ["prepareIronA1Delegation", "readIronA1Status"]

def test_expired_token_foreign_origin_and_replay_are_denied():
    client, db, vault, _ = _fixture()
    token = _prepare(client).json()["delegation_token"]
    for origin in ("https://evil.example", "", "https://app.ironfitcore.com.br.evil.example"):
        headers = {"Content-Type":"application/json", **({"Origin":origin} if origin else {})}
        result = client.post("/v1/iron/a1/upload", headers=headers,
                             json={"delegation_token":token,
                                   "pfx_base64":base64.b64encode(b"test").decode(),
                                   "password":"x"})
        assert result.status_code == 403
    headers = {"Origin":_ORIGIN,"Content-Type":"application/json"}
    preflight = client.options("/v1/iron/a1/upload",headers={
        "Origin":_ORIGIN, "Access-Control-Request-Method":"POST",
    })
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == _ORIGIN
    db.db.execute("UPDATE fm_iron_a1_delegations SET expires_at='2000-01-01T00:00:00+00:00'")
    db.db.commit()
    assert client.post("/v1/iron/a1/upload",headers=headers,json={
        "delegation_token":token,"pfx_base64":base64.b64encode(b"test").decode(),
        "password":"x"}).status_code == 409
    assert vault.calls == []

def test_exact_cnpj_profile_binding_no_foreign_host_and_no_production_delegation():
    client,db,vault,_ = _fixture()
    assert _prepare(client, "22333444000180").status_code == 403
    assert client.post("/v1/iron/a1/delegations",headers=_workload_headers(host="fm-other"),
                       json={"issuer_cnpj":_CNPJ,"actor_user_id":"owner"}).status_code == 403
    db.cnpj = "22333444000180"
    assert _prepare(client).status_code == 403
    assert db.db.execute("SELECT COUNT(*) FROM fm_iron_a1_delegations").fetchone()[0] == 0
    prod,_,_,_ = _fixture(environment=FiscalEnvironment.PRODUCTION)
    assert _prepare(prod).status_code == 403
    disabled,_,_,_ = _fixture(origin=None)
    assert _prepare(disabled).status_code == 503

def test_revoked_issuer_fails_closed_after_atomic_consumption():
    client,db,vault,_ = _fixture()
    token = _prepare(client).json()["delegation_token"]
    db.cnpj = "22333444000180"
    result = client.post("/v1/iron/a1/upload",
                         headers={"Origin":_ORIGIN,"Content-Type":"application/json"},
                         json={"delegation_token":token,
                               "pfx_base64":base64.b64encode(b"synthetic").decode(),
                               "password":"x"})
    assert result.status_code == 403
    assert vault.calls == []
    assert client.post("/v1/iron/a1/upload",
                       headers={"Origin":_ORIGIN,"Content-Type":"application/json"},
                       json={"delegation_token":token,
                             "pfx_base64":base64.b64encode(b"synthetic").decode(),
                             "password":"x"}).status_code == 409

def test_store_token_is_hashed_and_one_time_with_real_sql_atomic_update():
    db=_Database()
    store=IronA1DelegationStore(db.connection)
    now=datetime.now(UTC)
    token,expires=store.issue(host_namespace="fm.iron",tenant_id="tenant-a",unit_id="unit-a",
                              environment="homologation",issuer_cnpj=_CNPJ,
                              allowed_origin=_ORIGIN,issued_by="owner",now=now)
    assert expires-now == timedelta(minutes=5)
    assert db.db.execute("SELECT token_sha256 FROM fm_iron_a1_delegations").fetchone()[0] != token
    args={"token":token,"origin":_ORIGIN,"now":now}
    assert store.consume(**args)["tenant_id"] == "tenant-a"
    assert store.consume(**args) is None
    assert store.consume(token="wrong",origin=_ORIGIN,now=now) is None
    assert trusted_iron_origin("https://app.ironfitcore.com.br.evil.example") != _ORIGIN
    assert trusted_iron_origin("http://app.ironfitcore.com.br") is None
    assert trusted_iron_origin(_ORIGIN) == _ORIGIN
