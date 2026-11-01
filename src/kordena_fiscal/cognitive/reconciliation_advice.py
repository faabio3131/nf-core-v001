"""Reconciliation and accountant-question advisory. Read-only: no retry, no authorization."""

from __future__ import annotations

from .baseline import Baseline, insufficient
from .contracts import (
    AdviceRequest,
    AdviceSection,
    AdviceStatus,
    Evidence,
    EvidenceKind,
    SectionKind,
)
from .knowledge.reconciliation import ReconciliationKnowledgeBase

_NO_SIDE_EFFECT = "Nenhum reenvio, cancelamento ou correção foi executado."
_STATUS_TEXT = {
    "matched": "A conciliação está conciliada, sem divergências.",
    "pending": "A conciliação está pendente: o resultado fiscal ainda não é conhecido.",
    "divergent": "A conciliação encontrou divergências.",
}


class ReconciliationBaseline:
    def __init__(self, knowledge: ReconciliationKnowledgeBase) -> None:
        self._kb = knowledge

    def __call__(self, request: AdviceRequest) -> Baseline:
        items = [e for e in request.evidence if e.kind is EvidenceKind.RECONCILIATION_ISSUE]
        status_ev = next((e for e in items if "status" in e.data), None)
        issues = [e for e in items if "issue_code" in e.data]
        if status_ev is None and not issues:
            return insufficient(
                "Não há resultado de conciliação informado: não há base suficiente."
            )
        sections: list[AdviceSection] = []
        extra: list[Evidence] = []
        if status_ev is not None:
            raw = status_ev.data["status"].strip().lower()
            sections.append(
                AdviceSection(
                    SectionKind.FACT,
                    _STATUS_TEXT.get(raw, f"Estado de conciliação não reconhecido: {raw[:20]}."),
                    (status_ev.evidence_id,),
                )
            )
            if raw == "matched" and not issues:
                sections.append(
                    AdviceSection(SectionKind.SOURCE, self._source(), (status_ev.evidence_id,))
                )
                return Baseline(
                    status=AdviceStatus.BASELINE_ONLY,
                    sections=tuple(sections),
                    model_eligible=False,
                    no_model_reason="no_ai_needed",
                )
        known = 0
        guard_retry = False
        hypotheses: list[AdviceSection] = []
        actions: list[AdviceSection] = []
        for issue in issues:
            code = issue.data["issue_code"].strip()
            entry = self._kb.lookup(code)
            doc = f" (documento {issue.data['document_id']})" if "document_id" in issue.data else ""
            if entry is None:
                sections.append(
                    AdviceSection(
                        SectionKind.FACT,
                        f"Divergência {code[:40]}{doc} não consta do catálogo interno: "
                        "não há base suficiente para explicar.",
                        (issue.evidence_id,),
                    )
                )
                continue
            known += 1
            kb_ev = Evidence(
                evidence_id=f"kb:reconciliation:{entry.code}",
                kind=EvidenceKind.KNOWLEDGE_BASE,
                origin=f"reconciliation-kb@{self._kb.version}",
                data={
                    "meaning": entry.meaning,
                    "typical_causes": " | ".join(entry.typical_causes),
                    "suggested_checks": " | ".join(entry.suggested_checks),
                    "review_status": entry.review_status.value,
                },
                tenant_id=issue.tenant_id,
                unit_id=issue.unit_id,
            )
            extra.append(kb_ev)
            cited = (issue.evidence_id, kb_ev.evidence_id)
            sections.append(
                AdviceSection(SectionKind.FACT, f"{entry.meaning}{doc}", cited)
            )
            hypotheses.append(
                AdviceSection(
                    SectionKind.HYPOTHESIS,
                    "Causas típicas (hipóteses a confirmar): " + "; ".join(entry.typical_causes),
                    (kb_ev.evidence_id,),
                )
            )
            actions.append(
                AdviceSection(
                    SectionKind.ACTION,
                    "Verificações sugeridas para decisão humana: "
                    + "; ".join(entry.suggested_checks),
                    (kb_ev.evidence_id,),
                )
            )
            guard_retry = guard_retry or entry.never_retry_blindly
        sections.extend(hypotheses)
        sections.extend(actions)
        anchor = (status_ev or issues[0]).evidence_id
        if guard_retry or (status_ev is not None
                           and status_ev.data["status"].strip().lower() == "pending"):
            sections.append(
                AdviceSection(
                    SectionKind.ACTION,
                    "Atenção: resultado fiscal não confirmado. Não presumir sucesso nem "
                    f"reenviar antes de consultar o autorizador. {_NO_SIDE_EFFECT}",
                    (anchor,),
                )
            )
        sections.append(AdviceSection(SectionKind.SOURCE, self._source(), (anchor,)))
        return Baseline(
            status=AdviceStatus.BASELINE_ONLY,
            sections=tuple(sections),
            model_eligible=known > 0,
            extra_evidence=tuple(extra),
        )

    def _source(self) -> str:
        return (
            f"Catálogo operacional {self._kb.version} (status: pending_normative_review); "
            "derivado dos códigos do motor de conciliação."
        )


class AccountantQuestionBaseline:
    """Answers only from supplied evidence; otherwise declares uncertainty."""

    def __call__(self, request: AdviceRequest) -> Baseline:
        if not request.question:
            return insufficient("Nenhuma pergunta informada: não há base suficiente.")
        usable = [e for e in request.evidence if e.kind is not EvidenceKind.KNOWLEDGE_BASE]
        if not usable:
            return insufficient(
                "Não há evidência fiscal da unidade para fundamentar esta pergunta: não há "
                "base suficiente. Confirme a resposta na norma vigente com o contador."
            )
        ids = tuple(e.evidence_id for e in usable)
        return Baseline(
            status=AdviceStatus.BASELINE_ONLY,
            sections=(
                AdviceSection(
                    SectionKind.FACT,
                    "A resposta se limita às evidências fiscais listadas abaixo; não cobre "
                    "legislação fora delas.",
                    ids,
                ),
                AdviceSection(
                    SectionKind.ACTION,
                    "Confirmar a resposta na norma vigente com o contador responsável antes "
                    "de agir. " + _NO_SIDE_EFFECT,
                    ids,
                ),
                AdviceSection(
                    SectionKind.SOURCE,
                    "Evidências autorizadas da unidade, sem consulta a fontes externas.",
                    ids,
                ),
            ),
            model_eligible=True,
        )
