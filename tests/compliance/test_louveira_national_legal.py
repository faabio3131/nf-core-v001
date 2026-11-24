"""Louveira Lei 3.023/2025 art. 2 §5 — exact local cancellation dates."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from kordena_fiscal.compliance.louveira_national_legal import (
    LOUVEIRA_IBGE,
    enforce_louveira_national_cancellation_window,
)
from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError

_SP = ZoneInfo("America/Sao_Paulo")
_LOUVEIRA = BrazilianJurisdiction("SP", LOUVEIRA_IBGE)


@pytest.mark.parametrize(
    ("emitted", "requested", "allowed"),
    [
        ("2026-11-01T10:00:00-03:00", "2026-11-01T10:00:00-03:00", True),
        ("2026-11-30T23:59:59-03:00", "2026-12-15T23:59:59-03:00", True),
        ("2026-11-30T23:59:59-03:00", "2026-12-16T00:00:00-03:00", False),
        ("2026-12-31T09:00:00-03:00", "2027-01-15T23:59:59-03:00", True),
        ("2026-12-31T09:00:00-03:00", "2027-01-16T00:00:00-03:00", False),
        ("2026-01-31T20:00:00-03:00", "2026-02-15T11:00:00-03:00", True),
        ("2026-01-31T20:00:00-03:00", "2026-02-16T11:00:00-03:00", False),
        ("2026-02-01T00:00:00-03:00", "2026-01-31T23:59:59-03:00", False),
    ],
)
def test_louveira_cancel_cutoff_official_local_calendar(
    emitted: str, requested: str, allowed: bool,
) -> None:
    original = datetime.fromisoformat(emitted)
    attempt = datetime.fromisoformat(requested)
    if allowed:
        enforce_louveira_national_cancellation_window(
            issuer_jurisdiction=_LOUVEIRA,
            original_issued_at=original, requested_at=attempt,
        )
    else:
        with pytest.raises(FiscalValidationError, match="statutory period"):
            enforce_louveira_national_cancellation_window(
                issuer_jurisdiction=_LOUVEIRA,
                original_issued_at=original, requested_at=attempt,
            )


def test_louveira_uses_brazilian_local_day_not_utc_midnight() -> None:
    # December 16 00:20 UTC is still December 15 in Louveira.
    enforce_louveira_national_cancellation_window(
        issuer_jurisdiction=_LOUVEIRA,
        original_issued_at=datetime(2026, 11, 15, 14, tzinfo=UTC),
        requested_at=datetime(2026, 12, 16, 0, 20, tzinfo=UTC),
    )


@pytest.mark.parametrize("value", [
    datetime(2026, 11, 12),
    datetime(2026, 11, 12, tzinfo=None),
])
def test_louveira_refuses_naive_timestamp(value: datetime) -> None:
    with pytest.raises(FiscalValidationError, match="timezone-aware"):
        enforce_louveira_national_cancellation_window(
            issuer_jurisdiction=_LOUVEIRA,
            original_issued_at=value,
            requested_at=datetime.now(_SP),
        )


def test_louveira_refuses_naive_request_instant() -> None:
    with pytest.raises(FiscalValidationError, match="timezone-aware"):
        enforce_louveira_national_cancellation_window(
            issuer_jurisdiction=_LOUVEIRA,
            original_issued_at=datetime.now(_SP),
            requested_at=datetime(2026, 12, 15),
        )


def test_louveira_rule_does_not_spill_into_salto_or_other_uf() -> None:
    for jurisdiction in (
        BrazilianJurisdiction("SP", "3545209"),
        BrazilianJurisdiction("MG", "3106200"),
    ):
        enforce_louveira_national_cancellation_window(
            issuer_jurisdiction=jurisdiction,
            original_issued_at=datetime(2023, 11, 10, tzinfo=UTC),
            requested_at=datetime(2026, 11, 15, tzinfo=UTC),
        )
