from __future__ import annotations

from datetime import UTC, datetime

from kordena_fiscal.application import DurableFiscalOutboxWorker
from kordena_fiscal.contingency import (
    FiscalDispatchResult,
    FiscalDispatchStatus,
    FiscalOutboxEntry,
    FiscalOutboxService,
    FiscalOutboxStatus,
)
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
)
from kordena_fiscal.numbering import FiscalSequenceManager, InMemoryFiscalSequenceStore
from kordena_fiscal.observability import (
    InMemoryMetricSink,
    MetricDefinition,
    MetricKind,
    MetricRecorder,
    ObservabilityContext,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase

NOW = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _CountingHandler:
    def __init__(self) -> None:
        self.calls = 0

    def dispatch(self, entry: FiscalOutboxEntry) -> FiscalDispatchResult:
        self.calls += 1
        return FiscalDispatchResult(
            FiscalDispatchStatus.SUCCEEDED,
            reference=f"load-{entry.entry_id}",
        )


def _scope(
    *,
    tenant: str = "tenant-load",
    unit: str = "unit-load",
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.hardening",
        tenant_id=tenant,
        unit_id=unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=f"corr-{tenant}-{unit}",
    )


def test_sequence_baseline_reserves_2048_unique_contiguous_numbers() -> None:
    manager = FiscalSequenceManager(InMemoryFiscalSequenceStore())
    numbers = [
        manager.reserve(
            _scope(),
            model=ElectronicInvoiceModel.NFCE,
            series=99,
        ).number
        for _ in range(2048)
    ]

    assert numbers[0] == 1
    assert numbers[-1] == 2048
    assert len(set(numbers)) == 2048


def test_metric_baseline_keeps_5000_points_in_one_governed_series() -> None:
    definition = MetricDefinition(
        name="fiscal.hardening.load.counter",
        kind=MetricKind.COUNTER,
        max_series=4,
    )
    sink = InMemoryMetricSink()
    recorder = MetricRecorder(sink=sink, clock=_Clock())
    context = ObservabilityContext(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        provider_id="provider-load",
        operation="query",
    )

    for _ in range(5000):
        assert recorder.record(definition=definition, context=context, value=1)

    assert recorder.series_count(definition.name) == 1
    assert len(sink.points) == 5000


def test_metric_baseline_caps_noisy_neighbor_series() -> None:
    definition = MetricDefinition(
        name="fiscal.hardening.load.bounded",
        kind=MetricKind.GAUGE,
        max_series=32,
    )
    sink = InMemoryMetricSink()
    recorder = MetricRecorder(sink=sink, clock=_Clock())

    accepted = 0
    for index in range(128):
        context = ObservabilityContext(
            scope=_scope(tenant=f"tenant-{index:03d}"),
            document_kind=FiscalDocumentKind.NFE,
            provider_id="provider-load",
            operation="query",
        )
        accepted += int(recorder.record(definition=definition, context=context, value=index))

    assert accepted == 32
    assert recorder.series_count(definition.name) == 32
    assert len(sink.points) == 32


def test_durable_outbox_baseline_drains_200_entries_without_duplication(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "load-baseline.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    scope = _scope()

    with database.unit_of_work() as uow:
        service = FiscalOutboxService(uow.outbox)
        for index in range(200):
            service.enqueue(
                scope=scope,
                operation="load-baseline",
                deduplication_key=f"load-{index:04d}",
                payload=f'{{"index":{index}}}'.encode(),
                created_at=NOW,
            )
        uow.commit()

    handler = _CountingHandler()
    worker = DurableFiscalOutboxWorker(uow_factory=database, handler=handler)
    outcomes: list[FiscalOutboxEntry] = []
    for _ in range(4):
        outcomes.extend(worker.run_once(now=NOW, limit=50))

    assert len(outcomes) == 200
    assert handler.calls == 200
    assert len({entry.entry_id for entry in outcomes}) == 200
    assert all(entry.status is FiscalOutboxStatus.SUCCEEDED for entry in outcomes)
    assert worker.run_once(now=NOW, limit=50) == ()
