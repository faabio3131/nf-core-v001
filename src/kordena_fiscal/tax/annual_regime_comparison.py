"""T12 deterministic annual comparison; no fiscal election or payment authority.

First supported cell: full calendar 2026, established ordinary domestic trade
and general services, below the ICMS/ISS sublimit in both calendar years.
Existing T07 and T11 remain the only tax calculation authorities.
"""
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field

from kordena_fiscal.cognitive.economy_contract import Cents, ContractModel
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.quarterly_simulation import Quarter, Reference, simulate
from kordena_fiscal.tax.simples_nacional import (
    SUBLIMIT,
    Activity,
    MonthFacts,
    SimplesFacts,
)
from kordena_fiscal.tax.simples_segregation import (
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    assess_segregated,
)

SCHEMA = "nfcore.annual-regime-comparison/v1"
Regime = Literal["simples_nacional", "lucro_presumido", "lucro_real"]
REGIMES: tuple[Regime, ...] = ("simples_nacional", "lucro_presumido", "lucro_real")


class OutsideTax(ContractModel):
    """Reviewed amounts not already included in DAS or the T11 federal taxes."""

    icms: Cents
    iss: Cents
    employer_contributions: Cents
    other_mandatory_taxes: Cents
    # Net incremental RTC burden after legally reviewed 2026 offsets/dispensation.
    # Gross T11 RTC balances are disclosed separately, not added a second time.
    rtc_net_increment: Cents
    evidence: Reference

    def total(self) -> int:
        return (self.icms + self.iss + self.employer_contributions
                + self.other_mandatory_taxes + self.rtc_net_increment)


class HistoryMonth(ContractModel):
    competence: str
    trade_revenue: Cents
    service_revenue: Cents
    payroll: Cents
    evidence: Reference

    @property
    def revenue(self) -> int:
        return self.trade_revenue + self.service_revenue


class OutsideMonth(ContractModel):
    competence: str
    simples_nacional: OutsideTax
    lucro_presumido: OutsideTax
    lucro_real: OutsideTax


class Scenario(ContractModel):
    review_reference: Reference
    # Explicitly attested comparability and legal eligibility; not inferred by CNAE.
    eligibility_reference: Reference
    accounting_scope: Literal["all_establishments_ordinary_domestic_accrual"]
    settlement_scope: Literal["reviewed_net_tax_burden_no_unallocated_credit"]
    uf: str
    service_activity: Literal["service_iii", "service_iv", "service_factor_r"]
    history: Annotated[list[HistoryMonth], Field(min_length=24, max_length=24)]
    outside: Annotated[list[OutsideMonth], Field(min_length=12, max_length=12)]
    quarters: Annotated[list[Quarter], Field(min_length=4, max_length=4)]


class AnnualComparison(ContractModel):
    schema_version: Literal["nfcore.annual-regime-comparison/v1"]
    review_status: Literal["reviewed"]
    baseline: Scenario
    margin: Scenario
    payroll: Scenario


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FiscalValidationError(message)


def _year(scenario: Scenario) -> dict[str, Any]:
    expected = [date(year, month, 1).isoformat()
                for year in (2025, 2026) for month in range(1, 13)]
    _require([m.competence for m in scenario.history] == expected,
             "complete ordered 2025-2026 history required")
    _require([m.competence for m in scenario.outside] == expected[12:],
             "complete reviewed outside tax evidence required")
    _require(all(0 <= sum(m.revenue for m in scenario.history[i:i + 12]) <= SUBLIMIT
                 for i in range(13)), "outside ordinary sublimit comparison")
    months = scenario.history[12:]
    revenue = sum(m.revenue for m in months)
    _require(revenue > 0, "positive annual revenue required for comparison")
    history = tuple(MonthFacts(date.fromisoformat(m.competence), m.revenue, 0, m.payroll,
                               m.evidence) for m in scenario.history)
    totals: dict[str, int] = {regime: 0 for regime in REGIMES}
    details: list[dict[str, Any]] = []
    quarter_details: list[dict[str, Any]] = []
    seen: set[str] = set()
    accounting_result = 0
    for index, quarter in enumerate(scenario.quarters):
        start = index * 3
        group = months[start:start + 3]
        _require(quarter.period_start == group[0].competence
                 and quarter.trade_revenue == sum(m.trade_revenue for m in group)
                 and quarter.services_revenue == sum(m.service_revenue for m in group),
                 "quarter revenue or competence does not reconcile")
        for entry in quarter.months:
            for document in entry.documents:
                _require(document.document_reference not in seen,
                         "duplicate RTC document across annual quarters")
                seen.add(document.document_reference)
        report = simulate(date.fromisoformat(quarter.period_start), quarter)
        accounting_result += quarter.real_accounting_result
        quarter_details.append(report)
        for regime in ("lucro_presumido", "lucro_real"):
            taxes = report[regime]
            totals[regime] += sum(taxes[t] for t in ("irpj", "additional_irpj", "csll"))
        for offset, monthly in enumerate(report["months"]):
            pos = start + offset
            m = months[pos]
            outside = scenario.outside[pos]
            # This initial cell accepts ordinary full bases only. It does not
            # silently approximate differential exclusions, carry or cross-tax credit.
            _require(quarter.months[offset].cumulative_base == m.revenue
                     and quarter.months[offset].noncumulative_base == m.revenue,
                     "ordinary monthly federal bases must reconcile to revenue")
            federal = monthly["noncumulative"]
            _require(federal["pis_balance"] >= 0 and federal["cofins_balance"] >= 0,
                     "unallocated federal credit requires additional review")
            facts = SimplesFacts(
                date.fromisoformat(m.competence), date(2025, 1, 1), scenario.uf,
                Activity.COMMERCE, history[:13 + pos], scenario.review_reference,
                scenario.eligibility_reference, scenario.eligibility_reference,
            )
            lines = tuple(RevenueLine(
                f"{m.competence}-{activity.value}", amount, activity, Market.DOMESTIC,
                FederalTreatment.ORDINARY, LocalTreatment.ORDINARY,
                m.evidence, scenario.review_reference,
            ) for activity, amount in (
                (Activity.COMMERCE, m.trade_revenue),
                (Activity(scenario.service_activity), m.service_revenue),
            ) if amount)
            assessment = assess_segregated(
                facts, lines, domestic_cents=m.revenue, export_cents=0,
            )
            das = assessment["estimated_das_cents"]
            direct = assessment["local_direct_collection"]
            if (assessment["status"] != "estimated" or type(das) is not int
                    or not isinstance(direct, dict) or direct["status"] != "not_applicable"):
                raise FiscalValidationError("Simples comparison outside supported cell")
            _require(outside.simples_nacional.icms == outside.simples_nacional.iss == 0,
                     "local taxes already included in DAS")
            if scenario.service_activity != "service_iv" or not m.service_revenue:
                _require(outside.simples_nacional.employer_contributions == 0,
                         "employer contributions already included in DAS")
            monthly_tax = {
                "simples_nacional": das + outside.simples_nacional.total(),
                "lucro_presumido": sum(monthly["cumulative"].values())
                + outside.lucro_presumido.total(),
                "lucro_real": sum(federal.values()) + outside.lucro_real.total(),
            }
            for regime in REGIMES:
                totals[regime] += monthly_tax[regime]
            details.append({
                "competence": m.competence, "revenue_cents": m.revenue,
                "payroll_cents": m.payroll, "das_cents": das,
                "assessment_digest": assessment["digest"],
                "outside": outside.model_dump(), "monthly_tax_before_quarterly_income": monthly_tax,
                "gross_rtc": monthly["regular_vat"],
            })
    minimum = min(totals.values())
    cheapest = [regime for regime in REGIMES if totals[regime] == minimum]
    return {
        "review_reference": scenario.review_reference, "revenue_cents": revenue,
        "payroll_cents": sum(m.payroll for m in months),
        "real_accounting_result_cents": accounting_result,
        "annual_tax_cents": totals,
        "lowest_tax_burden": cheapest,
        "difference_to_lowest_cents": {regime: totals[regime] - minimum for regime in REGIMES},
        "months": details, "quarters": quarter_details,
    }


def _same_revenue(base: Scenario, variant: Scenario) -> bool:
    return (
        base.uf == variant.uf and base.service_activity == variant.service_activity
        and [(m.competence, m.trade_revenue, m.service_revenue) for m in base.history]
        == [(m.competence, m.trade_revenue, m.service_revenue) for m in variant.history]
        and base.history[:12] == variant.history[:12]
    )


def compare(facts: AnnualComparison) -> dict[str, Any]:
    """Rank reviewed comparable scenarios; never recommend a legal election."""
    base, margin, payroll = facts.baseline, facts.margin, facts.payroll
    _require(len({s.review_reference for s in (base, margin, payroll)}) == 3,
             "each sensitivity scenario requires independent reviewed evidence")
    _require(_same_revenue(base, margin) and _same_revenue(base, payroll),
             "sensitivity must hold revenue, prior history, UF and activity constant")
    _require([m.payroll for m in base.history] == [m.payroll for m in margin.history]
             and sum(q.real_accounting_result for q in base.quarters)
             != sum(q.real_accounting_result for q in margin.quarters),
             "margin sensitivity must vary annual accounting result, not payroll")
    _require([m.payroll for m in base.history[12:]] != [m.payroll for m in payroll.history[12:]],
             "payroll sensitivity must vary reviewed current-year payroll")
    results = {name: _year(scenario) for name, scenario in
               (("baseline", base), ("margin", margin), ("payroll", payroll))}
    baseline = results["baseline"]
    return {
        "schema_version": SCHEMA, "status": "compared", "year": 2026, "unit": "BRL_cent",
        "scenarios": results,
        "sensitivity_tax_delta_cents": {
            name: {regime: results[name]["annual_tax_cents"][regime]
                   - baseline["annual_tax_cents"][regime] for regime in REGIMES}
            for name in ("margin", "payroll")
        },
        "recommendation": {
            "status": "review_required" if len(baseline["lowest_tax_burden"]) == 1 else "tie",
            "candidates": baseline["lowest_tax_burden"],
            "criterion": "lowest_reviewed_annual_tax_burden",
            "requires_accounting_review": True,
        },
        "advisory_only": True, "issuance_authorized": False,
        "payment_authorized": False, "regime_change_authorized": False,
    }
