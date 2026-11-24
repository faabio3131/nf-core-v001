"""Osasco municipal automatic cancellation period and replacement semantics.

Official Osasco FAQ (Decreto 14.010/2023): ordinary taxpayer cancellation
is available until the tenth day of the month following invoice issuance.
After the deadline the municipal administrative process is distinct from WCF.
Manual WS v2.1, p.33: cancellation type N disallows a replacement; type S
identifies a cancellation for a separately issued substitute note.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from kordena_fiscal.domain import FiscalValidationError

_SP = ZoneInfo("America/Sao_Paulo")


def validate_osasco_automatic_cancellation(
    *, issued_at: datetime, reviewed_at: datetime,
) -> date:
    """Return official day-10 limit or reject WCF cancellation after expiry."""
    if (
        not isinstance(issued_at, datetime)
        or issued_at.tzinfo is None
        or issued_at.utcoffset() is None
        or not isinstance(reviewed_at, datetime)
        or reviewed_at.tzinfo is None
        or reviewed_at.utcoffset() is None
    ):
        raise FiscalValidationError("Osasco fiscal timestamps must be timezone-aware")
    issue = issued_at.astimezone(_SP).date()
    review = reviewed_at.astimezone(_SP).date()
    if review < issue:
        raise FiscalValidationError("Osasco municipal invoice cannot be future-dated")
    year = issue.year + (1 if issue.month == 12 else 0)
    month = 1 if issue.month == 12 else issue.month + 1
    deadline = date(year, month, 10)
    if review > deadline:
        raise FiscalValidationError(
            "Osasco cancellation after day 10 requires municipal administrative process"
        )
    return deadline


def validate_osasco_substitution_references(
    original_id: str, replacement_id: str,
) -> None:
    """Manual: type S must have a distinct reviewed replacement before cancel."""
    if (
        not isinstance(original_id, str)
        or not isinstance(replacement_id, str)
        or not original_id.strip()
        or not replacement_id.strip()
        or original_id == replacement_id
        or len(original_id) > 256
        or len(replacement_id) > 256
    ):
        raise FiscalValidationError("Osasco substitution needs two distinct fiscal records")
