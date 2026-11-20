"""T04 — deterministic Simples Nacional base-rate engine, calendar 2026.

LC 123/2006 arts. 3, 18, 19, 20 and annexes I–V; CGSN 140/2018 arts.
12, 21–24, 26; Portaria CGSN 54/2025. No PGDAS submission or tax activation.
Company-wide accrual history is distinct from unit taxable revenue; no CNAE
guessing, no implicit eligibility, no automatic assumption of zero revenue.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode

RULE_VERSION = "simples-lc123-cgsn140-2026/v1"
LEGAL_REFERENCES = (
    "https://legis.senado.gov.br/norma/572878/publicacao/34621013",
    "https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=92278",
    "https://www8.receita.fazenda.gov.br/SIMPLESNACIONAL/noticias/"
    "NoticiaCompleta.aspx?id=94c10cc2-7eb5-4ef0-bfb2-5479e72caff8",
)
UF_CODES = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)
LIMIT = 480_000_000
SUBLIMIT = 360_000_000
FACTOR_R_THRESHOLD = Fraction(28, 100)
CEILINGS = (18_000_000, 36_000_000, 72_000_000, 180_000_000, SUBLIMIT, LIMIT)
_MAX_CENTS = 10**15


class Annex(StrEnum):
    ANNEX_I = "I"
    ANNEX_II = "II"
    ANNEX_III = "III"
    ANNEX_IV = "IV"
    ANNEX_V = "V"


class Activity(StrEnum):
    COMMERCE = "commerce"
    INDUSTRY = "industry"
    INDUSTRY_WITHOUT_IPI = "industry_without_ipi"
    SERVICE_III = "service_iii"
    SERVICE_IV = "service_iv"
    SERVICE_FACTOR_R = "service_factor_r"


class LimitStatus(StrEnum):
    WITHIN = "within"
    NEXT_YEAR = "excess_effect_next_year"
    NEXT_MONTH = "excess_effect_next_month"
    OUTSIDE = "outside_current_period"
    RETROACTIVE = "retroactive_to_start"


# Percentages as basis points, deduction in integer cents.
_ROWS = MappingProxyType({
    Annex.ANNEX_I: ((400, 0), (730, 594000), (950, 1386000), (1070, 2250000),
              (1430, 8730000), (1900, 37800000)),
    Annex.ANNEX_II: ((450, 0), (780, 594000), (1000, 1386000), (1120, 2250000),
               (1470, 8550000), (3000, 72000000)),
    Annex.ANNEX_III: ((600, 0), (1120, 936000), (1350, 1764000), (1600, 3564000),
                (2100, 12564000), (3300, 64800000)),
    Annex.ANNEX_IV: ((450, 0), (900, 810000), (1020, 1242000), (1400, 3978000),
               (2200, 18378000), (3300, 82800000)),
    Annex.ANNEX_V: ((1550, 0), (1800, 450000), (1950, 990000), (2050, 1710000),
              (2300, 6210000), (3050, 54000000)),
})
# LC 123 annexes I–V, 2026: IRPJ, CSLL, COFINS, PIS, CPP, IPI, ICMS, ISS.
# Single partition authority; the legacy T04 local view and digest are preserved.
TAXES = ("irpj", "csll", "cofins", "pis", "cpp", "ipi", "icms", "iss")
_PARTITION = MappingProxyType({
    Annex.ANNEX_I: (
        (550, 350, 1274, 276, 4150, 0, 3400, 0),
        (550, 350, 1274, 276, 4150, 0, 3400, 0),
        *((550, 350, 1274, 276, 4200, 0, 3350, 0),) * 3,
        (1350, 1000, 2827, 613, 4210, 0, 0, 0),
    ),
    Annex.ANNEX_II: (
        *((550, 350, 1151, 249, 3750, 750, 3200, 0),) * 5,
        (850, 750, 2096, 454, 2350, 3500, 0, 0),
    ),
    Annex.ANNEX_III: (
        (400, 350, 1282, 278, 4340, 0, 0, 3350),
        (400, 350, 1405, 305, 4340, 0, 0, 3200),
        (400, 350, 1364, 296, 4340, 0, 0, 3250),
        (400, 350, 1364, 296, 4340, 0, 0, 3250),
        (400, 350, 1282, 278, 4340, 0, 0, 3350),
        (3500, 1500, 1603, 347, 3050, 0, 0, 0),
    ),
    Annex.ANNEX_IV: (
        (1880, 1520, 1767, 383, 0, 0, 0, 4450),
        (1980, 1520, 2055, 445, 0, 0, 0, 4000),
        (2080, 1520, 1973, 427, 0, 0, 0, 4000),
        (1780, 1920, 1890, 410, 0, 0, 0, 4000),
        (1880, 1920, 1808, 392, 0, 0, 0, 4000),
        (5350, 2150, 2055, 445, 0, 0, 0, 0),
    ),
    Annex.ANNEX_V: (
        (2500, 1500, 1410, 305, 2885, 0, 0, 1400),
        (2300, 1500, 1410, 305, 2785, 0, 0, 1700),
        (2400, 1500, 1492, 323, 2385, 0, 0, 1900),
        (2100, 1500, 1574, 341, 2385, 0, 0, 2100),
        (2300, 1250, 1410, 305, 2385, 0, 0, 2350),
        (3500, 1550, 1644, 356, 2950, 0, 0, 0),
    ),
})
_LOCAL = MappingProxyType({
    annex: tuple(row[6] + row[7] for row in rows)
    for annex, rows in _PARTITION.items()
})
RULE_DIGEST = hashlib.sha256(json.dumps({
    "version": RULE_VERSION, "rows": dict(_ROWS), "local": dict(_LOCAL),
    "ceilings": CEILINGS, "ufs": sorted(UF_CODES), "sources": LEGAL_REFERENCES,
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _month(value: date) -> date:
    if type(value) is not date or value.day != 1:
        raise FiscalValidationError("competence must be the first day of the month")
    return value


def _add_month(value: date, delta: int) -> date:
    number = value.year * 12 + value.month - 1 + delta
    return date(number // 12, number % 12 + 1, 1)


def _cents(value: int) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_CENTS:
        raise FiscalValidationError("money must be nonnegative integer cents")
    return value


def _decimal(value: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return Decimal(value.numerator) / Decimal(value.denominator)


def _round_cents(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


@dataclass(frozen=True, slots=True)
class MonthFacts:
    competence: date
    domestic_cents: int
    export_cents: int
    payroll_cents: int
    evidence_reference: str

    def __post_init__(self) -> None:
        _month(self.competence)
        for value in (self.domestic_cents, self.export_cents, self.payroll_cents):
            _cents(value)
        if not isinstance(self.evidence_reference, str) or (
            not self.evidence_reference.strip() or len(self.evidence_reference) > 256
        ):
            raise FiscalValidationError("monthly fiscal evidence is required")


@dataclass(frozen=True, slots=True)
class SimplesFacts:
    competence: date
    opened_month: date
    uf: str
    activity: Activity
    months: tuple[MonthFacts, ...]
    company_history_reference: str
    activity_reference: str
    optant_reference: str
    registered_on: date | None = None

    def __post_init__(self) -> None:
        _month(self.competence)
        _month(self.opened_month)
        if self.registered_on is not None and (
            self.competence.year != 2027 or type(self.registered_on) is not date
            or self.registered_on.replace(day=1) != self.opened_month
        ):
            raise FiscalValidationError("registration date must match reviewed opening month")
        if self.competence.year not in {2026, 2027} or self.opened_month > self.competence:
            raise FiscalValidationError("only reviewed 2026/2027 rules are available")
        if self.uf not in UF_CODES or not isinstance(self.activity, Activity):
            raise FiscalValidationError("UF and documented activity classification are required")
        if self.competence.year == 2026 and self.activity is Activity.INDUSTRY_WITHOUT_IPI:
            raise FiscalValidationError("transition activity unavailable in 2026")
        for ref in (self.company_history_reference, self.activity_reference, self.optant_reference):
            if not isinstance(ref, str) or not ref.strip() or len(ref) > 256:
                raise FiscalValidationError("documented company/regime/activity evidence required")
        if not isinstance(self.months, tuple) or any(
            not isinstance(item, MonthFacts) for item in self.months
        ):
            raise FiscalValidationError("immutable complete company monthly history required")
        # Prior calendar year and rolling 12, including all establishments.
        start = max(
            self.opened_month,
            date(2025, 1 if self.competence.year == 2026 else 12, 1),
        )
        expected: list[date] = []
        while start <= self.competence:
            expected.append(start)
            start = _add_month(start, 1)
        if tuple(item.competence for item in self.months) != tuple(expected):
            raise FiscalValidationError("missing, duplicate or unordered company month")


@dataclass(frozen=True, slots=True)
class MarketRate:
    rbt12_cents: Decimal
    bracket: int
    nominal_rate: Decimal
    deduction_cents: int
    effective_rate: Decimal
    local_effective_rate: Decimal
    federal_effective_rate: Decimal
    rba_cents: int
    rbaa_cents: int


@dataclass(frozen=True, slots=True)
class SimplesResult:
    rule_version: str
    rule_digest: str
    annex: Annex
    factor_r: Decimal | None
    factor_payroll_cents: int
    factor_revenue_cents: int
    domestic: MarketRate
    export: MarketRate
    sublimit_cents: int
    limit_cents: int
    sublimit_status: LimitStatus
    limit_status: LimitStatus
    domestic_sublimit_excess_fraction: Decimal
    domestic_limit_excess_fraction: Decimal
    ordinary_domestic_federal_rate: Decimal | None
    ordinary_domestic_local_rate: Decimal | None
    ordinary_domestic_rate: Decimal | None
    ordinary_domestic_estimate_cents: int | None
    cpp_outside_das: bool
    review_reasons: tuple[str, ...]
    calculation_digest: str


def _factor(payroll: int, revenue: int, *, first: bool) -> Fraction | None:
    if not revenue:
        return FACTOR_R_THRESHOLD if payroll else (None if first else Fraction(1, 100))
    return Fraction(payroll, revenue) if payroll else Fraction(1, 100)


def _annex(activity: Activity, factor: Fraction | None) -> Annex:
    if activity is Activity.SERVICE_FACTOR_R:
        if factor is None:
            raise FiscalValidationError("opening month without payroll/revenue: factor undefined")
        return Annex.ANNEX_III if factor >= FACTOR_R_THRESHOLD else Annex.ANNEX_V
    return {
        Activity.COMMERCE: Annex.ANNEX_I, Activity.INDUSTRY: Annex.ANNEX_II,
        Activity.INDUSTRY_WITHOUT_IPI: Annex.ANNEX_I,
        Activity.SERVICE_III: Annex.ANNEX_III, Activity.SERVICE_IV: Annex.ANNEX_IV,
    }[activity]


def _annual_limit(opened: date, year: int, ceiling: int) -> int:
    return ceiling // 12 * (13 - opened.month) if opened.year == year else ceiling


def _status(
    prior_year: int, before: int, total: int, cap: int, previous_cap: int, startup: bool,
) -> LimitStatus:
    if prior_year > previous_cap and not startup:
        return LimitStatus.OUTSIDE
    if startup and total * 5 > cap * 6:
        return LimitStatus.RETROACTIVE
    if not startup and before * 5 > cap * 6:
        return LimitStatus.OUTSIDE
    if total * 5 > cap * 6:
        return LimitStatus.NEXT_MONTH
    if total > cap:
        return LimitStatus.NEXT_YEAR
    return LimitStatus.WITHIN


def _worst(a: LimitStatus, b: LimitStatus) -> LimitStatus:
    order = (LimitStatus.WITHIN, LimitStatus.NEXT_YEAR, LimitStatus.NEXT_MONTH,
             LimitStatus.OUTSIDE, LimitStatus.RETROACTIVE)
    return max((a, b), key=order.index)


def _rate(annex: Annex, rbt: Fraction, bracket: int) -> Fraction:
    nominal, deduct = _ROWS[annex][bracket]
    denominator = rbt if rbt else Fraction(100)
    return Fraction(nominal, 10000) - Fraction(deduct) / denominator


def _local_rate(annex: Annex, total_rate: Fraction, bracket: int) -> Fraction:
    local = total_rate * Fraction(_LOCAL[annex][bracket], 10000)
    if annex in {Annex.ANNEX_III, Annex.ANNEX_IV, Annex.ANNEX_V}:
        return min(local, Fraction(5, 100))
    return local


def _market_rate(
    annex: Annex, rbt: Fraction, rba: int, rbaa: int, outside_local: bool,
    *, competence: date, mode: SimplesIbsCbsMode | None,
) -> tuple[MarketRate, Fraction, Fraction]:
    idx = next((i for i, ceiling in enumerate(CEILINGS) if rbt <= ceiling), 5)
    if competence.year == 2027:
        nominal, deduct, _ = transition_band(competence, annex, idx + 1)
        effective = _transition_rate(competence, annex, rbt, idx + 1)
    else:
        nominal, deduct = _ROWS[annex][idx]
        effective = _rate(annex, rbt, idx)
    # T04 and T07 use a single effective partition authority, including
    # the sixth-band local supplement and ISS redistribution.
    if competence.year == 2027:
        parts = transition_effective_rate(
            competence, annex, rbt, outside_local=outside_local, mode=mode,
        )
    else:
        parts = partition_effective_rate(annex, rbt, outside_local=outside_local)
    local = parts["icms"] + parts["iss"] + parts.get("ibs", Fraction(0))
    federal = sum(parts.values(), Fraction(0)) - local
    return MarketRate(
        _decimal(rbt), idx + 1, _decimal(Fraction(nominal, 10000)), deduct,
        _decimal(effective), _decimal(local), _decimal(federal), rba, rbaa,
    ), federal, local


def _excess_fraction(year_total: int, month_revenue: int, cap: int) -> Fraction:
    """Art. 24: fraction of current monthly revenue above the annual ceiling."""
    if month_revenue == 0:
        return Fraction(0)
    excess = min(month_revenue, max(0, year_total - cap))
    return Fraction(excess, month_revenue)


def calculate_simples(
    facts: SimplesFacts, *, ordinary_domestic_base_cents: int,
    mode: SimplesIbsCbsMode | None = None,
) -> SimplesResult:
    """Return base-rate diagnostic, not a PGDAS declaration.

    Ordinary base is a documented unit/activity domestic accrual base, without
    ST, monophase, withholding, export relief or fixed tax treatment. T06/T07
    own special segregation and final assessment. Art.24 excess splitting
    yields an ordinary-base diagnostic only, never a definitive DAS. Local
    taxes outside Simples and Annex IV CPP are not part of that amount.
    MonthFacts payroll is the documented qualifying FS aggregate (art.26),
    not all employer costs or an inferred payroll.
    """
    if not isinstance(facts, SimplesFacts):
        raise FiscalValidationError("SimplesFacts required")
    base = _cents(ordinary_domestic_base_cents)
    current = facts.months[-1]
    if base > current.domestic_cents:
        raise FiscalValidationError("unit base exceeds company domestic accrued revenue")
    year_number = facts.competence.year
    transition = year_number == 2027
    _verify_mode(facts.competence, mode)
    window = _rate_window(facts)
    fs = sum(item.payroll_cents for item in window)
    fr = sum(item.domestic_cents + item.export_cents for item in window)
    first = facts.opened_month == facts.competence
    factor = FACTOR_R_THRESHOLD if transition and not window else _factor(fs, fr, first=first)
    annex = _annex(facts.activity, factor)
    domestic_rbt = _window_revenue(window, export=False)
    export_rbt = _window_revenue(window, export=True)
    prior = tuple(item for item in facts.months if item.competence.year == year_number - 1)
    year = tuple(item for item in facts.months if item.competence.year == year_number)
    startup = facts.opened_month.year == year_number
    sub = _annual_limit(facts.opened_month, year_number, SUBLIMIT)
    cap = _annual_limit(facts.opened_month, year_number, LIMIT)
    drba = sum(item.domestic_cents for item in year)
    erba = sum(item.export_cents for item in year)
    drbaa = sum(item.domestic_cents for item in prior)
    erbaa = sum(item.export_cents for item in prior)

    def status(ceiling: int, actual_cap: int) -> LimitStatus:
        previous = _annual_limit(facts.opened_month, year_number - 1, ceiling)
        return _worst(
            _status(drbaa, drba - current.domestic_cents, drba, actual_cap, previous, startup),
            _status(erbaa, erba - current.export_cents, erba, actual_cap, previous, startup),
        )

    substatus, limstatus = status(SUBLIMIT, sub), status(LIMIT, cap)
    outside = {LimitStatus.OUTSIDE, LimitStatus.RETROACTIVE}
    domestic, _, _ = _market_rate(
        annex, domestic_rbt, drba, drbaa, substatus in outside,
        competence=facts.competence, mode=mode,
    )
    exported, _, _ = _market_rate(
        annex, export_rbt, erba, erbaa, substatus in outside,
        competence=facts.competence, mode=mode,
    )
    # Art. 24: reuse the same partition as the segregated apuração.
    assessed, limit_fraction, sub_fraction = assessment_partition(
        facts, annex, export=False, outside_local=substatus in outside, mode=mode,
    )
    assessed_local = assessed["icms"] + assessed["iss"] + assessed.get("ibs", Fraction(0))
    assessed_federal = sum(assessed.values(), Fraction(0)) - assessed_local
    reasons: list[str] = []
    if limstatus in outside:
        reasons.append("simples_excluded_or_retroactive")
    if substatus is LimitStatus.RETROACTIVE:
        reasons.append("local_tax_retroactive_review")
    amount_rate = None if reasons else assessed_federal + assessed_local
    amount = None if amount_rate is None else _round_cents(base * amount_rate)
    rule_digest = TRANSITION_TABLE_DIGEST if transition else RULE_DIGEST
    partition_digest = TRANSITION_PARTITION_DIGEST if transition else PARTITION_DIGEST
    fingerprint = hashlib.sha256(json.dumps({
        "rule": rule_digest, "partition": partition_digest,
        **({"ibs_cbs_mode": mode} if transition else {}),
        "period": facts.competence.isoformat(),
        "opened": facts.opened_month.isoformat(), "uf": facts.uf, "activity": facts.activity,
        "history_ref": facts.company_history_reference, "activity_ref": facts.activity_reference,
        "optant_ref": facts.optant_reference,
        "months": [(m.competence.isoformat(), m.domestic_cents, m.export_cents, m.payroll_cents,
                    m.evidence_reference) for m in facts.months],
        "base": base,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SimplesResult(
        TRANSITION_RULE_VERSION if transition else RULE_VERSION,
        rule_digest, annex, _decimal(factor) if factor is not None else None,
        fs, fr, domestic, exported, sub, cap, substatus, limstatus,
        _decimal(sub_fraction), _decimal(limit_fraction),
        _decimal(assessed_federal) if amount_rate is not None else None,
        _decimal(assessed_local) if amount_rate is not None else None,
        _decimal(amount_rate) if amount_rate is not None else None, amount,
        annex is Annex.ANNEX_IV, tuple(reasons), fingerprint,
    )


PARTITION_VERSION = "simples-partition-2026/v2"
PARTITION_DIGEST = hashlib.sha256(json.dumps({
    "version": PARTITION_VERSION, "base_rule": RULE_DIGEST,
    "taxes": TAXES, "partition": dict(_PARTITION),
    "iss_cap": {"III": (602, 526, 1928, 418, 6526), "IV": (3133, 3200, 3013, 654, 0)},
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sixth_band_local_components(annex: Annex, rbt: Fraction) -> dict[str, Fraction]:
    """Local fifth-band supplement, including federal redistribution of ISS.

    PGDAS-D manual, example 8, pp. 117–118; LC 123 annexes III–V.
    This supplement is independent of the sixth-band federal component.
    """
    parts = dict.fromkeys(TAXES, Fraction(0))
    raw = _rate(annex, rbt, 4) * Fraction(_LOCAL[annex][4], 10000)
    if annex in {Annex.ANNEX_I, Annex.ANNEX_II}:
        parts["icms"] = raw
        return parts
    parts["iss"] = min(raw, Fraction(5, 100))
    excess = raw - parts["iss"]
    if excess:
        fixed = {
            Annex.ANNEX_III: (602, 526, 1928, 418, 6526),
            Annex.ANNEX_IV: (3133, 3200, 3013, 654, 0),
        }
        if annex in fixed:
            for tax, share in zip(TAXES[:5], fixed[annex], strict=True):
                parts[tax] = excess * Fraction(share, 10000)
        else:
            shares = _PARTITION[annex][4][:6]
            for tax, share in zip(TAXES[:6], shares, strict=True):
                parts[tax] = excess * Fraction(share, sum(shares))
    return parts


def partition_effective_rate(
    annex: Annex, rbt: Fraction, *, outside_local: bool = False,
) -> dict[str, Fraction]:
    """Exact 2026 effective components from the existing rate authority.

    No eligibility or treatment inference. Sixth-band local formula is the
    same one used by T04. ISS cap uses the explicit statutory annex shares.
    """
    idx = next((i for i, ceiling in enumerate(CEILINGS) if rbt <= ceiling), 5)
    effective = _rate(annex, rbt, idx)
    shares = _PARTITION[annex][idx]
    result = {tax: effective * Fraction(share, 10000)
              for tax, share in zip(TAXES, shares, strict=True)}
    if result["iss"] > Fraction(5, 100):
        remaining = effective - Fraction(5, 100)
        capped = {
            Annex.ANNEX_III: (602, 526, 1928, 418, 6526),
            Annex.ANNEX_IV: (3133, 3200, 3013, 654, 0),
        }
        if annex in capped:
            for tax, share in zip(TAXES[:5], capped[annex], strict=True):
                result[tax] = remaining * Fraction(share, 10000)
        else:
            federal = effective - result["iss"]
            for tax in TAXES[:6]:
                result[tax] *= remaining / federal
        result["iss"] = Fraction(5, 100)
    if outside_local:
        result["icms"] = result["iss"] = Fraction(0)
    elif idx == 5:
        supplement = _sixth_band_local_components(annex, rbt)
        for tax in TAXES:
            result[tax] += supplement[tax]
    return result


def assessment_partition(
    facts: SimplesFacts, annex: Annex, *, export: bool, outside_local: bool,
    mode: SimplesIbsCbsMode | None = None,
) -> tuple[dict[str, Fraction], Fraction, Fraction]:
    """Art. 24: versioned treatment of excess revenue by market and tax."""
    _verify_mode(facts.competence, mode)
    history = _rate_window(facts)
    if facts.competence.year == 2027:
        rbt = _window_revenue(history, export=export)
        return transition_effective_rate(
            facts.competence, annex, rbt, outside_local=outside_local, mode=mode,
        ), Fraction(0), Fraction(0)
    def revenue(month: MonthFacts) -> int:
        return month.export_cents if export else month.domestic_cents
    rbt = Fraction(sum(map(revenue, history)) * 12, len(history))
    annual = sum(revenue(m) for m in facts.months if m.competence.year == 2026)
    current = revenue(facts.months[-1])
    federal_fraction = _excess_fraction(
        annual, current, _annual_limit(facts.opened_month, 2026, LIMIT),
    )
    local_fraction = _excess_fraction(
        annual, current, _annual_limit(facts.opened_month, 2026, SUBLIMIT),
    )
    federal_cap = partition_effective_rate(annex, Fraction(LIMIT), outside_local=True)
    if rbt > SUBLIMIT and not outside_local:
        federal = partition_effective_rate(annex, rbt, outside_local=True)
        local = _sixth_band_local_components(annex, rbt)
        capped_local = _sixth_band_local_components(annex, Fraction(SUBLIMIT))
        return {
            tax: federal[tax] * (1 - federal_fraction)
            + federal_cap[tax] * federal_fraction
            + local[tax] * (1 - local_fraction)
            + capped_local[tax] * local_fraction
            for tax in TAXES
        }, federal_fraction, local_fraction
    normal = partition_effective_rate(annex, rbt, outside_local=outside_local)
    local_cap = partition_effective_rate(annex, Fraction(SUBLIMIT))
    for tax in TAXES:
        if tax in {"icms", "iss"}:
            if not outside_local:
                normal[tax] = normal[tax] * (1 - local_fraction) + (
                    local_cap[tax] * local_fraction
                )
        else:
            normal[tax] = normal[tax] * (1 - federal_fraction) + (
                federal_cap[tax] * federal_fraction
            )
    return normal, federal_fraction, local_fraction


# LC 214/2025 annexes XVIII–XXII, consolidated by LC 227/2026.
# Data for the 2027–2028 transition; not authorization to assess future PA.
TRANSITION_TAXES = ("irpj", "csll", "cbs", "cpp", "ipi", "icms", "iss", "ibs")
TRANSITION_SOURCE = (
    "https://www2.camara.leg.br/legin/fed/leicom/2025/"
    "leicomplementar-214-16-janeiro-2025-796905-normaatualizada-pl.html"
)
_TRANSITION_PARTITION = MappingProxyType({
    Annex.ANNEX_I: (
        (550, 350, 1533, 4150, 0, 3400, 0, 17),
        (550, 350, 1533, 4150, 0, 3400, 0, 17),
        (550, 350, 1533, 4200, 0, 3350, 0, 17),
        (550, 350, 1533, 4200, 0, 3350, 0, 17),
        (550, 350, 1533, 4200, 0, 3350, 0, 17),
        (1358, 1006, 3402, 4234, 0, 0, 0, 0),
    ),
    Annex.ANNEX_II: (
        (550, 350, 1385, 3750, 750, 3200, 0, 15),
        (550, 350, 1385, 3750, 750, 3200, 0, 15),
        (550, 350, 1385, 3750, 750, 3200, 0, 15),
        (550, 350, 1385, 3750, 750, 3200, 0, 15),
        (550, 350, 1385, 3750, 750, 3200, 0, 15),
        (853, 753, 2522, 2359, 3513, 0, 0, 0),
    ),
    Annex.ANNEX_III: (
        (400, 350, 1543, 4340, 0, 0, 3350, 17),
        (400, 350, 1691, 4340, 0, 0, 3200, 19),
        (400, 350, 1641, 4340, 0, 0, 3250, 19),
        (400, 350, 1641, 4340, 0, 0, 3250, 19),
        (400, 350, 1543, 4340, 0, 0, 3350, 17),
        (3509, 1504, 1929, 3058, 0, 0, 0, 0),
    ),
    Annex.ANNEX_IV: (
        (1880, 1520, 2126, 0, 0, 0, 4450, 24),
        (1980, 1520, 2473, 0, 0, 0, 4000, 27),
        (2080, 1520, 2374, 0, 0, 0, 4000, 26),
        (1780, 1920, 2275, 0, 0, 0, 4000, 25),
        (1880, 1920, 2176, 0, 0, 0, 4000, 24),
        (5371, 2159, 2470, 0, 0, 0, 0, 0),
    ),
    Annex.ANNEX_V: (
        (2500, 1500, 1696, 2885, 0, 0, 1400, 19),
        (2300, 1500, 1696, 2785, 0, 0, 1700, 19),
        (2400, 1500, 1795, 2385, 0, 0, 1900, 20),
        (2100, 1500, 1894, 2385, 0, 0, 2100, 21),
        (2300, 1250, 1696, 2385, 0, 0, 2350, 19),
        (3510, 1554, 1978, 2958, 0, 0, 0, 0),
    ),
})
_TRANSITION_ROWS = MappingProxyType({
    annex: (*rows[:5], (rows[5][0] - 10, rows[5][1]))
    for annex, rows in _ROWS.items()
})
_TRANSITION_ISS_CAP = MappingProxyType({
    Annex.ANNEX_III: (602, 526, 2320, 6526, 0, 0, 0, 26),
    Annex.ANNEX_IV: (3133, 3200, 3627, 0, 0, 0, 0, 40),
})
TRANSITION_TABLE_DIGEST = hashlib.sha256(json.dumps({
    "version": "lc214-lc227-2027-2028/v1",
    "source": TRANSITION_SOURCE, "valid_from": "2027-01-01",
    "valid_until": "2029-01-01", "taxes": TRANSITION_TAXES,
    "rows": dict(_TRANSITION_ROWS), "partition": dict(_TRANSITION_PARTITION),
    "iss_cap": dict(_TRANSITION_ISS_CAP),
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def transition_band(
    competence: date, annex: Annex, band: int,
) -> tuple[int, int, dict[str, int]]:
    """Versioned statutory lookup, before any regime, rate or basis decision."""
    if _month(competence).year not in {2027, 2028}:
        raise FiscalValidationError("transition table only valid in 2027–2028")
    if not isinstance(annex, Annex) or type(band) is not int or not 1 <= band <= 6:
        raise FiscalValidationError("explicit annex and band required")
    nominal, deduction = _TRANSITION_ROWS[annex][band - 1]
    return nominal, deduction, dict(zip(
        TRANSITION_TAXES, _TRANSITION_PARTITION[annex][band - 1], strict=True,
    ))


# CGSN 190/2026 arts. 21, 22, 22-A, 24 and 26. These rates are
# consultative; the application must resolve the canonical election.
TRANSITION_RULE_VERSION = "simples-cgsn190-2027/v1"
TRANSITION_PARTITION_DIGEST = hashlib.sha256(json.dumps({
    "version": TRANSITION_RULE_VERSION, "table_digest": TRANSITION_TABLE_DIGEST,
    "history": "lagged-12-months", "startup": "first-two-28-percent-first-band",
    "excess": "same-effective-rate", "local_taxes": ["icms", "iss", "ibs"],
    "regular_option": "remove-ibs-cbs-without-redistribution",
    "source": LEGAL_REFERENCES[1],
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _verify_mode(competence: date, mode: SimplesIbsCbsMode | None) -> None:
    if competence.year == 2027:
        if not isinstance(mode, SimplesIbsCbsMode) or mode not in {
            SimplesIbsCbsMode.SIMPLES_UNIFIED, SimplesIbsCbsMode.REGULAR_SEPARATE,
        }:
            raise FiscalValidationError("resolved IBS/CBS mode required for 2027")
    elif mode is not None:
        raise FiscalValidationError("IBS/CBS election does not apply to 2026 assessment")


def _rate_window(facts: SimplesFacts) -> tuple[MonthFacts, ...]:
    if facts.competence.year == 2027:
        return facts.months[:-2][-12:]
    return facts.months[:-1][-12:] or facts.months[-1:]


def _window_revenue(window: tuple[MonthFacts, ...], *, export: bool) -> Fraction:
    if not window:
        return Fraction(0)
    total = sum(m.export_cents if export else m.domestic_cents for m in window)
    return Fraction(total * 12, len(window))


def _transition_rate(competence: date, annex: Annex, rbt: Fraction, band: int) -> Fraction:
    nominal, deduction, _ = transition_band(competence, annex, band)
    return Fraction(nominal, 10000) - Fraction(deduction) / (rbt or Fraction(100))


def _transition_iss_excess(
    annex: Annex, shares: dict[str, int], excess: Fraction,
) -> dict[str, Fraction]:
    if annex in _TRANSITION_ISS_CAP:
        cap_shares = dict(zip(TRANSITION_TAXES, _TRANSITION_ISS_CAP[annex], strict=True))
        return {tax: excess * Fraction(share, 10000) for tax, share in cap_shares.items()}
    eligible = {
        tax: share for tax, share in shares.items() if tax not in {"iss", "icms"}
    }
    return {tax: excess * Fraction(share, sum(eligible.values()))
            for tax, share in eligible.items()}


def transition_effective_rate(
    competence: date, annex: Annex, rbt: Fraction, *, outside_local: bool,
    mode: SimplesIbsCbsMode | None, redistribute_iss: bool = True,
) -> dict[str, Fraction]:
    """Exact ordinary components, before reviewed operation-specific exclusions."""
    if competence.year != 2027 or rbt < 0:
        raise FiscalValidationError("reviewed 2027 rate window required")
    _verify_mode(competence, mode)
    idx = next((i for i, ceiling in enumerate(CEILINGS) if rbt <= ceiling), 5)
    _, _, shares = transition_band(competence, annex, idx + 1)
    effective = _transition_rate(competence, annex, rbt, idx + 1)
    result = {tax: effective * Fraction(share, 10000) for tax, share in shares.items()}
    if idx == 5 and not outside_local:
        _, _, fifth = transition_band(competence, annex, 5)
        fifth_effective = _transition_rate(competence, annex, rbt, 5)
        for tax in ("icms", "iss", "ibs"):
            result[tax] = fifth_effective * Fraction(fifth[tax], 10000)
        shares = fifth
    if result["iss"] > Fraction(5, 100):
        excess = result["iss"] - Fraction(5, 100)
        result["iss"] = Fraction(5, 100)
        if redistribute_iss and not outside_local:
            if idx < 5 and annex in _TRANSITION_ISS_CAP:
                cap_shares = dict(zip(
                    TRANSITION_TAXES, _TRANSITION_ISS_CAP[annex], strict=True,
                ))
                for tax, share in cap_shares.items():
                    if tax != "iss":
                        result[tax] = (effective - Fraction(5, 100)) * Fraction(share, 10000)
            else:
                for tax, extra in _transition_iss_excess(annex, shares, excess).items():
                    result[tax] += extra
    if outside_local:
        for tax in ("icms", "iss", "ibs"):
            result[tax] = Fraction(0)
    if mode is SimplesIbsCbsMode.REGULAR_SEPARATE:
        result["ibs"] = result["cbs"] = Fraction(0)
    return result
