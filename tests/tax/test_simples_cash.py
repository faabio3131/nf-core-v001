from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.simples_cash import reconcile_cash, verify_cash_continuity


def register(event="none", prior_taxed=200, received=300):
    compulsory = 1000 - prior_taxed - max(0, received - (prior_taxed - 200))
    compulsory = compulsory if event != "none" else 0
    return {
        "review_reference": "review", "closing_event": event, "event_reference": "decision",
        "installments": [{
            "installment_id": "a", "issued_on": "2025-11-01", "due_on": "2026-11-30",
            "principal_cents": 1000, "prior_received_cents": 200,
            "prior_taxed_cents": prior_taxed, "received_cents": received,
            "activity": "commerce", "market": "domestic", "federal": "ordinary",
            "local": "ordinary", "evidence_reference": "doc", "treatment_reference": "review",
        }],
        "control_totals": {
            "opening": 800, "accrued": 0, "received": received, "closing": 800 - received,
            "previously_taxed_received": min(received, prior_taxed - 200),
            "compulsory": compulsory,
            "taxable": max(0, received - (prior_taxed - 200)) + compulsory,
        },
    }


@pytest.mark.parametrize("event", ["closure", "return_to_accrual", "exclusion"])
def test_closing_recognizes_remaining(event):
    lines, totals = reconcile_cash(date(2026, 11, 1), register(event))
    assert lines[0].cents == 800
    assert totals["compulsory"] == 500


def test_partial_receipt_and_previously_taxed():
    lines, totals = reconcile_cash(date(2026, 11, 1), register(prior_taxed=400))
    assert lines[0].cents == 100
    assert totals["previously_taxed_received"] == 200


def test_transition_requires_closure_and_future_is_refused():
    with pytest.raises(FiscalValidationError, match="transition"):
        reconcile_cash(date(2026, 12, 1), register())
    with pytest.raises(FiscalValidationError, match="2026"):
        reconcile_cash(date(2027, 1, 1), register())


def test_control_mismatch_refused():
    data = register()
    data["control_totals"]["closing"] = 1
    with pytest.raises(FiscalValidationError, match="reconcile"):
        reconcile_cash(date(2026, 11, 1), data)


def test_monthly_continuity_rejects_missing_or_rewritten_installment():
    previous = register()
    current = register(prior_taxed=500, received=100)
    row = current["installments"][0]
    row["prior_received_cents"] = 500
    current["control_totals"].update(
        opening=500, closing=400, taxable=100, previously_taxed_received=0,
    )
    verify_cash_continuity(date(2026, 11, 1), current, previous)
    current["installments"] = []
    with pytest.raises(FiscalValidationError, match="missing"):
        verify_cash_continuity(date(2026, 11, 1), current, previous)
    current["installments"] = [row]
    row["principal_cents"] = 2000
    with pytest.raises(FiscalValidationError, match="changed"):
        verify_cash_continuity(date(2026, 11, 1), current, previous)
