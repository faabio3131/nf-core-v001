"""T05 — deterministic, advisory Simples Nacional diagnosis and what-if analysis.

All tax rates, factor windows, exclusions and limits come from the T04 engine.
A hypothetical payroll increment never rewrites an observed snapshot. Only the
next competence under the reviewed 2026 rules may be simulated here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from kordena_fiscal.domain import FiscalValidationError

from .simples_nacional import (
    FACTOR_R_THRESHOLD,
    LEGAL_REFERENCES,
    Activity,
    Annex,
    LimitStatus,
    MonthFacts,
    SimplesFacts,
    SimplesResult,
    calculate_simples,
)

DIAGNOSTIC_VERSION = "nfcore.simples-diagnostic/2026-v1"

# Operational warning thresholds, not statutory thresholds.
WARNING_PERCENT = 80
CRITICAL_PERCENT = 90


@dataclass(frozen=True, slots=True)
class PayrollScenario:
    """Explicit hypothetical inputs; never a declaration or payroll instruction."""

    next_month: MonthFacts
    ordinary_domestic_base_cents: int
    additional_pro_labore_cents: int
    additional_tax_cost_cents: int | None = None
    cost_reference: str | None = None

    def __post_init__(self) -> None:
        # Reuse the engine's exact monetary-domain validation.
        MonthFacts(
            self.next_month.competence, self.ordinary_domestic_base_cents,
            self.additional_pro_labore_cents, 0, "scenario-validation",
        )
        if self.additional_tax_cost_cents is not None:
            MonthFacts(
                self.next_month.competence, self.additional_tax_cost_cents,
                0, 0, "scenario-cost-validation",
            )
            if not isinstance(self.cost_reference, str) or (
                not self.cost_reference.strip() or len(self.cost_reference) > 256
            ):
                raise FiscalValidationError("scenario cost evidence is required")
        elif self.cost_reference is not None:
            raise FiscalValidationError("scenario cost amount is required")
        if self.ordinary_domestic_base_cents > self.next_month.domestic_cents:
            raise FiscalValidationError("scenario base exceeds projected domestic revenue")


def _gap(result: SimplesResult) -> int | None:
    revenue = result.factor_revenue_cents
    if revenue == 0:
        # The zero-revenue conventions are not a practical payroll target.
        return None
    target = revenue * FACTOR_R_THRESHOLD
    required = -(-target.numerator // target.denominator)
    return max(0, required - result.factor_payroll_cents)


def _limits(result: SimplesResult) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for market_name, market in (("domestic", result.domestic), ("export", result.export)):
        for name, ceiling, state in (
            ("sublimit", result.sublimit_cents, result.sublimit_status),
            ("limit", result.limit_cents, result.limit_status),
        ):
            revenue = market.rba_cents
            if revenue > ceiling:
                severity = "exceeded"
            elif revenue == ceiling:
                severity = "at_limit"
            elif revenue * 100 >= ceiling * CRITICAL_PERCENT:
                severity = "critical"
            elif revenue * 100 >= ceiling * WARNING_PERCENT:
                severity = "warning"
            else:
                continue
            alerts.append({
                "market": market_name,
                "kind": name,
                "severity": severity,
                "year_revenue_cents": revenue,
                "ceiling_cents": ceiling,
                "headroom_cents": max(0, ceiling - revenue),
                "combined_legal_status": state.value,
            })
    # A prior-year excess or retroactive exclusion must never be hidden by a
    # low current-year percentage. The statutory status comes from T04.
    for name, state in (
        ("sublimit", result.sublimit_status), ("limit", result.limit_status),
    ):
        if state is not LimitStatus.WITHIN:
            alerts.append({
                "market": "combined_statutory_status",
                "kind": name,
                "severity": "legal_review",
                "combined_legal_status": state.value,
            })
    return alerts


def _projection(result: SimplesResult, activity: Activity) -> dict[str, Any]:
    applies = activity is Activity.SERVICE_FACTOR_R
    return {
        "annex": result.annex.value,
        "factor_r": str(result.factor_r) if applies and result.factor_r is not None else None,
        "factor_payroll_cents": result.factor_payroll_cents if applies else None,
        "factor_revenue_cents": result.factor_revenue_cents if applies else None,
        "factor_gap_cents": _gap(result) if applies else None,
        "ordinary_domestic_estimate_cents": result.ordinary_domestic_estimate_cents,
        "ordinary_domestic_rate": (
            str(result.ordinary_domestic_rate)
            if result.ordinary_domestic_rate is not None else None
        ),
        "sublimit_status": result.sublimit_status.value,
        "limit_status": result.limit_status.value,
        "calculation_digest": result.calculation_digest,
        "review_reasons": list(result.review_reasons),
        "alerts": _limits(result),
    }


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _simulate(
    facts: SimplesFacts, scenario: PayrollScenario,
) -> dict[str, Any]:
    next_month = _next_month(facts.competence)
    if next_month.year != 2026 or scenario.next_month.competence != next_month:
        raise FiscalValidationError("scenario requires the next reviewed 2026 competence")
    if facts.activity is not Activity.SERVICE_FACTOR_R:
        raise FiscalValidationError("activity is not subject to Factor R")

    baseline_facts = replace(
        facts, competence=next_month, months=(*facts.months, scenario.next_month),
    )
    baseline = calculate_simples(
        baseline_facts, ordinary_domestic_base_cents=scenario.ordinary_domestic_base_cents,
    )

    # Simulate payment during the source month, not a change to historical
    # evidence. The next period's own payroll must not enter the 2026 window.
    source = facts.months[-1]
    hypothetical_payment = replace(
        source, payroll_cents=source.payroll_cents + scenario.additional_pro_labore_cents,
        evidence_reference="hypothetical-pro-labore-payment",
    )
    projected_facts = replace(
        baseline_facts, months=(*facts.months[:-1], hypothetical_payment, scenario.next_month),
    )
    projected = calculate_simples(
        projected_facts, ordinary_domestic_base_cents=scenario.ordinary_domestic_base_cents,
    )
    comparable = (
        baseline.limit_status is LimitStatus.WITHIN
        and baseline.sublimit_status is LimitStatus.WITHIN
        and projected.limit_status is LimitStatus.WITHIN
        and projected.sublimit_status is LimitStatus.WITHIN
        and baseline.ordinary_domestic_estimate_cents is not None
        and projected.ordinary_domestic_estimate_cents is not None
    )
    before = baseline.ordinary_domestic_estimate_cents
    after = projected.ordinary_domestic_estimate_cents
    gross = before - after if comparable and before is not None and after is not None else None
    contrast = (
        baseline.annex is Annex.ANNEX_V and projected.annex is Annex.ANNEX_III
    )
    net = (
        gross - scenario.additional_tax_cost_cents
        if gross is not None and scenario.additional_tax_cost_cents is not None else None
    )
    return {
        "status": "hypothetical",
        "payment_competence": facts.competence.isoformat(),
        "target_competence": next_month.isoformat(),
        "baseline": _projection(baseline, facts.activity),
        "projected": _projection(projected, facts.activity),
        "minimum_additional_qualifying_payroll_cents": _gap(baseline),
        "additional_pro_labore_cents": scenario.additional_pro_labore_cents,
        "additional_tax_cost_cents": scenario.additional_tax_cost_cents,
        "transition_v_to_iii": contrast,
        "gross_ordinary_das_saving_cents": gross,
        "net_estimated_tax_saving_cents": net,
        "total_business_cash_impact_cents": None,
        "monetary_comparison_available": comparable,
        "cost_basis_complete": scenario.additional_tax_cost_cents is not None,
        "requires_accountant_review": True,
    }


def diagnose_simples(
    facts: SimplesFacts, *, ordinary_domestic_base_cents: int,
    scenario: PayrollScenario | None = None,
) -> dict[str, Any]:
    """Compute ordinary-base estimates and legal-state alerts without fiscal writes."""
    current = calculate_simples(facts, ordinary_domestic_base_cents=ordinary_domestic_base_cents)
    return {
        "schema_version": DIAGNOSTIC_VERSION,
        "rule_version": current.rule_version,
        "rule_digest": current.rule_digest,
        "competence": facts.competence.isoformat(),
        "activity": facts.activity.value,
        "current": _projection(current, facts.activity),
        "scenario": _simulate(facts, scenario) if scenario is not None else None,
        "legal_references": list(LEGAL_REFERENCES),
        "advisory_only": True,
        "requires_human_approval": True,
        "final_pgdas_assessment": False,
        "warning_policy_percent": {"warning": WARNING_PERCENT, "critical": CRITICAL_PERCENT},
    }
