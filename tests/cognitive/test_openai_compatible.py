from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from kordena_fiscal.cognitive import SectionKind
from kordena_fiscal.cognitive.adapters.central_fm import HttpResponse
from kordena_fiscal.cognitive.adapters.openai_compatible import (
    FallbackAdvisoryClient,
    OpenAICompatibleAdvisoryClient,
    OpenAICompatibleConfig,
    build_model_from_environ,
)
from kordena_fiscal.cognitive.context import ContextPackBuilder
from kordena_fiscal.cognitive.ports import (
    ModelProviderDenied,
    ModelProviderMalformed,
    ModelProviderRateLimited,
    ModelProviderUnavailable,
)

from .conftest import make_request, rejection_evidence

SECRET = "sk-test-secret-value-0123456789abcdef"


def prompt():  # type: ignore[no-untyped-def]
    return ContextPackBuilder().build(make_request(
        evidence=rejection_evidence("204", message="Contato 11.222.333/0001-81 rejeitou"),
    )).prompt


def completion(sections: object, *, extra: Mapping[str, object] | None = None) -> bytes:
    body = {"model": "m-1", "usage": {"prompt_tokens": 100, "completion_tokens": 40},
            "choices": [{"message": {"content": json.dumps({"sections": sections})}}]}
    body.update(extra or {})
    return json.dumps(body).encode()


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def post(self, url, headers, body, timeout_seconds):  # type: ignore[no-untyped-def]
        self.calls.append((url, dict(headers), body, timeout_seconds))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(transport: FakeTransport, key: str | None = SECRET, provider: str = "gemini"):  # type: ignore[no-untyped-def]
    cfg = OpenAICompatibleConfig(provider, "https://api.example.test/v1", "model-x")
    return OpenAICompatibleAdvisoryClient(config=cfg, api_key=lambda: key, transport=transport)


GOOD = [{"kind": "hypothesis", "text": "Provável reenvio.", "evidenceIds": ["rej-1"]},
        {"kind": "action", "text": "Consultar a situação pela chave.", "evidenceIds": ["rej-1"]}]


def test_success_maps_sections_usage_and_sends_key_only_in_authorization_header() -> None:
    transport = FakeTransport(HttpResponse(200, completion(GOOD)))
    answer = client(transport).advise(prompt(), deadline_seconds=3.0)
    assert [s.kind for s in answer.sections] == [SectionKind.HYPOTHESIS, SectionKind.ACTION]
    assert answer.provider_id == "gemini" and answer.usage.input_tokens == 100
    url, headers, body, timeout = transport.calls[0]
    assert url == "https://api.example.test/v1/chat/completions" and timeout == 3.0
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET.encode() not in body
    sent = json.loads(body)
    assert sent["temperature"] == 0 and sent["response_format"] == {"type": "json_object"}


def test_outgoing_prompt_is_redacted_and_data_is_fenced() -> None:
    transport = FakeTransport(HttpResponse(200, completion(GOOD)))
    client(transport).advise(prompt(), deadline_seconds=3.0)
    body = transport.calls[0][2].decode()
    assert "11.222.333/0001-81" not in body
    assert "NÃO CONFIÁVEIS" in body and "Responda SOMENTE" in body


@pytest.mark.parametrize(("status", "error"), [
    (401, ModelProviderDenied), (403, ModelProviderDenied), (429, ModelProviderRateLimited),
    (500, ModelProviderUnavailable), (503, ModelProviderUnavailable), (404, ModelProviderMalformed),
])
def test_http_status_maps_to_typed_errors_without_leaking_body(status: int, error: type) -> None:
    transport = FakeTransport(HttpResponse(status, SECRET.encode()))
    with pytest.raises(error) as caught:
        client(transport).advise(prompt(), deadline_seconds=1.0)
    assert SECRET not in str(caught.value)


def test_transport_failures_and_missing_key() -> None:
    with pytest.raises(ModelProviderUnavailable):
        client(FakeTransport(TimeoutError("t"))).advise(prompt(), deadline_seconds=1.0)
    with pytest.raises(ModelProviderUnavailable):
        client(FakeTransport(ConnectionError("c"))).advise(prompt(), deadline_seconds=1.0)
    transport = FakeTransport()
    with pytest.raises(ModelProviderDenied):
        client(transport, key=None).advise(prompt(), deadline_seconds=1.0)
    assert not transport.calls  # no request without a key


@pytest.mark.parametrize("raw", [
    b"not json", b"{}", b'{"choices":[]}',
    completion([{"kind": "fact", "text": "x", "evidenceIds": []}]),
    completion([{"kind": "source", "text": "x", "evidenceIds": []}]),
    completion([{"kind": "hypothesis", "text": 5, "evidenceIds": []}]),
    completion([{"kind": "hypothesis", "text": "x", "evidenceIds": [1]}]),
    completion("nao-lista"),
    completion([{"kind": "hypothesis", "text": "x", "evidenceIds": []}] * 13),
    b"x" * (64 * 1024 + 1),
])
def test_malformed_or_overreaching_responses_are_rejected(raw: bytes) -> None:
    with pytest.raises(ModelProviderMalformed):
        client(FakeTransport(HttpResponse(200, raw))).advise(prompt(), deadline_seconds=1.0)


def test_config_requires_https_and_rejects_embedded_credentials() -> None:
    for url in ("http://api.example.test/v1", "https://u:p@api.example.test/v1",
                "https://api.example.test/v1?key=abc", "ftp://x"):
        with pytest.raises(ValueError):
            OpenAICompatibleConfig("p", url, "m")
    OpenAICompatibleConfig("p", "http://127.0.0.1:9/v1", "m", allow_insecure_loopback=True)


def test_fallback_uses_secondary_when_primary_fails_and_reports_last_error() -> None:
    primary = client(FakeTransport(HttpResponse(503, b"")), provider="gemini")
    secondary = client(FakeTransport(HttpResponse(200, completion(GOOD))), provider="openai")
    answer = FallbackAdvisoryClient([primary, secondary]).advise(prompt(), deadline_seconds=3.0)
    assert answer.provider_id == "openai"
    both = FallbackAdvisoryClient([
        client(FakeTransport(HttpResponse(401, b""))),
        client(FakeTransport(HttpResponse(429, b""))),
    ])
    with pytest.raises(ModelProviderRateLimited):
        both.advise(prompt(), deadline_seconds=3.0)


def test_fallback_respects_the_total_deadline() -> None:
    clock = iter([0.0, 0.0, 10.0, 10.0])
    skipped = FakeTransport(HttpResponse(200, completion(GOOD)))
    chain = FallbackAdvisoryClient(
        [client(FakeTransport(HttpResponse(503, b""))), client(skipped)],
        monotonic=lambda: next(clock),
    )
    with pytest.raises(ModelProviderUnavailable):
        chain.advise(prompt(), deadline_seconds=2.0)
    assert not skipped.calls


def test_environment_builder_skips_invalid_slots_and_reads_key_lazily() -> None:
    assert build_model_from_environ({}) is None
    env = {
        "NFCORE_COGNITIVE_AI_PRIMARY_BASE_URL": "http://insecure.test/v1",
        "NFCORE_COGNITIVE_AI_PRIMARY_MODEL": "m",
    }
    assert build_model_from_environ(env) is None  # insecure primary is skipped
    env.update({
        "NFCORE_COGNITIVE_AI_SECONDARY_BASE_URL": "https://api.example.test/v1",
        "NFCORE_COGNITIVE_AI_SECONDARY_MODEL": "m2",
        "NFCORE_COGNITIVE_AI_SECONDARY_PROVIDER": "openai",
    })
    transport = FakeTransport(HttpResponse(200, completion(GOOD)))
    model = build_model_from_environ(env, transport=transport)
    assert model is not None
    with pytest.raises(ModelProviderDenied):  # key not injected yet
        model.advise(prompt(), deadline_seconds=1.0)
    env["NFCORE_COGNITIVE_AI_SECONDARY_API_KEY"] = SECRET
    assert model.advise(prompt(), deadline_seconds=1.0).provider_id == "openai"


def test_service_end_to_end_guard_blocks_hostile_model_and_audit_has_no_text(caplog) -> None:  # type: ignore[no-untyped-def]
    import logging

    from kordena_fiscal.cognitive import (
        AdviceStatus,
        CognitiveAdviceService,
        default_baselines,
    )
    from kordena_fiscal.cognitive.adapters.logging_audit import LoggingAuditSink

    hostile = [{"kind": "hypothesis", "text": "Eu cancelei a nota automaticamente.",
                "evidenceIds": ["rej-1"]}]
    model = client(FakeTransport(HttpResponse(200, completion(hostile))))
    service = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=LoggingAuditSink(),
        deadline_seconds=2.0,
    )
    with caplog.at_level(logging.INFO, logger="nfcore.cognitive.audit"):
        result = service.advise(make_request())
    assert result.status is not AdviceStatus.DENIED and result.advisory_only
    assert all("cancelei" not in s.text for s in result.sections)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "model_call" in logged or "outcome" in logged
    assert "cancelei" not in logged and "Duplicidade" not in logged and SECRET not in logged


def test_composition_enables_ai_only_when_a_provider_is_configured() -> None:
    from kordena_fiscal.cognitive import composition
    from kordena_fiscal.security.human_identity import HumanIdentityService

    class Reader:
        def surface(self, **kwargs):  # type: ignore[no-untyped-def]
            return ()

    identity = object.__new__(HumanIdentityService)
    base = {"NFCORE_COGNITIVE_ENABLED": "true"}
    with_ai = {**base, "NFCORE_COGNITIVE_AI_PRIMARY_BASE_URL": "https://api.example.test/v1",
               "NFCORE_COGNITIVE_AI_PRIMARY_MODEL": "m"}
    assert composition.build_cognitive_router(identity, Reader(), base) is not None  # type: ignore[arg-type]
    assert composition.build_cognitive_router(identity, Reader(), with_ai) is not None  # type: ignore[arg-type]
