"""Provider boundary is synthetic; archive, claims and HTTP recovery are durable."""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.domain import Cnpj, ElectronicInvoiceModel
from kordena_fiscal.operations import (
    FakeFiscalOperationsGateway,
    FiscalEventStatus,
    FiscalOperationsClient,
)
from kordena_fiscal.operations.event_archive import EVENT_RESULT_MEDIA_TYPE, event_archive_reference
from kordena_fiscal.runtime.provider_operation_wiring import build_provider_operation_handlers
from kordena_fiscal.xml import AccessKeyInput, build_access_key

spec = importlib.util.spec_from_file_location(
    "event_recovery_base", Path(__file__).with_name("test_p02_t07_fiscal_recovery.py")
)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
database = base.database


def event_handler(database, status, operation="inutilizeFiscalRange"):
    gateway = FakeFiscalOperationsGateway(event_status=status)
    handler = build_provider_operation_handlers(
        FiscalOperationsClient(gateway),
        application=FiscalApplicationService(database),
        archive_retention=RetentionPolicyMetadata(policy_id="synthetic-event", policy_version=1),
    )[operation]
    return handler, gateway


@pytest.mark.parametrize("status", list(FiscalEventStatus))
def test_cancellation_archives_validated_protocol_in_canonical_store(database, status):
    handler, gateway = event_handler(database, status, "cancelFiscalDocument")
    access_key = build_access_key(AccessKeyInput(
        state_ibge_code="35", issued_at=base.base.fixture.NOW,
        issuer_cnpj=Cnpj("12.345.678/0001-95"), model=ElectronicInvoiceModel.NFE,
        series=1, invoice_number=1, emission_type=1, numeric_code=12345678,
    )).value
    result = handler(base.base.fixture.scope(), {
        "access_key": access_key, "authorization_protocol": "SYNTHETIC-AUTH",
        "justification": "Justificativa sintetica de cancelamento",
    }, "event-key")
    assert len(gateway.cancel_calls) == 1
    with database() as uow:
        entry = uow.archive.get(result["entry_id"])
        evidence = json.loads(entry.content)
        assert evidence["operation"] == "cancelFiscalDocument"
        assert evidence["access_key"] == access_key
        assert evidence["status"] == status.value
        assert evidence["event_protocol_reference"] == result["event_protocol_reference"]
        assert entry.scope == base.base.fixture.scope()
        assert "authorization_protocol" not in evidence


@pytest.mark.parametrize("status", list(FiscalEventStatus))
def test_response_loss_after_event_archive_recovers_reference_without_redispatch(database, status):
    handler, gateway = event_handler(database, status)

    def lose_response(scope, payload, key):
        handler(scope, payload, key)
        raise HTTPException(503, detail="synthetic response loss after archive commit")

    app, _, _, calls = base.harness(database, handler=lose_response)
    http = base.login(app)
    intent = base.prepare(http)
    assert base.resume(http, intent).status_code == 503
    recovered = base.resume(base.login(app), intent, key="new-tab-key")
    assert recovered.status_code == 200, recovered.text
    receipt = recovered.json()
    assert receipt["state"] == "recorded"
    assert receipt["fiscal_confirmation"] == "not_inferred_from_receipt"
    assert not ({"result", "event_protocol_reference", "original_key"} & receipt.keys())
    assert calls == ["original-key"] and len(gateway.inutilization_calls) == 1
    with database() as uow:
        entry = uow.archive.get(receipt["reference_id"])
        assert entry.kind is FiscalArchiveKind.FISCAL_EVENT
        assert entry.media_type == EVENT_RESULT_MEDIA_TYPE
        assert entry.document_reference == event_archive_reference(
            "inutilizeFiscalRange", "original-key"
        )
        evidence = json.loads(entry.content)
        assert evidence["status"] == status.value
        assert evidence["request_id"] == gateway.inutilization_calls[0].request_id
        assert (evidence["event_protocol_reference"] is not None) == (
            status is FiscalEventStatus.ACCEPTED
        )
        assert "justification" not in evidence and "rejection_message" not in evidence
    # Rebuilding the app over the same database still returns the durable reference.
    restarted, _, _, restarted_calls = base.harness(database, handler=handler)
    replay = base.resume(base.login(restarted), intent)
    assert replay.status_code == 200 and replay.json()["reference_id"] == receipt["reference_id"]
    assert restarted_calls == [] and len(gateway.inutilization_calls) == 1


def test_archive_failure_never_records_success_or_retries_external_event(database, monkeypatch):
    handler, gateway = event_handler(database, FiscalEventStatus.ACCEPTED)
    app, _, _, calls = base.harness(database, handler=handler)
    http = base.login(app)
    intent = base.prepare(http)
    with database() as uow:
        archive_type = type(uow.archive)

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic archive unavailable")

    monkeypatch.setattr(archive_type, "append", unavailable)
    with pytest.raises(RuntimeError, match="archive unavailable"):
        base.resume(http, intent)
    assert base.stored(database, intent)["state"] == "executing"
    blocked = base.resume(base.login(app), intent)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "FISCAL_RECONCILIATION_REQUIRED"
    assert calls == ["original-key"] and len(gateway.inutilization_calls) == 1
