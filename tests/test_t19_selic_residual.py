"""T19 fixed-basis SELIC residual policy; no external services."""

from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount, subtract
from kordena_fiscal.tax.selic_residual import require_selic_reservation, selic_reconciliation
from kordena_fiscal.tax.tax_recovery import federal_interest

PAYMENT = date(2026, 1, 20)
VALUATION = date(2026, 11, 24)


def _amount(principal: int) -> Amount:
    projected = federal_interest(principal, PAYMENT, VALUATION)
    assert projected is not None
    return Amount(principal_cents=principal, selic_cents=projected[0])


@pytest.mark.parametrize(
    "principal,part,expected_difference",
    [(334, 1, 1), (10, 5, -1), (334, 100, 0)],
)
def test_partitions_preserve_components_or_fail_closed(principal, part, expected_difference):
    original = _amount(principal)
    first = _amount(part)
    last = _amount(principal - part)
    require_selic_reservation(original, first)
    remaining = subtract(original, first)
    result = selic_reconciliation(remaining, PAYMENT, VALUATION)
    assert result["signed_residual_cents"] == expected_difference
    assert result["status"] == ("balanced" if expected_difference == 0 else "valuation_difference")
    if expected_difference:
        message = (
            "SELIC residual" if expected_difference > 0 else "negative ledger component: SELIC"
        )
        with pytest.raises(FiscalValidationError, match=message):
            require_selic_reservation(remaining, last)
        assert remaining.principal_cents + first.principal_cents == original.principal_cents
        assert remaining.selic_cents + first.selic_cents == original.selic_cents
    else:
        require_selic_reservation(remaining, last)
        assert subtract(remaining, last) == Amount(principal_cents=0, selic_cents=0)


def test_stranded_legacy_residue_visible_but_not_spendable():
    available = Amount(principal_cents=0, selic_cents=1)
    result = selic_reconciliation(available, PAYMENT, VALUATION)
    assert result["status"] == "stranded_residual"
    assert result["signed_residual_cents"] == 1
    with pytest.raises(FiscalValidationError, match="requires principal"):
        require_selic_reservation(available, available)


def test_missing_basis_not_replaced_with_zero():
    result = selic_reconciliation(_amount(100), PAYMENT, date(2027, 1, 1))
    assert result["status"] == "basis_unavailable"
    assert result["expected_selic_cents"] is None
    assert result["signed_residual_cents"] is None


def test_equal_cent_and_same_month_no_extra_interest():
    available = Amount(principal_cents=1, selic_cents=0)
    require_selic_reservation(available, available)
    assert selic_reconciliation(available, PAYMENT, PAYMENT)["status"] == "balanced"


def test_many_partitions_never_silently_consume_or_invent_interest():
    # Enumerate bounded, deterministic two-part splits using the actual T17
    # authority. Each final reservation either closes both components or fails.
    for principal in range(2, 201):
        original = _amount(principal)
        for part in range(1, principal):
            first = _amount(part)
            last = _amount(principal - part)
            require_selic_reservation(original, first)
            remaining = subtract(original, first)
            if last.selic_cents == remaining.selic_cents:
                require_selic_reservation(remaining, last)
                assert subtract(remaining, last) == Amount(principal_cents=0, selic_cents=0)
            else:
                with pytest.raises(FiscalValidationError):
                    require_selic_reservation(remaining, last)
                assert remaining.selic_cents + first.selic_cents == original.selic_cents
                assert remaining.principal_cents + first.principal_cents == (
                    original.principal_cents
                )


def test_new_reserve_requires_positive_principal_and_independent_component_bounds():
    available = _amount(10)
    for requested in (
        Amount(principal_cents=0, selic_cents=1),
        Amount(principal_cents=11, selic_cents=0),
        Amount(principal_cents=1, selic_cents=2),
    ):
        with pytest.raises(FiscalValidationError):
            require_selic_reservation(available, requested)
