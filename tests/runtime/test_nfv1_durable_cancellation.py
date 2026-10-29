"""Cancellation claim, archive and lifecycle use the same durable authority."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway import FiscalGatewayClient
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.operations import (
    CancellationRequest,
    FakeFiscalOperationsGateway,
    FiscalEventStatus,
    FiscalOperationsClient,
)
from kordena_fiscal.runtime.fiscal_runtime import (
    CanonicalFiscalOperationPath,
    CanonicalPortalOperationExecutor,
)
from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers
from kordena_fiscal.security.human_identity import InMemoryHumanAccountRepository
from kordena_fiscal.web import create_app
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


base = module("test_nfv1_durable_issuance")
recovery = module("test_p02_t07_fiscal_recovery")
database = recovery.database
RETENTION = RetentionPolicyMetadata("synthetic-cancellation", 1)


def authorized(database, tmp_path):
    _, app, prepared = base.prepared(tmp_path, db=database, archive=True)
    app.authorize_prepared_document(
        document_id="doc-test", request=prepared, gateway=FiscalGatewayClient(base.Provider()),
        occurred_at=base.NOW,
    )
    request = CancellationRequest.build(
        scope=prepared.scope, access_key=prepared.access_key,
        authorization_protocol="protocol-test", justification="Justificativa sintetica valida",
    )
    return app, request


@pytest.mark.parametrize("status,expected", [
    (FiscalEventStatus.ACCEPTED, FiscalDocumentState.CANCELLED),
    (FiscalEventStatus.REJECTED, FiscalDocumentState.AUTHORIZED),
    (FiscalEventStatus.PENDING, FiscalDocumentState.CANCEL_REQUESTED),
])
def test_claim_precedes_provider_and_result_commits_with_lifecycle(
    database, tmp_path, status, expected
):
    app, request = authorized(database, tmp_path)

    class ObservedGateway(FakeFiscalOperationsGateway):
        def cancel(self, request):
            with database() as uow:
                assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.CANCEL_REQUESTED
            return super().cancel(request)

    gateway = ObservedGateway(event_status=status)
    outcome = app.cancel_prepared_document(
        document_id="doc-test", request=request, client=FiscalOperationsClient(gateway),
        archive_retention=RETENTION, occurred_at=base.NOW,
    )
    with database() as uow:
        assert uow.lifecycle.get("doc-test").state is expected
        assert uow.archive.get(outcome.archive_reference).kind is FiscalArchiveKind.FISCAL_EVENT
    assert len(gateway.cancel_calls) == 1
    assert outcome.lifecycle.state is expected


def test_timeout_blocks_new_dispatch_after_restart(database, tmp_path):
    app, request = authorized(database, tmp_path)
    calls = []

    class TimeoutGateway(FakeFiscalOperationsGateway):
        def cancel(self, request):
            calls.append(request)
            raise TimeoutError("synthetic timeout")

    client = FiscalOperationsClient(TimeoutGateway())
    with pytest.raises(TimeoutError):
        app.cancel_prepared_document(document_id="doc-test", request=request, client=client,
            archive_retention=RETENTION, occurred_at=base.NOW)
    restarted = type(app)(database)
    with pytest.raises(FiscalValidationError):
        restarted.cancel_prepared_document(document_id="doc-test", request=request, client=client,
            archive_retention=RETENTION, occurred_at=base.NOW)
    assert len(calls) == 1
    with database() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.CANCEL_REQUESTED


@pytest.mark.parametrize("parameter", ["request", "client", "archive_retention"])
def test_invalid_dependency_cannot_claim_cancellation(database, tmp_path, parameter):
    app, request = authorized(database, tmp_path)
    kwargs = {"document_id": "doc-test", "request": request,
              "client": FiscalOperationsClient(FakeFiscalOperationsGateway()),
              "archive_retention": RETENTION, "occurred_at": base.NOW}
    kwargs[parameter] = object()
    with pytest.raises(FiscalValidationError):
        app.cancel_prepared_document(**kwargs)
    with database() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.AUTHORIZED


def test_concurrent_cancellation_claim_dispatches_once(database, tmp_path):
    app, request = authorized(database, tmp_path)
    started, release = Event(), Event()

    class WaitingGateway(FakeFiscalOperationsGateway):
        def cancel(self, request):
            started.set()
            assert release.wait(10)
            return super().cancel(request)

    gateway = WaitingGateway()
    kwargs = {"document_id": "doc-test", "request": request,
              "client": FiscalOperationsClient(gateway), "archive_retention": RETENTION,
              "occurred_at": base.NOW}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(app.cancel_prepared_document, **kwargs)
        assert started.wait(10)
        try:
            with pytest.raises(FiscalValidationError):
                app.cancel_prepared_document(**kwargs)
        finally:
            release.set()
        assert first.result().lifecycle.state is FiscalDocumentState.CANCELLED
    assert len(gateway.cancel_calls) == 1


def test_archive_failure_rolls_back_terminal_cancellation(database, tmp_path, monkeypatch):
    app, request = authorized(database, tmp_path)
    with database() as uow:
        archive_type = type(uow.archive)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic archive failure")

    monkeypatch.setattr(archive_type, "append", fail)
    with pytest.raises(RuntimeError):
        app.cancel_prepared_document(document_id="doc-test", request=request,
            client=FiscalOperationsClient(FakeFiscalOperationsGateway()),
            archive_retention=RETENTION, occurred_at=base.NOW)
    with database() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.CANCEL_REQUESTED


def test_runtime_preflight_rejects_wrong_document_scope_and_protocol(database, tmp_path):
    app, request = authorized(database, tmp_path)
    gateway = FakeFiscalOperationsGateway()
    handler = build_provider_operation_handlers(
        FiscalOperationsClient(gateway), application=app, archive_retention=RETENTION,
    )["cancelFiscalDocument"]
    payload = {"document_id": "doc-test", "access_key": request.access_key.value,
               "authorization_protocol": "protocol-test", "justification": request.justification}
    for scope, fields in [
        (request.scope, {"document_id": "missing"}),
        (request.scope, {"authorization_protocol": "wrong-protocol"}),
        (replace(request.scope, unit_id="other-unit"), {}),
    ]:
        with pytest.raises(FiscalValidationError):
            handler.preflight(scope, {**payload, **fields}, "http-key")
    assert not gateway.cancel_calls
    handler.preflight(request.scope, payload, "http-key")
    result = handler(request.scope, payload, "http-key")
    assert result["status"] == "accepted" and result["entry_id"]
    with database() as uow:
        assert uow.lifecycle.get("doc-test").state is FiscalDocumentState.CANCELLED


def test_authenticated_http_cancellation_updates_document_and_replays_receipt(database):
    spec = importlib.util.spec_from_file_location(
        "cancellation_prepared_fixture",
        Path(__file__).parents[1] / "support/prepared_recovery_fixture.py",
    )
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    application = FiscalApplicationService(database)
    scope = recovery.base.fixture.scope()
    reconcile = fixture.seed_and_handler(application, scope, recovery.base.fixture.NOW)
    reconcile(scope, {"document_id": "PREPARED-RECOVERY-a"}, "seed-authorization")
    prepared = application.load_prepared_authorization(scope, "PREPARED-RECOVERY-a")
    gateway = FakeFiscalOperationsGateway()
    handlers = build_provider_operation_handlers(FiscalOperationsClient(gateway),
        application=application, archive_retention=RETENTION)
    app = create_app(
        human_identity=recovery.base.fixture.identity(InMemoryHumanAccountRepository()),
        portal_executor=DurableHumanPortalExecutor(database, operation_executor=
            CanonicalPortalOperationExecutor(unit_of_work_factory=database,
                path=CanonicalFiscalOperationPath(application, handlers=handlers))),
    )
    http = recovery.login(app)
    body = {"document_id": "PREPARED-RECOVERY-a", "access_key": prepared.access_key.value,
            "authorization_protocol": "SYNTHETIC-AUTH-PROTOCOL",
            "justification": "Justificativa sintetica de cancelamento",
            "unit_id": "unit-a", "environment": "homologation"}
    intent = recovery.prepare(http, path="/v1/portal/fiscal-intents/prepare/cancelFiscalDocument",
                              body=body)
    assert not gateway.cancel_calls
    response = recovery.resume(http, intent, body=body)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "recorded"
    assert recovery.resume(recovery.login(app), intent, body=body).json()["replay"]
    assert len(gateway.cancel_calls) == 1
    with database() as uow:
        assert uow.lifecycle.get("PREPARED-RECOVERY-a").state is FiscalDocumentState.CANCELLED
        archived = uow.archive.get(response.json()["reference_id"])
        assert archived.kind is FiscalArchiveKind.FISCAL_EVENT
