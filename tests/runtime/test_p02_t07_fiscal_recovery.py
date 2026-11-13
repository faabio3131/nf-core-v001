"""Synthetic durable HTTP recovery; no external fiscal operation/provider."""

from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.runtime.fiscal_runtime import (
    CanonicalFiscalOperationPath,
    CanonicalPortalOperationExecutor,
)
from kordena_fiscal.security.human_identity import InMemoryHumanAccountRepository, PortalRole
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor

spec = importlib.util.spec_from_file_location(
    "t07_base", Path(__file__).with_name("test_p02_t06_inutilization.py")
)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
database = base.database
BODY = base.BODY
PREPARE = "/v1/portal/fiscal-intents/prepare/inutilizeFiscalRange"
LIST = "/v1/portal/fiscal-intents?unit_id=unit-a&environment=homologation"


def harness(database, *, loss=False, handler=None):
    accounts = InMemoryHumanAccountRepository()
    identity = base.fixture.identity(accounts)
    calls = []
    enqueue = base.receipts.internal_handler(database, response_loss=loss)

    def dispatch(scope, payload, key):
        calls.append(key)
        return (handler or enqueue)(scope, payload, key)

    executor = CanonicalPortalOperationExecutor(
        unit_of_work_factory=database,
        path=CanonicalFiscalOperationPath(
            FiscalApplicationService(database), handlers={"inutilizeFiscalRange": dispatch}
        ),
    )
    application = create_app(
        human_identity=identity,
        portal_executor=DurableHumanPortalExecutor(database, operation_executor=executor),
    )
    return application, accounts, identity, calls


def login(application, name="operator"):
    http = TestClient(application, base_url="https://nfcore.test")
    assert (
        http.post(
            "/v1/auth/login",
            json={"email": name + "@example.com", "password": base.fixture.PASSWORD},
        ).status_code
        == 200
    )
    return http


def post(http, path=PREPARE, body=BODY, key="original-key"):
    return http.post(
        path,
        json=body,
        headers={CSRF_HEADER: http.cookies.get(CSRF_COOKIE) or "", "Idempotency-Key": key},
    )


def prepare(http, **kwargs):
    response = post(http, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["intent_id"]


def resume(http, intent, **kwargs):
    return post(http, path=f"/v1/portal/fiscal-intents/{intent}/resume", **kwargs)


def stored(database, intent):
    with database() as uow:
        return uow.commercial.configuration_receipt(base.fixture.scope(), intent)


def alter(database, intent, **changes):
    with database() as uow:
        old = uow.commercial.configuration_receipt(base.fixture.scope(), intent)
        assert old
        assert uow.commercial.replace_configuration_receipt(
            base.fixture.scope(), intent, old, dict(old) | changes
        )
        uow.commit()


def test_reload_after_prepare_reuses_original_key_and_has_no_payload_copy(database):
    app, _, _, calls = harness(database)
    intent = prepare(login(app))
    http = login(app)
    row = http.get(LIST).json()["rows"][0]
    assert row["intent_id"] == intent and row["state"] == "prepared"
    assert not ({"original_key", "fingerprint", "payload", "result"} & row.keys())
    assert BODY["justification"] not in str(stored(database, intent))
    assert stored(database, intent)["fingerprint"] not in str(row)
    assert resume(http, intent, key="fresh-browser-key").status_code == 200
    assert calls == ["original-key"]
    assert resume(http, intent).json()["replay"]
    assert calls == ["original-key"]


def test_lost_response_after_outbox_commit_resolves_without_dispatch(database):
    app, _, _, calls = harness(database, loss=True)
    http = login(app)
    intent = prepare(http)
    assert resume(http, intent).status_code == 503
    response = resume(login(app), intent, key="new-tab-key")
    assert response.status_code == 200 and response.json()["state"] == "recorded"
    assert response.json()["reference_id"]
    assert calls == ["original-key"]
    with database() as uow:
        assert (
            len(
                uow.outbox.list_for_scope(base.fixture.scope(), operations=frozenset({"inutilize"}))
            )
            == 1
        )


def test_unknown_outcome_never_redispatches(database):
    def fail(*args):
        raise HTTPException(503, detail={"code": "UNKNOWN_SYNTHETIC"})

    app, _, _, calls = harness(database, handler=fail)
    http = login(app)
    intent = prepare(http)
    assert resume(http, intent).status_code == 503
    assert resume(login(app), intent).json()["detail"]["code"] == "FISCAL_RECONCILIATION_REQUIRED"
    assert calls == ["original-key"]


def test_distinct_keys_tabs_share_one_receipt_and_original_key(database):
    app, _, _, calls = harness(database)
    http = login(app)
    first = prepare(http, key="tab-one")
    second = prepare(login(app), key="tab-two")
    assert first == second
    assert resume(http, second, key="tab-two").status_code == 200
    assert calls == ["tab-one"]
    assert post(http, body=dict(BODY) | {"last_number": 14}, key="tab-two").status_code == 409


@pytest.mark.parametrize("name", ["owner", "auditor", "billing", "other"])
def test_cross_account_role_tenant_and_platform_never_bypass(database, name):
    app, accounts, _, calls = harness(database)
    intent = prepare(login(app))
    account = accounts.by_id("synthetic-" + name)
    assert account
    accounts.save(replace(account, platform_admin=True))
    http = login(app, name)
    assert http.get(LIST).json()["rows"] == []
    assert resume(http, intent).status_code == 404
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"unit_id": "unit-b"},
        {"environment": "production"},
        {"host_namespace": "other"},
        {"tenant_id": "tenant-b"},
    ],
)
def test_scope_spoof_or_change_fails_closed(database, change):
    app, _, _, calls = harness(database)
    http = login(app)
    intent = prepare(http)
    assert resume(http, intent, body=dict(BODY) | change).status_code in {400, 403, 404}
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        {"session_epoch": 42},
        {"policy": "missing"},
        {"host_namespace": "other"},
    ],
)
def test_expiry_epoch_missing_policy_and_host_do_not_release_original(database, change):
    app, _, _, calls = harness(database)
    http = login(app)
    intent = prepare(http)
    alter(database, intent, **change)
    assert resume(http, intent).status_code in {403, 409}
    assert post(http, key="new-key").status_code in {403, 409}
    assert stored(database, intent)["state"] == "prepared"
    assert calls == []


def test_revoked_session_epoch_permission_and_csrf(database):
    app, accounts, identity, calls = harness(database)
    http = login(app)
    intent = prepare(http)
    assert http.post(f"/v1/portal/fiscal-intents/{intent}/resume", json=BODY).status_code == 403
    assert post(http, key="").status_code == 400
    assert resume(http, "missing").status_code == 404
    account = accounts.by_id("synthetic-operator")
    assert account
    accounts.save(replace(account, role=PortalRole.AUDITOR))
    assert resume(http, intent).status_code == 403
    with database() as uow:
        assert any(
            e.action.value == "fiscal_intent.blocked"
            for e in uow.control_plane.list_audit("tenant-a")
        )
    accounts.save(account)
    identity.revoke_all_sessions("synthetic-operator")
    assert resume(http, intent).status_code == 401
    fresh = login(app)
    assert resume(fresh, intent).status_code == 403
    account = accounts.by_id("synthetic-operator")
    assert account
    accounts.save(replace(account, role=PortalRole.AUDITOR))
    assert resume(login(app), intent).status_code == 403
    assert calls == []


def test_audit_failure_rolls_back_prepare_and_claim_before_effect(database, monkeypatch):
    app, _, _, calls = harness(database)
    http = login(app)
    with database() as uow:
        store_type = type(uow.control_plane)
    original = store_type.append_audit

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(store_type, "append_audit", fail)
    with pytest.raises(RuntimeError):
        prepare(http)
    with database() as uow:
        assert (
            uow.commercial.list_configuration_receipts(base.fixture.scope(), "fiscal-intent:") == ()
        )
    monkeypatch.setattr(store_type, "append_audit", original)
    intent = prepare(http)
    monkeypatch.setattr(store_type, "append_audit", fail)
    with pytest.raises(RuntimeError):
        resume(http, intent)
    assert stored(database, intent)["state"] == "prepared" and calls == []


def test_concurrent_claim_before_effect_invokes_handler_once(database):
    started, release = Event(), Event()
    enqueue = base.receipts.internal_handler(database)

    def waiting(scope, payload, key):
        started.set()
        assert release.wait(10)
        return enqueue(scope, payload, key)

    app, _, _, calls = harness(database, handler=waiting)
    one, two = login(app), login(app)
    intent = prepare(one)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(resume, one, intent)
        assert started.wait(10)
        try:
            assert resume(two, intent).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 200
    assert calls == ["original-key"]


def test_late_first_response_after_other_tab_resolves_commit(database):
    committed, release = Event(), Event()
    enqueue = base.receipts.internal_handler(database)

    def waiting(scope, payload, key):
        result = enqueue(scope, payload, key)
        committed.set()
        assert release.wait(10)
        return result

    app, _, _, calls = harness(database, handler=waiting)
    one, two = login(app), login(app)
    intent = prepare(one)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(resume, one, intent)
        assert committed.wait(10)
        try:
            assert resume(two, intent).json()["state"] == "recorded"
        finally:
            release.set()
        assert future.result().status_code == 200
    assert calls == ["original-key"]


def test_persistence_unavailable_prevents_dispatch(database, monkeypatch):
    from kordena_fiscal.persistence.ports import PersistenceStateError

    app, _, _, calls = harness(database)
    http = login(app)
    intent = prepare(http)

    def unavailable(*args, **kwargs):
        raise PersistenceStateError("synthetic database unavailable")

    monkeypatch.setattr(type(database), "__call__", unavailable)
    with pytest.raises(PersistenceStateError):
        resume(http, intent)
    assert calls == []



def test_rejection_reason_is_preserved_only_as_scoped_safe_status(database):
    def rejected(scope, payload, key):
        return {
            "document_id": "synthetic-doc", "status": "rejected",
            "rejection_reason": "X-TEST-001",
            "rejection_message": "Teste de rejeicao; corrigir fiscal",
            "recovery_required": False, "provider_secret": "NEVER-PROJECT",
        }

    app, _, _, calls = harness(database, handler=rejected)
    http = login(app)
    intent = prepare(http)
    response = resume(http, intent)
    assert response.status_code == 200, response.text
    projected = response.json()["operation_result"]
    assert projected["status"] == "rejected"
    assert projected["rejection_reason"] == "X-TEST-001"
    assert projected["rejection_message"] == "Teste de rejeicao; corrigir fiscal"
    assert "provider_secret" not in str(response.json())
    replay = resume(http, intent)
    assert replay.json()["operation_result"] == projected
    assert calls == ["original-key"]
