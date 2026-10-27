"""Vendor-neutral observability primitives for FM NFCORE runtime boundaries."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import Any, Protocol

from kordena_fiscal.contingency import FiscalOutboxStatus

_SENSITIVE_KEY = re.compile(
    r"(authorization|password|passwd|secret|token|cookie|private[_-]?key|certificate|pfx|p12|pem|csc|email|legal[_-]?name|buyer|customer[_-]?id)",
    re.IGNORECASE,
)
_PRIVATE_MARKER = "-----BEGIN " + "PRIVATE KEY-----"
_CERTIFICATE_MARKER = "-----BEGIN " + "CERTIFICATE-----"
_SENSITIVE_VALUE = re.compile(
    rf"({re.escape(_PRIVATE_MARKER)}|{re.escape(_CERTIFICATE_MARKER)}|Bearer\s+\S+)",
    re.IGNORECASE,
)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact known credential fields without mutating the source object."""

    if key is not None and _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, bytes):
        return "<redacted-bytes>"
    if isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        return "<redacted>"
    return value


LogSink = Callable[[str], None]


class StructuredLogger:
    def __init__(self, *, service: str, environment: str, sink: LogSink | None = None) -> None:
        self._service = service
        self._environment = environment
        self._sink = sink or print

    def emit(self, level: str, event: str, **fields: Any) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level.upper(),
            "service": self._service,
            "environment": self._environment,
            "event": event,
            **fields,
        }
        self._sink(json.dumps(redact(payload), sort_keys=True, separators=(",", ":")))


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    value: float
    labels: tuple[tuple[str, str], ...] = ()


class MetricsRegistry:
    """Small in-process adapter; export can later be wired to Prometheus/OTel."""

    _ALLOWED_LABELS = frozenset({"method", "status_class", "operation", "outcome", "service"})

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = RLock()
        self._collectors: list[Callable[[], None]] = []

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("metric increment must be finite and non-negative")
        unknown = set(labels) - self._ALLOWED_LABELS
        if unknown:
            raise ValueError(f"high-cardinality/unsupported metric labels: {sorted(unknown)}")
        key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
        with self._lock:
            updated = self._values[key] + float(value)
            if not math.isfinite(updated):
                raise ValueError("metric accumulation must remain finite")
            self._values[key] = updated

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("gauge must be finite and non-negative")
        if set(labels) - self._ALLOWED_LABELS:
            raise ValueError("high-cardinality/unsupported metric labels")
        key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
        with self._lock:
            self._values[key] = float(value)

    def register_collector(self, collector: Callable[[], None]) -> None:
        """Refresh process-local gauges at collection; collectors must not do I/O."""
        with self._lock:
            self._collectors.append(collector)

    def observe_seconds(self, name: str, seconds: float, **labels: str) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("metric duration must be finite and non-negative")
        # Validate the labels before either update; never create half an observation.
        if set(labels) - self._ALLOWED_LABELS:
            raise ValueError("high-cardinality/unsupported metric labels")
        dimensions = tuple(sorted((k, str(v)) for k, v in labels.items()))
        count_key = (f"{name}_count", dimensions)
        duration_key = (f"{name}_seconds_total", dimensions)
        with self._lock:
            count = self._values[count_key] + 1.0
            duration = self._values[duration_key] + seconds
            if not math.isfinite(count) or not math.isfinite(duration):
                raise ValueError("metric accumulation must remain finite")
            self._values[count_key] = count
            self._values[duration_key] = duration

    def snapshot(self) -> tuple[MetricSample, ...]:
        with self._lock:
            collectors = tuple(self._collectors)
        for collector in collectors:
            try:
                collector()
            except Exception:
                # A telemetry exporter must not terminate application execution.
                continue
        with self._lock:
            return tuple(
                MetricSample(name=name, value=value, labels=labels)
                for (name, labels), value in sorted(self._values.items())
            )

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {"name": sample.name, "value": sample.value, "labels": dict(sample.labels)}
            for sample in self.snapshot()
        ]


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    correlation_id: str
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TraceRecord:
    operation: str
    context: TraceContext
    started_at: datetime
    elapsed_seconds: float
    outcome: str
    attributes: Mapping[str, Any] = field(default_factory=dict)


class TraceSink(Protocol):
    def record(self, trace: TraceRecord) -> None: ...


class NullTraceSink:
    def record(self, trace: TraceRecord) -> None:
        del trace


class StructuredLogTraceSink:
    """Export bounded, non-sensitive runtime spans through the existing logger.

    Context identifiers and free-form attributes are intentionally excluded: the
    runtime logger is not a destination for client data or credential material.
    """

    # Fixed low-cardinality vocabulary: syntactically safe identifiers can still be PII.
    _ALLOWED_OPERATIONS = frozenset({
        "http.request",
        "worker.dispatch",
        "worker.cycle",
        "worker.poll",
        "db.outbox_counts",
        "db.readiness",
        "external.webhook",
    })
    _ALLOWED_OUTCOMES = frozenset({
        "ok",
        "error",
        "invalid",
        "succeeded",
        "retry_wait",
        "dead_letter",
        "failed",
    })

    def __init__(self, logger: StructuredLogger) -> None:
        self._logger = logger

    def record(self, trace: TraceRecord) -> None:
        operation = trace.operation
        outcome = trace.outcome
        if operation not in self._ALLOWED_OPERATIONS:
            operation = "other"
        if outcome not in self._ALLOWED_OUTCOMES:
            outcome = "other"
        duration = trace.elapsed_seconds
        if not math.isfinite(duration):
            duration = 0.0
        self._logger.emit(
            "info" if outcome == "ok" else "warning",
            "runtime.trace",
            operation=operation,
            outcome=outcome,
            elapsed_seconds=round(max(0.0, duration), 6),
        )


class SafeTracer:
    """Tracing adapter that redacts attributes and never breaks fiscal execution."""

    def __init__(self, sink: TraceSink | None = None) -> None:
        self._sink = sink or NullTraceSink()

    def record(
        self,
        *,
        operation: str,
        context: TraceContext,
        started_at: datetime,
        elapsed_seconds: float,
        outcome: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        safe_attributes = redact(dict(attributes or {}))
        try:
            self._sink.record(
                TraceRecord(
                    operation=operation,
                    context=context,
                    started_at=started_at,
                    elapsed_seconds=max(0.0, elapsed_seconds),
                    outcome=outcome,
                    attributes=safe_attributes,
                )
            )
        except Exception:
            # Observability must never become fiscal authority or take the runtime down.
            return


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    """Internal poll health, never fiscal/provider/production approval."""

    ready: bool
    stopped: bool
    queue_snapshot_valid: bool
    last_success_age_seconds: float | None


class WorkerObservability:
    def __init__(
        self,
        *,
        metrics: MetricsRegistry,
        logger: StructuredLogger,
        queue_counts: Callable[[], Mapping[FiscalOutboxStatus, int]] | None = None,
        heartbeat_timeout_seconds: float = 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not math.isfinite(heartbeat_timeout_seconds) or heartbeat_timeout_seconds <= 0:
            raise ValueError("heartbeat timeout must be finite and positive")
        self._metrics = metrics
        self._logger = logger
        self._queue_counts = queue_counts
        self._timeout = heartbeat_timeout_seconds
        self._clock = clock
        self._lock = RLock()
        self._last_success: float | None = None
        self._poll_ok = False
        self._stopped = False
        self._snapshot_valid = False
        metrics.set_gauge("nfcore_worker_last_success_timestamp_seconds", 0)
        metrics.register_collector(self._refresh_health_metrics)

    def health(self) -> WorkerHealth:
        with self._lock:
            age = (
                None if self._last_success is None else max(0.0, self._clock() - self._last_success)
            )
            return WorkerHealth(
                ready=(
                    not self._stopped
                    and self._poll_ok
                    and self._snapshot_valid
                    and age is not None
                    and age < self._timeout
                ),
                stopped=self._stopped,
                queue_snapshot_valid=self._snapshot_valid,
                last_success_age_seconds=age,
            )

    def _refresh_health_metrics(self) -> None:
        health = self.health()
        self._metrics.set_gauge("nfcore_worker_ready", int(health.ready))
        self._metrics.set_gauge("nfcore_worker_stopped", int(health.stopped))
        self._metrics.set_gauge(
            "nfcore_worker_queue_snapshot_valid", int(health.queue_snapshot_valid)
        )
        # No heartbeat has a separate validity signal, rather than an invented age.
        self._metrics.set_gauge(
            "nfcore_worker_heartbeat_observed", int(health.last_success_age_seconds is not None)
        )
        self._metrics.set_gauge(
            "nfcore_worker_heartbeat_age_seconds", health.last_success_age_seconds or 0.0
        )

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        try:
            self._logger.emit(level, event, **fields)
        except Exception:
            self._metrics.increment("nfcore_worker_telemetry_failures_total", outcome="log")

    def worker_started(self) -> None:
        with self._lock:
            self._last_success = None
            self._poll_ok = False
            self._snapshot_valid = False
            self._stopped = False
        self._metrics.set_gauge("nfcore_worker_last_success_timestamp_seconds", 0)
        self._emit("INFO", "worker_started")

    def worker_stopped(self) -> None:
        with self._lock:
            self._stopped = True
        self._emit("INFO", "worker_stopped")

    def cycle_completed(self, result: Any) -> None:
        for outcome in ("claimed", "succeeded", "retry_wait", "dead_letter"):
            self._metrics.increment(
                "nfcore_worker_jobs_total", int(getattr(result, outcome)), outcome=outcome
            )
        self._metrics.increment(
            "nfcore_worker_job_failures_total", result.retry_wait + result.dead_letter
        )
        self._metrics.observe_seconds("nfcore_worker_cycle", float(result.elapsed_seconds))
        with self._lock:
            self._last_success = self._clock()
            self._poll_ok = True
        self._metrics.set_gauge(
            "nfcore_worker_last_success_timestamp_seconds", datetime.now(UTC).timestamp()
        )
        try:
            if self._queue_counts is None:
                raise RuntimeError("queue snapshot source absent")
            counts = self._queue_counts()
            # Fixed enum keys only; never emit tenant IDs, payloads or raw SQL errors.
            values = {status: counts[status] for status in FiscalOutboxStatus}
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values.values()):
                raise ValueError("invalid queue snapshot")
            for status, value in values.items():
                self._metrics.set_gauge("nfcore_worker_queue_jobs", value, outcome=status.value)
            self._metrics.set_gauge(
                "nfcore_worker_backlog_jobs",
                sum(
                    values[s]
                    for s in (
                        FiscalOutboxStatus.PENDING,
                        FiscalOutboxStatus.RETRY_WAIT,
                        FiscalOutboxStatus.IN_FLIGHT,
                    )
                ),
            )
            with self._lock:
                self._snapshot_valid = True
        except Exception as exc:
            with self._lock:
                self._snapshot_valid = False
            self._metrics.increment("nfcore_worker_telemetry_failures_total", outcome="queue")
            self._emit("ERROR", "worker_queue_snapshot_failed", error_type=type(exc).__name__)
        self._emit(
            "INFO",
            "worker_cycle_completed",
            claimed=result.claimed,
            succeeded=result.succeeded,
            retry_wait=result.retry_wait,
            dead_letter=result.dead_letter,
            duration_seconds=result.elapsed_seconds,
        )

    def cycle_failed(self, *, error_type: str, elapsed_seconds: float) -> None:
        with self._lock:
            self._poll_ok = False
            self._snapshot_valid = False
        self._metrics.increment("nfcore_worker_cycle_failures_total", outcome="failed")
        self._metrics.observe_seconds("nfcore_worker_cycle", elapsed_seconds, outcome="failed")
        self._emit(
            "ERROR",
            "worker_cycle_failed",
            error_type=error_type,
            duration_seconds=elapsed_seconds,
        )


class RequestTimer:
    def __init__(self) -> None:
        self.started = monotonic()

    def elapsed(self) -> float:
        return max(0.0, monotonic() - self.started)
