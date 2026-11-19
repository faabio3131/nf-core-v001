"""Versioned Reforma Tributária do Consumo compliance primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from kordena_fiscal.domain import (
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalValidationError,
    Money,
    TaxRegimeCode,
)

_CODE = re.compile(r"^[A-Z0-9._/-]+$")


class RegulatoryBaselineError(FiscalDomainError):
    """Raised when regulatory evidence is incomplete or internally inconsistent."""


class RtcPolicyResolutionError(FiscalDomainError):
    """Raised when RTC obligation/validation policy cannot be resolved safely."""


class ReformTaxComponent(StrEnum):
    CBS = "cbs"
    IBS_STATE = "ibs_state"
    IBS_MUNICIPAL = "ibs_municipal"
    SELECTIVE_TAX = "selective_tax"


class RegulatoryArtifactKind(StrEnum):
    TECHNICAL_NOTE = "technical_note"
    TECHNICAL_REPORT = "technical_report"
    CLASSIFICATION_TABLE = "classification_table"
    RATE_TABLE = "rate_table"
    JOINT_ACT = "joint_act"
    TECHNICAL_JOINT_ACT = "technical_joint_act"
    SCHEMA = "schema"
    OTHER = "other"


class LegalObligationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    DEFERRED = "deferred"


class TechnicalValidationMode(StrEnum):
    STRICT_REJECTION = "strict_rejection"
    TOLERANT = "tolerant"


class RtcNfseSupplyCategory(StrEnum):
    """Reviewed category from Act 4/2026 art. 1 III as amended by Act 7/2026.

    Never infer legal classification from cTribNac or free-text browser inputs.
    The category must be supplied by independently reviewed fiscal policy.
    """

    ISS_GENERAL_D = "iss_general_d"
    DIGITAL_PLATFORM_A = "digital_platform_a"
    ISS_SOFTWARE_B = "iss_software_b"
    ISS_TRANSPORT_C = "iss_transport_c"
    INTANGIBLE_E = "intangible_e"
    CONDOMINIUM_F = "condominium_f"
    LEASE_G = "lease_g"
    OTHER_H = "other_h"


def _required(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _optional_code(value: str | None, field_name: str, max_length: int = 64) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if len(normalized) > max_length or not _CODE.fullmatch(normalized):
        raise FiscalValidationError(f"{field_name} has invalid format")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


def _percent(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FiscalValidationError(f"{field_name} must be a finite Decimal")
    if value < 0 or value > 100:
        raise FiscalValidationError(f"{field_name} must be between 0 and 100")
    return value


def _sha256_optional(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FiscalValidationError("checksum_sha256 must be SHA-256 hex")
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise FiscalValidationError("checksum_sha256 must be SHA-256 hex")
    return normalized


@dataclass(frozen=True, slots=True)
class RegulatoryArtifactPin:
    """Immutable metadata pin for one official regulatory artifact/version."""

    artifact_id: str
    kind: RegulatoryArtifactKind
    version: str
    published_on: date
    source_reference: str
    effective_from: date | None = None
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _required(self.artifact_id, "artifact_id", 128))
        if not isinstance(self.kind, RegulatoryArtifactKind):
            raise FiscalValidationError("kind must be RegulatoryArtifactKind")
        object.__setattr__(self, "version", _required(self.version, "version", 64))
        if not isinstance(self.published_on, date):
            raise FiscalValidationError("published_on must be date")
        if self.effective_from is not None and not isinstance(self.effective_from, date):
            raise FiscalValidationError("effective_from must be date")
        object.__setattr__(
            self,
            "source_reference",
            _required(self.source_reference, "source_reference", 1000),
        )
        object.__setattr__(self, "checksum_sha256", _sha256_optional(self.checksum_sha256))


@dataclass(frozen=True, slots=True)
class RegulatoryBaseline:
    """Auditable snapshot of which official artifact versions informed a release."""

    baseline_id: str
    version: int
    captured_at: datetime
    artifacts: tuple[RegulatoryArtifactPin, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_id", _required(self.baseline_id, "baseline_id", 128))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise FiscalValidationError("baseline version must be an integer >= 1")
        _aware(self.captured_at, "captured_at")
        if not self.artifacts:
            raise RegulatoryBaselineError("regulatory baseline requires at least one artifact")
        if not all(isinstance(item, RegulatoryArtifactPin) for item in self.artifacts):
            raise FiscalValidationError("artifacts must contain RegulatoryArtifactPin values")
        identities = [(item.artifact_id, item.version) for item in self.artifacts]
        if len(identities) != len(set(identities)):
            raise RegulatoryBaselineError("regulatory baseline contains duplicate artifact version")

    def artifact(self, artifact_id: str) -> RegulatoryArtifactPin:
        normalized = _required(artifact_id, "artifact_id", 128)
        matches = [item for item in self.artifacts if item.artifact_id == normalized]
        if len(matches) != 1:
            raise RegulatoryBaselineError(
                f"expected exactly one pinned artifact for {normalized}, found {len(matches)}"
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class ReformTaxClassificationSnapshot:
    """Versioned classification evidence resolved by external tax rules."""

    cst_code: str
    classification_code: str | None
    classification_table_version: str
    presumed_credit_code: str | None = None

    def __post_init__(self) -> None:
        cst = self.cst_code.strip()
        if not cst.isdigit() or not 2 <= len(cst) <= 3:
            raise FiscalValidationError("cst_code must contain 2 or 3 digits")
        object.__setattr__(self, "cst_code", cst)
        object.__setattr__(
            self,
            "classification_code",
            _optional_code(self.classification_code, "classification_code", 32),
        )
        object.__setattr__(
            self,
            "classification_table_version",
            _required(
                self.classification_table_version,
                "classification_table_version",
                64,
            ),
        )
        object.__setattr__(
            self,
            "presumed_credit_code",
            _optional_code(self.presumed_credit_code, "presumed_credit_code", 32),
        )


@dataclass(frozen=True, slots=True)
class ReformTaxComponentSnapshot:
    """Frozen resolved tax evidence; this class does not invent tax-calculation formulas."""

    component: ReformTaxComponent
    tax_base: Money
    nominal_rate_percent: Decimal
    effective_rate_percent: Decimal
    tax_amount: Money
    classification: ReformTaxClassificationSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.component, ReformTaxComponent):
            raise FiscalValidationError("component must be ReformTaxComponent")
        if not isinstance(self.tax_base, Money) or self.tax_base.amount < 0:
            raise FiscalValidationError("tax_base must be non-negative Money")
        _percent(self.nominal_rate_percent, "nominal_rate_percent")
        _percent(self.effective_rate_percent, "effective_rate_percent")
        if not isinstance(self.tax_amount, Money) or self.tax_amount.amount < 0:
            raise FiscalValidationError("tax_amount must be non-negative Money")
        if not isinstance(self.classification, ReformTaxClassificationSnapshot):
            raise FiscalValidationError(
                "classification must be ReformTaxClassificationSnapshot"
            )


@dataclass(frozen=True, slots=True)
class ReformTaxSnapshot:
    """Immutable IBS/CBS/IS result linked to a regulatory baseline and rule set."""

    rule_set_id: str
    rule_set_version: int
    source_normative: str
    resolved_at: datetime
    baseline_id: str
    baseline_version: int
    components: tuple[ReformTaxComponentSnapshot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_set_id", _required(self.rule_set_id, "rule_set_id", 128))
        if not isinstance(self.rule_set_version, int) or isinstance(self.rule_set_version, bool):
            raise FiscalValidationError("rule_set_version must be an integer")
        if self.rule_set_version < 1:
            raise FiscalValidationError("rule_set_version must be >= 1")
        object.__setattr__(
            self,
            "source_normative",
            _required(self.source_normative, "source_normative", 1000),
        )
        _aware(self.resolved_at, "resolved_at")
        object.__setattr__(self, "baseline_id", _required(self.baseline_id, "baseline_id", 128))
        if not isinstance(self.baseline_version, int) or isinstance(self.baseline_version, bool):
            raise FiscalValidationError("baseline_version must be an integer")
        if self.baseline_version < 1:
            raise FiscalValidationError("baseline_version must be >= 1")
        if not self.components:
            raise FiscalValidationError("reform tax snapshot requires at least one component")
        if not all(isinstance(item, ReformTaxComponentSnapshot) for item in self.components):
            raise FiscalValidationError(
                "components must contain ReformTaxComponentSnapshot values"
            )
        identities = [item.component for item in self.components]
        if len(identities) != len(set(identities)):
            raise FiscalValidationError("reform tax components must be unique")


@dataclass(frozen=True, slots=True)
class RtcEmissionPolicyRule:
    """Effective-dated legal obligation kept separate from technical rejection behavior."""

    rule_id: str
    version: int
    document_kind: FiscalDocumentKind
    effective_from: datetime
    obligation: LegalObligationStatus
    validation_mode: TechnicalValidationMode
    source_normative: str
    tax_regime: TaxRegimeCode | None = None
    effective_to: datetime | None = None
    priority: int = 0
    nfse_supply_category: RtcNfseSupplyCategory | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _required(self.rule_id, "rule_id", 128))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise FiscalValidationError("rule version must be an integer >= 1")
        if not isinstance(self.document_kind, FiscalDocumentKind):
            raise FiscalValidationError("document_kind must be FiscalDocumentKind")
        _aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _aware(self.effective_to, "effective_to")
            if self.effective_to <= self.effective_from:
                raise FiscalValidationError("effective_to must be after effective_from")
        if not isinstance(self.obligation, LegalObligationStatus):
            raise FiscalValidationError("obligation must be LegalObligationStatus")
        if not isinstance(self.validation_mode, TechnicalValidationMode):
            raise FiscalValidationError("validation_mode must be TechnicalValidationMode")
        if self.tax_regime is not None and not isinstance(self.tax_regime, TaxRegimeCode):
            raise FiscalValidationError("tax_regime must be TaxRegimeCode")
        if self.nfse_supply_category is not None and (
            not isinstance(self.nfse_supply_category, RtcNfseSupplyCategory)
            or self.document_kind is not FiscalDocumentKind.NFSE
        ):
            raise FiscalValidationError("NFS-e supply category requires canonical NFS-e kind")
        object.__setattr__(
            self,
            "source_normative",
            _required(self.source_normative, "source_normative", 1000),
        )
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise FiscalValidationError("priority must be an integer >= 0")

    def matches(
        self,
        *,
        document_kind: FiscalDocumentKind,
        tax_regime: TaxRegimeCode,
        instant: datetime,
        nfse_supply_category: RtcNfseSupplyCategory | None = None,
    ) -> bool:
        _aware(instant, "instant")
        if self.document_kind is not document_kind:
            return False
        if self.tax_regime is not None and self.tax_regime is not tax_regime:
            return False
        if self.nfse_supply_category is not None and (
            self.nfse_supply_category is not nfse_supply_category
        ):
            return False
        if instant < self.effective_from:
            return False
        return self.effective_to is None or instant < self.effective_to

    @property
    def rank(self) -> tuple[int, int]:
        return (1 if self.tax_regime is not None else 0, self.priority)


class RtcEmissionPolicyResolver:
    """Deterministic fail-closed resolution of legal and technical RTC policy."""

    def __init__(self, rules: tuple[RtcEmissionPolicyRule, ...]) -> None:
        if not rules or not all(isinstance(rule, RtcEmissionPolicyRule) for rule in rules):
            raise FiscalValidationError("rules must contain at least one RtcEmissionPolicyRule")
        self._rules = rules

    def resolve(
        self,
        *,
        document_kind: FiscalDocumentKind,
        tax_regime: TaxRegimeCode,
        instant: datetime,
        nfse_supply_category: RtcNfseSupplyCategory | None = None,
    ) -> RtcEmissionPolicyRule:
        if not isinstance(document_kind, FiscalDocumentKind):
            raise FiscalValidationError("document_kind must be FiscalDocumentKind")
        if not isinstance(tax_regime, TaxRegimeCode):
            raise FiscalValidationError("tax_regime must be TaxRegimeCode")
        if nfse_supply_category is not None and (
            not isinstance(nfse_supply_category, RtcNfseSupplyCategory)
            or document_kind is not FiscalDocumentKind.NFSE
        ):
            raise FiscalValidationError("reviewed NFS-e supply category is invalid")
        _aware(instant, "instant")
        matches = [
            rule
            for rule in self._rules
            if rule.matches(
                document_kind=document_kind,
                tax_regime=tax_regime,
                instant=instant,
                nfse_supply_category=nfse_supply_category,
            )
        ]
        if not matches:
            raise RtcPolicyResolutionError("no effective RTC emission policy matches context")
        best_rank = max(rule.rank for rule in matches)
        winners = [rule for rule in matches if rule.rank == best_rank]
        if len(winners) != 1:
            raise RtcPolicyResolutionError("ambiguous RTC emission policy resolution")
        return winners[0]
