"""P09-T01: real SDK exports safe spans over localhost OTLP/HTTP."""

from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from kordena_fiscal.runtime.observability import SafeTracer, TraceContext
from kordena_fiscal.runtime.otel_trace_sink import OtelTraceSink


def test_real_otlp_http_exports_bounded_span_to_local_receiver() -> None:
    bodies: list[bytes] = []
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            paths.append(self.path)
            size = int(self.headers.get("Content-Length", "0"))
            bodies.append(self.rfile.read(size))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = TracerProvider(sampler=ALWAYS_ON)
    try:
        exporter = OTLPSpanExporter(endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces")
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        SafeTracer(OtelTraceSink(provider.get_tracer("nfcore.runtime"))).record(
            operation="worker.dispatch",
            context=TraceContext(trace_id="a" * 32, correlation_id="private-customer"),
            started_at=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
            elapsed_seconds=0.125,
            outcome="succeeded",
            attributes={"authorization": "Bearer not-for-export", "tenant_id": "private-customer"},
        )
        assert paths == ["/v1/traces"]
        request = ExportTraceServiceRequest()
        request.ParseFromString(bodies[0])
        spans = [
            span
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        assert len(spans) == 1
        assert spans[0].name == "worker.dispatch"
        assert [(a.key, a.value.string_value) for a in spans[0].attributes] == [
            ("nfcore.outcome", "succeeded")
        ]
        assert spans[0].end_time_unix_nano - spans[0].start_time_unix_nano == 125_000_000
        assert b"private-customer" not in bodies[0]
        assert b"not-for-export" not in bodies[0]
    finally:
        provider.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
