"""T06: deterministic segregation of reviewed Simples revenue facts, 2026 only.

No tax amount, eligibility inference, credit, declaration or issuance. T07
consumes these buckets with the existing T04 rate authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import Activity

VERSION = "simples-segregation-2026/v1"
SOURCE = "https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278"


class Market(StrEnum):
    DOMESTIC = "domestic"
    EXPORT = "export"


class FederalTreatment(StrEnum):
    ORDINARY = "ordinary"
    MONOPHASE = "monophase_downstream"
    UNKNOWN = "unknown"


class LocalTreatment(StrEnum):
    ORDINARY = "ordinary"
    ICMS_SUBSTITUTED = "icms_substituted"
    ICMS_SUBSTITUTE = "icms_substitute"
    ICMS_FINAL_ADVANCE = "icms_final_advance"
    ISS_WITHHELD = "iss_withheld"
    UNKNOWN = "unknown"


def _ref(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise FiscalValidationError("reviewed revenue evidence required")


def _amount(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 10**15:
        raise FiscalValidationError("revenue must be exact nonnegative cents")


@dataclass(frozen=True, slots=True)
class RevenueLine:
    line_id: str
    cents: int
    activity: Activity
    market: Market
    federal: FederalTreatment
    local: LocalTreatment
    evidence_reference: str
    treatment_reference: str

    def __post_init__(self) -> None:
        for value in (self.line_id, self.evidence_reference, self.treatment_reference):
            _ref(value)
        _amount(self.cents)
        if not all((
            isinstance(self.activity, Activity), isinstance(self.market, Market),
            isinstance(self.federal, FederalTreatment), isinstance(self.local, LocalTreatment),
        )):
            raise FiscalValidationError("explicit reviewed classification required")


def classify_revenue(
    competence: date, lines: tuple[RevenueLine, ...], *,
    domestic_cents: int, export_cents: int,
) -> dict[str, object]:
    """Produce mutually exclusive buckets, preserving combined tax treatments.

    The control totals are unit revenue for the selected accounting basis.
    Missing or conflicting treatment blocks the whole batch for T07.
    """
    if type(competence) is not date or competence.day != 1 or competence.year != 2026:
        raise FiscalValidationError("reviewed segregation rules require a 2026 competence")
    _amount(domestic_cents)
    _amount(export_cents)
    if not isinstance(lines, tuple) or len(lines) > 10000:
        raise FiscalValidationError("bounded immutable revenue lines required")
    seen: set[str] = set()
    totals = {market: 0 for market in Market}
    groups: dict[tuple[str, ...], int] = {}
    blocked: list[dict[str, str]] = []
    audit: list[dict[str, str | int]] = []
    for line in lines:
        if not isinstance(line, RevenueLine) or line.line_id in seen:
            raise FiscalValidationError("duplicate or invalid revenue line")
        seen.add(line.line_id)
        totals[line.market] += line.cents
        goods = line.activity in {Activity.COMMERCE, Activity.INDUSTRY}
        reason = ""
        if FederalTreatment.UNKNOWN is line.federal or LocalTreatment.UNKNOWN is line.local:
            reason = "unresolved_treatment"
        elif not goods and (
            line.federal is FederalTreatment.MONOPHASE
            or line.local not in {LocalTreatment.ORDINARY, LocalTreatment.ISS_WITHHELD}
        ):
            reason = "incompatible_service_treatment"
        elif goods and line.local is LocalTreatment.ISS_WITHHELD:
            reason = "incompatible_goods_treatment"
        elif line.market is Market.EXPORT and (
            line.local is not LocalTreatment.ORDINARY
            or line.federal is not FederalTreatment.ORDINARY
        ):
            reason = "export_special_treatment_requires_review"
        audit.append({
            "line_id": line.line_id, "cents": line.cents, "activity": line.activity.value,
            "market": line.market.value, "federal": line.federal.value,
            "local": line.local.value, "evidence_reference": line.evidence_reference,
            "treatment_reference": line.treatment_reference,
        })
        if reason:
            blocked.append({"line_id": line.line_id, "reason": reason})
            continue
        key = (line.activity.value, line.market.value, line.federal.value, line.local.value)
        groups[key] = groups.get(key, 0) + line.cents
    if totals[Market.DOMESTIC] != domestic_cents or totals[Market.EXPORT] != export_cents:
        raise FiscalValidationError("revenue control totals do not reconcile")
    buckets = [
        {"activity": a, "market": m, "federal": f, "local": l, "cents": cents}
        for (a, m, f, l), cents in sorted(groups.items())
    ]
    payload: dict[str, object] = {
        "version": VERSION, "competence": competence.isoformat(),
        "domestic_cents": domestic_cents, "export_cents": export_cents,
        "status": "blocked" if blocked else "classified",
        "buckets": [] if blocked else buckets,
        "blocked": sorted(blocked, key=lambda item: item["line_id"]),
        "evidence": sorted(audit, key=lambda item: str(item["line_id"])),
        "source": SOURCE,
    }
    return {**payload, "digest": hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()}
