"""T07: project the canonical monthly assessment into the pinned RTC contract.

The projection is advisory only: it is not a PGDAS declaration, an issuance
rate, or a substitute for reviewed operation classification. No second engine.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.regimes import SimplesIbsCbsMode
from kordena_fiscal.tax.rfb_simples_calculator import (
    AnnexRates,
    SimplesEffectiveRates,
)
from kordena_fiscal.tax.simples_nacional import (
    LimitStatus,
    SimplesFacts,
    _rate_window,
    _window_revenue,
    calculate_simples,
    transition_effective_rate,
)
from kordena_fiscal.tax.simples_segregation import RevenueLine


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
