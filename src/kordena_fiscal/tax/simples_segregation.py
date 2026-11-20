"""T06: deterministic segregation of reviewed Simples revenue facts, 2026 only.

No tax amount, eligibility inference, credit, declaration or issuance. T07
consumes these buckets with the existing T04 rate authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from fractions import Fraction

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode
from kordena_fiscal.tax.simples_nacional import (
    PARTITION_DIGEST,
    PARTITION_VERSION,
    TAXES,
    TRANSITION_PARTITION_DIGEST,
    TRANSITION_RULE_VERSION,
    TRANSITION_TAXES,
    Activity,
    LimitStatus,
    SimplesFacts,
    _rate_window,
    _round_cents,
    _verify_mode,
    _window_revenue,
    assessment_partition,
    calculate_simples,
    transition_effective_rate,
)

VERSION = "simples-segregation-2026/v1"
TRANSITION_VERSION = "simples-segregation-2027/v1"
TRANSITION_SPECIAL_TAXES = ("cbs", "ibs", "ipi", "icms", "iss")
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
    transition_treatments: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for value in (self.line_id, self.evidence_reference, self.treatment_reference):
            _ref(value)
        _amount(self.cents)
        if not all((
            isinstance(self.activity, Activity), isinstance(self.market, Market),
            isinstance(self.federal, FederalTreatment), isinstance(self.local, LocalTreatment),
        )):
            raise FiscalValidationError("explicit reviewed classification required")


def _transition_reason(line: RevenueLine) -> str:
    values = line.transition_treatments
    if not isinstance(values, tuple) or len(values) != len(TRANSITION_SPECIAL_TAXES):
        return "explicit_2027_per_tax_treatment_required"
    if line.federal is not FederalTreatment.ORDINARY or line.local is not LocalTreatment.ORDINARY:
        return "legacy_treatment_cannot_supply_2027_classification"
    treatments = dict(zip(TRANSITION_SPECIAL_TAXES, values, strict=True))
    common = {"ordinary", "export", "immune", "non_incident"}
    allowed = {
        "cbs": common | {"monophase_downstream", "substituted", "final_advance"},
        "ibs": common | {"monophase_downstream", "substituted", "final_advance"},
        "ipi": common, "icms": common | {"substituted", "final_advance"},
        "iss": common | {"withheld", "fixed_local"},
    }
    if any(not isinstance(value, str) or value not in allowed[tax]
           for tax, value in treatments.items()):
        return "unresolved_2027_tax_treatment"
    if (line.market is Market.EXPORT) != ("export" in values):
        return "export_incidence_requires_specific_tax_evidence"
    goods = line.activity in {
        Activity.COMMERCE, Activity.INDUSTRY, Activity.INDUSTRY_WITHOUT_IPI,
    }
    if goods and treatments["iss"] in {"withheld", "fixed_local"}:
        return "incompatible_goods_treatment"
    if line.activity is not Activity.INDUSTRY and treatments["ipi"] not in {
        "non_incident", "export",
    }:
        return "ipi_activity_requires_review"
    if line.activity is Activity.INDUSTRY and treatments["ipi"] not in {
        "ordinary", "export", "immune",
    }:
        return "industry_without_ipi_requires_annex_i"
    if not goods and treatments["icms"] in {"substituted", "final_advance"}:
        return "incompatible_service_treatment"
    return ""


def classify_revenue(
    competence: date, lines: tuple[RevenueLine, ...], *,
    domestic_cents: int, export_cents: int,
) -> dict[str, object]:
    """Produce mutually exclusive buckets, preserving combined tax treatments.

    The control totals are unit revenue for the selected accounting basis.
    Missing or conflicting treatment blocks the whole batch for T07.
    """
    if (type(competence) is not date or competence.day != 1
            or competence.year not in {2026, 2027}):
        raise FiscalValidationError("reviewed segregation rules require a 2026/2027 competence")
    transition = competence.year == 2027
    _amount(domestic_cents)
    _amount(export_cents)
    if not isinstance(lines, tuple) or len(lines) > 10000:
        raise FiscalValidationError("bounded immutable revenue lines required")
    seen: set[str] = set()
    totals = {market: 0 for market in Market}
    groups: dict[tuple[str, ...], int] = {}
    blocked: list[dict[str, str]] = []
    audit: list[dict[str, object]] = []
    for line in lines:
        if not isinstance(line, RevenueLine) or line.line_id in seen:
            raise FiscalValidationError("duplicate or invalid revenue line")
        seen.add(line.line_id)
        totals[line.market] += line.cents
        goods = line.activity in {Activity.COMMERCE, Activity.INDUSTRY}
        reason = ""
        if transition:
            reason = _transition_reason(line)
        elif (line.transition_treatments is not None
              or line.activity is Activity.INDUSTRY_WITHOUT_IPI):
            reason = "transition_treatment_unavailable_in_2026"
        elif FederalTreatment.UNKNOWN is line.federal or LocalTreatment.UNKNOWN is line.local:
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
            **({"transition_treatments": list(line.transition_treatments or ())}
               if transition else {}),
        })
        if reason:
            blocked.append({"line_id": line.line_id, "reason": reason})
            continue
        key = (line.activity.value, line.market.value, line.federal.value, line.local.value,
               *(line.transition_treatments or ()))
        groups[key] = groups.get(key, 0) + line.cents
    if totals[Market.DOMESTIC] != domestic_cents or totals[Market.EXPORT] != export_cents:
        raise FiscalValidationError("revenue control totals do not reconcile")
    buckets = [
        {"activity": key[0], "market": key[1], "federal": key[2],
         "local": key[3], "cents": cents,
         **({"transition_treatments": dict(zip(
             TRANSITION_SPECIAL_TAXES, key[4:], strict=True,
         ))} if transition else {})}
        for key, cents in sorted(groups.items())
    ]
    payload: dict[str, object] = {
        "version": TRANSITION_VERSION if transition else VERSION,
        "competence": competence.isoformat(),
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


def assess_segregated(
    facts: SimplesFacts, lines: tuple[RevenueLine, ...], *,
    domestic_cents: int, export_cents: int, cash: bool = False,
    cash_closing_event: str | None = None,
    local_outstanding: tuple[RevenueLine, ...] | None = None,
    mode: SimplesIbsCbsMode | None = None,
) -> dict[str, object]:
    """Reviewed assessment, not declaration, payment or tax credit.

    Reclassify canonical inputs, never accept caller-produced buckets.
    Excess/retroactive periods require an additional reviewed allocation.
    """
    transition = facts.competence.year == 2027
    _verify_mode(facts.competence, mode)
    if transition and cash:
        raise FiscalValidationError("cash recognition unavailable from 2027")
    taxes = TRANSITION_TAXES if transition else TAXES
    classified = classify_revenue(
        facts.competence, lines, domestic_cents=domestic_cents, export_cents=export_cents,
    )
    if not cash and (domestic_cents > facts.months[-1].domestic_cents
            or export_cents > facts.months[-1].export_cents):
        raise FiscalValidationError("unit revenue exceeds company totals")
    if not cash and (cash_closing_event is not None or local_outstanding is not None):
        raise FiscalValidationError("cash context requires cash basis")
    if cash_closing_event not in {None, "none", "closure", "return_to_accrual", "exclusion"}:
        raise FiscalValidationError("unknown cash closing context")
    if local_outstanding is not None:
        # Reclassify reviewed balances through the same classifier.
        outstanding_classification = classify_revenue(
            facts.competence, local_outstanding,
            domestic_cents=sum(line.cents for line in local_outstanding
                               if line.market is Market.DOMESTIC),
            export_cents=sum(line.cents for line in local_outstanding
                             if line.market is Market.EXPORT),
        )
    else:
        outstanding_classification = None
    reasons: list[str] = []
    rows: list[dict[str, object]] = []
    direct_rows: list[dict[str, object]] = []
    direct_totals = {"icms": Fraction(0), "iss": Fraction(0)}
    direct_required = False
    local_outside = False
    totals = {tax: Fraction(0) for tax in taxes}
    baseline = {tax: Fraction(0) for tax in taxes}
    if classified["status"] != "classified":
        reasons.append("classification_blocked")
    # Assess the same company history per documented activity. A single
    # company rate result cannot be applied to all its distinct annexes.
    rates = {}
    activities = {line.activity for line in lines}
    activities.update(line.activity for line in (local_outstanding or ()))
    for activity in sorted(activities or {facts.activity}):
        result = calculate_simples(
            replace(facts, activity=activity), ordinary_domestic_base_cents=0, mode=mode,
        )
        rates[activity] = result
        if result.limit_status in {LimitStatus.OUTSIDE, LimitStatus.RETROACTIVE}:
            reasons.append("simples_excluded_or_retroactive")
        if result.sublimit_status is LimitStatus.RETROACTIVE:
            reasons.append("local_tax_retroactive_review")
        local_outside = local_outside or result.sublimit_status is LimitStatus.OUTSIDE
        # CGSN 140 art. 20 II and IV distinguish termination of the cash
        # option from an ICMS/ISS impediment while cash basis continues.
        if cash:
            federal_exit = (
                result.limit_status is LimitStatus.NEXT_MONTH
                or result.limit_status is LimitStatus.NEXT_YEAR and facts.competence.month == 12
            )
            local_exit = (
                result.sublimit_status is LimitStatus.NEXT_MONTH
                or result.sublimit_status is LimitStatus.NEXT_YEAR and facts.competence.month == 12
            )
            if federal_exit and cash_closing_event not in {"exclusion", "closure"}:
                reasons.append("cash_exclusion_closing_evidence_required")
            if local_exit and cash_closing_event in {None, "none"}:
                direct_required = True
    if direct_required and (
        cash_closing_event != "none" or outstanding_classification is None
        or outstanding_classification["status"] != "classified"
    ):
        reasons.append("cash_local_impediment_requires_separate_reconciliation")
    if not reasons:
        groups: dict[
            tuple[Activity, Market, FederalTreatment, LocalTreatment, tuple[str, ...]], int
        ] = {}
        for line in lines:
            key = (line.activity, line.market, line.federal, line.local,
                   line.transition_treatments or ())
            groups[key] = groups.get(key, 0) + line.cents
        for (activity, market, federal, local, treatments), cents in sorted(groups.items()):
            result = rates[activity]
            ordinary, federal_excess, local_excess = assessment_partition(
                facts, result.annex, export=market is Market.EXPORT,
                outside_local=result.sublimit_status is LimitStatus.OUTSIDE, mode=mode,
            )
            excluded: set[str] = set()
            applicable = ordinary
            if transition:
                excluded.update(
                    tax for tax, treatment in zip(TRANSITION_SPECIAL_TAXES, treatments,
                                                 strict=True) if treatment != "ordinary"
                )
                if "iss" in excluded or result.sublimit_status is LimitStatus.OUTSIDE:
                    applicable = transition_effective_rate(
                        facts.competence, result.annex,
                        _window_revenue(_rate_window(facts), export=market is Market.EXPORT),
                        outside_local=result.sublimit_status is LimitStatus.OUTSIDE,
                        mode=mode, redistribute_iss=False,
                    )
            else:
                if market is Market.EXPORT:
                    excluded.update(("pis", "cofins", "ipi", "icms", "iss"))
                if federal is FederalTreatment.MONOPHASE:
                    excluded.update(("pis", "cofins"))
                if local in {LocalTreatment.ICMS_SUBSTITUTED, LocalTreatment.ICMS_FINAL_ADVANCE}:
                    excluded.add("icms")
                if local is LocalTreatment.ISS_WITHHELD:
                    excluded.add("iss")
            amounts = {tax: (Fraction(0) if tax in excluded else rate * cents)
                       for tax, rate in applicable.items()}
            for tax in taxes:
                totals[tax] += amounts[tax]
                baseline[tax] += ordinary[tax] * cents
            rows.append({
                "activity": activity.value, "annex": result.annex.value,
                "market": market.value, "federal": federal.value, "local": local.value,
                "cents": cents, "excluded": sorted(excluded),
                "rate_fractions": {tax: str(rate) for tax, rate in applicable.items()},
                **({"transition_treatments": dict(zip(
                    TRANSITION_SPECIAL_TAXES, treatments, strict=True,
                )), "ordinary_rate_fractions": {tax: str(rate) for tax, rate in ordinary.items()}}
                   if transition else {}),
                "amount_fractions_cents": {tax: str(value) for tax, value in amounts.items()},
                "base_calculation_digest": result.calculation_digest,
                "cpp_outside_das": result.cpp_outside_das,
                "federal_excess_fraction": str(federal_excess),
                "local_excess_fraction": str(local_excess),
                "local_outside_das": result.sublimit_status is LimitStatus.OUTSIDE,
            })
    if not reasons and direct_required:
        # The outstanding, non-recognized ICMS/ISS base is collectible
        # directly by the competent entity, not part of this DAS. No payment
        # or jurisdiction-specific collection instruction is generated here.
        for balance in sorted(local_outstanding or (), key=lambda item: item.line_id):
            if balance.market is Market.EXPORT:
                continue
            annex = rates[balance.activity].annex
            ordinary, _, _ = assessment_partition(
                facts, annex, export=False, outside_local=False,
            )
            tax = "icms" if annex.value in {"I", "II"} else "iss"
            if balance.local in {LocalTreatment.ICMS_SUBSTITUTED,
                                 LocalTreatment.ICMS_FINAL_ADVANCE,
                                 LocalTreatment.ISS_WITHHELD}:
                continue
            amount = ordinary[tax] * balance.cents
            direct_totals[tax] += amount
            direct_rows.append({
                "line_id": balance.line_id, "annex": annex.value,
                "tax": tax, "base_cents": balance.cents,
                "rate_fraction": str(ordinary[tax]), "amount_fraction_cents": str(amount),
                "treatment_reference": balance.treatment_reference,
            })
    def round_tax(value: Fraction) -> int:
        rounded = _round_cents(value)
        return max(1, rounded) if transition and value > 0 else rounded

    by_tax = {tax: round_tax(value) for tax, value in totals.items()}
    ordinary_by_tax = {tax: round_tax(value) for tax, value in baseline.items()}
    payload: dict[str, object] = {
        "status": "blocked" if reasons else "estimated",
        "partition_version": TRANSITION_RULE_VERSION if transition else PARTITION_VERSION,
        "partition_digest": TRANSITION_PARTITION_DIGEST if transition else PARTITION_DIGEST,
        **({"ibs_cbs_mode": mode, "gross_before_external_settlement": True}
           if transition else {}),
        "segregation_digest": classified["digest"], "competence": facts.competence.isoformat(),
        "review_reasons": sorted(set(reasons)), "buckets": rows,
        "tax_cents": None if reasons else by_tax,
        "estimated_das_cents": None if reasons else sum(by_tax.values()),
        "ordinary_comparison_cents": None if reasons else sum(ordinary_by_tax.values()),
        "excluded_comparison_cents": None if reasons else (
            sum(ordinary_by_tax.values()) - sum(by_tax.values())
        ),
        "basis": "cash" if cash else "accrual",
        "local_direct_collection": {
            "status": "blocked" if reasons else (
                "estimated_direct" if direct_required else (
                    "outside_das" if local_outside else "not_applicable"
                )
            ),
            "tax_cents": ({tax: _round_cents(value) for tax, value in direct_totals.items()}
                          if not reasons and direct_required else None),
            "items": direct_rows,
            "legal_basis": "CGSN 140/2018 art. 20 IV" if cash else None,
            "included_in_das": False,
        },
        "advisory_only": True, "rounding": (
            "half_up_per_tax_after_aggregation_minimum_positive_cent" if transition
            else "half_up_per_tax_after_aggregation"
        ),
    }
    return {**payload, "digest": hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()}
