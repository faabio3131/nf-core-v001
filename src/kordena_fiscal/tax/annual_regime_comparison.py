"""T12 deterministic annual comparison; no fiscal election or payment authority.

First supported cell: full calendar 2026, established ordinary domestic trade
and general services, below the ICMS/ISS sublimit in both calendar years.
Existing T07 and T11 remain the only tax calculation authorities.
"""
from datetime import date
from fractions import Fraction
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from kordena_fiscal.cognitive.economy_contract import Cents, ContractModel, Digest, Version
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.quarterly_simulation import Quarter, Reference, rounded, simulate
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
    zero_justifications: dict[
        Literal["icms", "iss", "employer_contributions"], Reference
    ] = Field(default_factory=dict)

    def total(self) -> int:
        return (self.icms + self.iss + self.employer_contributions
                + self.other_mandatory_taxes + self.rtc_net_increment)


class HistoryMonth(ContractModel):
    competence: str
    trade_revenue: Cents
    service_revenue: Cents
    payroll: Cents
    # Separately reviewed deductible expense; qualifying Fator R is not necessarily wages.
    real_payroll_expense_excluding_employer: Cents
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
    opened_month: str
    service_activity: Literal["service_iii", "service_iv", "service_factor_r"]
    history: Annotated[list[HistoryMonth], Field(min_length=24, max_length=24)]
    outside: Annotated[list[OutsideMonth], Field(min_length=12, max_length=12)]
    quarters: Annotated[list[Quarter], Field(min_length=4, max_length=4)]


class QuarterLink(ContractModel):
    record_id: Reference
    version: Version
    digest: Digest


class EvidenceArtifact(ContractModel):
    reference: Reference
    sha256: Digest
    content: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


class AnnualComparison(ContractModel):
    schema_version: Literal["nfcore.annual-regime-comparison/v1"]
    review_status: Literal["reviewed"]
    data_basis: Literal["reviewed_annual_scenarios"]
    source_mode: Literal["linked_t11_snapshots"]
    baseline_quarter_links: Annotated[list[QuarterLink], Field(min_length=4, max_length=4)]
    evidence_artifacts: Annotated[list[EvidenceArtifact], Field(min_length=1, max_length=500)]
    baseline: Scenario
    margin: Scenario
    payroll: Scenario


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FiscalValidationError(message)


def _year(scenario: Scenario) -> dict[str, Any]:
    try:
        opened = date.fromisoformat(scenario.opened_month)
    except ValueError as exc:
        raise FiscalValidationError("reviewed company opening month required") from exc
    _require(opened.isoformat() == scenario.opened_month and opened.day == 1
             and opened <= date(2025, 1, 1), "established company opening required")
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
    prior_revenue = 0
    prior_csll_revenue = 0
    # T11 validates the statutory first-quarter band; reuse it as the annual anchor.
    ordinary_band = scenario.quarters[0].irpj_ordinary_limit
    for index, quarter in enumerate(scenario.quarters):
        start = index * 3
        group = months[start:start + 3]
        _require(quarter.period_start == group[0].competence
                 and quarter.trade_revenue == sum(m.trade_revenue for m in group)
                 and quarter.services_revenue == sum(m.service_revenue for m in group),
                 "quarter revenue or competence does not reconcile")
        quarter_revenue = sum(m.revenue for m in group)
        _require(quarter_revenue <= quarter.irpj_ordinary_limit
                 <= (index + 1) * ordinary_band - prior_revenue
                 and (index == 0 or quarter_revenue <= quarter.csll_ordinary_limit
                      <= index * ordinary_band - prior_csll_revenue),
                 "reviewed presumption uplift requires broader annual reconciliation")
        prior_revenue += quarter_revenue
        if index > 0:
            prior_csll_revenue += quarter_revenue
        _require(quarter.irpj_other_taxable == quarter.csll_other_taxable == 0,
                 "additional revenue requires broader reviewed comparison")
        _require(quarter.irpj_loss_applied == quarter.csll_loss_applied == 0,
                 "loss carry requires a reviewed annual reconciliation")
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
            # Reviewed bases may exclude taxes; no additional revenue is supported.
            _require(quarter.months[offset].cumulative_base <= m.revenue
                     and quarter.months[offset].noncumulative_base <= m.revenue,
                     "reviewed federal bases exceed the reconciled revenue")
            federal = monthly["noncumulative"]
            _require(federal["pis_balance"] >= 0 and federal["cofins_balance"] >= 0,
                     "unallocated federal credit requires additional review")
            facts = SimplesFacts(
                date.fromisoformat(m.competence), opened, scenario.uf,
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
            for regime in REGIMES:
                taxes = getattr(outside, regime)
                required = []
                if regime != "simples_nacional":
                    if m.trade_revenue:
                        required.append("icms")
                    if m.service_revenue:
                        required.append("iss")
                if m.payroll and (regime != "simples_nacional" or (
                    scenario.service_activity == "service_iv" and m.service_revenue
                )):
                    required.append("employer_contributions")
                _require(all(getattr(taxes, key) or (
                    key in taxes.zero_justifications
                    and taxes.zero_justifications[key] != taxes.evidence
                ) for key in required), "missing specific reviewed zero-tax justification")
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
    _require(all(0 <= amount <= 10**15 for amount in totals.values())
             and abs(accounting_result) <= 10**15
             and sum(m.payroll for m in months) <= 10**15,
             "annual amounts exceed supported comparison precision")
    minimum = min(totals.values())
    cheapest = [regime for regime in REGIMES if totals[regime] == minimum]
    return {
        "review_reference": scenario.review_reference, "revenue_cents": revenue,
        "payroll_cents": sum(m.payroll for m in months),
        "real_accounting_result_cents": accounting_result,
        "accounting_margin_bps": (1 if accounting_result >= 0 else -1) * rounded(
            Fraction(abs(accounting_result) * 10000, revenue)),
        "qualifying_payroll_bps": rounded(
            Fraction(sum(m.payroll for m in months) * 10000, revenue)),
        "annual_tax_cents": totals,
        "lowest_tax_burden": cheapest,
        "difference_to_lowest_cents": {regime: totals[regime] - minimum for regime in REGIMES},
        "months": details, "quarters": quarter_details,
    }


def _same_revenue(base: Scenario, variant: Scenario) -> bool:
    return (
        base.uf == variant.uf and base.service_activity == variant.service_activity
        and base.opened_month == variant.opened_month
        and base.eligibility_reference == variant.eligibility_reference
        and [(m.competence, m.trade_revenue, m.service_revenue) for m in base.history]
        == [(m.competence, m.trade_revenue, m.service_revenue) for m in variant.history]
        and base.history[:12] == variant.history[:12]
    )


def _quarter_invariants(base: Quarter, variant: Quarter) -> bool:
    excluded = {"review_reference", "real_accounting_result"}
    return base.model_dump(exclude=excluded) == variant.model_dump(exclude=excluded)


def _outside_invariants(base: Scenario, variant: Scenario, *, payroll: bool) -> bool:
    excluded = {"evidence"}
    if payroll:
        excluded |= {"employer_contributions", "zero_justifications"}
    for a, b in zip(base.outside, variant.outside, strict=True):
        for regime in REGIMES:
            left, right = getattr(a, regime), getattr(b, regime)
            if left.model_dump(exclude=excluded) != right.model_dump(exclude=excluded):
                return False
            if payroll and {k: v for k, v in left.zero_justifications.items()
                            if k != "employer_contributions"} != {
                k: v for k, v in right.zero_justifications.items()
                if k != "employer_contributions"
            }:
                return False
    return True


def _verify_evidence(facts: AnnualComparison) -> None:
    evidence = {}
    for artifact in facts.evidence_artifacts:
        _require(artifact.reference not in evidence and
                 sha256(artifact.content.encode("utf-8")).hexdigest() == artifact.sha256,
                 "duplicate or invalid supporting evidence digest")
        evidence[artifact.reference] = artifact.sha256
    references: set[str] = set()
    for scenario in (facts.baseline, facts.margin, facts.payroll):
        references.update((scenario.review_reference, scenario.eligibility_reference))
        references.update(m.evidence for m in scenario.history)
        for month in scenario.outside:
            for regime in REGIMES:
                taxes = getattr(month, regime)
                references.add(taxes.evidence)
                references.update(taxes.zero_justifications.values())
        for quarter in scenario.quarters:
            references.add(quarter.review_reference)
            references.update(m.rtc_evidence for m in quarter.months)
    _require(references <= evidence.keys(), "missing supporting evidence artifact")


def _reconcile_payroll(base: Scenario, payroll: Scenario) -> None:
    for index, (before, after) in enumerate(zip(base.quarters, payroll.quarters, strict=True)):
        start = 12 + index * 3
        costs = sum(
            p.real_payroll_expense_excluding_employer - b.real_payroll_expense_excluding_employer
            for b, p in zip(base.history[start:start + 3], payroll.history[start:start + 3],
                            strict=True)
        )
        contributions = sum(
            p.lucro_real.employer_contributions - b.lucro_real.employer_contributions
            for b, p in zip(base.outside[index * 3:index * 3 + 3],
                            payroll.outside[index * 3:index * 3 + 3], strict=True)
        )
        _require(after.real_accounting_result == before.real_accounting_result - costs
                 - contributions, "payroll accounting result does not reconcile")


def compare(facts: AnnualComparison) -> dict[str, Any]:
    """Rank reviewed comparable scenarios; never recommend a legal election."""
    _verify_evidence(facts)
    base, margin, payroll = facts.baseline, facts.margin, facts.payroll
    _require(len({s.review_reference for s in (base, margin, payroll)}) == 3,
             "each sensitivity scenario requires independent reviewed evidence")
    _require(_same_revenue(base, margin) and _same_revenue(base, payroll),
             "sensitivity must hold revenue, prior history, UF and activity constant")
    _require(all(_quarter_invariants(a, b) for variant in (margin, payroll)
                 for a, b in zip(base.quarters, variant.quarters, strict=True)),
             "sensitivity changed independent quarterly tax facts")
    _require(_outside_invariants(base, margin, payroll=False)
             and _outside_invariants(base, payroll, payroll=True),
             "sensitivity changed independent outside taxes")
    _require(base.history == margin.history
             and sum(q.real_accounting_result for q in base.quarters)
             != sum(q.real_accounting_result for q in margin.quarters),
             "margin sensitivity must vary annual accounting result, not payroll")
    _require([m.payroll for m in base.history[12:]] != [m.payroll for m in payroll.history[12:]],
             "payroll sensitivity must vary reviewed current-year payroll")
    _reconcile_payroll(base, payroll)
    results = {name: _year(scenario) for name, scenario in
               (("baseline", base), ("margin", margin), ("payroll", payroll))}
    baseline = results["baseline"]
    return {
        "schema_version": SCHEMA, "status": "compared", "year": 2026, "unit": "BRL_cent",
        "data_basis": facts.data_basis, "scenarios": results,
        "source_mode": facts.source_mode,
        "baseline_quarter_links": [link.model_dump() for link in facts.baseline_quarter_links],
        "supporting_evidence_integrity": "digest_verified_not_accounting_approval",
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
            "sensitivity_stable": all(
                results[name]["lowest_tax_burden"] == baseline["lowest_tax_burden"]
                for name in ("margin", "payroll")
            ),
        },
        "advisory_only": True, "issuance_authorized": False,
        "payment_authorized": False, "regime_change_authorized": False,
    }
