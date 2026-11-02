"""RTC-04 candidate: strictly evidenced Decimal preview, not fiscal execution.

The artifact hash is an integrity check, NOT a proof of normative authenticity.
No default rate, tax type, XML, credit or fiscal side effect is provided. Production
use requires independently reviewed official source and a separate approval gate.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

from kordena_fiscal.compliance.rtc import (
    ReformTaxClassificationSnapshot,
    ReformTaxComponent,
    ReformTaxComponentSnapshot,
    RegulatoryArtifactKind,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_catalog import (
    VerifiedRtcClassificationCatalog,
    resolve_rule_with_verified_rtc_catalog,
)
from kordena_fiscal.compliance.rtc_evidence import verify_regulatory_artifact_bytes
from kordena_fiscal.domain import FiscalValidationError, Money, TaxRegimeCode
from kordena_fiscal.tax import TaxDecision, TaxRule, TaxRuleContext, TaxRuleEngine

_ALLOWED_ROUNDING = {"ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_HALF_EVEN": ROUND_HALF_EVEN}
_ALLOWED_QUANTA = {"0.01", "0.0001"}


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RegulatoryBaselineError("duplicate RTC rate artifact JSON key")
        result[key] = value
    return result


def _decimal_text(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise RegulatoryBaselineError(f"{field} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise RegulatoryBaselineError(f"{field} is not a Decimal") from exc
    if not parsed.is_finite():
        raise RegulatoryBaselineError(f"{field} must be finite")
    return parsed


def calculate_evidenced_rtc_preview(
    *,
    baseline: RegulatoryBaseline,
    rate_artifact_id: str,
    rate_payload: bytes,
    catalog: VerifiedRtcClassificationCatalog,
    classification: ReformTaxClassificationSnapshot,
    tax_base: Money,
    instant: datetime,
) -> ReformTaxComponentSnapshot:
    """Preview one pinned rate table entry using Decimal.

    Never take a rate/rounding policy from HTTP, model output or heuristic. The
    reviewed source and fiscal applicability remain obligations of the caller;
    this function is deliberately not connected to issuing or tax decisions.
    """
    if not isinstance(baseline, RegulatoryBaseline):
        raise RegulatoryBaselineError("regulatory baseline required")
    artifact = baseline.artifact(rate_artifact_id)
    if artifact.kind is not RegulatoryArtifactKind.RATE_TABLE:
        raise RegulatoryBaselineError("rate artifact must be a rate_table")
    # A checksum pin is not proof of temporal applicability. Do not calculate a
    # historical period from a source that was unpublished or not yet effective.
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise RegulatoryBaselineError("RTC preview instant must be timezone-aware")
    if artifact.effective_from is None:
        raise RegulatoryBaselineError("RTC rate artifact requires explicit effective_from")
    if instant.date() < artifact.published_on:
        raise RegulatoryBaselineError("RTC rate artifact was not published at instant")
    if instant.date() < artifact.effective_from:
        raise RegulatoryBaselineError("RTC rate artifact was not effective at instant")
    verify_regulatory_artifact_bytes(artifact, rate_payload)
    try:
        raw = json.loads(rate_payload, object_pairs_hook=_unique_json_pairs)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RegulatoryBaselineError("rate artifact must be valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "artifact_id", "artifact_version",
        "component", "rate_percent", "quantum", "rounding_mode",
    }:
        raise RegulatoryBaselineError("invalid RTC rate preview artifact schema")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise RegulatoryBaselineError("invalid RTC rate artifact schema_version")
    if raw["artifact_id"] != artifact.artifact_id or raw["artifact_version"] != artifact.version:
        raise RegulatoryBaselineError("RTC rate artifact identity or version mismatch")
    try:
        component = ReformTaxComponent(raw["component"])
    except (ValueError, TypeError) as exc:
        raise RegulatoryBaselineError("invalid RTC tax component") from exc
    rate = _decimal_text(raw["rate_percent"], "rate_percent")
    if not Decimal("0") <= rate <= Decimal("100"):
        raise RegulatoryBaselineError("rate_percent outside 0..100")
    if not isinstance(raw["quantum"], str) or raw["quantum"] not in _ALLOWED_QUANTA:
        raise RegulatoryBaselineError("unsupported monetary quantum")
    quantum = Decimal(raw["quantum"])
    rounding_name = raw["rounding_mode"]
    if not isinstance(rounding_name, str) or rounding_name not in _ALLOWED_ROUNDING:
        raise RegulatoryBaselineError("unsupported rounding mode")
    if not isinstance(tax_base, Money) or tax_base.amount < 0:
        raise FiscalValidationError("non-negative Money tax_base required")
    if not isinstance(catalog, VerifiedRtcClassificationCatalog):
        raise RegulatoryBaselineError("verified RTC classification catalog required")
    catalog.require_classification(classification)
    # This intentionally does not implement reductions, credits, deferrals,
    # tax-exclusive bases, selective-tax incidences or transitions.
    amount = (tax_base.amount * rate / Decimal("100")).quantize(
        quantum, rounding=_ALLOWED_ROUNDING[rounding_name]
    )
    return ReformTaxComponentSnapshot(
        component=component,
        tax_base=tax_base,
        nominal_rate_percent=rate,
        effective_rate_percent=rate,
        tax_amount=Money(amount),
        classification=classification,
    )


def calculate_rule_bound_rtc_preview(
    *,
    engine: TaxRuleEngine,
    context: TaxRuleContext,
    rules: Iterable[TaxRule],
    baseline: RegulatoryBaseline,
    rate_artifact_id: str,
    rate_payload: bytes,
    catalog: VerifiedRtcClassificationCatalog,
    tax_base: Money,
) -> tuple[TaxDecision, ReformTaxComponentSnapshot]:
    """Compose the canonical tax decision and an isolated evidence-only preview.

    Context and CST/cClassTrib come exclusively from the existing TaxRuleEngine;
    callers cannot substitute classification or fiscal instant after resolution.
    This is NOT an authoritative tax calculation or permission to issue XML.
    """
    if not isinstance(engine, TaxRuleEngine) or not isinstance(context, TaxRuleContext):
        raise FiscalValidationError("canonical TaxRuleEngine and TaxRuleContext required")
    decision, classification = resolve_rule_with_verified_rtc_catalog(
        engine=engine,
        context=context,
        rules=rules,
        catalog=catalog,
    )
    snapshot = calculate_evidenced_rtc_preview(
        baseline=baseline,
        rate_artifact_id=rate_artifact_id,
        rate_payload=rate_payload,
        catalog=catalog,
        classification=classification,
        tax_base=tax_base,
        instant=context.instant,
    )
    return decision, snapshot


# Law text: LC 214/2025, as amended by LC 227/2026, arts. 343, 346, 348.
# https://www2.camara.leg.br/legin/fed/leicom/2025/
# leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html
_RTC_2026_IBS_STATE_REFERENCE = Decimal("0.1")
_RTC_2026_CBS_REFERENCE = Decimal("0.9")
_RTC_2026_SOURCE = "LC 214/2025 (atualizada), arts. 343, 346 e 348"


@dataclass(frozen=True, slots=True)
class Rtc2026NominalReferencePreview:
    """Unrounded statutory nominal comparison, NEVER a payable/issuable tax amount.

    In particular this does not compute tax-base adjustments, benefits, credits,
    collection/compensation, currency rounding or XML totals.
    """

    decision: TaxDecision
    classification: ReformTaxClassificationSnapshot
    tax_base: Money
    cbs_rate_percent: Decimal
    ibs_state_rate_percent: Decimal
    cbs_unrounded: Decimal
    ibs_state_unrounded: Decimal
    source_normative: str


def calculate_2026_nominal_reference_preview(
    *,
    engine: TaxRuleEngine,
    context: TaxRuleContext,
    rules: Iterable[TaxRule],
    catalog: VerifiedRtcClassificationCatalog,
    tax_base: Money,
    confirmed_standard_nonfuel_operation: bool,
    confirmed_no_differentiated_or_special_regime: bool,
    confirmed_tax_base_reviewed: bool,
) -> Rtc2026NominalReferencePreview:
    """Isolated reference arithmetic from LC 214 arts. 343/346/348.

    Review flags are caller attestations, NOT proof of fiscal eligibility. The
    output is deliberately not a ReformTaxComponentSnapshot and cannot be used
    in authoritative fiscal emission; only law-scoped, unrounded comparison.
    No implied eligibility for Simples, fuel, benefits, exemptions or IS.
    """
    if not isinstance(context, TaxRuleContext) or not isinstance(engine, TaxRuleEngine):
        raise FiscalValidationError("canonical RTC tax context and engine required")
    if context.instant.year != 2026:
        raise RegulatoryBaselineError("2026 nominal reference applies only to 2026 facts")
    if context.tax_regime is not TaxRegimeCode.NORMAL:
        raise RegulatoryBaselineError("2026 reference not applicable to Simples Nacional")
    if (
        confirmed_standard_nonfuel_operation is not True
        or confirmed_no_differentiated_or_special_regime is not True
        or confirmed_tax_base_reviewed is not True
    ):
        raise RegulatoryBaselineError("2026 nominal reference requires reviewed standard scope")
    if (
        not isinstance(tax_base, Money)
        or not tax_base.amount.is_finite()
        or tax_base.amount < 0
    ):
        raise FiscalValidationError("2026 nominal reference requires nonnegative finite Money")
    decision, classification = resolve_rule_with_verified_rtc_catalog(
        engine=engine, context=context, rules=rules, catalog=catalog,
    )
    return Rtc2026NominalReferencePreview(
        decision=decision,
        classification=classification,
        tax_base=tax_base,
        cbs_rate_percent=_RTC_2026_CBS_REFERENCE,
        ibs_state_rate_percent=_RTC_2026_IBS_STATE_REFERENCE,
        cbs_unrounded=tax_base.amount * _RTC_2026_CBS_REFERENCE / Decimal("100"),
        ibs_state_unrounded=tax_base.amount * _RTC_2026_IBS_STATE_REFERENCE / Decimal("100"),
        source_normative=_RTC_2026_SOURCE,
    )
