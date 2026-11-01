"""Ports of the cognitive core. Adapters live outside the domain logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kordena_fiscal.domain import ExecutionScope

from .contracts import AdviceSection, Capability, ModelUsage, SectionKind


class ModelProviderError(Exception):
    """Base failure of a model provider. Always degrades to the deterministic baseline."""

    reason = "provider_error"


class ModelProviderUnavailable(ModelProviderError):
    reason = "provider_unavailable"


class ModelProviderRateLimited(ModelProviderError):
    reason = "provider_rate_limited"


class ModelProviderDenied(ModelProviderError):
    reason = "provider_denied"


class ModelProviderMalformed(ModelProviderError):
    reason = "provider_malformed"


@dataclass(frozen=True, slots=True)
class ModelPrompt:
    """What the provider receives. ``system`` is fixed text; data is fenced and untrusted."""

    capability: Capability
    system: str
    trusted_facts: str
    untrusted_data: str
    boundary: str
    context_hash: str
    tenant_id: str
    unit_id: str
    request_id: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ProviderSection:
    kind: SectionKind
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderAnswer:
    sections: tuple[ProviderSection, ...]
    provider_id: str
    model: str
    model_version: str
    usage: ModelUsage = ModelUsage()


class AdvisoryModelPort(Protocol):
    def advise(self, prompt: ModelPrompt, *, deadline_seconds: float) -> ProviderAnswer:
        """Return structured sections or raise a ``ModelProviderError`` subclass."""


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    reason: str = ""


class EntitlementPort(Protocol):
    def check(self, *, tenant_id: str, unit_id: str, capability: Capability) -> EntitlementDecision:
        """Plan/quota decision. Denial affects the AI only, never fiscal operations."""


@dataclass(frozen=True, slots=True)
class UsageRecord:
    request_id: str
    tenant_id: str
    unit_id: str
    actor_id: str
    capability: Capability
    provider_id: str
    model: str
    model_version: str
    usage: ModelUsage
    outcome: str


class UsageLedgerPort(Protocol):
    def record(self, record: UsageRecord) -> None:
        """Idempotent by ``request_id``. A second call with the same id must not double count."""


@dataclass(frozen=True, slots=True)
class AdviceAuditEvent:
    event: str
    request_id: str
    correlation_id: str
    tenant_id: str
    unit_id: str
    actor_id: str
    capability: Capability
    context_hash: str
    outcome: str
    detail: str = ""


class AuditSinkPort(Protocol):
    def emit(self, event: AdviceAuditEvent) -> None:
        """Never receives prompt text, answers, secrets or personal data: ids and hashes only."""


def section_from_provider(section: ProviderSection) -> AdviceSection:
    return AdviceSection(kind=section.kind, text=section.text, evidence_ids=section.evidence_ids)


@dataclass(frozen=True, slots=True)
class AdviceMetricsSample:
    scope: ExecutionScope
    capability: Capability
    status: str
    degraded_reason: str | None
    latency_ms: int
    usage: ModelUsage


class AdviceMetricsPort(Protocol):
    def observe(self, sample: AdviceMetricsSample) -> None:
        """Best-effort. Never receives prompt text, answers, secrets or personal data."""


class PlanResolverPort(Protocol):
    def plan_for(self, *, tenant_id: str, unit_id: str) -> str | None:
        """Plan id from the canonical commercial authority, or None when unknown."""
