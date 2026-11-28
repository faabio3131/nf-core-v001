"""Conservative sandbox SELIC residual diagnostics; T17 remains authoritative."""

from __future__ import annotations

from datetime import date

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount
from kordena_fiscal.tax.tax_recovery import federal_interest_from_memory


def require_selic_reservation(available: Amount, requested: Amount) -> None:
    """Reject new reservations that overspend or strand SELIC without principal.

    Called after validating the exact individual T17 valuation, under the T19
    lock, before any append. Do not apply prospectively new rules to replay or
    unwinding of historical movements. No automatic cent redistribution.
    """
    if requested.principal_cents <= 0:
        raise FiscalValidationError("SELIC reservation requires principal")
    if requested.principal_cents > available.principal_cents:
        raise FiscalValidationError("negative ledger component: principal")
    if requested.selic_cents > available.selic_cents:
        raise FiscalValidationError("negative ledger component: SELIC reserve exceeds balance")
    if (
        requested.principal_cents == available.principal_cents
        and requested.selic_cents != available.selic_cents
    ):
        residual = available.selic_cents - requested.selic_cents
        raise FiscalValidationError(
            "SELIC residual requires revised partition before principal exhaustion: "
            f"{residual} cents"
        )


def selic_reconciliation(
    available: Amount, original: Amount, payment: date, valuation: date, rate_memory: object,
) -> dict[str, int | str | None]:
    """Describe the available component against the original, fixed T17 basis.

    A difference is diagnostic, not an extra credit or proof of its cause.
    Standalone T18 movements may also explain differences. Missing basis is
    explicit; no current-month revaluation or fabricated rate is attempted.
    """
    original_interest = federal_interest_from_memory(
        original.principal_cents, payment, valuation, rate_memory,
    )
    expected = (
        federal_interest_from_memory(available.principal_cents, payment, valuation, rate_memory)
        if original_interest == original.selic_cents
        else None
    )
    difference = available.selic_cents - expected if expected is not None else None
    if available.principal_cents == 0 and available.selic_cents > 0:
        status = "stranded_residual"
    elif difference is None:
        status = "basis_unavailable"
    elif difference:
        status = "valuation_difference"
    else:
        status = "balanced"
    return {
        "available_principal_cents": available.principal_cents,
        "available_selic_cents": available.selic_cents,
        "expected_selic_cents": expected,
        "signed_residual_cents": difference,
        "status": status,
    }
