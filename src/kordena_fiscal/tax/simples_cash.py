"""Reviewed 2026 cash-basis receivables reconciliation (CGSN 140 arts. 16, 20, 77).

No independent tax rates or persistence. A complete reviewed installment
register is required; prior taxable amounts include compulsory recognition.
"""
from dataclasses import replace
from datetime import date
from typing import Any

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_nacional import Activity
from kordena_fiscal.tax.simples_segregation import (
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    _amount,
    _ref,
)


def reconcile_cash(
    competence: date, register: dict[str, Any],
) -> tuple[tuple[RevenueLine, ...], dict[str, int]]:
    lines, totals, _ = reconcile_cash_detail(competence, register)
    return lines, totals


def reconcile_cash_detail(
    competence: date, register: dict[str, Any],
) -> tuple[tuple[RevenueLine, ...], dict[str, int], tuple[RevenueLine, ...]]:
    """Return taxable lines, controls and remaining unrecognized balances.

    Separate balances support art. 20 IV for local-tax impediment. They are
    not added to the regular monthly DAS base.
    """
    if competence.year != 2026 or competence.day != 1:
        raise FiscalValidationError("cash rules limited to 2026")
    _ref(register["review_reference"])
    event = register["closing_event"]
    if event not in {"none", "closure", "return_to_accrual", "exclusion"}:
        raise FiscalValidationError("unknown cash closing event")
    # CGSN 140/2018 arts. 19–20: annual, irrevocable cash option.
    # Return to accrual is the last month of the calendar year; closure
    # and exclusion have their own event-dependent periods.
    if event == "return_to_accrual" and competence.month != 12:
        raise FiscalValidationError("cash return to accrual requires December")
    if event != "none":
        _ref(register["event_reference"])
    if competence.month == 12 and event == "none":
        raise FiscalValidationError("2027 transition requires reviewed closing event")
    rows = register["installments"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise FiscalValidationError("bounded installment register required")
    totals = dict(opening=0, accrued=0, received=0, closing=0, taxable=0,
                  previously_taxed_received=0, compulsory=0)
    seen: set[str] = set()
    result: list[RevenueLine] = []
    outstanding: list[RevenueLine] = []
    end = date(competence.year + (competence.month == 12), competence.month % 12 + 1, 1)
    for row in rows:
        key = row["installment_id"]
        _ref(key)
        if key in seen:
            raise FiscalValidationError("duplicate installment")
        seen.add(key)
        issued = date.fromisoformat(row["issued_on"])
        due = date.fromisoformat(row["due_on"])
        if issued >= end or due < issued:
            raise FiscalValidationError("invalid installment dates")
        principal, prior_received, prior_taxed, received = (
            row[k] for k in ("principal_cents", "prior_received_cents",
                             "prior_taxed_cents", "received_cents")
        )
        for amount in (principal, prior_received, prior_taxed, received):
            _amount(amount)
        if not prior_received <= prior_taxed <= principal or prior_received + received > principal:
            raise FiscalValidationError("installment balances do not reconcile")
        if issued >= competence and (prior_received or prior_taxed):
            raise FiscalValidationError("current installment has prior amounts")
        if issued.year + 1 < competence.year and prior_taxed != principal:
            raise FiscalValidationError("overdue mandatory recognition requires correction")
        old_taxed_credit = prior_taxed - prior_received
        already_taxed = min(received, old_taxed_credit)
        new_receipt = received - already_taxed
        remaining_unrecognized = principal - prior_taxed - new_receipt
        mandatory = (
            event != "none" or
            competence >= date(issued.year + 1, 12, 1)
        )
        compulsory = remaining_unrecognized if mandatory else 0
        taxable = new_receipt + compulsory
        totals["opening"] += principal - prior_received if issued < competence else 0
        totals["accrued"] += principal if issued >= competence else 0
        totals["received"] += received
        totals["closing"] += principal - prior_received - received
        totals["taxable"] += taxable
        totals["previously_taxed_received"] += already_taxed
        totals["compulsory"] += compulsory
        line = RevenueLine(
            key, taxable, Activity(row["activity"]), Market(row["market"]),
            FederalTreatment(row["federal"]), LocalTreatment(row["local"]),
            row["evidence_reference"], row["treatment_reference"],
        )
        result.append(line)
        if remaining_unrecognized > compulsory:
            outstanding.append(replace(line, cents=remaining_unrecognized - compulsory))
    if totals["opening"] + totals["accrued"] - totals["received"] != totals["closing"]:
        raise FiscalValidationError("cash register does not reconcile")
    for key, value in totals.items():
        _amount(register["control_totals"][key])
        if register["control_totals"][key] != value:
            raise FiscalValidationError("cash control totals do not reconcile")
    return tuple(result), totals, tuple(outstanding)


def verify_cash_continuity(
    competence: date, register: dict[str, Any], previous: dict[str, Any],
) -> None:
    """Require the exact preceding reviewed register, with no lost receivable."""
    month = date(competence.year - (competence.month == 1),
                 (competence.month - 2) % 12 + 1, 1)
    if month.year != 2026:
        raise FiscalValidationError("historical opening requires reviewed baseline")
    prior_lines, _ = reconcile_cash(month, previous)
    taxed = {line.line_id: line.cents for line in prior_lines}
    before = {row["installment_id"]: row for row in previous["installments"]}
    after = {row["installment_id"]: row for row in register["installments"]}
    for key, row in before.items():
        received = row["prior_received_cents"] + row["received_cents"]
        recognized = row["prior_taxed_cents"] + taxed[key]
        if key not in after:
            if received != row["principal_cents"] or recognized != row["principal_cents"]:
                raise FiscalValidationError("historical receivable missing")
            continue
        current = after[key]
        immutable = ("issued_on", "due_on", "principal_cents", "activity", "market",
                     "federal", "local", "evidence_reference", "treatment_reference")
        if any(current[k] != row[k] for k in immutable):
            raise FiscalValidationError("historical installment changed")
        if (current["prior_received_cents"] != received
                or current["prior_taxed_cents"] != recognized):
            raise FiscalValidationError("historical installment balances do not reconcile")
    for key, row in after.items():
        if key not in before and date.fromisoformat(row["issued_on"]) < competence:
            raise FiscalValidationError("historical installment lacks predecessor")
