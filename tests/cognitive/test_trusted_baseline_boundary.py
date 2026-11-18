"""REC-22: untrusted provider/user payloads never become deterministic fiscal facts."""

from __future__ import annotations

from dataclasses import replace

from kordena_fiscal.cognitive import (
    AccountantQuestionBaseline,
    AdviceStatus,
    Capability,
    ClassificationBaseline,
    Evidence,
    EvidenceKind,
    ReconciliationBaseline,
    RejectionBaseline,
)
from kordena_fiscal.cognitive.knowledge import (
    default_classification_catalog,
    default_reconciliation_knowledge_base,
    default_rejection_knowledge_base,
)

from .conftest import TENANT, UNIT, make_request, rejection_evidence


def _evidence(kind: EvidenceKind, **data: str) -> Evidence:
    return Evidence(
        evidence_id="untrusted-1", kind=kind,
        tenant_id=TENANT, unit_id=UNIT, origin="unverified-provider-message",
        data=data, trusted=False,
    )


def test_rejection_baseline_does_not_turn_untrusted_code_into_fact() -> None:
    raw = _evidence(EvidenceKind.REJECTION, code="204")
    result = RejectionBaseline(default_rejection_knowledge_base())(
        make_request(evidence=(raw,))
    )
    assert result.status is AdviceStatus.INSUFFICIENT_BASIS
    assert result.extra_evidence == ()
    assert all("Rejeição 204" not in item.text for item in result.sections)


def test_rejection_baseline_rejects_untrusted_document_state() -> None:
    trusted = rejection_evidence()[0]
    untrusted = _evidence(EvidenceKind.DOCUMENT_STATE, state="authorized")
    result = RejectionBaseline(default_rejection_knowledge_base())(
        make_request(evidence=(trusted, untrusted))
    )
    assert result.status is AdviceStatus.BASELINE_ONLY
    assert all("authorized" not in item.text for item in result.sections)


def test_classification_baseline_requires_trusted_tax_decision() -> None:
    raw = _evidence(EvidenceKind.TAX_DECISION, icms_code="00", crt="3", cfop="5102")
    result = ClassificationBaseline(default_classification_catalog())(
        make_request(
            evidence=(raw,), capability=Capability.SUGGEST_CLASSIFICATION,
        )
    )
    assert result.status is AdviceStatus.INSUFFICIENT_BASIS
    assert result.extra_evidence == ()
    assert all("Classificação atual" not in item.text for item in result.sections)


def test_classification_cannot_promote_untrusted_product_ncm() -> None:
    tax = Evidence(
        evidence_id="tax-1", kind=EvidenceKind.TAX_DECISION,
        tenant_id=TENANT, unit_id=UNIT, origin="canonical-tax-decision",
        data={"crt": "3", "icms_code": "00", "pis_cst": "01", "cofins_cst": "01"},
    )
    raw_product = _evidence(EvidenceKind.PRODUCT_PROFILE, ncm="99999999")
    result = ClassificationBaseline(default_classification_catalog())(
        make_request(
            evidence=(tax, raw_product), capability=Capability.SUGGEST_CLASSIFICATION,
        )
    )
    assert result.status is AdviceStatus.BASELINE_ONLY
    assert all("NCM 99999999" not in item.text for item in result.sections)


def test_reconciliation_baseline_ignores_untrusted_status_and_issue() -> None:
    raw = _evidence(EvidenceKind.RECONCILIATION_ISSUE, status="matched")
    result = ReconciliationBaseline(default_reconciliation_knowledge_base())(
        make_request(
            evidence=(raw,), capability=Capability.EXPLAIN_RECONCILIATION,
        )
    )
    assert result.status is AdviceStatus.INSUFFICIENT_BASIS
    assert all("conciliada" not in item.text for item in result.sections)


def test_accountant_question_requires_trusted_fiscal_evidence() -> None:
    raw = _evidence(EvidenceKind.RECONCILIATION_ISSUE, status="matched")
    request = make_request(
        evidence=(raw,), capability=Capability.ANSWER_ACCOUNTANT_QUESTION,
        question="A conciliação foi concluída?",
    )
    result = AccountantQuestionBaseline()(request)
    assert result.status is AdviceStatus.INSUFFICIENT_BASIS
    assert result.model_eligible is False


def test_accountant_question_cites_only_trusted_evidence() -> None:
    verified = replace(
        _evidence(EvidenceKind.RECONCILIATION_ISSUE, status="pending"),
        evidence_id="trusted-1", origin="canonical-reconciliation", trusted=True,
    )
    raw = _evidence(EvidenceKind.RECONCILIATION_ISSUE, status="matched")
    request = make_request(
        evidence=(verified, raw), capability=Capability.ANSWER_ACCOUNTANT_QUESTION,
        question="Qual o estado?",
    )
    result = AccountantQuestionBaseline()(request)
    assert result.status is AdviceStatus.BASELINE_ONLY
    assert result.model_eligible
    assert all(section.evidence_ids == ("trusted-1",) for section in result.sections)
