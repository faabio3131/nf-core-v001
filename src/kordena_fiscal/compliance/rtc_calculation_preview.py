"""RTC-04 candidate: strictly evidenced Decimal preview, not fiscal execution.

The artifact hash is an integrity check, NOT a proof of normative authenticity.
No default rate, tax type, XML, credit or fiscal side effect is provided. Production
use requires independently reviewed official source and a separate approval gate.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP

from kordena_fiscal.compliance.rtc import (
    ReformTaxClassificationSnapshot,
    ReformTaxComponent,
    ReformTaxComponentSnapshot,
    RegulatoryArtifactKind,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_catalog import VerifiedRtcClassificationCatalog
from kordena_fiscal.compliance.rtc_evidence import verify_regulatory_artifact_bytes
from kordena_fiscal.domain import FiscalValidationError, Money

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
