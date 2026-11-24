"""P09-T01: real OpenTelemetry SDK span capture without any network calls."""

from datetime import UTC, datetime

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from kordena_fiscal.runtime.observability import SafeTracer, TraceContext
from kordena_fiscal.runtime.otel_trace_sink import OtelTraceSink


def test_real_sdk_exports_bounded_span_without_context_or_secret() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    safe_tracer = SafeTracer(OtelTraceSink(provider.get_tracer("nfcore.runtime")))
    safe_tracer.record(
        operation="external.webhook",
        context=TraceContext(trace_id="a" * 32, correlation_id="customer-private"),
        started_at=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
        elapsed_seconds=0.4,
        outcome="error",
        attributes={"authorization": "Bearer forbidden", "tenant_id": "customer-private"},
    )
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "external.webhook"
    assert dict(span.attributes or {}) == {"nfcore.outcome": "error"}
    assert span.end_time - span.start_time == 400_000_000
    assert "customer-private" not in str(span.attributes)
    assert "forbidden" not in str(span.attributes)
    provider.shutdown()
