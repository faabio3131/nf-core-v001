"""T19 fixed-basis SELIC residual policy; no external services."""

from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount, subtract
from kordena_fiscal.tax.selic_residual import require_selic_reservation, selic_reconciliation
from kordena_fiscal.tax.tax_recovery import federal_interest, federal_interest_from_memory

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
    source = federal_interest(original.principal_cents, PAYMENT, VALUATION)
    assert source is not None
    result = selic_reconciliation(remaining, original, PAYMENT, VALUATION, source[1])
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
    original = _amount(8)
    source = federal_interest(8, PAYMENT, VALUATION)
    assert source is not None
    result = selic_reconciliation(available, original, PAYMENT, VALUATION, source[1])
    assert result["status"] == "stranded_residual"
    assert result["signed_residual_cents"] == 1
    with pytest.raises(FiscalValidationError, match="requires principal"):
        require_selic_reservation(available, available)


def test_missing_basis_not_replaced_with_zero():
    original = _amount(100)
    result = selic_reconciliation(original, original, PAYMENT, VALUATION, None)
    assert result["status"] == "basis_unavailable"
    assert result["expected_selic_cents"] is None
    assert result["signed_residual_cents"] is None


def test_equal_cent_and_same_month_no_extra_interest():
    available = Amount(principal_cents=1, selic_cents=0)
    require_selic_reservation(available, available)
    assert selic_reconciliation(available, available, PAYMENT, PAYMENT, [])["status"] == (
        "balanced"
    )


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


def test_historical_diagnostic_is_independent_of_revised_rate_table(monkeypatch):
    original = _amount(334)
    remaining = subtract(original, _amount(1))
    source = federal_interest(334, PAYMENT, VALUATION)
    assert source is not None
    before = selic_reconciliation(remaining, original, PAYMENT, VALUATION, source[1])
    monkeypatch.setattr("kordena_fiscal.tax.tax_recovery.monthly_selic", lambda: {})
    assert federal_interest(334, PAYMENT, VALUATION) is None
    assert selic_reconciliation(remaining, original, PAYMENT, VALUATION, source[1]) == before
    assert before["signed_residual_cents"] == 1


@pytest.mark.parametrize("damage", ["missing", "duplicate", "boolean", "final", "reordered"])
def test_invalid_historical_memory_is_explicitly_unavailable(damage):
    original = _amount(334)
    source = federal_interest(334, PAYMENT, VALUATION)
    assert source is not None
    memory = [dict(row) for row in source[1]]
    if damage == "missing":
        memory.pop(0)
    elif damage == "duplicate":
        memory.insert(1, dict(memory[0]))
    elif damage == "boolean":
        memory[0]["basis_points"] = True
    elif damage == "final":
        memory[-1]["basis_points"] = 99
    else:
        memory[0], memory[1] = memory[1], memory[0]
    assert federal_interest_from_memory(334, PAYMENT, VALUATION, memory) is None
    result = selic_reconciliation(original, original, PAYMENT, VALUATION, memory)
    assert result["status"] == "basis_unavailable"
    assert result["signed_residual_cents"] is None


def test_valid_shape_with_mismatched_original_value_is_not_a_basis():
    source = federal_interest(334, PAYMENT, VALUATION)
    assert source is not None
    original = Amount(principal_cents=334, selic_cents=source[0] + 1)
    result = selic_reconciliation(original, original, PAYMENT, VALUATION, source[1])
    assert result["status"] == "basis_unavailable"
    assert result["expected_selic_cents"] is None


def test_three_partitions_preserve_components_and_block_incompatible_final_reserve():
    for principal in range(3, 41):
        original = _amount(principal)
        for a in range(1, principal - 1):
            for b in range(1, principal - a):
                available = original
                accepted_principal = accepted_selic = 0
                for part in (a, b, principal - a - b):
                    requested = _amount(part)
                    try:
                        require_selic_reservation(available, requested)
                    except FiscalValidationError:
                        break
                    available = subtract(available, requested)
                    accepted_principal += requested.principal_cents
                    accepted_selic += requested.selic_cents
                assert available.principal_cents + accepted_principal == principal
                assert available.selic_cents + accepted_selic == original.selic_cents
                if available.principal_cents == 0:
                    assert available.selic_cents == 0
