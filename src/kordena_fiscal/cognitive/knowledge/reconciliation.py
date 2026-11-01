"""Operational knowledge for fiscal reconciliation issues.

Keyed by the canonical ``ReconciliationIssueCode`` values so that a new engine code without
an explanation fails the coverage test instead of silently producing an empty answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rejections import ReviewStatus


@dataclass(frozen=True, slots=True)
class ReconciliationEntry:
    code: str
    meaning: str
    typical_causes: tuple[str, ...]
    suggested_checks: tuple[str, ...]
    never_retry_blindly: bool = False
    review_status: ReviewStatus = ReviewStatus.PENDING_NORMATIVE_REVIEW


_PAYMENT_CHECKS = (
    "Comparar o snapshot de pagamento da operação com o do documento autorizado.",
    "Lembrar que o documento autorizado preserva o snapshot histórico: correção exige "
    "procedimento fiscal definido pelo responsável, não edição do cadastro.",
)
_TOTAL_CHECKS = (
    "Comparar os totais item a item entre a operação e o documento.",
    "Verificar descontos, acréscimos e arredondamentos aplicados depois da emissão.",
)
_RETRY_GUARD = (
    "Consultar a situação do documento no autorizador antes de qualquer novo envio.",
    "Não reenviar nem emitir novo número enquanto o resultado não estiver confirmado.",
)

_ENTRIES: tuple[ReconciliationEntry, ...] = (
    ReconciliationEntry(
        "operation_payment_mismatch",
        "O pagamento registrado na operação não corresponde ao registrado no documento.",
        ("Pagamento parcial ou troco tratado de forma diferente.", "Ajuste após a emissão."),
        _PAYMENT_CHECKS,
    ),
    ReconciliationEntry(
        "host_payment_mismatch",
        "O pagamento da venda de origem não corresponde ao do documento (código legado).",
        ("Pagamento parcial ou troco tratado de forma diferente.", "Ajuste após a emissão."),
        _PAYMENT_CHECKS,
    ),
    ReconciliationEntry(
        "missing_authorized_fiscal_document",
        "A operação está concluída, mas não há documento fiscal autorizado para ela.",
        (
            "Emissão não concluída ou rejeitada e ainda não tratada.",
            "Falha antes da transmissão ao autorizador.",
        ),
        (
            "Verificar as tentativas de emissão e o estado de cada uma.",
            *_RETRY_GUARD,
        ),
        never_retry_blindly=True,
    ),
    ReconciliationEntry(
        "fiscal_processing_pending",
        "O documento ainda está em processamento; o resultado final não é conhecido.",
        (
            "Transmissão em andamento ou resposta do autorizador não recebida.",
            "Documento em contingência aguardando regularização.",
        ),
        ("Aguardar e acompanhar o estado do documento.", *_RETRY_GUARD),
        never_retry_blindly=True,
    ),
    ReconciliationEntry(
        "closed_operation_with_cancelled_fiscal",
        "A operação está fechada, mas o documento fiscal associado foi cancelado.",
        ("Cancelamento fiscal posterior à conclusão da operação.",),
        (
            "Verificar se existe novo documento autorizado para a mesma operação.",
            "Levar o caso ao responsável fiscal para decidir o tratamento.",
        ),
    ),
    ReconciliationEntry(
        "closed_sale_with_cancelled_fiscal",
        "A venda está fechada, mas o documento fiscal associado foi cancelado (código legado).",
        ("Cancelamento fiscal posterior à conclusão da venda.",),
        (
            "Verificar se existe novo documento autorizado para a mesma venda.",
            "Levar o caso ao responsável fiscal para decidir o tratamento.",
        ),
    ),
    ReconciliationEntry(
        "duplicate_authorized_fiscal_document",
        "Há mais de um documento autorizado para a mesma operação.",
        (
            "Reenvio com nova numeração depois de uma resposta perdida.",
            "Tentativas concorrentes sem controle de idempotência.",
        ),
        (
            "Não cancelar automaticamente nenhum dos documentos.",
            "Levar ao contador qual documento manter e o procedimento e prazo normativos "
            "de cancelamento.",
        ),
        never_retry_blindly=True,
    ),
    ReconciliationEntry(
        "parallel_fiscal_attempt",
        "Existem tentativas de emissão paralelas para a mesma operação.",
        (
            "Duas emissões iniciadas quase ao mesmo tempo.",
            "Nova tentativa sem aguardar a anterior.",
        ),
        ("Aguardar o desfecho das tentativas em curso.", *_RETRY_GUARD),
        never_retry_blindly=True,
    ),
    ReconciliationEntry(
        "operation_fiscal_total_mismatch",
        "O total da operação difere do total do documento fiscal.",
        ("Arredondamento.", "Desconto ou item alterado depois da emissão."),
        _TOTAL_CHECKS,
    ),
    ReconciliationEntry(
        "sale_fiscal_total_mismatch",
        "O total da venda difere do total do documento fiscal (código legado).",
        ("Arredondamento.", "Desconto ou item alterado depois da emissão."),
        _TOTAL_CHECKS,
    ),
    ReconciliationEntry(
        "fiscal_payment_mismatch",
        "Os pagamentos declarados no documento não fecham com o total do documento.",
        ("Troco ou pagamento parcial informado incorretamente.",),
        _PAYMENT_CHECKS,
    ),
    ReconciliationEntry(
        "payment_snapshot_mismatch",
        "O snapshot de pagamento difere entre a operação e o documento.",
        ("Pagamento alterado depois da emissão.",),
        _PAYMENT_CHECKS,
    ),
)


class ReconciliationKnowledgeBase:
    def __init__(self, entries: tuple[ReconciliationEntry, ...] = _ENTRIES) -> None:
        self._entries = {e.code: e for e in entries}
        self.version = "reconciliation.seed/2026-10-31"

    def lookup(self, code: str) -> ReconciliationEntry | None:
        return self._entries.get(code.strip())

    def codes(self) -> frozenset[str]:
        return frozenset(self._entries)


def default_reconciliation_knowledge_base() -> ReconciliationKnowledgeBase:
    return ReconciliationKnowledgeBase()
