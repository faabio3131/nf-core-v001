"""Host-neutral models for deterministic tax-rule resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalProductProfile,
    FiscalValidationError,
    TaxRegimeCode,
)

_CODE = re.compile(r"^[A-Z0-9._/-]+$")
_DIGITS = re.compile(r"^\d+$")


class TaxOperationType(StrEnum):
    """Generic operation families understood by the fiscal rule engine."""

    SALE = "sale"
    RETURN = "return"
    TRANSFER = "transfer"
    OTHER = "other"


class RecipientTaxProfile(StrEnum):
    """Tax-relevant recipient profiles without host/customer-model coupling."""

    CONSUMER_FINAL = "consumer_final"
    TAXPAYER = "taxpayer"
    NON_TAXPAYER = "non_taxpayer"


def _required_text(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _optional_code(value: str | None, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if len(normalized) > max_length or not _CODE.fullmatch(normalized):
        raise FiscalValidationError(f"{field_name} has invalid format")
    return normalized


@dataclass(frozen=True, slots=True)
class TaxRuleContext:
    """All deterministic inputs used to resolve one tax decision."""

    scope: ExecutionScope
    instant: datetime
    jurisdiction: BrazilianJurisdiction
    tax_regime: TaxRegimeCode
    document_kind: FiscalDocumentKind
    operation_type: TaxOperationType
    recipient_profile: RecipientTaxProfile
    product: FiscalProductProfile

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be an ExecutionScope")
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise FiscalValidationError("instant must be timezone-aware")
        if not isinstance(self.jurisdiction, BrazilianJurisdiction):
            raise FiscalValidationError("jurisdiction must be a BrazilianJurisdiction")
        if not isinstance(self.tax_regime, TaxRegimeCode):
            raise FiscalValidationError("tax_regime must be a TaxRegimeCode")
        if not isinstance(self.document_kind, FiscalDocumentKind):
            raise FiscalValidationError("document_kind must be a FiscalDocumentKind")
        if not isinstance(self.operation_type, TaxOperationType):
            raise FiscalValidationError("operation_type must be a TaxOperationType")
        if not isinstance(self.recipient_profile, RecipientTaxProfile):
            raise FiscalValidationError("recipient_profile must be a RecipientTaxProfile")
        if not isinstance(self.product, FiscalProductProfile):
            raise FiscalValidationError("product must be a FiscalProductProfile")
        if self.product.scope.partition_key != self.scope.partition_key:
            raise FiscalValidationError("product and tax context must share the same scope")
        if not self.product.is_effective_at(self.instant):
            raise FiscalValidationError("product fiscal profile is not effective at instant")


@dataclass(frozen=True, slots=True)
class TaxRuleSelector:
    """Optional constraints that determine whether a rule matches a context."""

    state_code: str | None = None
    municipality_ibge_code: str | None = None
    tax_regime: TaxRegimeCode | None = None
    document_kind: FiscalDocumentKind | None = None
    operation_type: TaxOperationType | None = None
    recipient_profile: RecipientTaxProfile | None = None
    ncm_prefix: str | None = None

    def __post_init__(self) -> None:
        state_code = self.state_code
        municipality_code = self.municipality_ibge_code
        if state_code is not None:
            state_code = BrazilianJurisdiction(state_code).state_code
            object.__setattr__(self, "state_code", state_code)
        if municipality_code is not None:
            if state_code is None:
                raise FiscalValidationError(
                    "municipality selector requires an explicit state_code"
                )
            jurisdiction = BrazilianJurisdiction(state_code, municipality_code)
            object.__setattr__(
                self,
                "municipality_ibge_code",
                jurisdiction.municipality_ibge_code,
            )
        if self.tax_regime is not None and not isinstance(self.tax_regime, TaxRegimeCode):
            raise FiscalValidationError("tax_regime selector must be a TaxRegimeCode")
        if self.document_kind is not None and not isinstance(
            self.document_kind,
            FiscalDocumentKind,
        ):
            raise FiscalValidationError(
                "document_kind selector must be a FiscalDocumentKind"
            )
        if self.operation_type is not None and not isinstance(
            self.operation_type,
            TaxOperationType,
        ):
            raise FiscalValidationError(
                "operation_type selector must be a TaxOperationType"
            )
        if self.recipient_profile is not None and not isinstance(
            self.recipient_profile,
            RecipientTaxProfile,
        ):
            raise FiscalValidationError(
                "recipient_profile selector must be a RecipientTaxProfile"
            )
        if self.ncm_prefix is not None:
            prefix = self.ncm_prefix.strip()
            if not 2 <= len(prefix) <= 8 or not _DIGITS.fullmatch(prefix):
                raise FiscalValidationError(
                    "ncm_prefix must contain between 2 and 8 digits"
                )
            object.__setattr__(self, "ncm_prefix", prefix)

    @property
    def specificity(self) -> tuple[int, int]:
        """Return structural specificity and NCM prefix depth for deterministic ranking."""

        values = (
            self.state_code,
            self.municipality_ibge_code,
            self.tax_regime,
            self.document_kind,
            self.operation_type,
            self.recipient_profile,
            self.ncm_prefix,
        )
        constrained = sum(value is not None for value in values)
        ncm_depth = len(self.ncm_prefix) if self.ncm_prefix is not None else 0
        return constrained, ncm_depth

    def matches(self, context: TaxRuleContext) -> bool:
        if self.state_code is not None and self.state_code != context.jurisdiction.state_code:
            return False
        if (
            self.municipality_ibge_code is not None
            and self.municipality_ibge_code
            != context.jurisdiction.municipality_ibge_code
        ):
            return False
        if self.tax_regime is not None and self.tax_regime != context.tax_regime:
            return False
        if self.document_kind is not None and self.document_kind != context.document_kind:
            return False
        if self.operation_type is not None and self.operation_type != context.operation_type:
            return False
        if (
            self.recipient_profile is not None
            and self.recipient_profile != context.recipient_profile
        ):
            return False
        if self.ncm_prefix is not None and not context.product.ncm.value.startswith(
            self.ncm_prefix
        ):
            return False
        return True


@dataclass(frozen=True, slots=True)
class TaxRuleOutcome:
    """Canonical tax classification selected by a rule, not provider-specific XML."""

    cfop: str
    icms_code: str
    pis_cst: str
    cofins_cst: str
    ibs_cbs_classification_code: str | None = None
    legal_notes: tuple[str, ...] = ()
    # RTC metadata is opt-in: legacy TaxRule outcomes keep their original contract.
    ibs_cbs_cst_code: str | None = None
    ibs_cbs_classification_table_version: str | None = None

    def __post_init__(self) -> None:
        cfop = self.cfop.strip()
        if len(cfop) != 4 or not cfop.isdigit():
            raise FiscalValidationError("cfop must contain exactly 4 digits")
        object.__setattr__(self, "cfop", cfop)

        icms_code = self.icms_code.strip()
        if len(icms_code) not in {2, 3} or not icms_code.isdigit():
            raise FiscalValidationError("icms_code must contain 2 or 3 digits")
        object.__setattr__(self, "icms_code", icms_code)

        for field_name in ("pis_cst", "cofins_cst"):
            value = getattr(self, field_name).strip()
            if len(value) != 2 or not value.isdigit():
                raise FiscalValidationError(f"{field_name} must contain exactly 2 digits")
            object.__setattr__(self, field_name, value)

        object.__setattr__(
            self,
            "ibs_cbs_classification_code",
            _optional_code(
                self.ibs_cbs_classification_code,
                "ibs_cbs_classification_code",
                32,
            ),
        )
        if self.ibs_cbs_cst_code is not None:
            cst = self.ibs_cbs_cst_code.strip()
            if len(cst) != 3 or not cst.isascii() or not cst.isdigit():
                raise FiscalValidationError("ibs_cbs_cst_code must contain 3 digits")
            object.__setattr__(self, "ibs_cbs_cst_code", cst)
        if self.ibs_cbs_classification_table_version is not None:
            version = _required_text(
                self.ibs_cbs_classification_table_version,
                "ibs_cbs_classification_table_version",
                max_length=64,
            )
            object.__setattr__(self, "ibs_cbs_classification_table_version", version)
        normalized_notes = tuple(
            _required_text(note, "legal_note", max_length=500) for note in self.legal_notes
        )
        object.__setattr__(self, "legal_notes", normalized_notes)


@dataclass(frozen=True, slots=True)
class TaxRule:
    """Versioned, effective-dated and explainable fiscal classification rule."""

    rule_id: str
    version: int
    selector: TaxRuleSelector
    outcome: TaxRuleOutcome
    source_normative: str
    effective_from: datetime
    effective_to: datetime | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_id",
            _required_text(self.rule_id, "rule_id", max_length=128),
        )
        if self.version < 1:
            raise FiscalValidationError("rule version must be >= 1")
        if not isinstance(self.selector, TaxRuleSelector):
            raise FiscalValidationError("selector must be a TaxRuleSelector")
        if not isinstance(self.outcome, TaxRuleOutcome):
            raise FiscalValidationError("outcome must be a TaxRuleOutcome")
        object.__setattr__(
            self,
            "source_normative",
            _required_text(self.source_normative, "source_normative", max_length=500),
        )
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise FiscalValidationError("rule effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise FiscalValidationError("rule effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise FiscalValidationError(
                    "rule effective_to must be after effective_from"
                )
        if self.priority < 0:
            raise FiscalValidationError("rule priority must be >= 0")

    def is_effective_at(self, instant: datetime) -> bool:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise FiscalValidationError("instant must be timezone-aware")
        if instant < self.effective_from:
            return False
        return self.effective_to is None or instant < self.effective_to

    def matches(self, context: TaxRuleContext) -> bool:
        return self.is_effective_at(context.instant) and self.selector.matches(context)

    @property
    def rank(self) -> tuple[int, int, int]:
        constrained, ncm_depth = self.selector.specificity
        return constrained, ncm_depth, self.priority


@dataclass(frozen=True, slots=True)
class TaxDecision:
    """Explainable result of deterministic rule resolution."""

    rule_id: str
    rule_version: int
    source_normative: str
    outcome: TaxRuleOutcome
    rank: tuple[int, int, int]
