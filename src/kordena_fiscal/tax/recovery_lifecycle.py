"""T19 deterministic lifecycle for reviewed, simulated fiscal cases only."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount, Movement
from kordena_fiscal.tax.historical_audit import Day, Digest, Id, Strict, Version
from kordena_fiscal.tax.unused_credits import CreditTax

SCHEMA = "nfcore.recovery-case/v1"
MAX_CASE_EVENTS = 100
MAX_CASES = 1000
MAX_CASE_SCAN_EVENTS = 5000
Kind = Literal["compensation", "restitution"]
Route = Literal["perdcomp", "administrative"]
Status = Literal[
    "requested", "transmitted", "homologated", "granted", "paid", "denied",
    "cancelled", "reversed", "released", "invalidated",
]
Action = Literal[
    "request", "transmit", "reject", "approve", "deny", "pay",
    "cancel", "reverse", "release", "invalidate",
]


class Terms(Strict):
    case_id: Digest
    competence: Day
    finding_id: Digest
    tax: CreditTax
    kind: Kind
    route: Route
    amount: Amount
    target_reference: Id
    legal_reference: Id

    @model_validator(mode="after")
    def valid(self) -> Terms:
        if self.amount.principal_cents <= 0:
            raise ValueError("case requires principal")
        if self.route == "perdcomp" and self.tax not in {"pis", "cofins"}:
            raise ValueError("PER/DCOMP route requires a supported federal credit")
        if self.tax == "icms" and self.kind != "compensation":
            raise ValueError("ICMS bookkeeping supports only administrative compensation")
        if self.tax == "icms" and self.amount.selic_cents:
            raise ValueError("ICMS bookkeeping source has no SELIC")
        if date.fromisoformat(self.competence).day != 1:
            raise ValueError("invalid case competence")
        return self


class Event(Strict):
    terms: Terms
    action: Action
    expected_version: Annotated[int, Field(ge=0, lt=MAX_CASE_EVENTS)]
    request_id: Id
    opinion_reference: Id
    professional_reference: Id
    evidence_reference: Id
    # Explicit reviewed operational deadline, not an automatic legal ruling.
    due_on: Day | None = None
    source_version: Version | None = None
    source_digest: Digest | None = None

    @model_validator(mode="after")
    def valid(self) -> Event:
        needs_source = self.action in {"request", "transmit", "release"}
        if needs_source != (self.source_version is not None and self.source_digest is not None):
            raise ValueError("case event requires exact current source binding")
        if not needs_source and (self.source_version is not None or self.source_digest is not None):
            raise ValueError("unexpected current source binding")
        needs_deadline = self.action in {"request", "transmit", "reject", "deny", "reverse"} or (
            self.action == "approve" and self.terms.kind == "restitution"
        )
        if needs_deadline:
            if self.due_on is None:
                raise ValueError("reviewed follow-up deadline required")
        elif self.due_on is not None:
            raise ValueError("unexpected terminal deadline")
        if self.due_on is not None:
            date.fromisoformat(self.due_on)
        return self


def plan(previous: Status | None, event: Event) -> tuple[Status, tuple[Movement, ...]]:
    """Pure transition plan. A rejected transport can be retried without a new reserve."""
    kind, action = event.terms.kind, event.action
    if previous is None and action == "request":
        return "requested", ("reserved",)
    if previous == "requested":
        if action == "reject":
            return "requested", ()
        if action == "transmit":
            return "transmitted", ("compensated",) if kind == "compensation" else ()
        if action == "cancel":
            return "cancelled", ("released",)
    if previous == "transmitted":
        if action == "approve":
            return ("homologated" if kind == "compensation" else "granted"), ()
        if action == "deny":
            # Quarantine: denial is not proof that the credit is reusable.
            return "denied", ("compensation_reversed",) if kind == "compensation" else ()
    if previous == "granted":
        if action == "pay":
            return "paid", ("restituted",)
        if action == "deny":
            return "denied", ()
    if previous == "homologated" and action == "reverse" and kind == "compensation":
        return "reversed", ("compensation_reversed",)
    if previous == "paid" and action == "reverse" and kind == "restitution":
        return "reversed", ("restitution_reversed",)
    if previous in {"denied", "reversed"}:
        if action == "release":
            return "released", ("released",)
        if action == "invalidate":
            return "invalidated", ("released", "reversed")
    raise FiscalValidationError("invalid recovery case transition")


def alert(status: Status, deadline: str | None, today: date) -> dict[str, object] | None:
    if deadline is None or status in {
        "homologated", "paid", "cancelled", "released", "invalidated",
    }:
        return None
    days = (date.fromisoformat(deadline) - today).days
    if days > 30:
        return None
    return {
        "due_on": deadline,
        "days_remaining": days,
        "severity": "overdue" if days < 0 else "due_soon",
        "automatic_legal_effect": False,
    }
