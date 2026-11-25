"""T17 reviewed recovery estimates. Never recognizes, submits or realizes credit."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from fractions import Fraction
from typing import Annotated, Any, Literal

from lxml import etree
from pydantic import Field

from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.tax.historical_audit import (
    Cents,
    Day,
    Digest,
    Id,
    IssuerContext,
    Strict,
    Version,
    _required,
    _text,
    closed_months,
)
from kordena_fiscal.tax.simples_nacional import _round_cents
from kordena_fiscal.tax.unused_credits import Batch, CreditTax, Evidence, _unique_fields

SCHEMA = "nfcore.tax-recovery/v1"
TABLE_VERSION = "sicalc-2026-11-01-v1"
TABLE_VALUATION_MONTH = date(2026, 11, 1)
TABLE_URL = "https://www5.sefaz.mt.gov.br/documents/d/sefaz/selic-acumulada-11-2026-pdf"
# Sicalc accumulated percentages for payment in November 2026 (pp. 3-4).
# Integer hundredths of one percent, transcribed from the official RFB report.
# Consecutive differences yield the closed-month SELIC; never use the
# report's October 1% terminal charge as the October monthly rate.
_ACCUMULATED = {
    2021: (6136, 6077, 6000),  # Oct-Dec
    2022: (5927, 5851, 5758, 5675, 5572, 5470, 5367, 5250, 5143, 5041, 4939, 4827),
    2023: (4715, 4623, 4506, 4414, 4302, 4195, 4088, 3974, 3877, 3777, 3685, 3596),
    2024: (3499, 3419, 3336, 3247, 3164, 3085, 2994, 2907, 2823, 2730, 2651, 2558),
    2025: (2457, 2358, 2262, 2156, 2042, 1932, 1804, 1688, 1566, 1438, 1333, 1211),
    2026: (1095, 995, 874, 765, 658, 546, 424, 315, 207, 100),
}
ICMS_SOURCE = "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp87.htm"
CTN_SOURCE = "https://www.planalto.gov.br/ccivil_03/leis/l5172compilado.htm"
RFB_SOURCE = "https://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=122002"
Modality = Literal["icms_bookkeeping", "federal_undue_payment"]


def next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def monthly_selic() -> dict[str, int]:
    rows = [
        (date(year, start + index, 1), value)
        for year, values in sorted(_ACCUMULATED.items())
        for start in [10 if year == 2021 else 1]
        for index, value in enumerate(values)
    ]
    result = {}
    for (previous, old), (current, new) in zip(rows, rows[1:], strict=False):
        if next_month(previous) != current or not 0 < old - new <= 10000:
            raise FiscalValidationError("invalid official SELIC table")
        result[current.isoformat()] = old - new
    return result


def selic_reference() -> dict[str, Any]:
    data = monthly_selic()
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return {
        "version": TABLE_VERSION,
        "source_url": TABLE_URL,
        "normalized_sha256": hashlib.sha256(raw).hexdigest(),
        "first_month": min(data),
        "last_month": max(data),
        "unit": "basis_points",
        "last_valuation_month": TABLE_VALUATION_MONTH.isoformat(),
    }


def federal_interest(
    principal: int, payment: date, valuation: date
) -> tuple[int, list[dict[str, Any]]] | None:
    """Simple sum of closed-month rates, plus 1% in the projected final month."""
    if type(principal) is not int or principal < 0 or valuation < payment:
        raise FiscalValidationError("invalid recovery principal or dates")
    rates = monthly_selic()
    final = valuation.replace(day=1)
    current = payment.replace(day=1)
    if final > TABLE_VALUATION_MONTH:
        return None
    if current == final:
        return 0, []
    current = next_month(current)
    memory: list[dict[str, Any]] = []
    while current < final:
        key = current.isoformat()
        if key not in rates:
            return None
        memory.append({"competence": key, "basis_points": rates[key], "kind": "selic"})
        current = next_month(current)
    memory.append({"competence": final.isoformat(), "basis_points": 100, "kind": "final_month"})
    amount = _round_cents(Fraction(principal * sum(x["basis_points"] for x in memory), 10000))
    return amount, memory


def ordinary_deadline(anchor: date) -> date | None:
    # Exceptional calendars and leap-day anniversaries need specific legal review.
    try:
        deadline = anchor.replace(year=anchor.year + 5)
        # Weekend and non-working-day extensions are not assumed.
        return deadline if deadline.weekday() < 5 else None
    except ValueError:
        return None


class FederalCorrection(Strict):
    """Reviewed rectification for one fully reconciled receipt/tax component."""

    historical_digest: Digest
    payment_sha256: Digest
    assessment_reference: Id
    corrected_assessment_reference: Id
    corrected_assessment_sha256: Digest
    originally_due_cents: Cents
    corrected_due_cents: Cents


class Claim(Strict):
    issuer_cnpj: str
    competence: Day
    t16_digest: Digest
    finding_id: Digest
    tax: CreditTax
    modality: Modality
    checked_through: Day
    principal_cents: Cents
    anchor: Day
    ordinary_deadline: Day
    # Reviewed scope, enforceability, local rules and history; never inferred from XML.
    ordinary_clock_confirmed: bool
    no_prior_use_or_claim: bool
    causal_basis_confirmed: bool
    receipt_id: Id | None = None
    federal_correction: FederalCorrection | None = None
    citation: LegalCitation


class ReviewedClaim(Strict):
    claim: Claim
    review: Evidence
    legal_source: Evidence
    corrected_assessment: Evidence | None = None

    def verify(self) -> None:
        normalized = json.loads(self.review.contents(), object_pairs_hook=_unique_fields)
        if json.dumps(normalized, sort_keys=True) != json.dumps(
            self.claim.model_dump(), sort_keys=True
        ):
            raise FiscalValidationError("recovery review projection differs from source")
        self.legal_source.contents()
        if self.legal_source.sha256 != self.claim.citation.source_sha256:
            raise FiscalValidationError("recovery legal source digest mismatch")
        correction = self.claim.federal_correction
        if correction is None and self.corrected_assessment is not None:
            raise FiscalValidationError("correction source without reviewed correction")
        if correction is not None:
            if (
                self.corrected_assessment is None
                or self.corrected_assessment.sha256 != correction.corrected_assessment_sha256
            ):
                raise FiscalValidationError("missing or mismatched corrected assessment source")
            corrected = json.loads(
                self.corrected_assessment.contents(), object_pairs_hook=_unique_fields
            )
            expected = correction.model_dump(exclude={"corrected_assessment_sha256"}) | {
                "issuer_cnpj": self.claim.issuer_cnpj,
                "competence": self.claim.competence,
                "tax": self.claim.tax,
                "receipt_id": self.claim.receipt_id,
                "t16_digest": self.claim.t16_digest,
            }
            if json.dumps(corrected, sort_keys=True) != json.dumps(expected, sort_keys=True):
                raise FiscalValidationError("corrected assessment differs from reviewed source")


class RecoveryBatch(Strict):
    competence: Day
    t16_version: Version
    t16_digest: Digest
    claims: Annotated[list[ReviewedClaim], Field(max_length=1000)]


def invoice_dates(batch: Batch) -> dict[str, date]:
    """Called only after T16 validates every original XML and its protocol."""
    result = {}
    for purchase in batch.purchases:
        root = etree.fromstring(
            purchase.xml.contents(),
            parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
        )
        info = _required(_required(root, "NFe"), "infNFe")
        stamp = _text(_required(info, "ide"), "dhEmi")
        assert stamp is not None
        result[purchase.xml.sha256] = datetime.fromisoformat(stamp).date()
    return result


def estimate(
    batch: RecoveryBatch,
    issuer: Cnpj,
    context: IssuerContext,
    as_of: date,
    findings: list[dict[str, Any]],
    dates: dict[str, date],
    payments: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Estimate only independently reviewed, non-overlapping candidates."""
    period = date.fromisoformat(batch.competence)
    closed_months(period, as_of)
    by_id = {row["identity"]: row for row in findings}
    if len(by_id) != len(findings):
        raise FiscalValidationError("duplicate T16 finding identity")
    claims = {}
    allocated: dict[tuple[str, str], int] = {}
    corrections: dict[tuple[str, str], FederalCorrection] = {}
    for submitted in batch.claims:
        submitted.verify()
        claim = submitted.claim
        row = by_id.get(claim.finding_id)
        if (
            row is None
            or claim.finding_id in claims
            or (claim.issuer_cnpj, claim.competence, claim.t16_digest, claim.tax)
            != (issuer.value, batch.competence, batch.t16_digest, row["tax"])
        ):
            raise FiscalValidationError("recovery claim scope or identity mismatch")
        claims[claim.finding_id] = submitted
        if claim.modality == "federal_undue_payment" and claim.receipt_id is not None:
            payment_key = (claim.receipt_id, claim.tax)
            if payment_key in payments:
                allocated[payment_key] = allocated.get(payment_key, 0) + claim.principal_cents
                if allocated[payment_key] > payments[payment_key]["allocated_cents"]:
                    raise FiscalValidationError("recovery receipt principal overallocated")
                correction = claim.federal_correction
                if correction is not None:
                    prior = corrections.get(payment_key)
                    if prior is not None and prior != correction:
                        raise FiscalValidationError("conflicting reviewed receipt corrections")
                    corrections[payment_key] = correction

    rows = []
    for finding in findings:
        row = {
            "finding_id": finding["identity"],
            "tax": finding["tax"],
            "access_key": finding["access_key"],
            "item": finding["item"],
            "t16_candidate_cents": finding["candidate_cents"],
            "status": "insufficient_basis",
            "reason": "review_missing",
            "principal_cents": None,
            "adjustment_cents": None,
            "estimated_cents": None,
            "credit_recognized": False,
            "rate_memory": [],
        }
        reviewed = claims.get(finding["identity"])
        if finding["status"] != "unused_candidate" or not finding["candidate_cents"]:
            row["reason"] = "t16_not_eligible"
        elif reviewed is not None:
            claim = reviewed.claim
            row.update(
                modality=claim.modality,
                review_sha256=reviewed.review.sha256,
                citation=claim.citation.model_dump(),
                legal_source_sha256=reviewed.legal_source.sha256,
                anchor=claim.anchor,
                deadline=claim.ordinary_deadline,
                receipt_id=claim.receipt_id,
            )
            if not 0 < claim.principal_cents <= finding["candidate_cents"]:
                raise FiscalValidationError("recovery principal exceeds T16 balance")
            issued = dates[finding["xml_sha256"]]
            anchor = date.fromisoformat(claim.anchor)
            deadline = ordinary_deadline(anchor)
            citation = claim.citation
            if (
                claim.checked_through != as_of.isoformat()
                or not claim.ordinary_clock_confirmed
                or not claim.no_prior_use_or_claim
                or not claim.causal_basis_confirmed
                or deadline is None
                or claim.ordinary_deadline != deadline.isoformat()
                or anchor < issued
                or anchor > as_of
                or date.fromisoformat(citation.published_on) > as_of
                or date.fromisoformat(citation.valid_from) > anchor
                or (
                    citation.valid_until is not None
                    and date.fromisoformat(citation.valid_until) <= as_of
                )
            ):
                row["reason"] = "review_or_clock_unconfirmed"
            else:
                eligible = False
                if claim.modality == "icms_bookkeeping":
                    eligible = (
                        claim.tax == "icms"
                        and claim.receipt_id is None
                        and claim.federal_correction is None
                        and context.regime != "simples_nacional"
                        and anchor == issued
                    )
                    row["policy"] = {"source": ICMS_SOURCE, "provision": "art. 23"}
                elif claim.tax in {"pis", "cofins"} and context.regime != "simples_nacional":
                    payment = payments.get((claim.receipt_id or "", claim.tax))
                    correction = claim.federal_correction
                    payment_key = (claim.receipt_id or "", claim.tax)
                    eligible = (
                        payment is not None
                        and correction is not None
                        and payment["paid_on"] == claim.anchor
                        and correction.historical_digest == payment["historical_digest"]
                        and correction.payment_sha256 == payment["sha256"]
                        and correction.assessment_reference == payment["assessment_reference"]
                        and correction.corrected_assessment_reference
                        != correction.assessment_reference
                        and correction.originally_due_cents == payment["allocated_cents"]
                        and correction.originally_due_cents - correction.corrected_due_cents
                        == allocated.get(payment_key)
                    )
                    if eligible and correction is not None:
                        row["payment"] = payment
                        row["federal_correction"] = correction.model_dump()
                    row["policy"] = {
                        "deadline_source": CTN_SOURCE,
                        "deadline_provision": "art. 168, I",
                        "interest_source": RFB_SOURCE,
                        "interest_provision": "arts. 148, 149 and 151",
                    }
                if not eligible:
                    row["reason"] = "modality_or_payment_unconfirmed"
                elif as_of > deadline:
                    row.update(status="expired", reason="reviewed_ordinary_deadline_elapsed")
                else:
                    interest = (
                        (0, [])
                        if claim.modality == "icms_bookkeeping"
                        else federal_interest(claim.principal_cents, anchor, as_of)
                    )
                    if interest is None:
                        row["reason"] = "official_selic_month_missing"
                    else:
                        adjustment, memory = interest
                        row.update(
                            status="potential",
                            reason="reviewed_candidate_only",
                            principal_cents=claim.principal_cents,
                            adjustment_cents=adjustment,
                            estimated_cents=claim.principal_cents + adjustment,
                            rate_memory=memory,
                        )
        rows.append(row)
    # A shared correction is atomic for valuation: do not count an apparently
    # valid fraction if another allocation of the same receipt is unresolved.
    incomplete = {
        (row.get("receipt_id"), row["tax"])
        for row in rows
        if row.get("modality") == "federal_undue_payment"
        and row["status"] == "insufficient_basis"
    }
    for row in rows:
        if (
            row.get("modality") == "federal_undue_payment"
            and row["status"] == "potential"
            and (row.get("receipt_id"), row["tax"]) in incomplete
        ):
            row.update(
                status="insufficient_basis",
                reason="shared_receipt_correction_incomplete",
                principal_cents=None,
                adjustment_cents=None,
                estimated_cents=None,
                rate_memory=[],
            )
    return rows
