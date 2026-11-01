from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.cognitive import AdviceStatus, CognitiveAdviceService, default_baselines
from kordena_fiscal.cognitive.adapters.control_plane_audit import ControlPlaneAuditSink
from kordena_fiscal.cognitive.adapters.openai_compatible import OpenAICompatibleConfig
from kordena_fiscal.cognitive.command_api import TOKEN_ENV, create_command_metrics_router
from kordena_fiscal.cognitive.governance import (
    InMemoryUsageLedger,
    pilot_entitlement,
)
from kordena_fiscal.cognitive.ports import AdviceAuditEvent
from kordena_fiscal.cognitive.usage_aggregates import CognitiveUsageAggregates
from kordena_fiscal.control_plane.models import (
    ControlPlaneAuditAction,
    FiscalOrganization,
    FiscalUnitRegistration,
)
from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.persistence import SqliteFiscalDatabase

from .conftest import ScriptedModel, good_sections, make_request
from .test_openai_compatible import SECRET

TOKEN = "t" * 40


@pytest.fixture
def database(tmp_path: Path) -> SqliteFiscalDatabase:
    db = SqliteFiscalDatabase(tmp_path / "cog.sqlite3")
    db.initialize()
    with db() as uow:
        uow.control_plane.add_organization(
            FiscalOrganization(tenant_id="tenant-a", legal_name="Synthetic")
        )
        uow.control_plane.add_unit(
            FiscalUnitRegistration(
                tenant_id="tenant-a", unit_id="unit-a", display_name="u",
                enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
            )
        )
        uow.commit()
    return db


def event(outcome: str = "started") -> AdviceAuditEvent:
    from kordena_fiscal.cognitive import Capability

    return AdviceAuditEvent(
        event="advice", request_id="req-1", correlation_id="corr-1", tenant_id="tenant-a",
        unit_id="unit-a", actor_id="actor-1", capability=Capability.EXPLAIN_REJECTION,
        context_hash="a" * 64, outcome=outcome, detail="PROMPT TEXT MUST NOT BE STORED",
    )


def test_audit_is_durable_idempotent_and_content_free(database) -> None:  # type: ignore[no-untyped-def]
    sink = ControlPlaneAuditSink(database)
    sink.emit(event())
    sink.emit(event())  # retry of the same request/event: no duplicate, no error
    sink.emit(event("completed"))
    with database() as uow:
        rows = [e for e in uow.control_plane.list_audit("tenant-a")
                if e.action is ControlPlaneAuditAction.COGNITIVE_ADVICE_RECORDED]
    assert len(rows) == 2
    joined = " ".join(f"{r.target_type} {r.target_id} {r.actor_id}" for r in rows)
    assert "PROMPT" not in joined and "req-1|cognitive.explain_rejection" in joined
    assert all(r.tenant_id == "tenant-a" and r.unit_id == "unit-a" for r in rows)


def test_unavailable_ledger_means_no_model_but_baseline_still_served(database) -> None:  # type: ignore[no-untyped-def]
    def broken():  # type: ignore[no-untyped-def]
        raise ConnectionError("db down")

    model = ScriptedModel(sections=good_sections())
    service = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=ControlPlaneAuditSink(broken),
        deadline_seconds=2.0,
    )
    result = service.advise(make_request())
    assert model.calls == 0
    assert result.status is AdviceStatus.BASELINE_ONLY
    assert result.provenance.degraded_reason == "audit_unavailable"


def test_end_to_end_with_durable_audit_and_aggregates(database) -> None:  # type: ignore[no-untyped-def]
    aggregates = CognitiveUsageAggregates()
    service = CognitiveAdviceService(
        baselines=default_baselines(), model=ScriptedModel(sections=good_sections()),
        audit=ControlPlaneAuditSink(database), metrics=aggregates, deadline_seconds=2.0,
    )
    result = service.advise(make_request())
    assert result.status is AdviceStatus.ADVISED
    snap = aggregates.snapshot()
    assert snap["requests"]["total"] == 1 and snap["model"]["calls"] == 1
    assert snap["model"]["costReportedCalls"] == 1 and snap["model"]["costMicroBrl"] == 1500
    with database() as uow:
        assert any(e.action is ControlPlaneAuditAction.COGNITIVE_ADVICE_RECORDED
                   for e in uow.control_plane.list_audit("tenant-a"))


def test_aggregates_never_turn_absent_cost_into_zero_and_bound_tenants() -> None:
    from kordena_fiscal.cognitive import Capability, ModelUsage
    from kordena_fiscal.cognitive.ports import AdviceMetricsSample
    from kordena_fiscal.cognitive.usage_aggregates import MAX_TENANTS, OVERFLOW_TENANT

    from .conftest import make_scope

    aggregates = CognitiveUsageAggregates()
    for i in range(MAX_TENANTS + 5):
        aggregates.observe(AdviceMetricsSample(
            scope=make_scope(f"tenant-{i}"), capability=Capability.EXPLAIN_REJECTION,
            status="baseline_only", degraded_reason="ai_disabled", latency_ms=5,
            usage=ModelUsage(),
        ))
    snap = aggregates.snapshot()
    assert snap["model"]["costMicroBrl"] is None and snap["model"]["calls"] == 0
    assert len(snap["tenants"]) == MAX_TENANTS + 1
    assert snap["tenants"][OVERFLOW_TENANT]["requests"] == 5


def command_client(aggregates: CognitiveUsageAggregates, **env: str) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_command_metrics_router(aggregates, env, ai_enabled=False,
                                      clock=lambda: datetime(2026, 11, 2, tzinfo=UTC))
    )
    return TestClient(app)


def auth(token: str = TOKEN, correlation: str | None = "corr-9") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if correlation:
        headers["X-Correlation-Id"] = correlation
    return headers


def test_command_metrics_envelope_and_security() -> None:
    aggregates = CognitiveUsageAggregates()
    client = command_client(aggregates, **{TOKEN_ENV: TOKEN})
    ok = client.get("/v1/command/cognitive/metrics", headers=auth())
    assert ok.status_code == 200 and ok.headers["cache-control"].startswith("no-store")
    body = ok.json()
    assert body["productId"] == "nfcore" and body["schemaVersion"] == "nfcore.cognitive.metrics/v1"
    assert body["correlationId"] == "corr-9" and body["freshness"]["scope"] == "process"
    assert body["facts"]["requests"]["total"] == 0
    assert body["facts"]["model"]["costMicroBrl"] is None
    dumped = json.dumps(body)
    assert TOKEN not in dumped
    assert SECRET not in dumped
    assert client.get("/v1/command/cognitive/metrics", headers=auth("x" * 40)).status_code == 401
    assert client.get("/v1/command/cognitive/metrics").status_code == 401
    missing = client.get("/v1/command/cognitive/metrics", headers=auth(correlation=None))
    assert missing.status_code == 400


def test_command_metrics_fail_closed_without_a_strong_token() -> None:
    for env in ({}, {TOKEN_ENV: "short"}):
        client = command_client(CognitiveUsageAggregates(), **env)
        assert client.get("/v1/command/cognitive/metrics", headers=auth("short")).status_code == 503


def test_pilot_quota_denies_only_the_ai_after_the_daily_limit() -> None:
    ledger = InMemoryUsageLedger()
    service = CognitiveAdviceService(
        baselines=default_baselines(), model=ScriptedModel(sections=good_sections()),
        entitlements=pilot_entitlement(ledger, daily_limit=1), ledger=ledger,
        audit=ControlPlaneAuditSinkStub(), deadline_seconds=2.0,
    )
    first = service.advise(make_request(request_id="r1"))
    second = service.advise(make_request(request_id="r2"))
    assert first.status is AdviceStatus.ADVISED
    assert second.status is AdviceStatus.BASELINE_ONLY  # operation continues without AI
    assert second.provenance.degraded_reason == "entitlement_denied"
    assert second.sections  # deterministic answer still delivered


class ControlPlaneAuditSinkStub:
    def emit(self, event: AdviceAuditEvent) -> None:
        return None


def test_composition_mounts_both_routes_only_when_enabled(database) -> None:  # type: ignore[no-untyped-def]
    from kordena_fiscal.cognitive.composition import build_cognitive_router

    class Reader:
        def surface(self, **kwargs):  # type: ignore[no-untyped-def]
            return ()

    identity = object.__new__(__import__(
        "kordena_fiscal.security.human_identity", fromlist=["HumanIdentityService"]
    ).HumanIdentityService)
    assert build_cognitive_router(identity, Reader(), {}) is None  # type: ignore[arg-type]
    env = {"NFCORE_COGNITIVE_ENABLED": "true", TOKEN_ENV: TOKEN}
    router = build_cognitive_router(identity, Reader(), env, audit_uow_factory=database)  # type: ignore[arg-type]
    assert router is not None
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])
    assert "/v1/portal/cognitive/advise" in paths
    assert "/v1/command/cognitive/metrics" in paths
    OpenAICompatibleConfig("p", "https://api.example.test/v1", "m")  # config import sanity
