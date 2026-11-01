"""Default wiring of deterministic baselines for the enabled capabilities."""

from __future__ import annotations

from .baseline import BaselineFn, RejectionBaseline
from .classification import ClassificationBaseline
from .contracts import Capability
from .knowledge import (
    ClassificationCatalog,
    default_classification_catalog,
    default_reconciliation_knowledge_base,
    default_rejection_knowledge_base,
)
from .reconciliation_advice import AccountantQuestionBaseline, ReconciliationBaseline


def default_baselines(
    *, classification_catalog: ClassificationCatalog | None = None
) -> dict[Capability, BaselineFn]:
    return {
        Capability.EXPLAIN_REJECTION: RejectionBaseline(default_rejection_knowledge_base()),
        Capability.SUGGEST_CLASSIFICATION: ClassificationBaseline(
            classification_catalog or default_classification_catalog()
        ),
        Capability.EXPLAIN_RECONCILIATION: ReconciliationBaseline(
            default_reconciliation_knowledge_base()
        ),
        Capability.ANSWER_ACCOUNTANT_QUESTION: AccountantQuestionBaseline(),
    }
