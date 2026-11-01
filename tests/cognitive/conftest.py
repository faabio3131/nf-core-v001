from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from kordena_fiscal.cognitive import (
    AdviceRequest,
    Capability,
    CognitiveAdviceService,
    Evidence,
    EvidenceKind,
    ModelUsage,
    RejectionBaseline,
    SectionKind,
    default_rejection_knowledge_base,
)
from kordena_fiscal.cognitive.ports import (
    AdviceAuditEvent,
    EntitlementDecision,
    ModelPrompt,
    ModelProviderUnavailable,
    ProviderAnswer,
    ProviderSection,
    UsageRecord,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment

TENANT = "tenant-a"
UNIT = "unit-a"


def make_scope(tenant: str = TENANT, unit: str = UNIT) -> ExecutionScope:
    return ExecutionScope(
        tenant_id=tenant,
        unit_id=unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-1",
    )


def rejection_evidence(
    code: str = "204",
    *,
    tenant: str = TENANT,
    unit: str = UNIT,
    message: str | None = None,
) -> tuple[Evidence, ...]:
    items = [
        Evidence(
            evidence_id="rej-1",
            kind=EvidenceKind.REJECTION,
            tenant_id=tenant,
            unit_id=unit,
            origin="provider-result",
            data={"code": code},
        ),
        Evidence(
            evidence_id="doc-1",
            kind=EvidenceKind.DOCUMENT_STATE,
            tenant_id=tenant,
            unit_id=unit,
            origin="lifecycle",
            data={"state": "rejected"},
        ),
    ]
    if message is not None:
        items.append(
            Evidence(
                evidence_id="msg-1",
                kind=EvidenceKind.REJECTION,
                tenant_id=tenant,
                unit_id=unit,
                origin="provider-message",
                data={"message": message},
                trusted=False,
            )
        )
    return tuple(items)


def make_request(
    *,
    evidence: tuple[Evidence, ...] | None = None,
    capability: Capability = Capability.EXPLAIN_REJECTION,
    granted: frozenset[Capability] | None = None,
    request_id: str = "req-1",
    question: str = "",
    scope: ExecutionScope | None = None,
) -> AdviceRequest:
    return AdviceRequest(
        scope=scope or make_scope(),
        request_id=request_id,
        actor_id="actor-1",
        granted_capabilities=granted if granted is not None else frozenset(Capability),
        capability=capability,
        evidence=evidence if evidence is not None else rejection_evidence(),
        question=question,
    )


@dataclass
class ScriptedModel:
    """Test double for AdvisoryModelPort. Records every prompt it receives."""

    sections: tuple[ProviderSection, ...] = ()
    error: Exception | None = None
    delay: float = 0.0
    prompts: list[ModelPrompt] = field(default_factory=list)
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def advise(self, prompt: ModelPrompt, *, deadline_seconds: float) -> ProviderAnswer:
        with self._lock:
            self.calls += 1
            self.prompts.append(prompt)
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return ProviderAnswer(
            sections=self.sections,
            provider_id="test-provider",
            model="test-model",
            model_version="1",
            usage=ModelUsage(input_tokens=120, output_tokens=80, cost_micro_brl=1500),
        )


def good_sections() -> tuple[ProviderSection, ...]:
    return (
        ProviderSection(
            SectionKind.HYPOTHESIS,
            "É provável que o documento 204 tenha sido reenviado após perda de resposta.",
            ("rej-1", "kb:rejection:204"),
        ),
        ProviderSection(
            SectionKind.ACTION,
            "Peça ao responsável fiscal para consultar a situação do documento pela chave.",
            ("kb:rejection:204",),
        ),
    )


class Recorder:
    def __init__(self) -> None:
        self.events: list[AdviceAuditEvent] = []
        self.usage: list[UsageRecord] = []
        self.fail = False

    def emit(self, event: AdviceAuditEvent) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.events.append(event)

    def record(self, record: UsageRecord) -> None:
        if self.fail:
            raise RuntimeError("ledger down")
        if any(r.request_id == record.request_id for r in self.usage):
            return
        self.usage.append(record)

    def check(self, *, tenant_id: str, unit_id: str, capability: Capability) -> EntitlementDecision:
        return EntitlementDecision(allowed=True)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def build_service(recorder: Recorder) -> Callable[..., CognitiveAdviceService]:
    def _build(model: ScriptedModel | None, **overrides: object) -> CognitiveAdviceService:
        kb = default_rejection_knowledge_base()
        kwargs: dict[str, object] = {
            "baselines": {Capability.EXPLAIN_REJECTION: RejectionBaseline(kb)},
            "model": model,
            "audit": recorder,
            "ledger": recorder,
            "deadline_seconds": 2.0,
        }
        kwargs.update(overrides)
        return CognitiveAdviceService(**kwargs)  # type: ignore[arg-type]

    return _build


__all__ = ["ModelProviderUnavailable", "ScriptedModel", "good_sections"]
