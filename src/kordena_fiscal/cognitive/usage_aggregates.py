"""Process-local aggregate counters for the cognitive core, read by the FM Command.

Counters are monotonic since ``since`` (process start); the reader detects restarts by a new
``since``. Absence is never zero: cost is reported only for calls that reported a cost, and the
snapshot says how many did. Per-tenant cardinality is bounded. No content is ever stored.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .ports import AdviceMetricsSample

MAX_TENANTS = 500
OVERFLOW_TENANT = "_overflow"
LATENCY_BUCKETS_MS = (250, 500, 1000, 2000, 4000, 8000)


class CognitiveUsageAggregates:
    """Implements ``AdviceMetricsPort``."""

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.since = clock()
        self._total = 0
        self._by_status: dict[str, int] = defaultdict(int)
        self._by_capability: dict[str, int] = defaultdict(int)
        self._degraded: dict[str, int] = defaultdict(int)
        self._model_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_calls = 0
        self._cost_micro_brl = 0
        self._latency_sum_ms = 0
        self._latency_buckets: dict[str, int] = defaultdict(int)
        self._tenants: dict[str, dict[str, int]] = {}
        self._last_at: datetime | None = None

    def observe(self, sample: AdviceMetricsSample) -> None:
        usage = sample.usage
        with self._lock:
            self._total += 1
            self._by_status[sample.status] += 1
            self._by_capability[sample.capability.value] += 1
            if sample.degraded_reason:
                self._degraded[sample.degraded_reason] += 1
            called_model = usage.input_tokens > 0 or usage.output_tokens > 0
            if called_model:
                self._model_calls += 1
                self._input_tokens += usage.input_tokens
                self._output_tokens += usage.output_tokens
            if usage.cost_micro_brl is not None:
                self._cost_calls += 1
                self._cost_micro_brl += usage.cost_micro_brl
            self._latency_sum_ms += sample.latency_ms
            bucket = next((str(b) for b in LATENCY_BUCKETS_MS if sample.latency_ms <= b), "inf")
            self._latency_buckets[bucket] += 1
            tenant = sample.scope.tenant_id
            if tenant not in self._tenants and len(self._tenants) >= MAX_TENANTS:
                tenant = OVERFLOW_TENANT
            row = self._tenants.setdefault(tenant, {"requests": 0, "modelCalls": 0, "degraded": 0})
            row["requests"] += 1
            row["modelCalls"] += 1 if called_model else 0
            row["degraded"] += 1 if sample.degraded_reason else 0
            self._last_at = self._clock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "since": self.since.isoformat(),
                "lastObservedAt": self._last_at.isoformat() if self._last_at else None,
                "requests": {
                    "total": self._total,
                    "byStatus": dict(self._by_status),
                    "byCapability": dict(self._by_capability),
                    "degradedByReason": dict(self._degraded),
                },
                "model": {
                    "calls": self._model_calls,
                    "inputTokens": self._input_tokens,
                    "outputTokens": self._output_tokens,
                    "costReportedCalls": self._cost_calls,
                    "costMicroBrl": self._cost_micro_brl if self._cost_calls else None,
                },
                "latencyMs": {
                    "sum": self._latency_sum_ms,
                    "count": self._total,
                    "bucketsLe": dict(self._latency_buckets),
                },
                "tenants": {k: dict(v) for k, v in sorted(self._tenants.items())},
            }
