"""Deterministic baselines. They produce every FACT/SOURCE and work with the AI switched off."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .contracts import (
    AdviceRequest,
    AdviceSection,
    AdviceStatus,
    Evidence,
    EvidenceKind,
    SectionKind,
)
from .knowledge import RejectionKnowledgeBase

BASELINE_VERSION = "baseline/1"


@dataclass(frozen=True, slots=True)
class Baseline:
    status: AdviceStatus
    sections: tuple[AdviceSection, ...]
    model_eligible: bool = False
    no_model_reason: str = "insufficient_basis"
    error: str | None = None
    extra_evidence: tuple[Evidence, ...] = ()


BaselineFn = Callable[[AdviceRequest], Baseline]


def insufficient(text: str, *, evidence_ids: tuple[str, ...] = ()) -> Baseline:
    return Baseline(
        status=AdviceStatus.INSUFFICIENT_BASIS,
        sections=(AdviceSection(SectionKind.FACT, text, evidence_ids),),
    )


class RejectionBaseline:
    """Explains a fiscal rejection from the curated knowledge base and authorized evidence."""

    def __init__(self, knowledge: RejectionKnowledgeBase) -> None:
        self._kb = knowledge

    def __call__(self, request: AdviceRequest) -> Baseline:
        rejection = next(
            (e for e in request.evidence if e.kind is EvidenceKind.REJECTION and "code" in e.data),
            None,
        )
        if rejection is None:
            return insufficient("Não há rejeição informada para explicar: não há base suficiente.")
        code = rejection.data["code"].strip()
        entry = self._kb.lookup(code)
        if entry is None:
            return insufficient(
                f"O código de rejeição {code[:12]} não consta do catálogo interno "
                f"({self._kb.version}): não há base suficiente para explicar a causa. "
                "Consulte a tabela oficial vigente e o retorno completo do autorizador.",
                evidence_ids=(rejection.evidence_id,),
            )
        kb_evidence = Evidence(
            evidence_id=f"kb:rejection:{entry.code}",
            kind=EvidenceKind.KNOWLEDGE_BASE,
            origin=f"rejection-kb@{self._kb.version}",
            data={
                "code": entry.code,
                "title": entry.title,
                "meaning": entry.meaning,
                "typical_causes": " | ".join(entry.typical_causes),
                "suggested_checks": " | ".join(entry.suggested_checks),
                "review_status": entry.review_status.value,
            },
            tenant_id=rejection.tenant_id,
            unit_id=rejection.unit_id,
        )
        kb_id = kb_evidence.evidence_id
        sections: list[AdviceSection] = [
            AdviceSection(
                SectionKind.FACT,
                f"Rejeição {entry.code} — {entry.title}. {entry.meaning}",
                (rejection.evidence_id, kb_id),
            )
        ]
        state = next((e for e in request.evidence if e.kind is EvidenceKind.DOCUMENT_STATE), None)
        if state is not None and "state" in state.data:
            sections.append(
                AdviceSection(
                    SectionKind.FACT,
                    f"Estado atual do documento: {state.data['state']}.",
                    (state.evidence_id,),
                )
            )
        sections.append(
            AdviceSection(
                SectionKind.HYPOTHESIS,
                "Causas típicas (hipóteses a confirmar): " + "; ".join(entry.typical_causes),
                (kb_id,),
            )
        )
        sections.append(
            AdviceSection(
                SectionKind.ACTION,
                "Verificações sugeridas para decisão humana: " + "; ".join(entry.suggested_checks),
                (kb_id,),
            )
        )
        sections.append(
            AdviceSection(
                SectionKind.SOURCE,
                f"Catálogo interno {self._kb.version} (status: {entry.review_status.value}). "
                f"{entry.source_ref}",
                (kb_id,),
            )
        )
        return Baseline(
            status=AdviceStatus.BASELINE_ONLY,
            sections=tuple(sections),
            model_eligible=True,
            extra_evidence=(kb_evidence,),
        )
