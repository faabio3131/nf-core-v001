from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock

import pytest

from kordena_fiscal.application import DurableFiscalOutboxWorker
from kordena_fiscal.contingency import (
    FiscalDispatchResult,
    FiscalDispatchStatus,
    FiscalOutboxEntry,
    FiscalOutboxService,
    FiscalOutboxStatus,
    FiscalRetryPolicy,
    OutboxStateError,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence import SqliteFiscalDatabase


def _now() -> datetime:
    return datetime(2026, 9, 12, 1, 0, tzinfo=UTC)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="kordena",
        tenant_id="fiscal-account-1",
        unit_id="fiscal-unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-v2-08-outbox",
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-v2.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _enqueue(database: SqliteFiscalDatabase, key: str = "event-1") -> FiscalOutboxEntry:
    with database.unit_of_work() as uow:
        result = FiscalOutboxService(uow.outbox).enqueue(
            scope=_scope(),
            operation="publish_event",
            deduplication_key=key,
            payload=f'{{"event":"{key}"}}'.encode(),
            created_at=_now(),
        )
        uow.commit()
        return result.entry


class _SequenceHandler:
    def __init__(self, results: list[FiscalDispatchResult]) -> None:
        self._results = list(results)
        self.calls: list[FiscalOutboxEntry] = []

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        self.calls.append(entry)
        if not self._results:
            raise AssertionError("unexpected dispatch call")
        return self._results.pop(0)


class _ReentrantDatabaseHandler:
    def __init__(self, database: SqliteFiscalDatabase) -> None:
        self._database = database
        self.calls = 0

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        self.calls += 1
        with self._database.unit_of_work() as uow:
            persisted = uow.outbox.get(entry.entry_id)
            assert persisted is not None
            assert persisted.status is FiscalOutboxStatus.IN_FLIGHT
            assert persisted.attempt_count == entry.attempt_count
            uow.commit()
        return FiscalDispatchResult(
            FiscalDispatchStatus.SUCCEEDED,
            reference="delivery-1",
        )


class _CountingHandler:
    def __init__(self) -> None:
        self._lock = Lock()
        self.calls = 0

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        with self._lock:
            self.calls += 1
        return FiscalDispatchResult(
            FiscalDispatchStatus.SUCCEEDED,
            reference=f"delivery-{entry.attempt_count}",
        )


class _ExplodingHandler:
    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        raise TimeoutError(f"transport timeout for {entry.entry_id[:8]}")


def test_worker_commits_claim_before_handler_io_and_finalizes_in_new_transaction(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    handler = _ReentrantDatabaseHandler(database)
    worker = DurableFiscalOutboxWorker(uow_factory=database, handler=handler)

    outcome = worker.run_once(now=_now())[0]

    assert handler.calls == 1
    assert outcome.entry_id == entry.entry_id
    assert outcome.status is FiscalOutboxStatus.SUCCEEDED
    assert outcome.completion_reference == "delivery-1"
    with database.unit_of_work() as uow:
        assert uow.outbox.get(entry.entry_id) == outcome


def test_retry_backoff_survives_database_restart(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    policy = FiscalRetryPolicy(
        max_attempts=3,
        initial_delay_seconds=7,
        multiplier=2,
        max_delay_seconds=60,
    )
    first_handler = _SequenceHandler(
        [
            FiscalDispatchResult(
                FiscalDispatchStatus.RETRYABLE_FAILURE,
                error="broker temporarily unavailable",
            )
        ]
    )
    first_worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=first_handler,
        retry_policy=policy,
    )

    first = first_worker.run_once(now=_now())[0]
    assert first.status is FiscalOutboxStatus.RETRY_WAIT
    assert first.available_at == _now() + timedelta(seconds=7)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    second_handler = _SequenceHandler(
        [
            FiscalDispatchResult(
                FiscalDispatchStatus.SUCCEEDED,
                reference="delivery-after-restart",
            )
        ]
    )
    second_worker = DurableFiscalOutboxWorker(
        uow_factory=restarted,
        handler=second_handler,
        retry_policy=policy,
    )

    assert second_worker.run_once(now=_now() + timedelta(seconds=6)) == ()
    second = second_worker.run_once(now=_now() + timedelta(seconds=7))[0]
    assert second.entry_id == entry.entry_id
    assert second.status is FiscalOutboxStatus.SUCCEEDED
    assert second.attempt_count == 2
    assert second.completion_reference == "delivery-after-restart"


def test_expired_lease_is_recovered_after_simulated_worker_crash(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)

    with database.unit_of_work() as uow:
        crashed_claim = uow.outbox.claim_due(
            now=_now(),
            limit=1,
            lease_duration=timedelta(seconds=10),
        )[0]
        uow.commit()
    assert crashed_claim.attempt_count == 1

    restarted = SqliteFiscalDatabase(database.path)
    handler = _SequenceHandler(
        [FiscalDispatchResult(FiscalDispatchStatus.SUCCEEDED, reference="recovered")]
    )
    worker = DurableFiscalOutboxWorker(uow_factory=restarted, handler=handler)

    assert worker.run_once(now=_now() + timedelta(seconds=9)) == ()
    recovered = worker.run_once(now=_now() + timedelta(seconds=10))[0]
    assert recovered.entry_id == entry.entry_id
    assert recovered.status is FiscalOutboxStatus.SUCCEEDED
    assert recovered.attempt_count == 2
    assert recovered.completion_reference == "recovered"


def test_two_durable_workers_do_not_dispatch_same_live_lease(tmp_path) -> None:
    database = _database(tmp_path)
    _enqueue(database)
    handler = _CountingHandler()

    def run_worker(_: int) -> tuple[FiscalOutboxEntry, ...]:
        worker = DurableFiscalOutboxWorker(uow_factory=database, handler=handler)
        return worker.run_once(
            now=_now(),
            limit=1,
            lease_duration=timedelta(seconds=30),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_worker, range(2)))

    outcomes = [entry for batch in results for entry in batch]
    assert len(outcomes) == 1
    assert handler.calls == 1
    assert outcomes[0].status is FiscalOutboxStatus.SUCCEEDED


def test_stale_worker_cannot_finalize_after_lease_reclaim(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    with database.unit_of_work() as uow:
        first_claim = uow.outbox.claim_due(
            now=_now(),
            limit=1,
            lease_duration=timedelta(seconds=5),
        )[0]
        uow.commit()

    handler = _SequenceHandler(
        [FiscalDispatchResult(FiscalDispatchStatus.SUCCEEDED, reference="new-owner")]
    )
    worker = DurableFiscalOutboxWorker(uow_factory=database, handler=handler)
    new_owner = worker.run_once(now=_now() + timedelta(seconds=5))[0]
    assert new_owner.attempt_count == 2
    assert new_owner.status is FiscalOutboxStatus.SUCCEEDED

    with pytest.raises(OutboxStateError, match="not in flight|attempt version"):
        with database.unit_of_work() as uow:
            uow.outbox.mark_succeeded(
                entry.entry_id,
                expected_attempt=first_claim.attempt_count,
                completion_reference="stale-owner",
            )
            uow.commit()


def test_handler_exception_is_bounded_retry_then_dead_letter(tmp_path) -> None:
    database = _database(tmp_path)
    entry = _enqueue(database)
    policy = FiscalRetryPolicy(
        max_attempts=2,
        initial_delay_seconds=3,
        multiplier=2,
        max_delay_seconds=30,
    )
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=_ExplodingHandler(),
        retry_policy=policy,
    )

    first = worker.run_once(now=_now())[0]
    assert first.status is FiscalOutboxStatus.RETRY_WAIT
    assert first.attempt_count == 1
    assert first.available_at == _now() + timedelta(seconds=3)
    assert first.last_error is not None
    assert "TimeoutError" in first.last_error

    second = worker.run_once(now=_now() + timedelta(seconds=3))[0]
    assert second.entry_id == entry.entry_id
    assert second.status is FiscalOutboxStatus.DEAD_LETTER
    assert second.attempt_count == 2
    assert second.last_error is not None
    assert "TimeoutError" in second.last_error
    assert worker.run_once(now=_now() + timedelta(days=1)) == ()
