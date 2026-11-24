"""Cajamar municipal NFS-e deadlines and allowed cancellation motives.

Authoritative basis: Cajamar Decree 7.311/2024, articles 15, 15-A, 15-B
and 15-C, Diário Oficial edition 1292 (2024-10-01), pages 1 and 2.
Administrative exceptions are NOT approvals for automated SOAP execution.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from kordena_fiscal.domain import FiscalValidationError

CAJAMAR_GAZETTE = (
    "https://cajamar.sp.gov.br/diariooficial/wp-content/uploads/sites/3/1292-1.pdf"
)
_SAO_PAULO = ZoneInfo("America/Sao_Paulo")
CANCELLATION_MOTIVES = frozenset({
    "service_not_provided",
    "duplicate_invoice",
    "incorrect_taker",
    "incorrect_amount",
})


def cajamar_regular_deadline(competence: date) -> date:
    """The tenth day of the calendar month after service competence."""
    if type(competence) is not date:
        raise FiscalValidationError("Cajamar requires a validated fiscal competence")
    year = competence.year + (competence.month == 12)
    month = competence.month % 12 + 1
    return date(year, month, 10)


def validate_cajamar_automatic_cancellation(
    *,
    competence: date,
    reason: str,
    reviewed_at: datetime,
) -> date:
    """Validate a *direct* municipal cancellation before its sole SOAP POST.

    Outside the deadline, the municipality's administrative process is the
    applicable separate authority. Never infer administrative approval.
    """
    if (
        not isinstance(reason, str)
        or reason not in CANCELLATION_MOTIVES
        or not isinstance(reviewed_at, datetime)
        or reviewed_at.tzinfo is None
    ):
        raise FiscalValidationError("Cajamar cancellation requires one legal motive")
    deadline = cajamar_regular_deadline(competence)
    if reviewed_at.astimezone(_SAO_PAULO).date() > deadline:
        raise FiscalValidationError(
            "Cajamar direct cancellation expired; municipal administrative process required"
        )
    return deadline
