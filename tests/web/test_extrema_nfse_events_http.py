"""Authenticated Web ingress regression for Extrema cancellation and substitution.

The deliberately inert recorder verifies session authority, CSRF, permissions,
scoped payloads, idempotency and fail-closed delegation. It is NOT a fiscal
provider and cannot establish municipal approval. The real stateful municipal
adapter is exercised separately by the gateway/application E2E suites.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    PortalRole,
)
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

# Pytest executes these files from repository root, and tests/web is not a
# package on sys.path. Reuse the existing authenticated HTTP fixture explicitly.
_fixture_path = Path(__file__).with_name("test_extrema_nfse_preparation_http.py")
_fixture_spec = importlib.util.spec_from_file_location(
    "_nfcore_extrema_web_http_fixture", _fixture_path,
)
assert _fixture_spec is not None and _fixture_spec.loader is not None
_fixture = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
_client = _fixture._client
_database = _fixture._database


@dataclass
class _InertCanonicalExecutor:
    configured_operations: tuple[str, ...] = (
        "cancelExtremaNfse", "substituteExtremaNfse",
    )
    calls: list[tuple[str, str, str, Mapping[str, Any], str]] = field(
        default_factory=list,
    )

    def execute(
        self, *, operation_id: str, authority: AuthenticatedHuman,
        payload: Mapping[str, Any], idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        if idempotency_key is None:
            raise AssertionError("HTTP idempotency gate bypassed")
        self.calls.append((
            operation_id,
            authority.tenant_id,
            authority.account.account_id,
            dict(payload),
            idempotency_key,
        ))
        # Inert response: never invent municipal confirmation or fiscal state.
        return {"delegation_verified": True}


def _post(
    client: TestClient, operation: str, payload: dict[str, Any], *,
    key: str | None = "extrema-review-event-123",
    csrf: bool = True,
) -> Any:
    headers: dict[str, str] = {}
    if key is not None:
        headers["Idempotency-Key"] = key
    if csrf:
        token = client.cookies.get(CSRF_COOKIE)
        assert token
        headers[CSRF_HEADER] = token
    return client.post(
        f"/v1/portal/operations/{operation}", json=payload, headers=headers,
    )


_CANCEL = {
    "unit_id": "unit-extrema",
    "environment": "homologation",
    "document_id": "extrema-original-1",
    "cancellation_code": "1",
    "human_approval": True,
}
_SUBSTITUTE = {
    "unit_id": "unit-extrema",
    "environment": "homologation",
    "original_id": "extrema-original-1",
    "replacement_id": "extrema-replacement-2",
    "cancellation_code": "1",
    "human_approval": True,
}


@pytest.mark.parametrize("operation,payload", [
    ("cancelExtremaNfse", _CANCEL),
    ("substituteExtremaNfse", _SUBSTITUTE),
])
def test_extrema_event_routes_are_session_scoped_and_delegate_once(
    tmp_path: Path, operation: str, payload: dict[str, Any],
) -> None:
    executor = _InertCanonicalExecutor()
    web = _client(
        _database(tmp_path / (operation + ".sqlite")),
        role=PortalRole.OWNER, operation_executor=executor,
    )
    result = _post(web, operation, payload)
    assert result.status_code == 200, result.text
    assert result.json() == {"delegation_verified": True}
    assert executor.calls == [
        (
            operation, "tenant-extrema", "webiss-user-owner",
            payload, "extrema-review-event-123",
        )
    ]


@pytest.mark.parametrize("operation,payload", [
    ("cancelExtremaNfse", _CANCEL),
    ("substituteExtremaNfse", _SUBSTITUTE),
])
def test_extrema_event_routes_require_csrf_key_and_unit_authority(
    tmp_path: Path, operation: str, payload: dict[str, Any],
) -> None:
    executor = _InertCanonicalExecutor()
    web = _client(
        _database(tmp_path / (operation + ".sqlite")),
        role=PortalRole.OWNER, operation_executor=executor,
    )
    assert _post(web, operation, payload, csrf=False).status_code == 403
    assert _post(web, operation, payload, key=None).status_code == 400
    assert _post(
        web, operation, payload | {"unit_id": "another-unit"},
    ).status_code == 403
    assert _post(
        web, operation, payload | {"tenant_id": "another-tenant"},
    ).status_code == 400
    assert not executor.calls


@pytest.mark.parametrize("operation,payload", [
    ("cancelExtremaNfse", _CANCEL),
    ("substituteExtremaNfse", _SUBSTITUTE),
])
def test_extrema_event_routes_have_no_fake_fiscal_success_without_executor(
    tmp_path: Path, operation: str, payload: dict[str, Any],
) -> None:
    web = _client(_database(tmp_path / (operation + ".sqlite")), role=PortalRole.OWNER)
    result = _post(web, operation, payload)
    assert result.status_code == 503, result.text
    assert result.json()["detail"]["code"] == "FISCAL_RUNTIME_NOT_READY"


def test_extrema_substitution_rejects_auditor_without_issue_or_cancel_authority(
    tmp_path: Path,
) -> None:
    executor = _InertCanonicalExecutor()
    web = _client(
        _database(tmp_path / "auditor.sqlite"),
        role=PortalRole.AUDITOR, operation_executor=executor,
    )
    assert _post(web, "substituteExtremaNfse", _SUBSTITUTE).status_code == 403
    assert not executor.calls


@pytest.mark.parametrize("operation,payload", [
    ("cancelExtremaNfse", _CANCEL),
    ("substituteExtremaNfse", _SUBSTITUTE),
])
def test_browser_cannot_inject_session_or_tenant_authority(
    tmp_path: Path, operation: str, payload: dict[str, Any],
) -> None:
    executor = _InertCanonicalExecutor()
    web = _client(
        _database(tmp_path / (operation + ".sqlite")),
        role=PortalRole.OWNER, operation_executor=executor,
    )
    for key, value in (
        ("tenant_id", "spoofed"),
        ("host_namespace", "spoofed"),
        ("account_id", "spoofed"),
        ("session_epoch", 999),
    ):
        result = _post(web, operation, payload | {key: value})
        assert result.status_code in {400, 403}, (key, result.text)
    assert not executor.calls
