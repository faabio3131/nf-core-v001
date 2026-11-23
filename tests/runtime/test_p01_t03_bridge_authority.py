from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalEnvironment,
    FiscalUnitId,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.fiscal_runtime import (
    CanonicalBridgeRequestExecutor,
    CanonicalBridgeSecurityBoundary,
    CanonicalFiscalOperationPath,
)
from kordena_fiscal.security.s2s import (
    AuthorizedFiscalRequest,
    CallerIdentity,
    FiscalCapability,
    HostScopeGrant,
    InMemorySecurityAuditSink,
    S2SAuthorizer,
    WorkloadAuthenticator,
    WorkloadCredentialRecord,
)
from kordena_fiscal.web import create_app
from kordena_fiscal.web.app import BridgeHttpContext, HttpContractError

WORKLOAD_SECRET = "s" * 40
VALID_FROM = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRES_AT = datetime(2027, 1, 1, tzinfo=UTC)


class _RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[ExecutionScope, Mapping[str, Any], str | None]] = []

    def __call__(
        self,
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        self.calls.append((scope, payload, idempotency_key))
        return {
            "tenant_id": scope.tenant_id,
            "unit_id": scope.unit_id,
            "idempotency_key": idempotency_key,
        }


def _database(tmp_path: Path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "bridge-authority.sqlite3")
    database.initialize()
    with database() as uow:
        uow.bindings.add(
            FiscalAccountBinding(
                binding_id="binding-a",
                host_scope=HostScope(
                    namespace=HostNamespace("fm-nfcore"),
                    tenant_id="tenant-a",
                    unit_id="unit-a",
                ),
                fiscal_account_id=FiscalAccountId("fiscal-account-a"),
                fiscal_unit_id=FiscalUnitId("fiscal-unit-a"),
            )
        )
        uow.commit()
    return database


def _client(
    database: SqliteFiscalDatabase,
    handler: _RecordingHandler,
    *,
    grants: tuple[HostScopeGrant, ...] | None = None,
) -> tuple[TestClient, InMemorySecurityAuditSink]:
    path = CanonicalFiscalOperationPath(
        FiscalApplicationService(database),
        handlers={
            "issueFiscalDocument": handler,
            "queryFiscalDocument": handler,
        },
    )
    caller = CallerIdentity(
        caller_id="nfcore-host",
        host_namespace=HostNamespace("fm-nfcore"),
        capabilities=frozenset({FiscalCapability.ISSUE, FiscalCapability.QUERY}),
        scope_grants=grants
        or (HostScopeGrant(tenant_id="tenant-a", unit_id="unit-a"),),
    )
    credential = WorkloadCredentialRecord.from_secret(
        credential_id="credential-a",
        caller=caller,
        secret=WORKLOAD_SECRET,
        valid_from=VALID_FROM,
        expires_at=EXPIRES_AT,
    )
    audit = InMemorySecurityAuditSink()
    security = CanonicalBridgeSecurityBoundary(
        authenticator=WorkloadAuthenticator((credential,)),
        authorizer=S2SAuthorizer(bindings=path, audit_sink=audit),
    )
    return (
        TestClient(
            create_app(
                security=security,
                executor=CanonicalBridgeRequestExecutor(path),
            ),
            base_url="https://nfcore.test",
        ),
        audit,
    )


def _headers(
    *,
    tenant_id: str = "tenant-a",
    unit_id: str = "unit-a",
    host_namespace: str = "fm-nfcore",
    idempotency_key: str | None = None,
) -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {WORKLOAD_SECRET}",
        "X-FM-Workload-Credential-Id": "credential-a",
        "X-FM-Host-Namespace": host_namespace,
        "X-FM-Tenant-Id": tenant_id,
        "X-FM-Unit-Id": unit_id,
        "X-FM-Environment": "homologation",
        "X-Correlation-Id": "corr-authority-cert",
    }
    if idempotency_key is not None:
        result["Idempotency-Key"] = idempotency_key
    return result


def test_authorized_bridge_maps_to_internal_fiscal_scope(tmp_path: Path) -> None:
    handler = _RecordingHandler()
    client, audit = _client(_database(tmp_path), handler)

    response = client.post(
        "/v1/queries",
        headers=_headers(),
        json={"document_id": "DOC-1"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "fiscal-account-a"
    assert response.json()["unit_id"] == "fiscal-unit-a"
    assert len(handler.calls) == 1
    assert audit.records[-1].reason_code == "authorized"


def test_bridge_rejects_tenant_unit_and_host_spoofing(tmp_path: Path) -> None:
    handler = _RecordingHandler()
    client, audit = _client(_database(tmp_path), handler)

    attempts = (
        _headers(tenant_id="tenant-b"),
        _headers(unit_id="unit-b"),
        _headers(host_namespace="fm-other"),
    )
    for request_headers in attempts:
        response = client.post(
            "/v1/queries",
            headers=request_headers,
            json={"document_id": "DOC-1"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "WORKLOAD_AUTHORIZATION_FAILED"

    assert handler.calls == []
    assert all(record.outcome.value == "denied" for record in audit.records)


def test_bridge_missing_exact_binding_is_explicitly_fail_closed(tmp_path: Path) -> None:
    handler = _RecordingHandler()
    client, audit = _client(
        _database(tmp_path),
        handler,
        grants=(HostScopeGrant(),),
    )

    response = client.post(
        "/v1/queries",
        headers=_headers(unit_id="unit-without-binding"),
        json={"document_id": "DOC-1"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FISCAL_BINDING_REQUIRED"
    assert handler.calls == []
    assert audit.records[-1].reason_code == "binding_not_found"


def test_bridge_mutation_requires_and_preserves_idempotency_key(
    tmp_path: Path,
) -> None:
    handler = _RecordingHandler()
    client, _audit = _client(_database(tmp_path), handler)

    missing = client.post(
        "/v1/issuances",
        headers=_headers(),
        json={"document_kind": "nfe"},
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "MISSING_IDEMPOTENCY_KEY"

    accepted = client.post(
        "/v1/issuances",
        headers=_headers(idempotency_key="idem-bridge-001"),
        json={"document_kind": "nfe"},
    )
    assert accepted.status_code == 202
    assert accepted.json()["idempotency_key"] == "idem-bridge-001"
    assert handler.calls[-1][2] == "idem-bridge-001"


def test_iron_a1_withdrawal_requires_distinct_capability_and_exact_scope(
    tmp_path: Path,
) -> None:
    """Exercise the real boundary, not the A1 router's mocked authorizer."""
    database = _database(tmp_path)
    with database() as uow:
        uow.bindings.add(
            FiscalAccountBinding(
                binding_id="iron-binding-a",
                host_scope=HostScope(
                    namespace=HostNamespace("fm.iron"),
                    tenant_id="gym-a",
                    unit_id="gym-unit-a",
                ),
                fiscal_account_id=FiscalAccountId("iron-fiscal-account-a"),
                fiscal_unit_id=FiscalUnitId("iron-fiscal-unit-a"),
            )
        )
        uow.commit()
    path = CanonicalFiscalOperationPath(FiscalApplicationService(database))
    audit = InMemorySecurityAuditSink()
    reader = CallerIdentity(
        caller_id="iron-reader",
        host_namespace=HostNamespace("fm.iron"),
        capabilities=frozenset({
            FiscalCapability.CERTIFICATE_DELEGATE,
            FiscalCapability.CERTIFICATE_STATUS_READ,
        }),
        scope_grants=(HostScopeGrant(tenant_id="gym-a", unit_id="gym-unit-a"),),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
    )
    withdrawer = replace(
        reader, caller_id="iron-withdrawer",
        capabilities=frozenset({FiscalCapability.CERTIFICATE_WITHDRAW}),
    )
    credentials = tuple(
        WorkloadCredentialRecord.from_secret(
            credential_id=identity.caller_id, caller=identity,
            secret=WORKLOAD_SECRET, valid_from=VALID_FROM, expires_at=EXPIRES_AT,
        )
        for identity in (reader, withdrawer)
    )
    boundary = CanonicalBridgeSecurityBoundary(
        authenticator=WorkloadAuthenticator(credentials),
        authorizer=S2SAuthorizer(bindings=path, audit_sink=audit),
    )
    context = BridgeHttpContext(
        host_namespace="fm.iron", tenant_id="gym-a", unit_id="gym-unit-a",
        environment="homologation", correlation_id="iron-a1-withdraw-test",
        causation_id=None, credential_id="iron-reader",
        presented_secret=WORKLOAD_SECRET, idempotency_key=None,
    )
    read = boundary.authorize(operation_id="readIronA1Status", context=context)
    assert isinstance(read.authority, AuthorizedFiscalRequest)
    assert read.authority.capability is FiscalCapability.CERTIFICATE_STATUS_READ
    with pytest.raises(HttpContractError) as denied:
        boundary.authorize(operation_id="withdrawIronA1", context=context)
    assert denied.value.status_code == 403
    assert audit.records[-1].reason_code == "capability_denied"

    authorized_context = replace(context, credential_id="iron-withdrawer")
    allowed = boundary.authorize(
        operation_id="withdrawIronA1", context=authorized_context,
    )
    assert isinstance(allowed.authority, AuthorizedFiscalRequest)
    assert allowed.authority.capability is FiscalCapability.CERTIFICATE_WITHDRAW
    assert allowed.authority.scope.host_namespace == "fm.iron"
    assert allowed.authority.scope.tenant_id == "iron-fiscal-account-a"
    assert allowed.authority.scope.unit_id == "iron-fiscal-unit-a"
    assert audit.records[-1].reason_code == "authorized"

    for forged in (
        replace(authorized_context, tenant_id="gym-b"),
        replace(authorized_context, unit_id="gym-unit-b"),
        replace(authorized_context, host_namespace="fm.kordena"),
        replace(authorized_context, environment="production"),
    ):
        with pytest.raises(HttpContractError) as rejected:
            boundary.authorize(operation_id="withdrawIronA1", context=forged)
        assert rejected.value.status_code == 403
        assert audit.records[-1].outcome.value == "denied"
