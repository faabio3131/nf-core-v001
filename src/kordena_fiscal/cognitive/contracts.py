"""Versioned, provider-neutral contracts for the fiscal cognitive core.

Everything here is advisory. No contract carries a write path into the fiscal domain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from kordena_fiscal.domain import ExecutionScope, FiscalValidationError

SCHEMA_VERSION = "nfcore.cognitive.advice/v1"

MAX_QUESTION_CHARS = 1000
MAX_EVIDENCE_ITEMS = 40
MAX_EVIDENCE_VALUE_CHARS = 500
MAX_SECTION_CHARS = 1200


class Capability(StrEnum):
    EXPLAIN_REJECTION = "cognitive.explain_rejection"
    SUGGEST_CLASSIFICATION = "cognitive.suggest_classification"
    EXPLAIN_RECONCILIATION = "cognitive.explain_reconciliation"
    ANSWER_ACCOUNTANT_QUESTION = "cognitive.answer_accountant_question"


class EvidenceKind(StrEnum):
    REJECTION = "rejection"
    DOCUMENT_STATE = "document_state"
    TAX_DECISION = "tax_decision"
    PRODUCT_PROFILE = "product_profile"
    CLASSIFICATION_CATALOG = "classification_catalog"
    RECONCILIATION_ISSUE = "reconciliation_issue"
    KNOWLEDGE_BASE = "knowledge_base"


class SectionKind(StrEnum):
    FACT = "fact"
    HYPOTHESIS = "hypothesis"
    ACTION = "action"
    SOURCE = "source"


class AdviceStatus(StrEnum):
    ADVISED = "advised"
    BASELINE_ONLY = "baseline_only"
    INSUFFICIENT_BASIS = "insufficient_basis"
    DENIED = "denied"


def _text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise FiscalValidationError(f"{field_name} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise FiscalValidationError(f"{field_name} is required")
    if len(cleaned) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds {max_length} characters")
    return cleaned


@dataclass(frozen=True, slots=True)
class Evidence:
    """One authorized fact. ``trusted`` is True only for deterministic domain output.

    Provider payloads, XML text and user text must be ``trusted=False`` and are fenced as
    data in the prompt; they never become instructions.
    """

    evidence_id: str
    kind: EvidenceKind
    tenant_id: str
    unit_id: str
    origin: str
    data: Mapping[str, str]
    trusted: bool = True
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id", 128))
        if not isinstance(self.kind, EvidenceKind):
            raise FiscalValidationError("kind must be EvidenceKind")
        object.__setattr__(self, "tenant_id", _text(self.tenant_id, "tenant_id", 256))
        object.__setattr__(self, "unit_id", _text(self.unit_id, "unit_id", 256))
        object.__setattr__(self, "origin", _text(self.origin, "origin", 200))
        if not self.data:
            raise FiscalValidationError("evidence data is required")
        frozen: dict[str, str] = {}
        for key, value in self.data.items():
            clean_key = _text(key, "evidence key", 64)
            if not isinstance(value, str):
                raise FiscalValidationError("evidence values must be text")
            if len(value) > MAX_EVIDENCE_VALUE_CHARS:
                raise FiscalValidationError("evidence value is too long")
            frozen[clean_key] = value
        object.__setattr__(self, "data", MappingProxyType(frozen))
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise FiscalValidationError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AdviceRequest:
    scope: ExecutionScope
    request_id: str
    actor_id: str
    granted_capabilities: frozenset[Capability]
    capability: Capability
    evidence: tuple[Evidence, ...]
    question: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id", 128))
        object.__setattr__(self, "actor_id", _text(self.actor_id, "actor_id", 128))
        if not isinstance(self.capability, Capability):
            raise FiscalValidationError("capability must be Capability")
        if not all(isinstance(item, Capability) for item in self.granted_capabilities):
            raise FiscalValidationError("granted_capabilities must contain Capability values")
        if len(self.evidence) > MAX_EVIDENCE_ITEMS:
            raise FiscalValidationError("too many evidence items")
        if not all(isinstance(item, Evidence) for item in self.evidence):
            raise FiscalValidationError("evidence must contain Evidence values")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise FiscalValidationError("evidence ids must be unique")
        question = self.question.strip()
        if len(question) > MAX_QUESTION_CHARS:
            raise FiscalValidationError("question is too long")
        object.__setattr__(self, "question", question)


@dataclass(frozen=True, slots=True)
class AdviceSection:
    kind: SectionKind
    text: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SectionKind):
            raise FiscalValidationError("kind must be SectionKind")
        object.__setattr__(self, "text", _text(self.text, "section text", MAX_SECTION_CHARS))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micro_brl: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise FiscalValidationError("token counts cannot be negative")
        if self.cost_micro_brl is not None and self.cost_micro_brl < 0:
            raise FiscalValidationError("cost cannot be negative")


@dataclass(frozen=True, slots=True)
class Provenance:
    correlation_id: str
    request_id: str
    capability: Capability
    schema_version: str
    context_hash: str
    evidence_ids: tuple[str, ...]
    baseline_version: str
    provider_id: str | None = None
    model: str | None = None
    model_version: str | None = None
    guard_findings: tuple[str, ...] = ()
    degraded_reason: str | None = None
    latency_ms: int | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)


@dataclass(frozen=True, slots=True)
class AdviceResult:
    status: AdviceStatus
    sections: tuple[AdviceSection, ...]
    provenance: Provenance
    disclaimer: str = (
        "Conteúdo consultivo gerado com apoio de IA. Não é decisão fiscal nem altera "
        "nenhum documento ou configuração. Confirme com o contador responsável."
    )

    @property
    def advisory_only(self) -> bool:
        return True

    @property
    def requires_human_approval(self) -> bool:
        return True


def stable_hash(payload: object) -> str:
    """SHA-256 of a canonical JSON rendering; used for context hashes, never for secrets."""

    rendered = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
