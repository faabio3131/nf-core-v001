"""OutputGuard: model text is untrusted until it passes grounding and safety checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .context import INJECTION_MARKERS
from .contracts import (
    MAX_SECTION_CHARS,
    AdviceRequest,
    AdviceSection,
    Evidence,
    EvidenceKind,
    SectionKind,
)
from .ports import ProviderSection
from .redaction import Redactor

MAX_MODEL_SECTIONS = 6
_MODEL_KINDS = frozenset({SectionKind.HYPOTHESIS, SectionKind.ACTION})
_CODE_TOKEN = re.compile(r"(?<![\w.])\d{3,}(?![\w])")
_CLASSIFICATION_REF = re.compile(
    r"(?i)\b(cst|csosn|cfop|ncm|cclasstrib|cclass)\b[^\d\n]{0,12}(\d{2,8})"
)
_DIGIT_RUN = re.compile(r"\d+")
_CLASSIFICATION_FIELDS = frozenset({"cst", "csosn", "cfop", "ncm", "cclasstrib"})
_CLASSIFICATION_EVIDENCE_KINDS = frozenset({
    EvidenceKind.TAX_DECISION,
    EvidenceKind.PRODUCT_PROFILE,
    EvidenceKind.CLASSIFICATION_CATALOG,
})
# Money and percentages are different fiscal dimensions. Matching the same
# digits in an unrelated field (or another unit) is not valid grounding.
_PERCENTAGE = re.compile(r"(?<![\w.,])(?P<value>-?\d+(?:[.,]\d+)?)[ \t]*%(?!\w)")
_BRL_AMOUNT = re.compile(
    r"(?i)(?<!\w)(?P<leading_minus>-)?R\$[ \t]*(?P<value>-?"
    r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)(?!\d|,\d|\.\d)"
)
_BRL_MARKER = re.compile(r"(?i)R\$")
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


def _percent_value(match: re.Match[str]) -> Decimal:
    return Decimal(match.group("value").replace(",", "."))


def _brl_value(match: re.Match[str]) -> Decimal:
    value = Decimal(match.group("value").replace(".", "").replace(",", "."))
    return -value if match.group("leading_minus") else value


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
        # Only deterministic, trusted evidence may ground numeric fiscal claims.
        # The user's question and external untrusted provider messages are not
        # authority for codes, rates or monetary amounts.
        trusted_by_id = {
            item.evidence_id: item for item in request.evidence if item.trusted
        }
        trusted_corpus_by_id = {
            item_id: "\n".join(item.data.values())
            for item_id, item in trusted_by_id.items()
        }
        accepted: list[AdviceSection] = []
        findings: list[str] = []
        for index, section in enumerate(sections):
            tag = f"section[{index}]"
            # A claim must be supported by its own cited, trusted evidence.
            # Another unrelated fact in the request cannot launder a citation.
            cited_corpus = "\n".join(
                trusted_corpus_by_id.get(item_id, "")
                for item_id in section.evidence_ids
            )
            cited_facts = tuple(
                trusted_by_id[item_id]
                for item_id in section.evidence_ids if item_id in trusted_by_id
            )
            reason = self._reject_reason(section, known_ids, cited_corpus, cited_facts)
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
        self, section: ProviderSection, known_ids: set[str], corpus: str,
        cited_facts: tuple[Evidence, ...],
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
        percentages = tuple(_PERCENTAGE.finditer(text))
        money = tuple(_BRL_AMOUNT.finditer(text))
        # Reject malformed or ambiguous amounts, not just absent ones.
        if text.count("%") != len(percentages) or len(_BRL_MARKER.findall(text)) != len(money):
            return "ungrounded_amount"
        # Monetary digits and rate digits are not fiscal classification codes.
        # Still require exact codes elsewhere in the cited trusted corpus.
        codes_only = _BRL_AMOUNT.sub("", _PERCENTAGE.sub("", text))
        corpus_numbers = set(_DIGIT_RUN.findall(corpus))
        for token in _CODE_TOKEN.findall(codes_only):
            if token not in corpus_numbers:
                return "ungrounded_code"
        trusted_percentages = {
            _percent_value(match) for match in _PERCENTAGE.finditer(corpus)
        }
        trusted_money = {_brl_value(match) for match in _BRL_AMOUNT.finditer(corpus)}
        if any(_percent_value(match) not in trusted_percentages for match in percentages):
            return "ungrounded_amount"
        if any(_brl_value(match) not in trusted_money for match in money):
            return "ungrounded_amount"
        for match in _CLASSIFICATION_REF.finditer(text):
            field = match.group(1).lower()
            if field == "cclass":
                field = "cclasstrib"
            # A code from a money value, rejection or different classification
            # must not authorize a model-authored fiscal classification claim.
            if field not in _CLASSIFICATION_FIELDS or not any(
                fact.kind in _CLASSIFICATION_EVIDENCE_KINDS
                and fact.data.get(field, "").strip() == match.group(2)
                for fact in cited_facts
            ):
                return "ungrounded_classification_code"
        return None
