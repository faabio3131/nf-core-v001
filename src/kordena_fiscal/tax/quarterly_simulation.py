"""Advisory 2026 scenarios for a reviewed, ordinary non-financial legal entity."""
from __future__ import annotations

from datetime import date
from fractions import Fraction
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from kordena_fiscal.cognitive.economy_contract import Cents, ContractModel, Digest
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.rfb_regime_regular_calculator import (
    CALCULATOR_DATABASE_VERSION,
    REGIME_REGULAR_CALCULATOR_PIN,
    parse_response,
)

SCHEMA = "nfcore.quarterly-regime-facts/v1"
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
SignedCents = Annotated[int, Field(ge=-(2**63 - 1), le=2**63 - 1)]


class OfficialDocument(ContractModel):
    document_reference: Reference
    response: Annotated[str, StringConstraints(min_length=1, max_length=131072)]
    response_sha256: Digest
    item_numbers: Annotated[list[Annotated[int, Field(ge=1, le=990)]], Field(min_length=1,
                                                                             max_length=990)]


class Month(ContractModel):
    competence: str
    cumulative_base: Cents
    noncumulative_base: Cents
    pis_credit: Cents
    cofins_credit: Cents
    # Sum of computed official line amounts, separately reconciled per month.
    documents: Annotated[list[OfficialDocument], Field(max_length=500)]
    ibs_credits: Cents
    cbs_credits: Cents
    rtc_evidence: Reference
    rtc_component: str


class Quarter(ContractModel):
    schema_version: Literal["nfcore.quarterly-regime-facts/v1"]
    review_status: Literal["reviewed"]
    review_reference: Reference
    period_start: str
    scope: Literal["consolidated_ordinary_nonfinancial_full_quarter_2026"]
    hypothesis: Literal["ordinary_trade_and_general_services"]
    trade_revenue: Cents
    services_revenue: Cents
    # Effective ordinary bands after reviewed YTD adjustments (LC 224).
    irpj_ordinary_limit: Cents
    csll_ordinary_limit: Cents
    irpj_other_taxable: Cents
    csll_other_taxable: Cents
    real_accounting_result: SignedCents
    irpj_additions: Cents
    irpj_exclusions: Cents
    csll_additions: Cents
    csll_exclusions: Cents
    irpj_loss_applied: Cents
    csll_loss_applied: Cents
    months: Annotated[list[Month], Field(min_length=3, max_length=3)]


def rounded(amount: Fraction) -> int:
    """Nearest cent, half up for non-negative bases."""
    return (2 * amount.numerator + amount.denominator) // (2 * amount.denominator)


def percentage(base: int, basis_points: int) -> int:
    return rounded(Fraction(base * basis_points, 10_000))


def presumed(facts: Quarter, trade_rate: int, limit: int, uplift: bool) -> int:
    revenue = facts.trade_revenue + facts.services_revenue
    if not revenue:
        return 0
    weighted = facts.trade_revenue * trade_rate + facts.services_revenue * 3200
    excess = max(0, revenue - limit) if uplift else 0
    return rounded(Fraction(weighted * (10 * revenue + excess), 100000 * revenue))


def adjusted(result: int, applied_loss: int) -> int:
    base = max(0, result)
    if applied_loss * 100 > base * 30:
        raise FiscalValidationError("loss offset exceeds ordinary limit")
    return base - applied_loss


def income(irpj: int, csll: int) -> dict[str, int]:
    return {"irpj_base": irpj, "csll_base": csll, "irpj": percentage(irpj, 1500),
            "additional_irpj": percentage(max(0, irpj - 6_000_000), 1000),
            "csll": percentage(csll, 900)}


def simulate(quarter: date, facts: Quarter) -> dict[str, Any]:
    if (quarter.year != 2026 or quarter.month not in (1, 4, 7, 10)
            or quarter.day != 1 or facts.period_start != quarter.isoformat()):
        raise FiscalValidationError("unsupported quarterly period")
    ordinal = (quarter.month + 2) // 3
    # Only the first period has no prior-period adjustment.
    if (facts.irpj_ordinary_limit > ordinal * 125_000_000
            or (ordinal == 1 and facts.irpj_ordinary_limit != 125_000_000)
            or facts.csll_ordinary_limit > max(0, ordinal - 1) * 125_000_000
            or (ordinal == 2 and facts.csll_ordinary_limit != 125_000_000)):
        raise FiscalValidationError("invalid reviewed presumption band")
    presumed_income = income(
        presumed(facts, 800, facts.irpj_ordinary_limit, True) + facts.irpj_other_taxable,
        presumed(facts, 1200, facts.csll_ordinary_limit, ordinal > 1) + facts.csll_other_taxable,
    )
    real_income = income(
        adjusted(facts.real_accounting_result + facts.irpj_additions - facts.irpj_exclusions,
                 facts.irpj_loss_applied),
        adjusted(facts.real_accounting_result + facts.csll_additions - facts.csll_exclusions,
                 facts.csll_loss_applied),
    )
    monthly = []
    app = REGIME_REGULAR_CALCULATOR_PIN.application_version
    version = f"app={app};db={CALCULATOR_DATABASE_VERSION}"
    seen: set[str] = set()
    for index, month in enumerate(facts.months):
        expected = date(quarter.year, quarter.month + index, 1).isoformat()
        if month.competence != expected or month.rtc_component != version:
            raise FiscalValidationError("reviewed monthly evidence mismatch")
        debits = {"vIBS": 0, "vCBS": 0}
        for document in month.documents:
            raw = document.response.encode("utf-8")
            if (document.document_reference in seen
                    or sha256(raw).hexdigest() != document.response_sha256):
                raise FiscalValidationError("duplicate document or invalid official reply digest")
            seen.add(document.document_reference)
            try:
                reply = parse_response(raw, expected_items=document.item_numbers,
                                       component_version=version).require_all_computed()
            except (AttributeError, TypeError, RecursionError) as exc:
                raise FiscalValidationError("malformed RTC item") from exc
            for item in reply.items:
                for tax in debits:
                    value = item.values.get(tax)
                    if value is None or not value.is_finite() or value < 0 or value > 10**16:
                        raise FiscalValidationError("invalid official tax value")
                    cents = value * 100
                    if cents != int(cents):
                        raise FiscalValidationError("official tax value requires whole cents")
                    debits[tax] += int(cents)
        monthly.append({
            "competence": expected,
            "cumulative": {"pis": percentage(month.cumulative_base, 65),
                           "cofins": percentage(month.cumulative_base, 300)},
            "noncumulative": {
                "pis_balance": percentage(month.noncumulative_base, 165) - month.pis_credit,
                "cofins_balance": percentage(month.noncumulative_base, 760) - month.cofins_credit,
            },
            "regular_vat": {"ibs_balance": debits["vIBS"] - month.ibs_credits,
                            "cbs_balance": debits["vCBS"] - month.cbs_credits,
                            "evidence": month.rtc_evidence, "component": version},
        })
    return {"status": "simulated", "lucro_presumido": presumed_income, "lucro_real": real_income,
            "months": monthly, "period_start": facts.period_start, "unit": "BRL_cent",
            "review_reference": facts.review_reference, "advisory_only": True,
            "issuance_authorized": False, "payment_authorized": False}
