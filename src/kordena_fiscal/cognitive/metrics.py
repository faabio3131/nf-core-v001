"""Cognitive metrics on top of the repository's bounded-cardinality metric recorder."""

from __future__ import annotations

from kordena_fiscal.observability.events import ObservabilityContext
from kordena_fiscal.observability.metrics import MetricDefinition, MetricKind, MetricRecorder

from .ports import AdviceMetricsSample

ADVICE_TOTAL = MetricDefinition(
    name="cognitive.advice.total",
    kind=MetricKind.COUNTER,
    optional_labels=frozenset({"status"}),
)
DEGRADED_TOTAL = MetricDefinition(
    name="cognitive.degraded.total",
    kind=MetricKind.COUNTER,
    optional_labels=frozenset({"reason_code"}),
)
MODEL_TOKENS_TOTAL = MetricDefinition(name="cognitive.model.tokens.total", kind=MetricKind.COUNTER)
MODEL_COST_MICRO_BRL_TOTAL = MetricDefinition(
    name="cognitive.model.cost_micro_brl.total", kind=MetricKind.COUNTER
)
ADVICE_DURATION_SECONDS = MetricDefinition(
    name="cognitive.advice.duration_seconds",
    kind=MetricKind.HISTOGRAM,
    optional_labels=frozenset({"status"}),
)


class ObservabilityAdviceMetrics:
    """Publishes counts, tokens, cost and latency. Labels never carry text or identifiers
    beyond the tenant/unit partition already mandated by the metric recorder."""

    def __init__(self, recorder: MetricRecorder) -> None:
        self._recorder = recorder

    def observe(self, sample: AdviceMetricsSample) -> None:
        if sample.scope.host_namespace is None:
            return  # observability requires a host namespace; skip rather than fail
        context = ObservabilityContext(scope=sample.scope, operation=sample.capability.name.lower())
        self._recorder.record(
            definition=ADVICE_TOTAL, context=context, value=1, labels={"status": sample.status}
        )
        if sample.degraded_reason:
            self._recorder.record(
                definition=DEGRADED_TOTAL,
                context=context,
                value=1,
                labels={"reason_code": sample.degraded_reason},
            )
        tokens = sample.usage.input_tokens + sample.usage.output_tokens
        if tokens:
            self._recorder.record(definition=MODEL_TOKENS_TOTAL, context=context, value=tokens)
        if sample.usage.cost_micro_brl:
            self._recorder.record(
                definition=MODEL_COST_MICRO_BRL_TOTAL,
                context=context,
                value=sample.usage.cost_micro_brl,
            )
        self._recorder.record(
            definition=ADVICE_DURATION_SECONDS,
            context=context,
            value=sample.latency_ms / 1000,
            labels={"status": sample.status},
        )
