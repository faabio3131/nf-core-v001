"""Versioned federal tax-regime classification, separate from NF-e/NFC-e CRT.

A declaration is an input/snapshot only; it does not modify FiscalProfile,
calculate taxes, persist data or grant fiscal production authority.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalProfile,
    FiscalValidationError,
    TaxRegimeCode,
)


class FederalIncomeTaxRegime(StrEnum):
    SIMPLES_NACIONAL = "simples_nacional"
    LUCRO_PRESUMIDO = "lucro_presumido"
    LUCRO_REAL = "lucro_real"


@dataclass(frozen=True, slots=True)
class FederalRegimeDeclaration:
    """Explicit, effective-dated and scope-bound corporate regime evidence.

    The CRT alone cannot distinguish Lucro Real from Lucro Presumido.
    Source authority and persistence integration remain subject to RTC-02 review.
    """

    scope: ExecutionScope
    crt: TaxRegimeCode
    federal_income_tax_regime: FederalIncomeTaxRegime
    effective_from: datetime
    source_reference: str
    version: int = 1
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.crt, TaxRegimeCode):
            raise FiscalValidationError("crt must be TaxRegimeCode")
        if not isinstance(self.federal_income_tax_regime, FederalIncomeTaxRegime):
            raise FiscalValidationError("federal_income_tax_regime must be explicit")
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise FiscalValidationError("effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise FiscalValidationError("effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise FiscalValidationError("effective_to must follow effective_from")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise FiscalValidationError("version must be an integer >= 1")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise FiscalValidationError("source_reference is required")
        if len(self.source_reference.strip()) > 1000:
            raise FiscalValidationError("source_reference exceeds length limit")
        object.__setattr__(self, "source_reference", self.source_reference.strip())

    def assert_effective_in_scope(self, scope: ExecutionScope, instant: datetime) -> None:
        """Raise on scope/time mismatch instead of selecting an unsafe fallback."""
        if not isinstance(scope, ExecutionScope) or scope.partition_key != self.scope.partition_key:
            raise FiscalValidationError("federal regime scope mismatch")
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise FiscalValidationError("instant must be timezone-aware")
        if instant < self.effective_from or (
            self.effective_to is not None and instant >= self.effective_to
        ):
            raise FiscalValidationError("federal regime declaration is not effective")


def resolve_federal_regime_for_profile(
    profile: FiscalProfile,
    declaration: FederalRegimeDeclaration,
    instant: datetime,
) -> FederalIncomeTaxRegime:
    """Validate a declaration against the existing issuer fiscal authority.

    This is a pure, fail-closed lookup: it never infers the federal regime
    from CRT and does not persist or activate the declaration.
    """
    if not isinstance(profile, FiscalProfile):
        raise FiscalValidationError("profile must be FiscalProfile")
    if not isinstance(declaration, FederalRegimeDeclaration):
        raise FiscalValidationError("federal regime declaration is required")
    declaration.assert_effective_in_scope(profile.scope, instant)
    if not profile.is_effective_at(instant):
        raise FiscalValidationError("issuer fiscal profile is not effective")
    if profile.tax_regime != declaration.crt:
        raise FiscalValidationError("federal regime CRT does not match issuer profile")
    return declaration.federal_income_tax_regime


def resolve_federal_regime_timeline(
    profile: FiscalProfile,
    declarations: Iterable[FederalRegimeDeclaration],
    instant: datetime,
) -> FederalIncomeTaxRegime:
    """Select one effective corporate regime, rejecting overlaps and foreign scopes.

    The caller must supply the authoritative declarations for one fiscal scope.
    Gaps, overlap and scope leakage never receive a default classification.
    """
    if not isinstance(profile, FiscalProfile):
        raise FiscalValidationError("profile must be FiscalProfile")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise FiscalValidationError("instant must be timezone-aware")
    items = tuple(declarations)
    if not items:
        raise FiscalValidationError("no federal regime declarations were supplied")
    for declaration in items:
        if not isinstance(declaration, FederalRegimeDeclaration):
            raise FiscalValidationError("invalid federal regime declaration in timeline")
        if declaration.scope.partition_key != profile.scope.partition_key:
            raise FiscalValidationError("federal regime timeline scope mismatch")
    ordered = sorted(items, key=lambda item: item.effective_from)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.effective_to is None or previous.effective_to > current.effective_from:
            raise FiscalValidationError("federal regime effective periods overlap")
    effective = [
        item for item in ordered
        if item.effective_from <= instant
        and (item.effective_to is None or instant < item.effective_to)
    ]
    if len(effective) != 1:
        raise FiscalValidationError("no unambiguous federal regime effective at instant")
    return resolve_federal_regime_for_profile(profile, effective[0], instant)
