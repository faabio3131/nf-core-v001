from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.application import FiscalApplicationService
from kordena_fiscal.contingency import FiscalOutboxService
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.events import (
    FiscalInboxService,
    FiscalInboxStatus,
    InboxConflictError,
    InboxStateError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase


def _now() -> datetime:
    return datetime(2026, 9, 12, 1, 0, tzinfo=UTC)


def _scope(*, host: str = "kordena", correlation_id: str = "corr-inbox-001") -> ExecutionScope:
    return ExecutionScope(
        host_namespace=host,
        tenant_id="fiscal-account-1",
        unit_id="fiscal-unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=correlation_id,
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-inbox.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _receive(service: FiscalApplicationService, *, payload: bytes = b'{"status":"authorized"}'):
    return service.receive_inbox_event(
        scope=_scope(),
        producer="provider-webhook",
        event_id="evt-001",
        event_type="fiscal.document.authorized",
        payload=payload,
        occurred_at=_now(),
        received_at=_now() + timedelta(seconds=1),
        causation_id="cause-001",
        idempotency_key="idem-001",
    )


def test_duplicate_event_replays_after_process_restart_without_new_row(tmp_path) -> None:
    database = _database(tmp_path)
    service = FiscalApplicationService(database)

    first = _receive(service)
    assert first.replay is False
    assert first.entry.status is FiscalInboxStatus.RECEIVED
    assert first.entry.version == 0

    restarted = FiscalApplicationService(SqliteFiscalDatabase(database.path))
    replay = restarted.receive_inbox_event(
        scope=_scope(),
        producer="provider-webhook",
        event_id="evt-001",
        event_type="fiscal.document.authorized",
        payload=b'{"status":"authorized"}',
        occurred_at=_now(),
        received_at=_now() + timedelta(minutes=5),
        causation_id="cause-001",
        idempotency_key="idem-001",
    )

    assert replay.replay is True
    assert replay.entry.entry_id == first.entry.entry_id
    assert replay.entry.received_at == first.entry.received_at


def test_same_semantic_event_identity_with_different_payload_fails_closed(tmp_path) -> None:
    service = FiscalApplicationService(_database(tmp_path))
    _receive(service)

    with pytest.raises(InboxConflictError, match="different content"):
        _receive(service, payload=b'{"status":"rejected"}')


def test_inbox_state_machine_is_versioned_and_terminal_state_survives_restart(tmp_path) -> None:
    database = _database(tmp_path)
    service = FiscalApplicationService(database)
    received = _receive(service).entry

    processing = service.begin_inbox_processing(received.entry_id, expected_version=0)
    assert processing.status is FiscalInboxStatus.PROCESSING
    assert processing.version == 1

    with pytest.raises(InboxStateError, match="version"):
        service.complete_inbox_event(
            received.entry_id,
            expected_version=0,
            processed_at=_now() + timedelta(seconds=2),
            outcome_reference="document-123",
        )

    processed = service.complete_inbox_event(
        received.entry_id,
        expected_version=1,
        processed_at=_now() + timedelta(seconds=2),
        outcome_reference="document-123",
    )
    assert processed.status is FiscalInboxStatus.PROCESSED
    assert processed.version == 2
    assert processed.outcome_reference == "document-123"

    restarted = FiscalApplicationService(SqliteFiscalDatabase(database.path))
    persisted = restarted.get_inbox_event(received.entry_id)
    assert persisted == processed

    replay = _receive(restarted)
    assert replay.replay is True
    assert replay.entry == processed


def test_rejected_inbox_event_records_terminal_error(tmp_path) -> None:
    service = FiscalApplicationService(_database(tmp_path))
    received = _receive(service).entry
    processing = service.begin_inbox_processing(received.entry_id, expected_version=0)

    rejected = service.reject_inbox_event(
        processing.entry_id,
        expected_version=1,
        processed_at=_now() + timedelta(seconds=3),
        error="unsupported upstream event semantics",
    )

    assert rejected.status is FiscalInboxStatus.REJECTED
    assert rejected.version == 2
    assert rejected.last_error == "unsupported upstream event semantics"
    assert rejected.outcome_reference is None


def test_inbox_and_outbox_share_one_v2_07_transaction_boundary(tmp_path) -> None:
    database = _database(tmp_path)
    scope = _scope()

    with database.unit_of_work() as uow:
        inbox = FiscalInboxService(uow.inbox).receive(
            scope=scope,
            producer="provider-webhook",
            event_id="evt-rollback",
            event_type="fiscal.issuance.updated",
            payload=b'{"state":"pending"}',
            occurred_at=_now(),
            received_at=_now() + timedelta(seconds=1),
        )
        outbox = FiscalOutboxService(uow.outbox).enqueue(
            scope=scope,
            operation="webhook-delivery",
            deduplication_key="evt-rollback",
            payload=b'{"notify":"host"}',
            created_at=_now(),
        )
        # Deliberately no commit: both repositories must roll back together.

    with database.unit_of_work() as uow:
        assert uow.inbox.get(inbox.entry.entry_id) is None
        assert uow.outbox.get(outbox.entry.entry_id) is None


def test_same_upstream_event_id_is_isolated_by_host_partition(tmp_path) -> None:
    database = _database(tmp_path)

    with database.unit_of_work() as uow:
        first = FiscalInboxService(uow.inbox).receive(
            scope=_scope(host="kordena", correlation_id="corr-kordena"),
            producer="provider-webhook",
            event_id="evt-shared",
            event_type="fiscal.document.authorized",
            payload=b'{"document":"1"}',
            occurred_at=_now(),
            received_at=_now(),
        )
        second = FiscalInboxService(uow.inbox).receive(
            scope=_scope(host="iron-fit", correlation_id="corr-iron"),
            producer="provider-webhook",
            event_id="evt-shared",
            event_type="fiscal.document.authorized",
            payload=b'{"document":"1"}',
            occurred_at=_now(),
            received_at=_now(),
        )
        uow.commit()

    assert first.replay is False
    assert second.replay is False
    assert first.entry.entry_id != second.entry.entry_id
