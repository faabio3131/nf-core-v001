"""Louveira/SP: statutory NFS-e cancellation deadline, Lei 3.023/2025.

This is a jurisdictional check over the existing national gateway, not another
provider, tax rule engine, issuer registry or transport. The original issue
timestamp MUST come from cryptographically verified official NFS-e XML dhProc,
not from the DPS preparation date or an untrusted request.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError

LOUVEIRA_IBGE = "3527306"
_LAW_SOURCE = "Lei Municipal Louveira 3.023/2025, art. 2, par. 5"
_LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def enforce_louveira_national_cancellation_window(
    *,
    issuer_jurisdiction: BrazilianJurisdiction,
    original_issued_at: datetime,
    requested_at: datetime,
) -> None:
    """Allow through the 15th of the NEXT local month; never extend by DPS date.

    Other municipalities are not subject to this policy. This does not claim to
    implement Louveira's separate municipal channel for registered individuals.
    """
    if not isinstance(issuer_jurisdiction, BrazilianJurisdiction):
        raise FiscalValidationError("Issuer jurisdiction is required")
    if (
        issuer_jurisdiction.state_code != "SP"
        or issuer_jurisdiction.municipality_ibge_code != LOUVEIRA_IBGE
    ):
        return
    if (
        not isinstance(original_issued_at, datetime)
        or original_issued_at.tzinfo is None
        or original_issued_at.utcoffset() is None
        or not isinstance(requested_at, datetime)
        or requested_at.tzinfo is None
        or requested_at.utcoffset() is None
    ):
        raise FiscalValidationError(
            "Louveira requires authenticated, timezone-aware official emission time"
        )
    emitted = original_issued_at.astimezone(_LOCAL_TZ).date()
    request_day = requested_at.astimezone(_LOCAL_TZ).date()
    if emitted.month == 12:
        deadline = date(emitted.year + 1, 1, 15)
    else:
        deadline = date(emitted.year, emitted.month + 1, 15)
    if not emitted <= request_day <= deadline:
        raise FiscalValidationError(
            "Louveira national cancellation outside statutory period: " + _LAW_SOURCE
        )
