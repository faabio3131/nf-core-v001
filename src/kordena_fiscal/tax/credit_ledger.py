"""T18 internal double-entry credit subledger; no fiscal or accounting realization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import Field

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.historical_audit import Cents, Day, Digest, Id, Strict, Version
from kordena_fiscal.tax.unused_credits import CreditTax

SCHEMA = "nfcore.credit-ledger/v1"
MAX_EVENTS = 1000
MAX_LOTS = 1000
MAX_SCAN_EVENTS = 5000
Movement = Literal[
    "identified", "reserved", "released", "compensated", "reversed", "compensation_reversed",
    "restituted", "restitution_reversed",
]
Account = Literal["available", "reserved", "compensated", "reversed", "restituted"]
ACCOUNTS: tuple[Account, ...] = ("available", "reserved", "compensated", "reversed", "restituted")


class Amount(Strict):
    principal_cents: Cents
    selic_cents: Cents

    @property
    def total(self) -> int:
        return self.principal_cents + self.selic_cents


ZERO = Amount(principal_cents=0, selic_cents=0)


def add(left: Amount, right: Amount) -> Amount:
    return Amount(
        principal_cents=left.principal_cents + right.principal_cents,
        selic_cents=left.selic_cents + right.selic_cents,
    )


def subtract(left: Amount, right: Amount) -> Amount:
    if (
        right.principal_cents > left.principal_cents
        or right.selic_cents > left.selic_cents
    ):
        raise FiscalValidationError("negative ledger component")
    return Amount(
        principal_cents=left.principal_cents - right.principal_cents,
        selic_cents=left.selic_cents - right.selic_cents,
    )


class Command(Strict):
    competence: Day
    finding_id: Digest
    tax: CreditTax
    recovery_version: Version
    recovery_digest: Digest
    expected_version: Annotated[int, Field(ge=0, lt=MAX_EVENTS)]
    request_id: Id
    movement: Movement
    amount: Amount
    review_reference: Id
    reservation_id: Id | None = None
    compensation_id: Id | None = None


@dataclass
class Compensation:
    reservation: str
    amount: Amount
    reversed: bool = False
    destination: Account = "compensated"


@dataclass
class State:
    """Replay state, never supplied by the caller or used as a mutable DB balance."""

    original: Amount = ZERO
    balances: dict[Account, Amount] = field(
        default_factory=lambda: {name: ZERO for name in ACCOUNTS}
    )
    reservations: dict[str, Amount] = field(default_factory=dict)
    compensations: dict[str, Compensation] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)

    def projection(self) -> dict[str, Any]:
        self.check()
        return {
            "identified": self.original.model_dump(),
            # Preserve the exact historical T18 snapshot projection until a
            # restitution event first occurs; then expose the additional account.
            **{
                name: self.balances[name].model_dump()
                for name in ACCOUNTS
                if name != "restituted" or any(
                    entry.destination == "restituted" for entry in self.compensations.values()
                )
            },
            "total_cents": self.original.total,
        }

    def check(self) -> None:
        for component in ("principal_cents", "selic_cents"):
            if sum(getattr(value, component) for value in self.balances.values()) != getattr(
                self.original, component
            ):
                raise FiscalValidationError("ledger lot is not balanced")
            if sum(getattr(value, component) for value in self.reservations.values()) != getattr(
                self.balances["reserved"], component
            ):
                raise FiscalValidationError("ledger reservation reconciliation mismatch")
            for destination in ("compensated", "restituted"):
                if sum(
                    getattr(value.amount, component)
                    for value in self.compensations.values()
                    if not value.reversed and value.destination == destination
                ) != getattr(self.balances[destination], component):
                    raise FiscalValidationError("ledger settlement reconciliation mismatch")


def transition(state: State, command: Command) -> list[dict[str, Any]]:
    """Apply a validated command. Debit destination, credit source, by component."""
    if command.expected_version != len(state.seen) or command.request_id in state.seen:
        raise FiscalValidationError("ledger version or request conflict")
    amount = command.amount
    if amount.total <= 0:
        raise FiscalValidationError("ledger movement must be positive")
    movement = command.movement
    # Conservative internal gate only. No legal proportionality is inferred:
    # T19 must apply the reviewed rule before any real fiscal compensation.
    if movement in {"reserved", "compensated", "restituted"} and amount.principal_cents == 0:
        raise FiscalValidationError("ledger reservation or compensation requires principal")
    reservation = command.reservation_id
    compensation = command.compensation_id
    source: Account | Literal["origin"]
    destination: Account
    if movement == "identified":
        if state.seen or reservation is not None or compensation is not None:
            raise FiscalValidationError("ledger lot already identified or invalid reference")
        if amount.principal_cents <= 0:
            raise FiscalValidationError("ledger identification requires principal")
        source, destination = "origin", "available"
    else:
        if not state.seen:
            raise FiscalValidationError("ledger identification required")
        if movement == "reserved":
            if reservation is not None or compensation is not None:
                raise FiscalValidationError("invalid reservation reference")
            source, destination = "available", "reserved"
        elif movement in {"released", "compensated", "restituted"}:
            if (
                reservation is None
                or reservation not in state.reservations
                or compensation is not None
            ):
                raise FiscalValidationError("unknown reservation")
            # Independent reservation limit, not just the global reserved account.
            subtract(state.reservations[reservation], amount)
            source = "reserved"
            destination = "available"
            if movement == "compensated":
                destination = "compensated"
            elif movement == "restituted":
                destination = "restituted"
        elif movement in {"compensation_reversed", "restitution_reversed"}:
            if reservation is not None or compensation is None:
                raise FiscalValidationError("exact compensation reference required")
            prior = state.compensations.get(compensation)
            settlement = "compensated" if movement == "compensation_reversed" else "restituted"
            if (
                prior is None or prior.reversed or prior.amount != amount
                or prior.destination != settlement
            ):
                raise FiscalValidationError("compensation missing, reversed or amount differs")
            source, destination = prior.destination, "reserved"
        else:
            if reservation is not None or compensation is not None:
                raise FiscalValidationError("invalid cancellation reference")
            # Cancel only unencumbered value. Compensations must first be reversed
            # and reservations released, each by separate append-only events.
            source, destination = "available", "reversed"

    # All checks and bounded arithmetic before mutating state.
    after_source = subtract(state.balances[source], amount) if source != "origin" else ZERO
    after_destination = add(state.balances[destination], amount)
    if movement == "identified":
        state.original = amount
    elif movement == "reserved":
        state.reservations[command.request_id] = amount
    elif movement in {"released", "compensated", "restituted"}:
        assert reservation is not None
        state.reservations[reservation] = subtract(state.reservations[reservation], amount)
        if movement != "released":
            state.compensations[command.request_id] = Compensation(
                reservation, amount, destination=destination
            )
    elif movement in {"compensation_reversed", "restitution_reversed"}:
        assert compensation is not None
        old = state.compensations[compensation]
        state.reservations[old.reservation] = add(state.reservations[old.reservation], amount)
        old.reversed = True

    if source != "origin":
        state.balances[source] = after_source
    state.balances[destination] = after_destination
    state.seen.add(command.request_id)
    state.check()
    return [
        {"account": destination, "side": "debit", **amount.model_dump()},
        {"account": source, "side": "credit", **amount.model_dump()},
    ]
