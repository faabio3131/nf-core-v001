"""Invalid prepared references must fail before an uncertain Portal intent exists."""

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.persistence import SqliteFiscalDatabase


@pytest.fixture
def http_system(tmp_path):
    path = Path(__file__).parents[1] / "e2e" / "fiscal_http_server.py"
    spec = importlib.util.spec_from_file_location("preflight_http_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = SqliteFiscalDatabase(tmp_path / "preflight.sqlite")
    database.initialize()
    with TestClient(
        module.build_app(database), base_url="https://nfcore.test", raise_server_exceptions=False
    ) as http:
        yield http, database, module.fixture.PASSWORD


def login(http, password, account="operator"):
    assert (
        http.post(
            "/v1/auth/login", json={"email": account + "@example.com", "password": password}
        ).status_code
        == 200
    )
    return {"X-CSRF-Token": http.cookies.get("nfcore_csrf"), "Idempotency-Key": "preflight-test"}


@pytest.mark.parametrize("reference", ["missing-prepared", "DOC-b", "DOC-other"])
def test_invalid_or_cross_scope_reference_has_no_execution_receipt(http_system, reference):
    http, database, password = http_system
    headers = login(http, password)
    response = http.post(
        "/v1/portal/fiscal-intents/prepare/reconcileFiscalOperation",
        headers=headers,
        json={"document_id": reference, "unit_id": "unit-a", "environment": "homologation"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_PREPARED_DOCUMENT"
    assert reference not in response.text
    receipts = http.get("/v1/portal/fiscal-intents?unit_id=unit-a&environment=homologation")
    assert receipts.status_code == 200
    assert receipts.json()["rows"] == []
    with database() as uow:
        assert uow.lifecycle.get("PREPARED-RECOVERY-a").state is FiscalDocumentState.TRANSMITTING

    # A corrected reference can proceed without a fabricated recovery of the bad input.
    payload = {
        "document_id": "PREPARED-RECOVERY-a",
        "unit_id": "unit-a",
        "environment": "homologation",
    }
    corrected = http.post(
        "/v1/portal/fiscal-intents/prepare/reconcileFiscalOperation", headers=headers, json=payload
    )
    assert corrected.status_code == 200
    intent = corrected.json()["intent_id"]
    with database() as uow:
        # Preflight itself never invokes the provider or finalizes the lifecycle.
        assert uow.lifecycle.get("PREPARED-RECOVERY-a").state is FiscalDocumentState.TRANSMITTING
    completed = http.post(
        f"/v1/portal/fiscal-intents/{intent}/resume", headers=headers, json=payload
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "recorded"
    with database() as uow:
        assert uow.lifecycle.get("PREPARED-RECOVERY-a").state is FiscalDocumentState.AUTHORIZED


def test_permission_is_checked_before_reading_prepared_document(http_system, monkeypatch):
    http, _, password = http_system
    headers = login(http, password, account="auditor")

    def forbidden_resolution(*args, **kwargs):
        raise AssertionError("prepared reference must not be resolved before permission")

    monkeypatch.setattr(
        FiscalApplicationService, "load_prepared_authorization", forbidden_resolution
    )
    response = http.post(
        "/v1/portal/fiscal-intents/prepare/reconcileFiscalOperation",
        headers=headers,
        json={
            "document_id": "PREPARED-RECOVERY-a",
            "unit_id": "unit-a",
            "environment": "homologation",
        },
    )
    assert response.status_code == 403
