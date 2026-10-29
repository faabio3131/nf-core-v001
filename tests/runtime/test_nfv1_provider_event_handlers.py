"""BLD-02: provider-neutral event handlers stay opt-in, scoped and fail-closed."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    Cnpj,
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.operations import (
    FakeFiscalOperationsGateway,
    FiscalOperationsClient,
    FiscalOperationsContractError,
    MutatingFiscalOperationsGateway,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.fiscal_runtime import (
    CanonicalFiscalOperationPath,
    CanonicalPortalOperationExecutor,
)
from kordena_fiscal.runtime.provider_event_handlers import (
    build_provider_cancel_handler,
    build_provider_inutilization_handler,
)
from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers
from kordena_fiscal.security.human_identity import InMemoryHumanAccountRepository
from kordena_fiscal.web import create_app
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor
from kordena_fiscal.xml import AccessKeyInput, build_access_key


def scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="event-test",
    )


def access_key() -> str:
    return build_access_key(
        AccessKeyInput(
            state_ibge_code="35",
            issued_at=datetime(2026, 9, 11, tzinfo=UTC),
            issuer_cnpj=Cnpj("12.345.678/0001-95"),
            model=ElectronicInvoiceModel.NFCE,
            series=3,
            invoice_number=10,
            emission_type=1,
            numeric_code=12345678,
        )
    ).value


def test_cancel_delegates_verified_identity_to_supplied_client() -> None:
    gateway = FakeFiscalOperationsGateway()
    handler = build_provider_cancel_handler(FiscalOperationsClient(gateway))
    result = handler(scope(), {
        "access_key": access_key(),
        "authorization_protocol": "AUTH-123",
        "justification": "Cancelamento de teste controlado",
    }, "retry-key")
    assert result["status"] == "accepted"
    assert result["request_id"] == gateway.cancel_calls[0].request_id
    assert result["event_protocol_reference"] == "SYNTHETIC-CANCEL-PROTOCOL"
    assert gateway.cancel_calls[0].scope == scope()


def test_inutilization_delegates_validated_range_to_supplied_client() -> None:
    gateway = FakeFiscalOperationsGateway()
    handler = build_provider_inutilization_handler(FiscalOperationsClient(gateway))
    payload = {"model": 55, "series": 1, "first_number": 10,
               "last_number": 12, "justification": "Faixa de teste controlada"}
    result = handler(scope(), payload, "retry-key")
    assert result["status"] == "accepted"
    assert result["request_id"] == gateway.inutilization_calls[0].request_id
    assert gateway.inutilization_calls[0].scope == scope()
    assert result["first_number"] == 10


def test_invalid_event_requests_do_not_call_gateway() -> None:
    gateway = FakeFiscalOperationsGateway()
    cancel = build_provider_cancel_handler(FiscalOperationsClient(gateway))
    inutilize = build_provider_inutilization_handler(FiscalOperationsClient(gateway))
    with pytest.raises(FiscalValidationError):
        cancel(scope(), {"access_key": access_key()}, None)
    with pytest.raises(FiscalValidationError):
        inutilize(scope(), {"model": True, "series": 1, "first_number": 1,
                            "last_number": 2, "justification": "Justificativa válida"}, None)
    assert not gateway.cancel_calls
    assert not gateway.inutilization_calls


def test_provider_identity_mismatch_is_rejected_before_result_exposure() -> None:
    cancel = build_provider_cancel_handler(
        FiscalOperationsClient(MutatingFiscalOperationsGateway(mutate="cancel_scope"))
    )
    with pytest.raises(FiscalOperationsContractError):
        cancel(scope(), {
            "access_key": access_key(),
            "authorization_protocol": "AUTH-123",
            "justification": "Cancelamento de teste controlado",
        }, None)


def test_inutilization_provider_range_mismatch_is_rejected() -> None:
    inutilize = build_provider_inutilization_handler(
        FiscalOperationsClient(MutatingFiscalOperationsGateway(mutate="inutilization_range"))
    )
    with pytest.raises(FiscalOperationsContractError):
        inutilize(scope(), {
            "model": 55, "series": 1, "first_number": 10, "last_number": 12,
            "justification": "Faixa de teste controlada",
        }, None)


@pytest.mark.parametrize("operation,bad_fields", [
    ("cancelFiscalDocument", {"access_key": "invalid"}),
    ("cancelFiscalDocument", {"authorization_protocol": ""}),
    ("cancelFiscalDocument", {"justification": "short"}),
    ("inutilizeFiscalRange", {"model": 99}),
    ("inutilizeFiscalRange", {"first_number": True}),
    ("inutilizeFiscalRange", {"last_number": 9}),
])
def test_invalid_event_is_rejected_before_http_intent_and_can_be_corrected(
    tmp_path, operation, bad_fields
):
    spec = importlib.util.spec_from_file_location(
        "event_fixture", Path(__file__).parents[1] / "support/p02_fiscal_fixture.py"
    )
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    database = SqliteFiscalDatabase(tmp_path / "events.sqlite")
    database.initialize()
    fixture.seed(database)
    gateway = FakeFiscalOperationsGateway()
    application = FiscalApplicationService(database)
    executor = CanonicalPortalOperationExecutor(
        unit_of_work_factory=database,
        path=CanonicalFiscalOperationPath(application, handlers=build_provider_operation_handlers(
            FiscalOperationsClient(gateway)
        )),
    )
    app = create_app(
        human_identity=fixture.identity(InMemoryHumanAccountRepository()),
        portal_executor=DurableHumanPortalExecutor(database, operation_executor=executor),
    )
    fields = (
        {"access_key": access_key(), "authorization_protocol": "AUTH-SYNTHETIC",
         "justification": "Cancelamento de teste controlado"}
        if operation == "cancelFiscalDocument" else
        {"model": 55, "series": 1, "first_number": 10, "last_number": 12,
         "justification": "Faixa de teste controlada"}
    )
    body = {**fields, "unit_id": "unit-a", "environment": "homologation"}
    with TestClient(app, base_url="https://nfcore.test") as http:
        assert http.post("/v1/auth/login", json={
            "email": "operator@example.com", "password": fixture.PASSWORD
        }).status_code == 200
        headers = {"X-CSRF-Token": http.cookies.get("nfcore_csrf"),
                   "Idempotency-Key": "event-preflight"}
        path = f"/v1/portal/fiscal-intents/prepare/{operation}"
        rejected = http.post(path, json={**body, **bad_fields}, headers=headers)
        assert rejected.status_code == 400, rejected.text
        assert http.get(
            "/v1/portal/fiscal-intents?unit_id=unit-a&environment=homologation"
        ).json()["rows"] == []
        corrected = http.post(path, json=body, headers=headers)
        assert corrected.status_code == 200, corrected.text
        assert not gateway.cancel_calls and not gateway.inutilization_calls
        intent = corrected.json()["intent_id"]
        path = f"/v1/portal/fiscal-intents/{intent}/resume"
        assert http.post(path, json=body, headers=headers).json()["state"] == "recorded"
        assert http.post(path, json=body, headers=headers).json()["replay"]
        assert len(gateway.cancel_calls) + len(gateway.inutilization_calls) == 1
