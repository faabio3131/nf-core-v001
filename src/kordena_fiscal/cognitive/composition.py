"""Composition of the cognitive advisory route for the runtime. Disabled unless explicitly on.

With no central FM model configured the route serves only the deterministic baseline
(``aiEnabled: false``): useful, free of AI cost and requiring no credential. Connecting the
central model is a separate, owner-authorized configuration step (Vault Secret Reference).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from fastapi import APIRouter

from kordena_fiscal.security.human_identity import HumanIdentityService

from .adapters.control_plane_audit import ControlPlaneAuditSink
from .adapters.logging_audit import LoggingAuditSink
from .adapters.openai_compatible import build_model_from_environ
from .api import create_cognitive_router
from .command_api import create_command_metrics_router
from .governance import DEFAULT_PILOT_DAILY_LIMIT, InMemoryUsageLedger, pilot_entitlement
from .knowledge.official import OfficialTablesError, cached_official_catalog
from .portal_evidence import PortalSurfaceEvidenceProvider, SurfaceReader
from .durable_usage import DurableTokenQuotaStore
from .quota_model import QuotaGovernedAdvisoryClient
from .ports import AuditSinkPort
from .registry import default_baselines
from .service import CognitiveAdviceService
from .usage_aggregates import CognitiveUsageAggregates

ENABLE_FLAG = "NFCORE_COGNITIVE_ENABLED"


def _daily_limit(environ: Mapping[str, str]) -> int:
    try:
        value = int(environ.get("NFCORE_COGNITIVE_AI_DAILY_LIMIT", ""))
    except ValueError:
        return DEFAULT_PILOT_DAILY_LIMIT
    return value if value >= 0 else DEFAULT_PILOT_DAILY_LIMIT


def build_cognitive_routers(
    identity: HumanIdentityService | None,
    portal_executor: SurfaceReader | None,
    environ: Mapping[str, str],
    *,
    audit_uow_factory: Callable[[], AbstractContextManager[Any]] | None = None,
    runtime_environment: str | None = None,
    quota_store: DurableTokenQuotaStore | None = None,
) -> list[APIRouter]:
    """Portal advisory route plus the Command metrics route; empty unless explicitly enabled.

    With a model configured, durable audit (control-plane ledger) is mandatory in the sense of
    the service rule "no audit, no model"; the log sink is only the non-durable dev fallback.
    """
    if environ.get(ENABLE_FLAG, "").strip().lower() != "true":
        return []
    if identity is None or portal_executor is None:
        return []
    try:
        catalog = cached_official_catalog()
    except OfficialTablesError:
        # Fail-open: without the official tables the advice says "não verificado".
        catalog = None
    # Production model use requires an independent opt-in, canonical subscription
    # quota storage and durable audit. A mere API key or ENABLE_FLAG is insufficient.
    allow_pilot_model = runtime_environment in {"development", "test"}
    allow_paid_model = (
        runtime_environment in {"staging", "production"}
        and environ.get("NFCORE_COGNITIVE_DURABLE_AI_ENABLED", "").lower() == "true"
        and quota_store is not None
        and audit_uow_factory is not None
    )
    model = (
        build_model_from_environ(environ)
        if (allow_pilot_model or allow_paid_model)
        else None
    )
    audit: AuditSinkPort | None = None
    entitlements = None
    ledger = None
    if model is not None:
        if allow_paid_model:
            assert quota_store is not None
            model = QuotaGovernedAdvisoryClient(model, quota_store)
            assert audit_uow_factory is not None
            audit = ControlPlaneAuditSink(audit_uow_factory)
        else:
            audit = (
                ControlPlaneAuditSink(audit_uow_factory)
                if audit_uow_factory is not None
                else LoggingAuditSink()
            )
            ledger = InMemoryUsageLedger()
            entitlements = pilot_entitlement(ledger, daily_limit=_daily_limit(environ))
    aggregates = CognitiveUsageAggregates()
    service = CognitiveAdviceService(
        baselines=default_baselines(classification_catalog=catalog),
        model=model,
        audit=audit,
        entitlements=entitlements,
        ledger=ledger,
        metrics=aggregates,
    )
    return [
        create_cognitive_router(
            identity,
            service,
            PortalSurfaceEvidenceProvider(portal_executor),
            ai_enabled=model is not None,
        ),
        create_command_metrics_router(aggregates, environ, ai_enabled=model is not None),
    ]


def build_cognitive_router(
    identity: HumanIdentityService | None,
    portal_executor: SurfaceReader | None,
    environ: Mapping[str, str],
    *,
    audit_uow_factory: Callable[[], AbstractContextManager[Any]] | None = None,
    runtime_environment: str | None = None,
    quota_store: DurableTokenQuotaStore | None = None,
) -> APIRouter | None:
    """One router mounting the Portal advisory route and the Command metrics route."""
    routers = build_cognitive_routers(
        identity, portal_executor, environ,
        audit_uow_factory=audit_uow_factory,
        runtime_environment=runtime_environment,
        quota_store=quota_store,
    )
    if not routers:
        return None
    combined = APIRouter()
    for router in routers:
        combined.include_router(router)
    return combined
