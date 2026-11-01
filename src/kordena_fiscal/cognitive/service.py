"""CognitiveAdviceService: orchestrates the advisory flow and never raises for AI failures."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from .baseline import BASELINE_VERSION, Baseline, BaselineFn, insufficient
from .context import ContextPackBuilder, ScopeViolationError
from .contracts import (
    SCHEMA_VERSION,
    AdviceRequest,
    AdviceResult,
    AdviceSection,
    AdviceStatus,
    Capability,
    Evidence,
    ModelUsage,
    Provenance,
    SectionKind,
    stable_hash,
)
from .guardrails import OutputGuard
from .ports import (
    AdviceAuditEvent,
    AdviceMetricsPort,
    AdviceMetricsSample,
    AdvisoryModelPort,
    AuditSinkPort,
    EntitlementPort,
    ModelPrompt,
    ModelProviderError,
    UsageLedgerPort,
    UsageRecord,
)
from .redaction import Redactor
from .resilience import (
    Bulkhead,
    BulkheadFull,
    CircuitBreaker,
    CircuitOpen,
    DeadlineExceeded,
    call_with_deadline,
)

_DENIED_CONTEXT = stable_hash({"denied": True})


@dataclass(frozen=True, slots=True)
class _ModelOutcome:
    sections: tuple[AdviceSection, ...] = ()
    findings: tuple[str, ...] = ()
    degraded_reason: str | None = None
    provider_id: str | None = None
    model: str | None = None
    model_version: str | None = None
    usage: ModelUsage = ModelUsage()


class CognitiveAdviceService:
    def __init__(
        self,
        *,
        baselines: Mapping[Capability, BaselineFn],
        model: AdvisoryModelPort | None = None,
        entitlements: EntitlementPort | None = None,
        ledger: UsageLedgerPort | None = None,
        audit: AuditSinkPort | None = None,
        metrics: AdviceMetricsPort | None = None,
        context_builder: ContextPackBuilder | None = None,
        guard: OutputGuard | None = None,
        breaker: CircuitBreaker | None = None,
        bulkhead: Bulkhead | None = None,
        redactor: Redactor | None = None,
        deadline_seconds: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        self._baselines = dict(baselines)
        self._model = model
        self._entitlements = entitlements
        self._ledger = ledger
        self._audit = audit
        self._metrics = metrics
        self._builder = context_builder or ContextPackBuilder()
        self._guard = guard or OutputGuard()
        self._breaker = breaker or CircuitBreaker()
        self._bulkhead = bulkhead or Bulkhead()
        self._redactor = redactor or Redactor()
        self._deadline = deadline_seconds
        self._clock = clock

    # ------------------------------------------------------------------ public

    def advise(self, request: AdviceRequest) -> AdviceResult:
        started = self._clock()
        if request.capability not in request.granted_capabilities:
            return self._denied(request, "capability_not_granted", started)
        try:
            self._builder.assert_scope(request)
        except ScopeViolationError:
            return self._denied(request, "scope_violation", started)

        baseline = self._run_baseline(request)
        augmented = replace(
            request, evidence=_merge_evidence(request.evidence, baseline.extra_evidence)
        )
        pack = self._builder.build(augmented)
        context_hash = pack.prompt.context_hash

        outcome = self._maybe_call_model(augmented, baseline, pack.prompt, context_hash)
        sections = self._merge(baseline, outcome)
        sections = tuple(self._clean(section) for section in sections)
        status = AdviceStatus.ADVISED if outcome.sections else baseline.status
        if status is AdviceStatus.ADVISED and outcome.degraded_reason:
            status = baseline.status

        findings = list(outcome.findings)
        if baseline.error:
            findings.append(f"baseline_error:{baseline.error}")
        if pack.injection_markers:
            findings.append(f"injection_markers_in_input:{pack.injection_markers}")
        if outcome.provider_id and self._ledger is not None:
            findings.extend(self._record_usage(request, outcome, status))

        provenance = Provenance(
            correlation_id=request.scope.correlation_id,
            request_id=request.request_id,
            capability=request.capability,
            schema_version=SCHEMA_VERSION,
            context_hash=context_hash,
            evidence_ids=pack.evidence_ids,
            baseline_version=BASELINE_VERSION,
            provider_id=outcome.provider_id,
            model=outcome.model,
            model_version=outcome.model_version,
            guard_findings=tuple(findings),
            degraded_reason=outcome.degraded_reason,
            latency_ms=int((self._clock() - started) * 1000),
            usage=outcome.usage,
        )
        self._emit(request, "advice.completed", context_hash, status.value, outcome.degraded_reason)
        self._observe(request, status, outcome.degraded_reason, provenance)
        return AdviceResult(status=status, sections=sections, provenance=provenance)

    # ----------------------------------------------------------------- helpers

    def _run_baseline(self, request: AdviceRequest) -> Baseline:
        fn = self._baselines.get(request.capability)
        if fn is None:
            return insufficient(
                "Esta capacidade ainda não está habilitada: não há base suficiente."
            )
        try:
            return fn(request)
        except Exception as exc:  # deterministic baseline must never take the caller down
            failed = insufficient("Não foi possível montar a base determinística desta consulta.")
            return replace(failed, error=type(exc).__name__)

    def _maybe_call_model(
        self, request: AdviceRequest, baseline: Baseline, prompt: ModelPrompt, context_hash: str
    ) -> _ModelOutcome:
        if self._model is None:
            return _ModelOutcome(degraded_reason="ai_disabled")
        if not baseline.model_eligible:
            return _ModelOutcome(degraded_reason=baseline.no_model_reason)
        if self._entitlements is not None:
            try:
                decision = self._entitlements.check(
                    tenant_id=request.scope.tenant_id,
                    unit_id=request.scope.unit_id,
                    capability=request.capability,
                )
            except Exception:
                return _ModelOutcome(degraded_reason="entitlement_unavailable")
            if not decision.allowed:
                return _ModelOutcome(degraded_reason="entitlement_denied")
        if self._audit is not None and not self._emit(
            request, "advice.model_call_started", context_hash, "started", None
        ):
            return _ModelOutcome(degraded_reason="audit_unavailable")
        try:
            self._breaker.before_call()
        except CircuitOpen:
            return _ModelOutcome(degraded_reason="circuit_open")
        try:
            self._bulkhead.acquire()
        except BulkheadFull:
            return _ModelOutcome(degraded_reason="overloaded")
        model = self._model
        try:
            answer = call_with_deadline(
                lambda: model.advise(prompt, deadline_seconds=self._deadline), self._deadline
            )
        except DeadlineExceeded:
            self._breaker.record_failure()
            return _ModelOutcome(degraded_reason="timeout")
        except ModelProviderError as exc:
            self._breaker.record_failure()
            return _ModelOutcome(degraded_reason=exc.reason)
        except Exception:
            self._breaker.record_failure()
            return _ModelOutcome(degraded_reason="provider_error")
        finally:
            self._bulkhead.release()
        self._breaker.record_success()
        result = self._guard.validate(answer.sections, request)
        reason = None if result.accepted else "guard_rejected_all"
        return _ModelOutcome(
            sections=result.accepted,
            findings=result.findings,
            degraded_reason=reason,
            provider_id=answer.provider_id,
            model=answer.model,
            model_version=answer.model_version,
            usage=answer.usage,
        )

    @staticmethod
    def _merge(baseline: Baseline, outcome: _ModelOutcome) -> tuple[AdviceSection, ...]:
        model_kinds = {s.kind for s in outcome.sections}
        merged: list[AdviceSection] = []
        for kind in (
            SectionKind.FACT,
            SectionKind.HYPOTHESIS,
            SectionKind.ACTION,
            SectionKind.SOURCE,
        ):
            if kind in model_kinds:
                merged.extend(s for s in outcome.sections if s.kind is kind)
            else:
                merged.extend(s for s in baseline.sections if s.kind is kind)
        return tuple(merged)

    def _clean(self, section: AdviceSection) -> AdviceSection:
        cleaned = self._redactor.redact(section.text)
        if not cleaned.redacted:
            return section
        return replace(section, text=cleaned.text)

    def _denied(self, request: AdviceRequest, reason: str, started: float) -> AdviceResult:
        provenance = Provenance(
            correlation_id=request.scope.correlation_id,
            request_id=request.request_id,
            capability=request.capability,
            schema_version=SCHEMA_VERSION,
            context_hash=_DENIED_CONTEXT,
            evidence_ids=(),
            baseline_version=BASELINE_VERSION,
            degraded_reason=reason,
            latency_ms=int((self._clock() - started) * 1000),
        )
        self._emit(request, "advice.denied", _DENIED_CONTEXT, "denied", reason)
        self._observe(request, AdviceStatus.DENIED, reason, provenance)
        return AdviceResult(
            status=AdviceStatus.DENIED,
            sections=(
                AdviceSection(
                    SectionKind.FACT,
                    "Acesso negado: sem permissão ou escopo válido para esta consulta.",
                ),
            ),
            provenance=provenance,
        )

    def _observe(
        self,
        request: AdviceRequest,
        status: AdviceStatus,
        reason: str | None,
        provenance: Provenance,
    ) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.observe(
                AdviceMetricsSample(
                    scope=request.scope,
                    capability=request.capability,
                    status=status.value,
                    degraded_reason=reason,
                    latency_ms=provenance.latency_ms or 0,
                    usage=provenance.usage,
                )
            )
        except Exception:  # metrics are best-effort and never affect the answer
            return

    def _emit(
        self,
        request: AdviceRequest,
        event: str,
        context_hash: str,
        outcome: str,
        detail: str | None,
    ) -> bool:
        if self._audit is None:
            return True
        try:
            self._audit.emit(
                AdviceAuditEvent(
                    event=event,
                    request_id=request.request_id,
                    correlation_id=request.scope.correlation_id,
                    tenant_id=request.scope.tenant_id,
                    unit_id=request.scope.unit_id,
                    actor_id=request.actor_id,
                    capability=request.capability,
                    context_hash=context_hash,
                    outcome=outcome,
                    detail=detail or "",
                )
            )
        except Exception:
            return False
        return True

    def _record_usage(
        self, request: AdviceRequest, outcome: _ModelOutcome, status: AdviceStatus
    ) -> list[str]:
        assert self._ledger is not None
        try:
            self._ledger.record(
                UsageRecord(
                    request_id=request.request_id,
                    tenant_id=request.scope.tenant_id,
                    unit_id=request.scope.unit_id,
                    actor_id=request.actor_id,
                    capability=request.capability,
                    provider_id=outcome.provider_id or "unknown",
                    model=outcome.model or "unknown",
                    model_version=outcome.model_version or "unknown",
                    usage=outcome.usage,
                    outcome=status.value,
                )
            )
        except Exception:
            return ["ledger_unavailable"]
        return []


def _merge_evidence(
    original: tuple[Evidence, ...], extra: tuple[Evidence, ...]
) -> tuple[Evidence, ...]:
    seen = {item.evidence_id for item in original}
    return original + tuple(item for item in extra if item.evidence_id not in seen)
