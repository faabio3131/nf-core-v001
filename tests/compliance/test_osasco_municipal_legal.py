"""Osasco official automatic cancellation and substitution rules (Apr/2026)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kordena_fiscal.compliance.osasco_municipal_legal import (
    validate_osasco_automatic_cancellation,
    validate_osasco_substitution_references,
)
from kordena_fiscal.domain import FiscalValidationError


@pytest.mark.parametrize(("issued", "reviewed", "deadline"), [
    (
        datetime(2026, 11, 13, 12, tzinfo=UTC),
        datetime(2026, 12, 10, 21, tzinfo=UTC),
        "2026-12-10",
    ),
    (
        datetime(2026, 12, 31, 22, tzinfo=UTC),
        datetime(2027, 1, 10, 12, tzinfo=UTC),
        "2027-01-10",
    ),
])
def test_osasco_cancellation_until_day_ten_is_supported(
    issued: datetime, reviewed: datetime, deadline: str,
) -> None:
    assert validate_osasco_automatic_cancellation(
        issued_at=issued, reviewed_at=reviewed,
    ).isoformat() == deadline


def test_osasco_cancellation_after_day_ten_requires_administrative_channel() -> None:
    with pytest.raises(FiscalValidationError, match="administrative"):
        validate_osasco_automatic_cancellation(
            issued_at=datetime(2026, 11, 13, tzinfo=UTC),
            reviewed_at=datetime(2026, 12, 11, 12, tzinfo=UTC),
        )


def test_osasco_cancellation_dates_must_be_aware() -> None:
    with pytest.raises(FiscalValidationError, match="timezone"):
        validate_osasco_automatic_cancellation(
            issued_at=datetime(2026, 11, 13),
            reviewed_at=datetime(2026, 11, 14, tzinfo=UTC),
        )


def test_osasco_type_s_requires_two_distinct_document_identities() -> None:
    validate_osasco_substitution_references("original", "replacement")
    for old, new in (("same", "same"), ("", "candidate"), ("old", "")):
        with pytest.raises(FiscalValidationError, match="two distinct"):
            validate_osasco_substitution_references(old, new)
