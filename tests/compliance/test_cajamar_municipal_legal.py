"""Cajamar law: municipal direct cancellation and human substitution limits."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from kordena_fiscal.compliance.cajamar_municipal_legal import (
    CANCELLATION_MOTIVES,
    cajamar_regular_deadline,
    validate_cajamar_automatic_cancellation,
)
from kordena_fiscal.domain import FiscalValidationError


@pytest.mark.parametrize("competence,deadline", [
    (date(2026, 10, 31), date(2026, 11, 10)),
    (date(2026, 11, 1), date(2026, 12, 10)),
    (date(2026, 12, 31), date(2027, 1, 10)),
])
def test_cajamar_deadline_is_next_month_tenth(
    competence: date, deadline: date,
) -> None:
    assert cajamar_regular_deadline(competence) == deadline


@pytest.mark.parametrize("reason", sorted(CANCELLATION_MOTIVES))
def test_cajamar_permits_only_decree_cancel_motives(reason: str) -> None:
    assert validate_cajamar_automatic_cancellation(
        competence=date(2026, 10, 31), reason=reason,
        reviewed_at=datetime(2026, 11, 10, 18, tzinfo=UTC),
    ) == date(2026, 11, 10)


@pytest.mark.parametrize("reason", [
    "customer_no_payment", "change_bank_account", "other", "", "5",
])
def test_cajamar_rejects_unauthorized_cancel_reason(reason: str) -> None:
    with pytest.raises(FiscalValidationError, match="legal motive"):
        validate_cajamar_automatic_cancellation(
            competence=date(2026, 10, 31), reason=reason,
            reviewed_at=datetime(2026, 11, 5, tzinfo=UTC),
        )


def test_cajamar_cancel_after_deadline_requires_separate_municipal_process() -> None:
    with pytest.raises(FiscalValidationError, match="administrative process"):
        validate_cajamar_automatic_cancellation(
            competence=date(2026, 10, 31), reason="incorrect_taker",
            reviewed_at=datetime(2026, 11, 11, 3, tzinfo=UTC),
        )
    with pytest.raises(FiscalValidationError, match="administrative process"):
        validate_cajamar_automatic_cancellation(
            competence=date(2026, 10, 31), reason="incorrect_amount",
            reviewed_at=datetime(2027, 3, 1, tzinfo=UTC),
        )


def test_cajamar_uses_local_timezone_at_deadline_midnight() -> None:
    valid = datetime(2026, 11, 11, 2, 59, tzinfo=UTC)
    invalid = valid + timedelta(minutes=1)
    assert validate_cajamar_automatic_cancellation(
        competence=date(2026, 10, 1), reason="duplicate_invoice",
        reviewed_at=valid,
    ) == date(2026, 11, 10)
    with pytest.raises(FiscalValidationError, match="administrative process"):
        validate_cajamar_automatic_cancellation(
            competence=date(2026, 10, 1), reason="duplicate_invoice",
            reviewed_at=invalid,
        )
