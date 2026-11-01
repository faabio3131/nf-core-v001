from __future__ import annotations

import threading

import pytest

from kordena_fiscal.cognitive import AdviceStatus, Capability, ModelUsage, default_baselines
from kordena_fiscal.cognitive.governance import (
    CapabilityQuota,
    InMemoryUsageLedger,
    PlanPolicy,
    PolicyEntitlement,
)
from kordena_fiscal.cognitive.metrics import ObservabilityAdviceMetrics
from kordena_fiscal.cognitive.ports import UsageRecord
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.observability.metrics import InMemoryMetricSink, MetricRecorder

from .conftest import TENANT, UNIT, ScriptedModel, good_sections, make_request


def usage_record(request_id: str, tokens: int = 100, tenant: str = TENANT) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        tenant_id=tenant,
        unit_id=UNIT,
        actor_id="a",
        capability=Capability.EXPLAIN_REJECTION,
        provider_id="p",
        model="m",
        model_version="1",
        usage=ModelUsage(input_tokens=tokens, output_tokens=0, cost_micro_brl=10),
        outcome="advised",
    )


class Plans:
    def __init__(self, mapping: dict[str, str | None]) -> None:
        self.mapping = mapping

    def plan_for(self, *, tenant_id: str, unit_id: str) -> str | None:
        return self.mapping.get(tenant_id)


def entitlement(ledger, plans, quota):  # type: ignore[no-untyped-def]
    policy = PlanPolicy("pro", {Capability.EXPLAIN_REJECTION: quota})
    return PolicyEntitlement(plans=plans, policies={"pro": policy}, ledger=ledger)


def test_ledger_is_idempotent_and_thread_safe() -> None:
    ledger = InMemoryUsageLedger(clock=lambda: 1000.0)
    threads = [
        threading.Thread(target=ledger.record, args=(usage_record("same"),)) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    kwargs = {"tenant_id": TENANT, "unit_id": UNIT, "capability": Capability.EXPLAIN_REJECTION}
    assert ledger.used(window_seconds=60, **kwargs) == (1, 100)
    assert ledger.cost_micro_brl(window_seconds=60, **kwargs) == 10


def test_window_rolls_over() -> None:
    now = [0.0]
    ledger = InMemoryUsageLedger(clock=lambda: now[0])
    ledger.record(usage_record("r1"))
    kwargs = {"tenant_id": TENANT, "unit_id": UNIT, "capability": Capability.EXPLAIN_REJECTION}
    assert ledger.used(window_seconds=60, **kwargs)[0] == 1
    now[0] = 61
    assert ledger.used(window_seconds=60, **kwargs)[0] == 0
    assert ledger.used(window_seconds=3600, **kwargs)[0] == 1


def test_quota_isolated_per_tenant_and_denies_when_exhausted() -> None:
    ledger = InMemoryUsageLedger(clock=lambda: 10.0)
    ent = entitlement(ledger, Plans({TENANT: "pro", "other": "pro"}),
                      CapabilityQuota(max_requests=2, window_seconds=60))
    def ask(tenant: str):  # type: ignore[no-untyped-def]
        return ent.check(
            tenant_id=tenant, unit_id=UNIT, capability=Capability.EXPLAIN_REJECTION
        )

    assert ask(TENANT).allowed
    ledger.record(usage_record("a"))
    ledger.record(usage_record("b"))
    denied = ask(TENANT)
    assert not denied.allowed and denied.reason == "quota_requests_exhausted"
    assert ask("other").allowed  # another tenant is unaffected


def test_token_quota_plan_unknown_and_capability_outside_plan() -> None:
    ledger = InMemoryUsageLedger(clock=lambda: 10.0)
    ent = entitlement(ledger, Plans({TENANT: "pro", "ghost": None}),
                      CapabilityQuota(max_requests=100, window_seconds=60, max_tokens=150))
    ledger.record(usage_record("a", tokens=200))
    def reason(tenant: str, capability: Capability) -> str:
        return ent.check(tenant_id=tenant, unit_id=UNIT, capability=capability).reason

    assert reason(TENANT, Capability.EXPLAIN_REJECTION) == "quota_tokens_exhausted"
    assert reason("ghost", Capability.EXPLAIN_REJECTION) == "plan_unknown"
    assert reason(TENANT, Capability.SUGGEST_CLASSIFICATION) == "capability_not_in_plan"


def test_policy_must_use_windows_the_ledger_tracks() -> None:
    ledger = InMemoryUsageLedger(windows=(60,))
    with pytest.raises(ValueError):
        entitlement(ledger, Plans({}), CapabilityQuota(max_requests=1, window_seconds=999))


def test_service_serves_baseline_when_quota_is_exhausted(build_service) -> None:  # type: ignore[no-untyped-def]
    ledger = InMemoryUsageLedger()
    ent = entitlement(ledger, Plans({TENANT: "pro"}),
                      CapabilityQuota(max_requests=1, window_seconds=60))
    model = ScriptedModel(sections=good_sections())
    service = build_service(model, entitlements=ent, ledger=ledger)
    first = service.advise(make_request(request_id="q1"))
    second = service.advise(make_request(request_id="q2"))
    assert first.status is AdviceStatus.ADVISED
    assert second.status is AdviceStatus.BASELINE_ONLY
    assert second.provenance.degraded_reason == "entitlement_denied"
    assert len(second.sections) == 5 and model.calls == 1


def metrics_scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id=TENANT, unit_id=UNIT, environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-1", host_namespace="nfcore",
    )


def test_metrics_publish_counts_tokens_cost_and_latency_without_payload(build_service) -> None:  # type: ignore[no-untyped-def]
    sink = InMemoryMetricSink()
    metrics = ObservabilityAdviceMetrics(MetricRecorder(sink=sink))
    service = build_service(ScriptedModel(sections=good_sections()), metrics=metrics)
    service.advise(make_request(scope=metrics_scope(), question="senha=hunter2x"))
    names = {p.definition.name for p in sink.points}
    assert names == {
        "cognitive.advice.total",
        "cognitive.model.tokens.total",
        "cognitive.model.cost_micro_brl.total",
        "cognitive.advice.duration_seconds",
    }
    assert "hunter2x" not in repr(sink.points)
    total = next(p for p in sink.points if p.definition.name == "cognitive.advice.total")
    assert total.labels["status"] == "advised" and total.labels["tenant_id"] == TENANT


def test_degradation_is_counted_and_metrics_failure_never_breaks_advice(build_service) -> None:  # type: ignore[no-untyped-def]
    sink = InMemoryMetricSink()
    metrics = ObservabilityAdviceMetrics(MetricRecorder(sink=sink))
    build_service(None, metrics=metrics).advise(make_request(scope=metrics_scope()))
    degraded = [p for p in sink.points if p.definition.name == "cognitive.degraded.total"]
    assert degraded and degraded[0].labels["reason_code"] == "ai_disabled"

    class Exploding:
        def observe(self, sample):  # type: ignore[no-untyped-def]
            raise RuntimeError("metrics backend down")

    result = build_service(None, metrics=Exploding()).advise(make_request())
    assert result.status is AdviceStatus.BASELINE_ONLY


def test_scope_without_host_namespace_skips_metrics_silently(build_service) -> None:  # type: ignore[no-untyped-def]
    sink = InMemoryMetricSink()
    metrics = ObservabilityAdviceMetrics(MetricRecorder(sink=sink))
    build_service(None, metrics=metrics).advise(make_request())  # default scope has no namespace
    assert sink.points == ()


def test_default_baselines_cover_every_capability() -> None:
    assert set(default_baselines()) == set(Capability)
