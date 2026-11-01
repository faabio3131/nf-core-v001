"""Plan entitlement, quota and usage ledger for the cognitive capability.

Mechanism only: no prices, no plan numbers and no persistence are decided here. Limits come
from configuration approved by the owner. The in-memory ledger is process-local and the
quota is a *soft* limit bounded by the bulkhead; a hard, cross-process limit needs an atomic
reservation in the canonical store, which requires a reviewed migration (out of scope).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .contracts import Capability
from .ports import EntitlementDecision, PlanResolverPort, UsageRecord


@dataclass(frozen=True, slots=True)
class CapabilityQuota:
    max_requests: int
    window_seconds: int
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_requests < 0 or self.window_seconds < 1:
            raise ValueError("invalid quota")
        if self.max_tokens is not None and self.max_tokens < 0:
            raise ValueError("invalid token quota")


@dataclass(frozen=True, slots=True)
class PlanPolicy:
    plan_id: str
    quotas: Mapping[Capability, CapabilityQuota]


@dataclass(slots=True)
class _Bucket:
    requests: int = 0
    tokens: int = 0
    cost_micro_brl: int = 0


class InMemoryUsageLedger:
    """Idempotent by ``request_id``; counts model calls in fixed windows."""

    def __init__(
        self,
        *,
        windows: tuple[int, ...] = (60, 3600, 86400),
        clock: Callable[[], float] = time.time,
        max_dedupe: int = 100_000,
    ) -> None:
        if not windows or any(w < 1 for w in windows):
            raise ValueError("windows must be positive seconds")
        self.windows = tuple(sorted(set(windows)))
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._max_dedupe = max_dedupe
        self._buckets: dict[tuple[str, str, Capability, int, int], _Bucket] = {}

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            if record.request_id in self._seen:
                return
            self._seen[record.request_id] = None
            while len(self._seen) > self._max_dedupe:
                self._seen.popitem(last=False)
            now = self._clock()
            for window in self.windows:
                index = int(now // window)
                for old in [k for k in self._buckets if k[3] == window and k[4] < index - 1]:
                    del self._buckets[old]
                key = (record.tenant_id, record.unit_id, record.capability, window, index)
                bucket = self._buckets.setdefault(key, _Bucket())
                bucket.requests += 1
                bucket.tokens += record.usage.input_tokens + record.usage.output_tokens
                bucket.cost_micro_brl += record.usage.cost_micro_brl or 0

    def _current(
        self, tenant_id: str, unit_id: str, capability: Capability, window_seconds: int
    ) -> _Bucket | None:
        if window_seconds not in self.windows:
            raise ValueError(f"window {window_seconds}s is not tracked by this ledger")
        index = int(self._clock() // window_seconds)
        with self._lock:
            return self._buckets.get((tenant_id, unit_id, capability, window_seconds, index))

    def used(
        self, *, tenant_id: str, unit_id: str, capability: Capability, window_seconds: int
    ) -> tuple[int, int]:
        bucket = self._current(tenant_id, unit_id, capability, window_seconds)
        return (bucket.requests, bucket.tokens) if bucket else (0, 0)

    def cost_micro_brl(
        self, *, tenant_id: str, unit_id: str, capability: Capability, window_seconds: int
    ) -> int:
        bucket = self._current(tenant_id, unit_id, capability, window_seconds)
        return bucket.cost_micro_brl if bucket else 0


class PolicyEntitlement:
    """Denies only the AI. Unknown plan, capability outside the plan or exhausted quota deny."""

    def __init__(
        self,
        *,
        plans: PlanResolverPort,
        policies: Mapping[str, PlanPolicy],
        ledger: InMemoryUsageLedger,
    ) -> None:
        self._plans = plans
        self._policies = dict(policies)
        self._ledger = ledger
        for policy in self._policies.values():
            for quota in policy.quotas.values():
                if quota.window_seconds not in ledger.windows:
                    raise ValueError(
                        f"plan {policy.plan_id} uses a window the ledger does not track"
                    )

    def check(
        self, *, tenant_id: str, unit_id: str, capability: Capability
    ) -> EntitlementDecision:
        plan_id = self._plans.plan_for(tenant_id=tenant_id, unit_id=unit_id)
        if plan_id is None or plan_id not in self._policies:
            return EntitlementDecision(False, "plan_unknown")
        quota = self._policies[plan_id].quotas.get(capability)
        if quota is None:
            return EntitlementDecision(False, "capability_not_in_plan")
        requests, tokens = self._ledger.used(
            tenant_id=tenant_id,
            unit_id=unit_id,
            capability=capability,
            window_seconds=quota.window_seconds,
        )
        if requests >= quota.max_requests:
            return EntitlementDecision(False, "quota_requests_exhausted")
        if quota.max_tokens is not None and tokens >= quota.max_tokens:
            return EntitlementDecision(False, "quota_tokens_exhausted")
        return EntitlementDecision(True)


class StaticPlanResolver:
    """Maps every tenant to one plan (pilot). Replace with the commercial authority later."""

    def __init__(self, plan_id: str) -> None:
        self._plan_id = plan_id

    def plan_for(self, *, tenant_id: str, unit_id: str) -> str | None:
        return self._plan_id


PILOT_PLAN_ID = "pilot"
DEFAULT_PILOT_DAILY_LIMIT = 100


def pilot_entitlement(
    ledger: InMemoryUsageLedger, *, daily_limit: int = DEFAULT_PILOT_DAILY_LIMIT
) -> PolicyEntitlement:
    """Conservative per-tenant/unit daily cap on model calls, protecting AI spend."""
    quota = CapabilityQuota(max_requests=daily_limit, window_seconds=86400)
    policy = PlanPolicy(PILOT_PLAN_ID, {capability: quota for capability in Capability})
    return PolicyEntitlement(
        plans=StaticPlanResolver(PILOT_PLAN_ID), policies={PILOT_PLAN_ID: policy}, ledger=ledger
    )
