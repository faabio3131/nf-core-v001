"""T07: project the canonical monthly assessment into the pinned RTC contract.

The projection is advisory only: it is not a PGDAS declaration, an issuance
rate, or a substitute for reviewed operation classification. No second engine.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.models import SIMPLES_ACTIVITY_CODES
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode
from kordena_fiscal.tax.rfb_regime_regular_calculator import (
    CALCULATOR_DATABASE_VERSION,
    RegimeRegularItem,
    RegimeRegularNominalRates,
    RfbRegimeRegularCalculatorClient,
    compare_regime_regular_shadow,
)
from kordena_fiscal.tax.rfb_regime_regular_calculator import (
    build_request as build_regular_request,
)
from kordena_fiscal.tax.rfb_simples_calculator import (
    AnnexRates,
    NfseSimplesItem,
    RfbCalculatorError,
    RfbSimplesCalculatorClient,
    SimplesEffectiveRates,
    build_nfse_request,
    calculate_unassisted,
    compare_shadow,
)
from kordena_fiscal.tax.simples_nacional import (
    Activity,
    LimitStatus,
    SimplesFacts,
    _rate_window,
    _round_cents,
    _window_revenue,
    calculate_simples,
    transition_effective_rate,
)
from kordena_fiscal.tax.simples_segregation import (
    TRANSITION_SPECIAL_TAXES,
    Market,
    RevenueLine,
    _amount,
    _ref,
)


def _percentage(rate: Fraction) -> str:
    with localcontext() as context:
        context.prec = 64
        value = Decimal(rate.numerator) * 100 / Decimal(rate.denominator)
        return format(value.quantize(Decimal("1e-28")), "f")


def project_rtc_rates(
    facts: SimplesFacts, lines: tuple[RevenueLine, ...], mode: SimplesIbsCbsMode,
) -> dict[str, object]:
    if facts.competence.year != 2027:
        raise FiscalValidationError("RTC Simples rate projection requires 2027")
    activities = {line.activity for line in lines} or {facts.activity}
    results = [
        calculate_simples(replace(facts, activity=activity),
                          ordinary_domestic_base_cents=0, mode=mode)
        for activity in sorted(activities)
    ]
    if any(result.limit_status in {LimitStatus.OUTSIDE, LimitStatus.RETROACTIVE}
           or result.sublimit_status is LimitStatus.RETROACTIVE for result in results):
        raise FiscalValidationError("excluded assessment cannot project RTC rates")
    outside = results[0].sublimit_status is LimitStatus.OUTSIDE
    payload: dict[str, object] = {
        "status": "advisory", "competence": facts.competence.isoformat(),
        "ibs_cbs_mode": mode.value, "requires_operation_review": True,
        "issuance_authorized": False, "regular_calculator_required": (
            mode is SimplesIbsCbsMode.REGULAR_SEPARATE or outside
        ),
    }
    if mode is SimplesIbsCbsMode.REGULAR_SEPARATE:
        return payload
    factor = results[0].factor_r
    for market, export in (("domestic", False), ("export", True)):
        annexes: dict[str, AnnexRates] = {}
        rbt = _window_revenue(_rate_window(facts), export=export)
        for result in results:
            annex = result.annex
            rates = transition_effective_rate(
                facts.competence, annex, rbt, outside_local=outside, mode=mode,
            )
            plain = transition_effective_rate(
                facts.competence, annex, rbt, outside_local=outside, mode=mode,
                redistribute_iss=False,
            )
            service = annex.value in {"III", "IV", "V"}
            annexes[annex.value] = AnnexRates(
                _percentage(rates["cbs"]),
                None if outside else _percentage(rates["ibs"]),
                _percentage(plain["cbs"]) if service else None,
                _percentage(plain["ibs"]) if service and not outside else None,
            )
        payload[market] = SimplesEffectiveRates(
            annexes=annexes, factor_r=None if factor is None else factor >= Decimal("0.28"),
            above_sublimit=outside,
        ).as_payload()
    return payload


@dataclass(frozen=True, slots=True)
class NfseComparisonPlan:
    line_id: str
    calculator: str
    request: dict[str, object]
    expected: dict[str, Decimal]
    monthly_reference: dict[str, Decimal] | None = None


def _money(cents: int) -> Decimal:
    _amount(cents)
    return Decimal(cents) / Decimal(100)


def _reviewed_decimal(value: str) -> Decimal:
    if not isinstance(value, str):
        raise FiscalValidationError("reviewed decimal text required")
    try:
        result = Decimal(value)
    except ArithmeticError as exc:
        raise FiscalValidationError("invalid reviewed decimal") from exc
    if not result.is_finite() or result < 0:
        raise FiscalValidationError("invalid reviewed decimal")
    return result


def plan_nfse_comparisons(
    facts: SimplesFacts, lines: tuple[RevenueLine, ...], mode: SimplesIbsCbsMode,
    operations: object,
) -> tuple[NfseComparisonPlan, ...]:
    """Use only scoped reviewed lines; document rounding is not DAS rounding."""
    if not isinstance(operations, list) or len(operations) > 20:
        raise FiscalValidationError("at most 20 reviewed NFS-e operations per snapshot")
    by_id = {line.line_id: line for line in lines}
    plans: list[NfseComparisonPlan] = []
    seen: set[str] = set()
    for raw in operations:
        if not isinstance(raw, dict):
            raise FiscalValidationError("invalid reviewed RTC operation")
        line_id = raw["line_id"]
        if not isinstance(line_id, str) or line_id in seen or line_id not in by_id:
            raise FiscalValidationError("duplicate or unknown RTC revenue line")
        seen.add(line_id)
        line = by_id[line_id]
        if line.activity not in {
            Activity.SERVICE_III, Activity.SERVICE_IV, Activity.SERVICE_FACTOR_R,
        }:
            raise FiscalValidationError("NFS-e comparison requires reviewed service revenue")
        if raw["document_reference"] != line.evidence_reference:
            raise FiscalValidationError("RTC document does not match revenue evidence")
        _ref(raw["review_reference"])
        instant = datetime.fromisoformat(raw["occurred_at"])
        if instant.utcoffset() is None:
            raise FiscalValidationError("RTC operation requires an offset")
        local = instant.astimezone(ZoneInfo("America/Sao_Paulo")).date()
        if local.replace(day=1) != facts.competence or (
            facts.registered_on is not None and local < facts.registered_on
        ):
            raise FiscalValidationError("RTC operation outside assessment competence")
        result = calculate_simples(
            replace(facts, activity=line.activity), ordinary_domestic_base_cents=0, mode=mode,
        )
        if result.limit_status in {LimitStatus.OUTSIDE, LimitStatus.RETROACTIVE} or (
            result.sublimit_status is LimitStatus.RETROACTIVE
        ):
            raise FiscalValidationError("excluded assessment cannot compare RTC operation")
        outside = result.sublimit_status is LimitStatus.OUTSIDE
        treatments = dict(zip(TRANSITION_SPECIAL_TAXES, line.transition_treatments or (),
                              strict=True))
        if mode is SimplesIbsCbsMode.SIMPLES_UNIFIED:
            if (type(raw["simples_base_cents"]) is not int
                    or raw["simples_base_cents"] != line.cents):
                raise FiscalValidationError("NFS-e base must reconcile with reviewed revenue")
            code = raw["activity_code"]
            if code not in SIMPLES_ACTIVITY_CODES or code == "90" or (
                (code == "09") != (line.activity is Activity.SERVICE_FACTOR_R)
            ):
                raise FiscalValidationError("NFS-e activity requires confirmed fiscal mapping")
            if type(raw["iss_withheld"]) is not bool:
                raise FiscalValidationError("explicit ISS retention required")
            if raw["iss_withheld"] != (treatments["iss"] == "withheld"):
                raise FiscalValidationError("ISS retention does not match segregation")
            without_iss = treatments["iss"] != "ordinary" or outside
            if not outside and (
                without_iss != (raw["iss_taxation"] != "1" or raw["iss_withheld"]
                                or raw.get("municipal_benefit") == "1")
            ):
                raise FiscalValidationError("ISS incidence does not match segregation")
            rbt = _window_revenue(_rate_window(facts), export=line.market is Market.EXPORT)
            rates = transition_effective_rate(
                facts.competence, result.annex, rbt, outside_local=outside, mode=mode,
            )
            plain = transition_effective_rate(
                facts.competence, result.annex, rbt, outside_local=outside, mode=mode,
                redistribute_iss=False,
            )
            pair = AnnexRates(
                _percentage(rates["cbs"]), None if outside else _percentage(rates["ibs"]),
                _percentage(plain["cbs"]), None if outside else _percentage(plain["ibs"]),
            )
            contract = SimplesEffectiveRates(
                {result.annex.value: pair},
                factor_r=None if result.factor_r is None else result.factor_r >= Decimal("0.28"),
                above_sublimit=outside,
            )
            request = build_nfse_request(
                operation_id=line_id, date=local.isoformat(), simples_option="3",
                ibs_cbs_regime="2" if outside else "1",
                taxes_regime="2" if outside else "1", rates=contract,
                item=NfseSimplesItem(
                    1, code, raw["c_class_trib"], raw["nbs"], _money(line.cents),
                    raw["iss_taxation"], raw["iss_withheld"], raw.get("municipal_benefit"),
                ),
            )
            applied = plain if without_iss else rates
            expected = {"vBC": _money(line.cents)}
            monthly_reference: dict[str, Decimal] = {}
            for tax, key in (("cbs", "vCBSSN"), ("ibs", "vIBSSN")):
                if tax == "ibs" and outside:
                    continue
                rate = applied[tax] if treatments[tax] == "ordinary" else Fraction(0)
                monthly_reference[key] = _money(_round_cents(rate * line.cents))
                # Pinned Java SimplesNacionalCalculoService rounds NFS-e rates
                # to 2 percentage-point decimals before calculating the item.
                layout_rate = Fraction(_round_cents(rate * 10_000), 10_000)
                expected[key] = _money(_round_cents(layout_rate * line.cents))
            plans.append(NfseComparisonPlan(
                line_id, "simples", request, expected, monthly_reference,
            ))
        if mode is SimplesIbsCbsMode.REGULAR_SEPARATE or outside:
            regular = raw["regular_reference"]
            _ref(regular["evidence_reference"])
            rates_object = regular["nominal_rates"]
            base = _money(regular["base_cents"])
            rr_request = build_regular_request(
                operation_id=line_id, occurred_at_iso=raw["occurred_at"],
                municipality_ibge=regular["municipality_ibge"], state_code=regular["uf"],
                document_type=91, items=[RegimeRegularItem(
                    1, regular["cst"], raw["c_class_trib"], base, nbs=raw["nbs"],
                    nominal_rates=RegimeRegularNominalRates(
                        _reviewed_decimal(rates_object["cbs"]),
                        _reviewed_decimal(rates_object["ibs_estadual"]),
                        _reviewed_decimal(rates_object["ibs_municipal"]),
                        rates_object["evidence_reference"],
                    ),
                )],
            )
            rr_expected = {"vBC": base, "vIBS": _money(regular["ibs_cents"])}
            if mode is SimplesIbsCbsMode.REGULAR_SEPARATE:
                rr_expected["vCBS"] = _money(regular["cbs_cents"])
            plans.append(NfseComparisonPlan(line_id, "regular", rr_request, rr_expected))
    return tuple(plans)


def execute_nfse_comparisons(
    plans: tuple[NfseComparisonPlan, ...],
    simples: RfbSimplesCalculatorClient | None,
    regular: RfbRegimeRegularCalculatorClient | None,
) -> dict[str, object]:
    outcomes: list[dict[str, Any]] = []
    for plan in plans:
        row: dict[str, Any] = {
            "line_id": plan.line_id, "calculator": plan.calculator,
            "comparison_basis": ("nfse_layout" if plan.calculator == "simples"
                                 else "reviewed_regular_document"),
            "monthly_reference_not_das": (
                {k: str(v) for k, v in plan.monthly_reference.items()}
                if plan.monthly_reference is not None else None
            ),
        }
        try:
            if plan.calculator == "simples":
                if simples is None:
                    raise RfbCalculatorError("Simples calculator unavailable")
                sn = calculate_unassisted(simples, plan.request).require_all_calculated()
                if not sn.component_version.endswith(f";db={CALCULATOR_DATABASE_VERSION}"):
                    raise RfbCalculatorError("Simples calculator database differs from pin")
                differences = compare_shadow(sn, {1: plan.expected}, fields=tuple(plan.expected))
                state = sn.items[0].state
                values = sn.items[0].values
                row["component_version"] = sn.component_version
            else:
                if regular is None:
                    raise RfbCalculatorError("Regular calculator unavailable")
                rr = regular.calculate(plan.request).require_all_computed()
                if not rr.component_version.endswith(f";db={CALCULATOR_DATABASE_VERSION}"):
                    raise RfbCalculatorError("Regular calculator database differs from pin")
                differences = compare_regime_regular_shadow(
                    rr, {1: plan.expected}, fields=tuple(plan.expected),
                )
                state = rr.items[0].state
                values = rr.items[0].values
                row["component_version"] = rr.component_version
            row.update({
                "status": ("simulated" if state != "CALCULADO"
                           else "divergent" if differences else "match"),
                "component_state": state,
                "expected": {k: str(v) for k, v in plan.expected.items()},
                "official": {k: str(v) for k, v in values.items()},
                "differences": [{
                    "field": diff.field, "expected": str(diff.nfcore),
                    "official": str(diff.official),
                } for diff in differences],
            })
        except RfbCalculatorError:
            row["status"] = "unavailable_or_rejected"
        outcomes.append(row)
    return {
        "status": ("not_requested" if not outcomes else
                   "match" if all(r["status"] == "match" for r in outcomes) else "review_required"),
        "operations": outcomes, "official_pgdas_certification": False,
        "issuance_authorized": False,
    }
