# ruff: noqa: F811 -- imported pytest fixtures are requested by name.
"""T17 deterministic rates, ordinary clocks and scoped PostgreSQL recovery."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _context, _setup, _xml, fixture
from test_t16_unused_credits import BUYER, batch, bind_book, evidence

from kordena_fiscal.application.historical_audit import TABLE, import_month
from kordena_fiscal.application.tax_recovery import import_recovery
from kordena_fiscal.application.unused_credits import import_credits
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.tax.historical_audit import Month
from kordena_fiscal.tax.tax_recovery import (
    RecoveryBatch,
    estimate,
    federal_interest,
    invoice_dates,
    monthly_selic,
    ordinary_deadline,
    selic_reference,
)
from kordena_fiscal.tax.unused_credits import Batch, detect

# Closed-month rates independently reconstructed from the official Sicalc
# 01/11/2026 report, pages 3-4. October 2026 monthly = 107, not terminal 100.
EXPECTED_RATES = (
    59, 77, 73, 76, 93, 83, 103, 102, 103, 117, 107, 102, 102, 112,
    112, 92, 117, 92, 112, 107, 107, 114, 97, 100, 92, 89, 97, 80,
    83, 89, 83, 79, 91, 87, 84, 93, 79, 93, 101, 99, 96, 106,
    114, 110, 128, 116, 122, 128, 105, 122, 116, 100, 121, 109, 107, 112,
    122, 109, 108, 107,
)


def test_official_closed_months_and_reference():
    rates = monthly_selic()
    assert list(rates.values()) == list(EXPECTED_RATES)
    assert len(rates) == 60
    assert sum(rates.values()) == 6036
    assert rates["2026-10-01"] == 107
    assert "2026-11-01" not in rates
    ref = selic_reference()
    assert ref["first_month"] == "2021-11-01"
    assert ref["last_month"] == "2026-10-01"
    assert ref["last_valuation_month"] == "2026-11-01"
    assert len(ref["normalized_sha256"]) == 64


@pytest.mark.parametrize(
    "principal,payment,valuation,expected",
    [
        (10000, date(2021, 10, 15), TODAY, 6136),
        (10000, date(2026, 1, 20), TODAY, 1095),
        (10000, date(2026, 9, 30), TODAY, 207),
        (10000, date(2026, 10, 15), TODAY, 100),
        (10000, date(2026, 11, 1), TODAY, 0),
        (50, date(2026, 10, 1), TODAY, 1),
        (49, date(2026, 10, 1), TODAY, 0),
        (10**12, date(2026, 1, 20), TODAY, 109500000000),
    ],
)
def test_interest_exact_cents(principal, payment, valuation, expected):
    value, memory = federal_interest(principal, payment, valuation)
    assert value == expected
    if memory:
        assert memory[-1]["kind"] == "final_month"
        assert memory[-1]["basis_points"] == 100
        assert all(row["kind"] == "selic" for row in memory[:-1])


def test_missing_rate_reversed_dates_and_no_forecast():
    assert federal_interest(100, date(2021, 9, 1), TODAY) is None
    assert federal_interest(100, TODAY, date(2026, 12, 1)) is None
    with pytest.raises(FiscalValidationError):
        federal_interest(-1, date(2026, 1, 1), TODAY)
    with pytest.raises(FiscalValidationError):
        federal_interest(100, TODAY, date(2026, 1, 1))


def test_deadlines_calendar():
    assert ordinary_deadline(date(2021, 11, 24)) == TODAY
    assert ordinary_deadline(date(2020, 2, 29)) is None
    assert ordinary_deadline(date(2021, 11, 28)) is None  # weekend anniversary


def _t16(tax="icms", period=MONTH, as_of=TODAY, context=None):
    context = context or _context()
    data = batch(tax=tax, period=period, as_of=as_of)
    data["rules"][0]["cnae"] = context.cnae
    bind_book(data)
    facts = Batch.model_validate(data)
    rows = detect(facts, BUYER, context, as_of)["findings"]
    return facts, rows


def _review(facts, row, digest, as_of=TODAY, **updates):
    rule = facts.rules[0]
    claim = {
        "issuer_cnpj": BUYER.value,
        "competence": facts.competence,
        "t16_digest": digest,
        "finding_id": row["identity"],
        "tax": row["tax"],
        "modality": "icms_bookkeeping",
        "checked_through": as_of.isoformat(),
        "principal_cents": row["candidate_cents"],
        "anchor": facts.competence[:8] + "15",
        "ordinary_deadline": str(int(facts.competence[:4]) + 5) + facts.competence[4:8] + "15",
        "ordinary_clock_confirmed": True,
        "no_prior_use_or_claim": True,
        "causal_basis_confirmed": True,
        "receipt_id": None,
        "federal_correction": None,
        "citation": rule.citation.model_dump(),
    }
    # Fixture sources are explicitly synthetic. Legal validity spans the test clock.
    claim["citation"]["valid_until"] = None
    claim.update(updates)
    correction_source = None
    if claim["federal_correction"] is not None:
        correction = claim["federal_correction"].copy()
        corrected = correction | {
            "issuer_cnpj": claim["issuer_cnpj"],
            "competence": claim["competence"],
            "tax": claim["tax"],
            "receipt_id": claim["receipt_id"],
            "t16_digest": claim["t16_digest"],
        }
        correction_source = evidence(json.dumps(corrected, sort_keys=True).encode())
        claim["federal_correction"] = correction | {
            "corrected_assessment_sha256": correction_source["sha256"]
        }
    return {
        "claim": claim,
        "review": evidence(json.dumps(claim, sort_keys=True).encode()),
        "legal_source": rule.legal_source.model_dump(),
        "corrected_assessment": correction_source,
    }


def _bundle(facts, reviewed, digest="a" * 64, t16_version=1):
    return RecoveryBatch.model_validate(
        {
            "competence": facts.competence,
            "t16_version": t16_version,
            "t16_digest": digest,
            "claims": reviewed,
        }
    )


def _estimate(facts, rows, reviewed, as_of=TODAY, payments=None):
    return estimate(
        _bundle(facts, reviewed),
        BUYER,
        _context(),
        as_of,
        rows,
        invoice_dates(facts),
        payments or {},
    )


def test_icms_no_interest_and_missing_review():
    facts, rows = _t16()
    assert _estimate(facts, rows, [])[0]["estimated_cents"] is None
    reviewed = _review(facts, rows[0], "a" * 64)
    row = _estimate(facts, rows, [reviewed])[0]
    assert row["status"] == "potential"
    assert row["principal_cents"] == 334
    assert row["adjustment_cents"] == 0
    assert row["estimated_cents"] == 334
    assert row["credit_recognized"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"checked_through": "2026-11-23"},
        {"ordinary_clock_confirmed": False},
        {"no_prior_use_or_claim": False},
        {"causal_basis_confirmed": False},
        {"ordinary_deadline": "2032-01-15"},
        {"anchor": "2026-01-16"},
        {"modality": "federal_undue_payment"},
    ],
)
def test_insufficient_basis_never_has_amount(change):
    facts, rows = _t16()
    claim = _review(facts, rows[0], "a" * 64, **change)
    row = _estimate(facts, rows, [claim])[0]
    assert row["status"] == "insufficient_basis"
    assert row["estimated_cents"] is None


@pytest.mark.parametrize("days,expected", [(0, "potential"), (1, "expired")])
def test_icms_expiration_boundary(days, expected):
    # 15 Oct 2026 is a business-day anniversary of the synthetic XML.
    period = date(2021, 10, 1)
    as_of = date(2026, 10, 15 + days)
    facts, rows = _t16(period=period, as_of=as_of)
    claim = _review(facts, rows[0], "a" * 64, as_of=as_of)
    row = _estimate(facts, rows, [claim], as_of=as_of)[0]
    assert row["status"] == expected
    assert row["estimated_cents"] == (334 if days == 0 else None)


def test_tampered_projection_duplicate_and_excess_balance():
    facts, rows = _t16()
    good = _review(facts, rows[0], "a" * 64)
    changed = copy.deepcopy(good)
    changed["claim"]["principal_cents"] = 1
    with pytest.raises(FiscalValidationError, match="projection"):
        _estimate(facts, rows, [changed])
    with pytest.raises(FiscalValidationError, match="identity"):
        _estimate(facts, rows, [good, good])
    excess = _review(facts, rows[0], "a" * 64, principal_cents=335)
    with pytest.raises(FiscalValidationError, match="balance"):
        _estimate(facts, rows, [excess])


def test_federal_reconciled_payment_and_corrected_assessment():
    facts, rows = _t16(tax="pis")
    correction = {
        "historical_digest": "b" * 64,
        "payment_sha256": "c" * 64,
        "assessment_reference": "assessment",
        "corrected_assessment_reference": "rectified",
        "originally_due_cents": 1000,
        "corrected_due_cents": 666,
    }
    claim = _review(
        facts, rows[0], "a" * 64,
        modality="federal_undue_payment",
        receipt_id="receipt",
        anchor="2026-01-20",
        ordinary_deadline="2031-01-20",
        federal_correction=correction,
    )
    payments = {
        ("receipt", "pis"): {
            "receipt_id": "receipt", "paid_on": "2026-01-20", "allocated_cents": 1000,
            "historical_digest": "b" * 64, "sha256": "c" * 64,
            "assessment_reference": "assessment",
        }
    }
    row = _estimate(facts, rows, [claim], payments=payments)[0]
    assert row["status"] == "potential"
    assert row["adjustment_cents"] == 37
    assert row["estimated_cents"] == 371
    assert _estimate(facts, rows, [claim])[0]["estimated_cents"] is None
    mismatched = _review(
        facts, rows[0], "a" * 64,
        modality="federal_undue_payment",
        receipt_id="receipt",
        anchor="2026-01-20",
        ordinary_deadline="2031-01-20",
        federal_correction=correction | {"corrected_due_cents": 665},
    )
    assert _estimate(facts, rows, [mismatched], payments=payments)[0]["estimated_cents"] is None


def test_postgres_scope_replay_revision_and_rollback(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    facts, rows = _t16(context=context)
    with db.economy(scope) as store:
        prior = import_credits(
            store, BUYER, MONTH, 1, facts, context=context, as_of=TODAY
        )
    digest = prior["snapshot_digest"]
    reviewed = _review(facts, rows[0], digest)
    payload = _bundle(facts, [reviewed], digest)
    key = f"tax-recovery-{BUYER.value}-{MONTH.isoformat()}"

    def write(store, version, bundle=payload):
        return import_recovery(
            store, BUYER, MONTH, version, bundle, context=context, as_of=TODAY
        )

    with db.economy(scope) as store:
        first = write(store, 1)
    with db.economy(scope) as store:
        assert write(store, 1) == {
            "version": 1, "snapshot_digest": first["snapshot_digest"], "replay": True,
        }
        index = store.record(TABLE, key)
        assert index["content"]["partial_totals_cents"] == {
            "icms": {"principal_cents": 334, "adjustment_cents": 0, "estimated_cents": 334}
        }
        ref = index["content"]["page_refs"][0]
        page = store.record(TABLE, ref["record_id"], 1)
        assert page["digest"] == ref["digest"]
        assert page["content"]["findings"][0]["credit_recognized"] is False
    for other in (
        replace(scope, unit_id="other-unit"),
        replace(scope, tenant_id="other-tenant"),
        replace(scope, host_namespace="other-host"),
        replace(scope, environment=FiscalEnvironment.PRODUCTION),
    ):
        with db.economy(other) as store:
            assert store.record(TABLE, key) is None
            with pytest.raises(FiscalValidationError):
                write(store, 1)
    with pytest.raises(FiscalValidationError, match="conflict"), db.economy(scope) as store:
        write(store, 1, _bundle(facts, [], digest))
    with pytest.raises(RuntimeError), db.economy(scope) as store:
        write(store, 2)
        raise RuntimeError("induced rollback")
    with db.economy(scope) as store:
        assert store.record(TABLE, key)["version"] == 1
        assert store.record(TABLE, key + "-source-0", 2) is None
        import_credits(store, BUYER, MONTH, 2, facts, context=context, as_of=TODAY)
    with pytest.raises(FiscalValidationError, match="current scoped T16"):
        with db.economy(scope) as store:
            write(store, 2)


def test_cli_recovery(economy_database, mapping, tmp_path):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    facts, rows = _t16(context=context, as_of=today)
    with db.economy(scope) as store:
        prior = import_credits(store, BUYER, MONTH, 1, facts, context=context, as_of=today)
    digest = prior["snapshot_digest"]
    reviewed = _review(facts, rows[0], digest, as_of=today)
    bundle = _bundle(facts, [reviewed], digest)
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps({
        "tenant": scope.tenant_id, "unit": scope.unit_id, "issuer_cnpj": BUYER.value,
        "version": 1, "facts": bundle.model_dump(),
    }))
    cli = Path(__file__).parents[1] / "scripts/nfcore_historical_audit_import.py"
    args = [
        sys.executable, str(cli), str(path), "--tenant", scope.tenant_id,
        "--unit", scope.unit_id, "--recovery",
    ]
    env = os.environ | {"NFCORE_ENVIRONMENT": "test", "DATABASE_URL": db._dsn}
    result = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["status_counts"] == {"potential": 1}
    result = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["replay"] is True
    result = subprocess.run(
        args, env=env | {"NFCORE_ENVIRONMENT": "production"}, capture_output=True, text=True
    )
    assert result.returncode == 2 and not result.stdout


def test_postgres_federal_receipt_and_no_t15_overlap(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    historical = fixture()
    original = _xml(MONTH, 1, issuer=BUYER)
    historical["documents"][0]["xml_b64"] = evidence(original)["data_b64"]
    historical["documents"][0]["xml_sha256"] = evidence(original)["sha256"]
    historical["catalog"][0]["federal"] = "ordinary"
    for item in historical["documents"][0]["items"]:
        for allocation in item["allocations"]:
            for field in (
                "reviewed_base_cents", "base_review_reference", "base_mode", "reviewed_rate",
            ):
                allocation[field] = None
            if item["number"] == 2 and allocation["tax"] == "icms":
                allocation["declared_cents"] = 0
    historical["controls"][2]["declared_principal_cents"] = 3600
    payment = historical["payments"][0]
    payment["issuer_cnpj"] = BUYER.value
    payment["allocations"]["icms"] = 3600
    payment["principal_cents"] = sum(payment["allocations"].values()) + 100
    history_facts = Month.model_validate(historical)
    credits, rows = _t16(tax="pis", context=context)
    with db.economy(scope) as store:
        history = import_month(
            store, BUYER, MONTH, 1, history_facts, context=context, as_of=TODAY
        )
        t16 = import_credits(
            store, BUYER, MONTH, 1, credits, context=context, as_of=TODAY
        )
    digest = t16["snapshot_digest"]
    correction = {
        "historical_digest": history["snapshot_digest"],
        "payment_sha256": historical["artifacts"][3]["sha256"],
        "assessment_reference": "assessment",
        "corrected_assessment_reference": "rectified",
        "originally_due_cents": 365,
        "corrected_due_cents": 31,
    }
    review = _review(
        credits, rows[0], digest, modality="federal_undue_payment",
        receipt_id=payment["receipt_id"], anchor=payment["paid_on"],
        ordinary_deadline="2031-01-20", federal_correction=correction,
    )
    payload = _bundle(credits, [review], digest)
    with db.economy(scope) as store:
        receipt = import_recovery(
            store, BUYER, MONTH, 1, payload, context=context, as_of=TODAY
        )
        assert receipt["status_counts"] == {"potential": 1}
        key = f"tax-recovery-{BUYER.value}-{MONTH.isoformat()}"
        index = store.record(TABLE, key)
        assert index["content"]["partial_totals_cents"]["pis"] == {
            "principal_cents": 334, "adjustment_cents": 37, "estimated_cents": 371,
        }
        assert index["content"]["realized_cents"] is None
    forged = copy.deepcopy(review)
    forged["corrected_assessment"] = evidence(b'{"wrong":"scope"}')
    with pytest.raises(FiscalValidationError, match="corrected assessment"):
        _estimate(credits, rows, [forged])
    with db.economy(scope) as store:
        import_month(store, BUYER, MONTH, 2, history_facts, context=context, as_of=TODAY)
    with pytest.raises(FiscalValidationError, match="historical snapshot changed"):
        with db.economy(scope) as store:
            import_recovery(store, BUYER, MONTH, 2, payload, context=context, as_of=TODAY)
