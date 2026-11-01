from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kordena_fiscal.cognitive import ContextPackBuilder, default_baselines
from kordena_fiscal.cognitive.adapters import (
    CONTRACT_VERSION,
    CentralFMAdvisoryClient,
    CentralFMConfig,
    HttpResponse,
    UrllibTransport,
)
from kordena_fiscal.cognitive.ports import (
    ModelProviderDenied,
    ModelProviderMalformed,
    ModelProviderRateLimited,
    ModelProviderUnavailable,
)
from kordena_fiscal.security.s2s import (
    InMemoryWebhookKeyRing,
    WebhookSecurity,
    WebhookSignature,
)

from .conftest import make_request

NOW = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
KEYS = InMemoryWebhookKeyRing(active_key_id="k1", keys={"k1": b"x" * 48})
SIGNER = WebhookSecurity(key_resolver=KEYS, signing_key_id="k1")
URL = "https://core.fm.example/v1/core/fiscal/advise"


def prompt_for(**kwargs):  # type: ignore[no-untyped-def]
    request = make_request(**kwargs)
    augmented_baseline = default_baselines()[request.capability](request)
    from dataclasses import replace

    request = replace(request, evidence=request.evidence + augmented_baseline.extra_evidence)
    return ContextPackBuilder().build(request).prompt


def ok_body(prompt, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "contractVersion": CONTRACT_VERSION,
        "requestId": prompt.request_id,
        "sections": [
            {"kind": "hypothesis", "text": "Possível reenvio.", "evidenceIds": ["rej-1"]}
        ],
        "provider": "fm-central",
        "model": "m",
        "modelVersion": "1",
        "usage": {"inputTokens": 10, "outputTokens": 5, "costMicroBrl": 300},
    }
    data.update(overrides)
    return json.dumps(data).encode()


class Capture:
    def __init__(self, response: HttpResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def post(self, url, headers, body, timeout_seconds):  # type: ignore[no-untyped-def]
        self.calls.append((url, dict(headers), body, timeout_seconds))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def client(transport, **kwargs):  # type: ignore[no-untyped-def]
    return CentralFMAdvisoryClient(
        config=CentralFMConfig(URL), signer=SIGNER, transport=transport,
        clock=lambda: NOW, **kwargs,
    )


def test_request_is_signed_scoped_and_carries_no_credentials() -> None:
    prompt = prompt_for()
    transport = Capture(HttpResponse(200, ok_body(prompt)))
    answer = client(transport).advise(prompt, deadline_seconds=3.0)
    url, headers, body, timeout = transport.calls[0]
    assert url == URL and timeout == 3.0
    payload = json.loads(body)
    assert payload["tenantId"] == "tenant-a" and payload["unitId"] == "unit-a"
    assert payload["requestId"] == "req-1" and payload["correlationId"] == "corr-1"
    assert payload["contractVersion"] == CONTRACT_VERSION and payload["productId"] == "nfcore"
    assert headers["Idempotency-Key"] == "req-1"
    assert not any(h.lower() in ("authorization", "x-api-key") for h in headers)
    # The Command side can verify the signature with the same scheme (rotation-ready key ring).
    command_side = WebhookSecurity(key_resolver=KEYS, signing_key_id="k1")
    command_side.verify(body, WebhookSignature.parse(headers["X-FM-Signature"]), now=NOW)
    assert answer.sections[0].text == "Possível reenvio."
    assert answer.usage.cost_micro_brl == 300 and answer.provider_id == "fm-central"


def test_signature_does_not_verify_for_tampered_body_or_after_replay_window() -> None:
    prompt = prompt_for()
    transport = Capture(HttpResponse(200, ok_body(prompt)))
    client(transport).advise(prompt, deadline_seconds=3.0)
    _, headers, body, _ = transport.calls[0]
    signature = WebhookSignature.parse(headers["X-FM-Signature"])
    command_side = WebhookSecurity(key_resolver=KEYS, signing_key_id="k1")
    with pytest.raises(Exception, match="mismatch"):
        command_side.verify(body + b" ", signature, now=NOW)
    with pytest.raises(Exception, match="stale"):
        command_side.verify(body, signature, now=NOW + timedelta(hours=1))


def test_payload_is_redacted_even_if_context_leaked_something() -> None:
    prompt = prompt_for()
    from dataclasses import replace

    leaky = replace(prompt, trusted_facts="emitente 11.222.333/0001-81 senha=hunter2x")
    transport = Capture(HttpResponse(200, ok_body(leaky)))
    client(transport).advise(leaky, deadline_seconds=1.0)
    sent = transport.calls[0][2].decode()
    assert "11.222.333" not in sent and "hunter2x" not in sent


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ModelProviderDenied),
        (403, ModelProviderDenied),
        (429, ModelProviderRateLimited),
        (500, ModelProviderUnavailable),
        (503, ModelProviderUnavailable),
        (404, ModelProviderMalformed),
        (302, ModelProviderMalformed),
    ],
)
def test_http_status_mapping(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        client(Capture(HttpResponse(status, b""))).advise(prompt_for(), deadline_seconds=1.0)


def test_transport_failures_are_unavailable() -> None:
    for failure in (TimeoutError("t"), ConnectionError("c")):
        with pytest.raises(ModelProviderUnavailable):
            client(Capture(failure)).advise(prompt_for(), deadline_seconds=1.0)


def test_strict_response_validation() -> None:
    prompt = prompt_for()
    bad_bodies = [
        b"not json",
        b"[]",
        ok_body(prompt, contractVersion="other/v9"),
        ok_body(prompt, requestId="someone-else"),
        ok_body(prompt, sections="nope"),
        ok_body(prompt, sections=[{"kind": "bogus", "text": "x", "evidenceIds": []}]),
        ok_body(prompt, sections=[{"kind": "fact", "text": 7, "evidenceIds": []}]),
        ok_body(prompt, sections=[{"kind": "action", "text": "x", "evidenceIds": [1]}]),
        ok_body(prompt, sections=[{"kind": "action", "text": "x"}] * 13),
        b"{" + b"a" * (64 * 1024 + 10),
    ]
    for body in bad_bodies:
        with pytest.raises(ModelProviderMalformed):
            client(Capture(HttpResponse(200, body))).advise(prompt, deadline_seconds=1.0)


def test_endpoint_must_be_https_without_embedded_credentials() -> None:
    for bad in (
        "http://core.fm.example/x",
        "ftp://core.fm.example/x",
        "https://user:pw@core.fm.example/x",
        "https://core.fm.example/x?token=abc",
        "http://127.0.0.1:9/x",
    ):
        with pytest.raises(ValueError):
            CentralFMConfig(bad)
    CentralFMConfig("http://127.0.0.1:9/x", allow_insecure_loopback=True)
    with pytest.raises(ValueError):
        CentralFMConfig("http://core.fm.example/x", allow_insecure_loopback=True)


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://evil.example/")
            self.end_headers()
            return
        if self.mode == "slow":
            import time

            time.sleep(1.0)
        payload = json.loads(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            ok_body(type("P", (), {"request_id": payload["requestId"]})())
        )

    def log_message(self, *args: object) -> None:
        return


def serve(mode: str) -> tuple[HTTPServer, str]:
    handler = type("H", (_Handler,), {"mode": mode})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/advise"


def real_client(url: str) -> CentralFMAdvisoryClient:
    return CentralFMAdvisoryClient(
        config=CentralFMConfig(url, allow_insecure_loopback=True),
        signer=SIGNER,
        transport=UrllibTransport(),
        clock=lambda: NOW,
    )


def test_real_http_roundtrip_redirect_refusal_and_timeout() -> None:
    prompt = prompt_for()
    server, url = serve("ok")
    try:
        assert real_client(url).advise(prompt, deadline_seconds=3).provider_id == "fm-central"
    finally:
        server.shutdown()
    server, url = serve("redirect")
    try:
        with pytest.raises(ModelProviderMalformed):  # 302 is never followed
            real_client(url).advise(prompt, deadline_seconds=3)
    finally:
        server.shutdown()
    server, url = serve("slow")
    try:
        with pytest.raises(ModelProviderUnavailable):
            real_client(url).advise(prompt, deadline_seconds=0.2)
    finally:
        server.shutdown()
    with pytest.raises(ModelProviderUnavailable):  # nothing listening
        real_client("http://127.0.0.1:9/advise").advise(prompt, deadline_seconds=0.5)
