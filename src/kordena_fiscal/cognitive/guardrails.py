"""OutputGuard: model text is untrusted until it passes grounding and safety checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .context import INJECTION_MARKERS, evidence_corpus
from .contracts import MAX_SECTION_CHARS, AdviceRequest, AdviceSection, SectionKind
from .ports import ProviderSection
from .redaction import Redactor

MAX_MODEL_SECTIONS = 6
_MODEL_KINDS = frozenset({SectionKind.HYPOTHESIS, SectionKind.ACTION})
_CODE_TOKEN = re.compile(r"(?<![\w.])\d{3,}(?![\w])")
_CLASSIFICATION_REF = re.compile(
    r"(?i)\b(cst|csosn|cfop|ncm|cclasstrib|cclass)\b[^\d\n]{0,12}(\d{2,8})"
)
_DIGIT_RUN = re.compile(r"\d+")
_AMOUNT = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*%|R\$\s*(\d[\d.,]*)")
_EXECUTION_CLAIM = re.compile(
    r"(?i)\b(eu\s+)?(emiti|cancelei|inutilizei|transmiti|assinei|alterei|corrigi|apliquei|"
    r"reenviei|autorizei|salvei|atualizei|reprocessei)\b"
    r"|\bfoi\s+(emitid|cancelad|inutilizad|transmitid|assinad|alterad|corrigid|reenviad|"
    r"aplicad|salv|atualizad|reprocessad)\w*\s+(automaticamente|pelo\s+(sistema|assistente|ia))"
    r"|\bj[áa]\s+(corrigi|emiti|cancelei|alterei)"
)
_UNSAFE_INSTRUCTION = re.compile(
    r"(?i)(desative|desabilite|ignore|contorne|burle|pule)\s+(a\s+|as\s+|o\s+|os\s+)?"
    r"(valida[cç][aã]o|valida[cç][õo]es|assinatura|rejei[cç][aã]o|rejei[cç][õo]es|sefaz|schema)"
    r"|emita\s+mesmo\s+assim|sonegar|fraud|adultere|falsifique"
)
_CONFIG_DIRECTIVE = re.compile(
    r"(?i)\b(altere|mude|troque|configure|defina|ajuste)\s+(a\s+|o\s+)?"
    r"(al[ií]quota|cst|cfop|ncm|cclasstrib|regime)\b"
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    accepted: tuple[AdviceSection, ...]
    findings: tuple[str, ...]


class OutputGuard:
    def __init__(self, *, redactor: Redactor | None = None) -> None:
        self._redactor = redactor or Redactor()

    def validate(
        self, sections: tuple[ProviderSection, ...], request: AdviceRequest
    ) -> GuardResult:
        known_ids = {item.evidence_id for item in request.evidence}
        corpus = evidence_corpus(request.evidence, request.question)
        accepted: list[AdviceSection] = []
        findings: list[str] = []
        for index, section in enumerate(sections):
            tag = f"section[{index}]"
            reason = self._reject_reason(section, known_ids, corpus)
            if reason is not None:
                findings.append(f"{tag}:{reason}")
                continue
            if len(accepted) >= MAX_MODEL_SECTIONS:
                findings.append(f"{tag}:too_many_sections")
                continue
            accepted.append(
                AdviceSection(
                    kind=section.kind,
                    text=section.text.strip(),
                    evidence_ids=tuple(section.evidence_ids),
                )
            )
        return GuardResult(accepted=tuple(accepted), findings=tuple(findings))

    def _reject_reason(
        self, section: ProviderSection, known_ids: set[str], corpus: str
    ) -> str | None:
        if section.kind not in _MODEL_KINDS:
            return "model_authored_fact_or_source"
        text = section.text.strip()
        if not text:
            return "empty"
        if len(text) > MAX_SECTION_CHARS:
            return "too_long"
        if not section.evidence_ids:
            return "uncited"
        if not set(section.evidence_ids) <= known_ids:
            return "unknown_evidence_id"
        if self._redactor.contains_sensitive(text):
            return "sensitive_output"
        if _EXECUTION_CLAIM.search(text):
            return "execution_claim"
        if _UNSAFE_INSTRUCTION.search(text):
            return "unsafe_instruction"
        if _CONFIG_DIRECTIVE.search(text):
            return "config_change_directive"
        if any(pattern.search(text) for pattern in INJECTION_MARKERS):
            return "injection_echo"
        for token in _CODE_TOKEN.findall(text):
            if token not in corpus:
                return "ungrounded_code"
        corpus_numbers = set(_DIGIT_RUN.findall(corpus))
        for amount in _AMOUNT.finditer(text):
            figure = amount.group(1) or amount.group(2)
            if figure.rstrip(".,") not in corpus:
                return "ungrounded_amount"
        for match in _CLASSIFICATION_REF.finditer(text):
            if match.group(2) not in corpus_numbers:
                return "ungrounded_classification_code"
        return None
