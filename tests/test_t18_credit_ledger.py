# ruff: noqa: F811 -- imported pytest fixtures requested by name.
"""T18 exact components, source provenance, journal and real PostgreSQL."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _setup, _xml, fixture
from test_t16_unused_credits import BUYER, batch, bind_book, evidence
from test_t17_tax_recovery import _bundle, _review, _t16

from kordena_fiscal.application import credit_ledger as ledger
from kordena_fiscal.application.credit_ledger import (
    ReviewedMovement,
    history,
    journal_id,
    post_movement,
    reconcile,
)
from kordena_fiscal.application.historical_audit import TABLE, import_month
from kordena_fiscal.application.tax_recovery import import_recovery
from kordena_fiscal.application.unused_credits import import_credits, verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount, Command, State, transition
from kordena_fiscal.tax.historical_audit import Month
from kordena_fiscal.tax.tax_recovery import federal_interest, ordinary_deadline
from kordena_fiscal.tax.unused_credits import Batch, detect


def _cmd(version=0, movement="identified", principal=334, selic=37, **changes):
    return Command.model_validate(
        {
            "competence": MONTH.isoformat(),
            "finding_id": "a" * 64,
            "tax": "pis",
            "recovery_version": 1,
            "recovery_digest": "b" * 64,
            "expected_version": version,
            "request_id": f"request-{version}",
            "movement": movement,
            "amount": {"principal_cents": principal, "selic_cents": selic},
            "review_reference": "synthetic-review",
        }
        | changes
    )


def _reviewed(scope, command):
    return ReviewedMovement.model_validate({
        "command": command.model_dump(),
        "review": evidence(json.dumps({
            "scope": list(scope.identity_material),
            "issuer_cnpj": BUYER.value,
            "simulation_only": True,
            "command": command.model_dump(),
        }, sort_keys=True).encode()),
    })


def _balanced(postings):
    assert len(postings) == 2
    assert [row["side"] for row in postings] == ["debit", "credit"]
    for component in ("principal_cents", "selic_cents"):
        assert postings[0][component] == postings[1][component]


def test_pure_exact_lifecycle_and_balanced_postings():
    state = State()
    commands = [
        _cmd(),
        _cmd(1, "reserved", 200, 20),
        _cmd(2, "compensated", 150, 15, reservation_id="request-1"),
        _cmd(3, "released", 50, 5, reservation_id="request-1"),
        _cmd(4, "compensation_reversed", 150, 15, compensation_id="request-2"),
        _cmd(5, "released", 150, 15, reservation_id="request-1"),
        _cmd(6, "reversed", 334, 37),
    ]
    for cmd in commands:
        _balanced(transition(state, cmd))
    assert state.projection() == {
        "identified": {"principal_cents": 334, "selic_cents": 37},
        "available": {"principal_cents": 0, "selic_cents": 0},
        "reserved": {"principal_cents": 0, "selic_cents": 0},
        "compensated": {"principal_cents": 0, "selic_cents": 0},
        "reversed": {"principal_cents": 334, "selic_cents": 37},
        "total_cents": 371,
    }
    assert len(state.seen) == 7


@pytest.mark.parametrize(
    "command",
    [
        _cmd(1),
        _cmd(1, "reserved", 335, 0),
        _cmd(1, "reserved", 0, 38),
        _cmd(1, "reserved", 0, 0),
        _cmd(1, "reserved", 1, 0, reservation_id="unknown"),
        _cmd(1, "released", 1, 0, reservation_id="unknown"),
        _cmd(1, "compensated", 1, 0, reservation_id="unknown"),
        _cmd(1, "compensation_reversed", 1, 0, compensation_id="unknown"),
        _cmd(2, "reserved", 1, 0),
        _cmd(1, "reversed", 0, 1, request_id="request-0"),
    ],
)
def test_invalid_transition_never_mutates_state(command):
    state = State()
    transition(state, _cmd())
    before = copy.deepcopy(state)
    with pytest.raises(FiscalValidationError):
        transition(state, command)
    assert state == before


def test_no_cross_reservation_and_exact_compensation_reversal():
    state = State()
    for cmd in (
        _cmd(), _cmd(1, "reserved", 10, 2), _cmd(2, "reserved", 50, 20),
    ):
        transition(state, cmd)
    with pytest.raises(FiscalValidationError, match="negative ledger component"):
        transition(state, _cmd(3, "compensated", 11, 2, reservation_id="request-1"))
    transition(state, _cmd(3, "compensated", 10, 2, reservation_id="request-1"))
    with pytest.raises(FiscalValidationError, match="amount differs"):
        transition(state, _cmd(4, "compensation_reversed", 9, 2, compensation_id="request-3"))
    transition(state, _cmd(4, "compensation_reversed", 10, 2, compensation_id="request-3"))
    with pytest.raises(FiscalValidationError, match="reversed"):
        transition(state, _cmd(5, "compensation_reversed", 10, 2, compensation_id="request-3"))
    assert state.balances["reserved"] == Amount(principal_cents=60, selic_cents=22)


@pytest.mark.parametrize("invalid", [-1, 1.5, True, "1", 10**12 + 1])
def test_exact_integer_schema(invalid):
    with pytest.raises(ValueError):
        _cmd(principal=invalid)


def _seed(db, scope, context, as_of=TODAY, version=1, tax="icms"):
    facts, rows = _t16(tax=tax, context=context, as_of=as_of)
    with db.economy(scope) as store:
        prior = import_credits(
            store, BUYER, MONTH, version, facts, context=context, as_of=as_of
        )
    digest = prior["snapshot_digest"]
    reviewed = _review(facts, rows[0], digest, as_of=as_of)
    payload = _bundle(facts, [reviewed], digest, t16_version=version)
    with db.economy(scope) as store:
        result = import_recovery(
            store, BUYER, MONTH, version, payload, context=context, as_of=as_of
        )
    return rows[0]["identity"], result["snapshot_digest"]


def _bound(finding, digest, version=0, movement="identified", principal=334, **changes):
    return _cmd(
        version, movement, principal, 0,
        finding_id=finding, recovery_digest=digest, tax="icms", **changes,
    )


def test_postgres_full_history_scope_idempotence_and_rollback(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    key = journal_id(BUYER, finding)

    def post(store, command, as_of=TODAY):
        return post_movement(
            store, BUYER, _reviewed(scope, command), context=context, as_of=as_of, unit=proof
        )

    first = _bound(finding, digest)
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="differs"):
            post(store, _bound(finding, digest, principal=333))
        assert store.record(TABLE, key) is None
        initial = post(store, first)
    with db.economy(scope) as store:
        assert post(store, first)["replay"] is True
        with pytest.raises(FiscalValidationError, match="request id conflict"):
            post(store, first.model_copy(update={"review_reference": "different"}))
        assert post(store, _bound(finding, digest, 1, "reserved", 100))["version"] == 2
        retry = post(store, first)
        assert retry["version"] == 1 and retry["digest"] == initial["digest"]
        assert retry["balances"] == initial["balances"]
        assert retry["current_version"] == 2
        assert retry["current_balances"]["reserved"]["principal_cents"] == 100
    with pytest.raises(RuntimeError), db.economy(scope) as store:
        post(store, _bound(finding, digest, 2, "compensated", 50, reservation_id="request-1"))
        raise RuntimeError("induced rollback")
    with db.economy(scope) as store:
        assert store.record(TABLE, key)["version"] == 2
        assert store.record(TABLE, key, 3) is None
        post(store, _bound(finding, digest, 2, "compensated", 50, reservation_id="request-1"))
        post(store, _bound(finding, digest, 3, "released", 50, reservation_id="request-1"))
        post(store, _bound(finding, digest, 4, "compensation_reversed", 50,
                           compensation_id="request-2"))
        post(store, _bound(finding, digest, 5, "released", 50, reservation_id="request-1"))
        post(store, _bound(finding, digest, 6, "reversed", 334))
        h = history(store, BUYER, MONTH, finding)
        assert len(h["events"]) == 7
        assert h["events"][0]["digest"] == initial["digest"]
        for idx, row in enumerate(h["events"]):
            _balanced(row["content"]["postings"])
            assert row["content"]["credit_recognized"] is False
            assert row["content"]["realized_cents"] is None
            if idx:
                assert row["content"]["previous_digest"] == h["events"][idx - 1]["digest"]
        report = reconcile(store, BUYER)
        assert report["lot_count"] == 1 and report["event_count"] == 7
        assert report["by_tax"]["icms"]["reversed"] == {
            "principal_cents": 334, "selic_cents": 0,
        }
        assert report["by_competence"][MONTH.isoformat()] == report["by_tax"]
        assert store.records("fm_economy_credit_entries") == ()
    for other in (
        replace(scope, unit_id="other-unit"),
        replace(scope, tenant_id="other-tenant"),
        replace(scope, host_namespace="other-host"),
    ):
        with db.economy(other) as store:
            assert reconcile(store, BUYER)["lot_count"] == 0
            assert store.record(TABLE, key) is None
            with pytest.raises(FiscalValidationError):
                post(store, first)
    with db.economy(replace(scope, environment=FiscalEnvironment.PRODUCTION)) as store:
        with pytest.raises(FiscalValidationError, match="non-production"):
            reconcile(store, BUYER)
        with pytest.raises(FiscalValidationError, match="non-production"):
            post(store, first)


def test_postgres_stale_source_refresh_and_stable_lot(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)

    def post(store, command, day):
        return post_movement(
            store, BUYER, _reviewed(scope, command), context=context, as_of=day, unit=proof
        )

    with db.economy(scope) as store:
        post(store, _bound(finding, digest), TODAY)
        post(store, _bound(finding, digest, 1, "reserved", 100), TODAY)
    next_day = TODAY + timedelta(days=1)
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="cutoff"):
            post(store, _bound(finding, digest, 2, "reserved", 10), next_day)
        post(store, _bound(finding, digest, 2, "released", 50,
                           reservation_id="request-1"), next_day)
    refreshed, new_digest = _seed(db, scope, context, as_of=next_day, version=2)
    assert finding == refreshed
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="current scoped T17"):
            post(store, _bound(finding, digest, 3, "reserved", 10), next_day)
        with pytest.raises(FiscalValidationError, match="already identified"):
            post(store, _bound(finding, new_digest, 3, recovery_version=2), next_day)
        post(store, _bound(finding, new_digest, 3, "reserved", 10,
                           recovery_version=2), next_day)
        assert reconcile(store, BUYER)["lot_count"] == 1
        with pytest.raises(FiscalValidationError, match="last source binding"):
            post(store, _bound(finding, digest, 4, "released", 10,
                               reservation_id="request-3"), next_day)
        post(store, _bound(finding, new_digest, 4, "released", 10,
                           recovery_version=2, reservation_id="request-3"), next_day)


def test_postgres_concurrent_overreservation(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    with db.economy(scope) as store:
        post_movement(store, BUYER, _reviewed(scope, _bound(finding, digest)),
                      context=context, as_of=TODAY, unit=proof)
    barrier = Barrier(2)

    def reserve(number):
        command = _bound(finding, digest, 1, "reserved", 200, request_id=f"race-{number}")
        barrier.wait(timeout=20)
        try:
            with db.economy(scope) as store:
                post_movement(store, BUYER, _reviewed(scope, command),
                              context=context, as_of=TODAY, unit=proof)
            return "committed"
        except FiscalValidationError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, (1, 2))) == ["committed", "conflict"]
    with db.economy(scope) as store:
        result = reconcile(store, BUYER)
        assert result["event_count"] == 2
        assert result["by_tax"]["icms"]["reserved"]["principal_cents"] == 200
        assert result["by_tax"]["icms"]["available"]["principal_cents"] == 134


def test_postgres_federal_principal_and_selic(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    source = fixture()
    original = _xml(MONTH, 1, issuer=BUYER)
    source["documents"][0]["xml_b64"] = evidence(original)["data_b64"]
    source["documents"][0]["xml_sha256"] = evidence(original)["sha256"]
    source["catalog"][0]["federal"] = "ordinary"
    for item in source["documents"][0]["items"]:
        for allocation in item["allocations"]:
            for field in (
                "reviewed_base_cents", "base_review_reference", "base_mode", "reviewed_rate",
            ):
                allocation[field] = None
            if item["number"] == 2 and allocation["tax"] == "icms":
                allocation["declared_cents"] = 0
    source["controls"][2]["declared_principal_cents"] = 3600
    payment = source["payments"][0]
    payment["issuer_cnpj"] = BUYER.value
    payment["allocations"]["icms"] = 3600
    payment["principal_cents"] = sum(payment["allocations"].values()) + 100
    credits, findings = _t16(tax="pis", context=context)
    with db.economy(scope) as store:
        prior = import_month(
            store, BUYER, MONTH, 1, Month.model_validate(source), context=context, as_of=TODAY
        )
        t16 = import_credits(store, BUYER, MONTH, 1, credits, context=context, as_of=TODAY)
    digest = t16["snapshot_digest"]
    review = _review(
        credits, findings[0], digest, modality="federal_undue_payment",
        receipt_id=payment["receipt_id"], anchor=payment["paid_on"],
        ordinary_deadline="2031-01-20", federal_correction={
            "historical_digest": prior["snapshot_digest"],
            "payment_sha256": source["artifacts"][3]["sha256"],
            "assessment_reference": "assessment",
            "corrected_assessment_reference": "rectified",
            "originally_due_cents": 365,
            "corrected_due_cents": 31,
        },
    )
    with db.economy(scope) as store:
        result = import_recovery(
            store, BUYER, MONTH, 1, _bundle(credits, [review], digest),
            context=context, as_of=TODAY,
        )
    binding = {
        "finding_id": findings[0]["identity"], "recovery_digest": result["snapshot_digest"],
    }
    with db.economy(scope) as store:
        def post(command):
            return post_movement(store, BUYER, _reviewed(scope, command),
                                 context=context, as_of=TODAY, unit=proof)

        post(_cmd(**binding))
        post(_cmd(1, "reserved", 200, 20, **binding))
        post(_cmd(2, "compensated", 100, 10, reservation_id="request-1", **binding))
        report = reconcile(store, BUYER, MONTH)["by_tax"]["pis"]
        assert report["identified"] == {"principal_cents": 334, "selic_cents": 37}
        assert report["available"] == {"principal_cents": 134, "selic_cents": 17}
        assert report["reserved"] == {"principal_cents": 100, "selic_cents": 10}
        assert report["compensated"] == {"principal_cents": 100, "selic_cents": 10}


def test_cli_and_tampered_review(economy_database, mapping, tmp_path):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    finding, digest = _seed(db, scope, context, as_of=today)
    reviewed = _reviewed(scope, _bound(finding, digest))
    changed = reviewed.model_dump()
    changed["command"]["amount"]["principal_cents"] = 1
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="reviewed movement differs"):
            post_movement(store, BUYER, ReviewedMovement.model_validate(changed),
                          context=context, as_of=today, unit=proof)
    payload = tmp_path / "ledger.json"
    payload.write_text(json.dumps(reviewed.model_dump()), encoding="utf-8")
    cli = Path(__file__).parents[1] / "scripts/nfcore_credit_ledger.py"
    args = [
        sys.executable, str(cli), "--tenant", scope.tenant_id, "--unit", scope.unit_id,
        "--issuer", BUYER.value, "--competence", MONTH.isoformat(),
    ]
    env = os.environ | {"NFCORE_ENVIRONMENT": "test", "DATABASE_URL": db._dsn}
    result = subprocess.run([*args, "--post", str(payload)], env=env,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["version"] == 1
    result = subprocess.run([*args, "--report"], env=env,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["lot_count"] == 1
    result = subprocess.run([*args[:-2], "--report"], env=env,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["lot_count"] == 1
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 65537)
    result = subprocess.run([*args, "--post", str(oversized)], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 2 and not result.stdout
    result = subprocess.run([*args, "--history", finding], env=env,
                            capture_output=True, text=True, check=True)
    assert len(json.loads(result.stdout)["events"]) == 1
    result = subprocess.run([*args, "--report"], env=env | {"NFCORE_ENVIRONMENT": "production"},
                            capture_output=True, text=True)
    assert result.returncode == 2 and not result.stdout


def test_postgres_new_source_cannot_reallocate_an_active_lot(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    with db.economy(scope) as store:
        post_movement(
            store, BUYER, _reviewed(scope, _bound(finding, digest)),
            context=context, as_of=TODAY, unit=proof,
        )
    data = batch()
    data["rules"][0]["cnae"] = context.cnae
    new_xml = (
        _xml(MONTH, 2)
        .replace(b"</emit>", f"</emit><dest><CNPJ>{BUYER.value}</CNPJ></dest>".encode())
        .replace(b"</prod>", b"<vProd>100.00</vProd></prod>")
        .replace(b"</imposto>", b"<IPI><IPITrib><vIPI>18.00</vIPI></IPITrib></IPI></imposto>")
    )
    data["purchases"][0]["xml"] = evidence(new_xml)
    bind_book(data)
    facts = Batch.model_validate(data)
    rows = detect(facts, BUYER, context, TODAY)["findings"]
    assert rows[0]["identity"] != finding
    with db.economy(scope) as store:
        t16 = import_credits(store, BUYER, MONTH, 2, facts, context=context, as_of=TODAY)
        t16_digest = t16["snapshot_digest"]
        reviewed = _review(facts, rows[0], t16_digest)
        t17 = import_recovery(
            store, BUYER, MONTH, 2, _bundle(facts, [reviewed], t16_digest, t16_version=2),
            context=context, as_of=TODAY,
        )
    candidate = _bound(rows[0]["identity"], t17["snapshot_digest"], recovery_version=2)
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="active ledger lot absent"):
            post_movement(store, BUYER, _reviewed(scope, candidate),
                          context=context, as_of=TODAY, unit=proof)
        cancel = _bound(finding, digest, 1, "reversed")
        post_movement(
            store, BUYER, _reviewed(scope, cancel), context=context, as_of=TODAY, unit=proof
        )
        post_movement(
            store, BUYER, _reviewed(scope, candidate), context=context, as_of=TODAY, unit=proof
        )
        result = reconcile(store, BUYER)
        assert result["lot_count"] == 2
        assert result["by_tax"]["icms"]["available"]["principal_cents"] == 334
        assert result["by_tax"]["icms"]["reversed"]["principal_cents"] == 334


def test_postgres_forged_postings_fail_closed_on_replay(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    key = journal_id(BUYER, finding)
    with db.economy(scope) as store:
        result = post_movement(
            store, BUYER, _reviewed(scope, _bound(finding, digest)),
            context=context, as_of=TODAY, unit=proof,
        )
        row = store.record(TABLE, key, 1)
        forged = copy.deepcopy(row["content"])
        forged["event_version"] = 2
        forged["previous_digest"] = result["digest"]
        command = _bound(finding, digest, 1, "reserved", 1)
        forged["reviewed"] = _reviewed(scope, command).model_dump()
        # Even a valid hash over a tampered document is not accepted as a
        # journal event: replay must derive both postings and every balance.
        store.append_snapshot(
            record_id=key, version=2, competence=MONTH, issuer=BUYER, content=forged
        )
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="postings or balance"):
            reconcile(store, BUYER)


def _federal_seed(db, scope, period, claims, *, receipt="receipt-1", raw=None, version=1):
    """Import authentic-shaped synthetic T15/T16/T17 through their real services.

    claims: ordered (tax, principal) pairs, one distinct purchase per pair.
    No monkeypatch of provenance or journal persistence in the receipt tests.
    """
    _, context = historical_issuer_context(db, scope, period)
    source = fixture(period=period, receipt=receipt)
    original = _xml(period, 1, issuer=BUYER)
    source["documents"][0]["xml_b64"] = evidence(original)["data_b64"]
    source["documents"][0]["xml_sha256"] = evidence(original)["sha256"]
    source["catalog"][0]["federal"] = "ordinary"
    for item in source["documents"][0]["items"]:
        for allocation in item["allocations"]:
            for field in (
                "reviewed_base_cents", "base_review_reference", "base_mode", "reviewed_rate",
            ):
                allocation[field] = None
            if item["number"] == 2 and allocation["tax"] == "icms":
                allocation["declared_cents"] = 0
    source["controls"][2]["declared_principal_cents"] = 3600
    payment = source["payments"][0]
    payment["issuer_cnpj"] = BUYER.value
    payment["allocations"]["icms"] = 3600
    payment["principal_cents"] = sum(payment["allocations"].values()) + 100
    if raw is not None:
        source["artifacts"][3].update(evidence(raw))

    data = batch(tax=claims[0][0], period=period)
    data["rules"] = []
    data["purchases"] = []
    data["books"]["complete_taxes"] = sorted({tax for tax, _ in claims})
    for number, (tax, _) in enumerate(claims, 1):
        one = batch(tax=tax, period=period)
        if not any(rule["tax"] == tax for rule in data["rules"]):
            rule = one["rules"][0]
            rule["citation"]["review_reference"] = f"synthetic-{tax}"
            rule["cnae"] = context.cnae
            data["rules"].append(rule)
        purchase = one["purchases"][0]
        purchase["xml"] = evidence(
            _xml(period, number)
            .replace(b"</emit>", f"</emit><dest><CNPJ>{BUYER.value}</CNPJ></dest>".encode())
            .replace(b"</prod>", b"<vProd>100.00</vProd></prod>")
            .replace(b"</imposto>", b"<IPI><IPITrib><vIPI>18.00</vIPI></IPITrib></IPI></imposto>")
        )
        data["purchases"].append(purchase)
    bind_book(data)
    facts = Batch.model_validate(data)
    rows = detect(facts, BUYER, context, TODAY)["findings"]
    assert len(rows) == len(claims)
    amounts = {
        tax: [principal for name, principal in claims if name == tax]
        for tax, _ in claims
    }
    totals = {tax: sum(principals) for tax, principals in amounts.items()}
    with db.economy(scope) as store:
        prior = import_month(
            store, BUYER, period, version, Month.model_validate(source),
            context=context, as_of=TODAY,
        )
        t16 = import_credits(store, BUYER, period, version, facts, context=context, as_of=TODAY)
        digest = t16["snapshot_digest"]
        reviewed, commands = [], []
        paid_on = date.fromisoformat(payment["paid_on"])
        deadline = ordinary_deadline(paid_on)
        assert deadline is not None
        for row in rows:
            tax = row["tax"]
            principal = amounts[tax].pop(0)
            originally_due = payment["allocations"][tax]
            reviewed.append(_review(
                facts, row, digest, principal_cents=principal,
                modality="federal_undue_payment", receipt_id=receipt,
                anchor=paid_on.isoformat(), ordinary_deadline=deadline.isoformat(),
                federal_correction={
                    "historical_digest": prior["snapshot_digest"],
                    "payment_sha256": source["artifacts"][3]["sha256"],
                    "assessment_reference": "assessment",
                    "corrected_assessment_reference": "rectified",
                    "originally_due_cents": originally_due,
                    "corrected_due_cents": originally_due - totals[tax],
                },
            ))
            interest = federal_interest(principal, paid_on, TODAY)
            assert interest is not None
            commands.append(_cmd(
                principal=principal, selic=interest[0],
                competence=period.isoformat(), tax=tax,
                recovery_version=version, finding_id=row["identity"],
            ))
        result = import_recovery(
            store, BUYER, period, version,
            _bundle(facts, reviewed, digest, t16_version=version),
            context=context, as_of=TODAY,
        )
    assert result["status_counts"] == {"potential": len(claims)}
    return [
        Command.model_validate(cmd.model_dump() | {"recovery_digest": result["snapshot_digest"]})
        for cmd in commands
    ]


def _event(command, version, movement, amount=None, **changes):
    return Command.model_validate(command.model_dump() | {
        "expected_version": version,
        "request_id": f"request-{version}",
        "movement": movement,
        "amount": (amount or command.amount).model_dump(),
    } | changes)


def _write(store, scope, proof, context, command, day=TODAY):
    return post_movement(
        store, BUYER, _reviewed(scope, command), context=context, as_of=day, unit=proof
    )


@pytest.mark.parametrize("other_tax", ["pis", "cofins"])
@pytest.mark.parametrize("match_by", ["receipt", "hash"])
def test_postgres_federal_receipt_is_unique_across_competences(
    economy_database, mapping, other_tax, match_by,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    feb = date(2026, 2, 1)
    _, jan_context = historical_issuer_context(db, scope, MONTH)
    _, feb_context = historical_issuer_context(db, scope, feb)
    first, = _federal_seed(db, scope, MONTH, [("pis", 334)], raw=b"same-DARF")
    second, = _federal_seed(
        db, scope, feb, [(other_tax, 334)],
        receipt="receipt-1" if match_by == "receipt" else "receipt-alias",
        raw=b"different-DARF" if match_by == "receipt" else b"same-DARF",
    )
    partial = Amount(principal_cents=1, selic_cents=0)
    rest = Amount(principal_cents=333, selic_cents=first.amount.selic_cents)
    with db.economy(scope) as store:
        _write(store, scope, proof, jan_context, first)
        for version in (1, 2):
            with pytest.raises(FiscalValidationError, match="another period"):
                _write(store, scope, proof, feb_context, second)
            assert store.record(TABLE, journal_id(BUYER, second.finding_id)) is None
            cancel = _event(first, version, "reversed", partial if version == 1 else rest)
            _write(store, scope, proof, jan_context, cancel)
        _write(store, scope, proof, feb_context, second)
        report = reconcile(store, BUYER)
        assert report["lot_count"] == 2
        assert report["by_competence"][MONTH.isoformat()]["pis"]["reversed"] == (
            first.amount.model_dump()
        )
        assert report["by_competence"][feb.isoformat()][other_tax]["available"] == (
            second.amount.model_dump()
        )


def test_postgres_shared_receipt_and_multitax_multiperiod_reconcile(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    commands = _federal_seed(db, scope, MONTH, [("pis", 150), ("pis", 184), ("cofins", 334)])
    apr = date(2026, 4, 1)
    _, apr_context = historical_issuer_context(db, scope, apr)
    facts, rows = _t16(period=apr, context=apr_context)
    with db.economy(scope) as store:
        t16 = import_credits(store, BUYER, apr, 1, facts, context=apr_context, as_of=TODAY)
        digest = t16["snapshot_digest"]
        t17 = import_recovery(
            store, BUYER, apr, 1, _bundle(facts, [_review(facts, rows[0], digest)], digest),
            context=apr_context, as_of=TODAY,
        )
    icms = _bound(
        rows[0]["identity"], t17["snapshot_digest"], competence=apr.isoformat()
    )
    with db.economy(scope) as store:
        for command in commands:
            _write(store, scope, proof, context, command)
        _write(store, scope, proof, apr_context, icms)
        report = reconcile(store, BUYER)
        assert report["lot_count"] == 4
        assert report["event_count"] == 4
        assert set(report["by_tax"]) == {"icms", "pis", "cofins"}
        assert set(report["by_competence"]) == {MONTH.isoformat(), apr.isoformat()}
        assert report["by_tax"]["pis"]["available"]["principal_cents"] == 334
        assert report["by_tax"]["pis"]["available"]["selic_cents"] == sum(
            command.amount.selic_cents for command in commands if command.tax == "pis"
        )
        assert report["by_tax"]["cofins"]["available"]["principal_cents"] == 334
        assert report["by_tax"]["icms"]["available"]["principal_cents"] == 334


@pytest.mark.parametrize("change", ["amount", "identity"])
def test_postgres_source_changes_block_new_commitments_but_allow_unwind(
    economy_database, mapping, change,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, = _federal_seed(db, scope, MONTH, [("pis", 334)])
    reserved = Amount(principal_cents=200, selic_cents=20)
    compensated = Amount(principal_cents=100, selic_cents=10)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, first)
        _write(store, scope, proof, context, _event(first, 1, "reserved", reserved))
        _write(
            store, scope, proof, context,
            _event(first, 2, "compensated", compensated, reservation_id="request-1"),
        )
    revised, = _federal_seed(
        db, scope, MONTH, [("pis", 333 if change == "amount" else 334)],
        receipt="new-receipt" if change == "identity" else "receipt-1",
        version=2,
    )
    assert revised.finding_id == first.finding_id
    with db.economy(scope) as store:
        for movement in ("reserved", "compensated"):
            kwargs = {"reservation_id": "request-1"} if movement == "compensated" else {}
            with pytest.raises(FiscalValidationError, match="amount|identity"):
                _write(
                    store, scope, proof, context,
                    _event(revised, 3, movement, compensated, **kwargs),
                )
        release = _event(first, 3, "released", compensated, reservation_id="request-1")
        with pytest.raises(FiscalValidationError, match="date moved backwards"):
            _write(store, scope, proof, context, release, TODAY - timedelta(days=1))
        _write(store, scope, proof, context, release)
        _write(
            store, scope, proof, context,
            _event(first, 4, "compensation_reversed", compensated, compensation_id="request-2"),
        )
        _write(
            store, scope, proof, context,
            _event(first, 5, "released", compensated, reservation_id="request-1"),
        )
        _write(store, scope, proof, context, _event(first, 6, "reversed"))
        assert reconcile(store, BUYER)["by_tax"]["pis"]["reversed"] == first.amount.model_dump()


def test_partial_reversal_and_selic_only_gate():
    state = State()
    transition(state, _cmd())
    transition(state, _cmd(1, "reversed", 100, 10))
    before = copy.deepcopy(state)
    with pytest.raises(FiscalValidationError, match="requires principal"):
        transition(state, _cmd(2, "reserved", 0, 1))
    assert state == before
    transition(state, _cmd(2, "reserved", 100, 10))
    before = copy.deepcopy(state)
    with pytest.raises(FiscalValidationError, match="requires principal"):
        transition(state, _cmd(3, "compensated", 0, 1, reservation_id="request-2"))
    assert state == before
    transition(state, _cmd(3, "compensated", 100, 9, reservation_id="request-2"))
    # SELIC-only unwind remains possible: do not strand a residual component.
    transition(state, _cmd(4, "released", 0, 1, reservation_id="request-2"))
    assert state.balances["available"] == Amount(principal_cents=134, selic_cents=18)
    assert state.balances["compensated"] == Amount(principal_cents=100, selic_cents=9)


@pytest.mark.parametrize(
    "raw,reason",
    [(b"{", "invalid ledger review JSON"),
     (b"\xff", "invalid ledger review JSON"),
     (b" " * 16385, "exceeds 16 KiB")],
)
def test_invalid_evidence_is_normalized(raw, reason):
    reviewed = ReviewedMovement.model_validate({
        "command": _cmd().model_dump(), "review": evidence(raw),
    })
    with pytest.raises(FiscalValidationError, match=reason):
        reviewed.verify(("host", "tenant", "unit", "homologation"), BUYER)


def test_postgres_unit_proof_and_legacy_entry_gate(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    command = _bound(finding, digest)
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="verified credit recipient unit required"):
            _write(store, scope, None, context, command)
        with pytest.raises(FiscalValidationError, match="scope mismatch"):
            wrong = replace(proof, scope_identity=("wrong", *proof.scope_identity[1:]))
            _write(store, scope, wrong, context, command)
        with pytest.raises(FiscalValidationError, match="legacy credit entry"):
            store.append_credit_entry(
                record_id=journal_id(BUYER, finding), opportunity_id="legacy",
                opportunity_version=1, tax_code="icms", competence=MONTH,
                movement="identified", amount_cents=334, evidence_reference="test",
            )
        assert reconcile(store, BUYER)["lot_count"] == 0


def test_postgres_ambiguous_cnpj_cannot_obtain_unit_proof(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    assert proof.scope_identity == scope.identity_material
    assert proof.issuer == BUYER
    other = replace(scope, unit_id="second-unit")
    with db() as uow:
        old = uow.control_plane.get_profile(context.profile_id, context.profile_version)
        unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        assert old is not None and unit is not None
        uow.control_plane.add_unit(replace(unit, unit_id=other.unit_id))
        uow.control_plane.add_profile(replace(old, profile_id="second-profile", scope=other))
        uow.commit()
    for unit_scope in (scope, other):
        with pytest.raises(FiscalValidationError, match="ambiguous credit recipient"):
            verify_credit_unit(db, unit_scope, BUYER)


def test_postgres_scan_bounds_fail_closed(economy_database, mapping, monkeypatch):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    commands = _federal_seed(db, scope, MONTH, [("pis", 150), ("pis", 184)])
    with db.economy(scope) as store:
        for command in commands:
            _write(store, scope, proof, context, command)
        first, second = commands
        reserve = _event(first, 1, "reserved", Amount(principal_cents=10, selic_cents=1))
        _write(store, scope, proof, context, reserve)
        with monkeypatch.context() as patch:
            patch.setattr(ledger, "MAX_EVENTS", 1)
            with pytest.raises(FiscalValidationError, match="history exceeds"):
                history(store, BUYER, MONTH, first.finding_id)
        with monkeypatch.context() as patch:
            patch.setattr(ledger, "MAX_LOTS", 1)
            with pytest.raises(FiscalValidationError, match="lot bound"):
                reconcile(store, BUYER)
            with pytest.raises(FiscalValidationError, match="lot bound"):
                _write(store, scope, proof, context, _event(second, 1, "reserved", reserve.amount))
        with monkeypatch.context() as patch:
            patch.setattr(ledger, "MAX_SCAN_EVENTS", 1)
            with pytest.raises(FiscalValidationError, match="event bound"):
                reconcile(store, BUYER)
            with pytest.raises(FiscalValidationError, match="event bound"):
                _write(store, scope, proof, context, _event(second, 1, "reserved", reserve.amount))
        assert reconcile(store, BUYER)["event_count"] == 3


@pytest.mark.parametrize("bound", ["MAX_LOTS", "MAX_SCAN_EVENTS"])
def test_postgres_prospective_new_lot_capacity(economy_database, mapping, monkeypatch, bound):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, second, third = _federal_seed(
        db, scope, MONTH, [("pis", 100), ("pis", 110), ("pis", 124)],
    )
    monkeypatch.setattr(ledger, bound, 2)
    with db.economy(scope) as store:
        a = _write(store, scope, proof, context, first)
        assert reconcile(store, BUYER)["lot_count"] == 1
        _write(store, scope, proof, context, second)
        before = reconcile(store, BUYER)
        assert before["lot_count"] == before["event_count"] == 2
        with pytest.raises(FiscalValidationError, match="prospective .*bound"):
            _write(store, scope, proof, context, third)
        assert store.record(TABLE, journal_id(BUYER, third.finding_id)) is None
        replay = _write(store, scope, proof, context, first)
        assert replay["replay"] is True and replay["digest"] == a["digest"]
        assert reconcile(store, BUYER) == before
        assert len(history(store, BUYER, MONTH, first.finding_id)["events"]) == 1
        assert reconcile(store, BUYER, MONTH) == before
    with db.economy(replace(scope, tenant_id="isolated-capacity-tenant")) as other:
        assert reconcile(other, BUYER)["lot_count"] == 0
    with db.economy(scope) as store:
        assert reconcile(store, BUYER) == before


def test_postgres_existing_lot_at_global_lot_limit(economy_database, mapping, monkeypatch):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, = _federal_seed(db, scope, MONTH, [("pis", 334)])
    monkeypatch.setattr(ledger, "MAX_LOTS", 1)
    monkeypatch.setattr(ledger, "MAX_SCAN_EVENTS", 2)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, first)
        reserve = _event(first, 1, "reserved", Amount(principal_cents=10, selic_cents=1))
        saved = _write(store, scope, proof, context, reserve)
        before = history(store, BUYER, MONTH, first.finding_id)
        with pytest.raises(FiscalValidationError, match="prospective .*event bound"):
            _write(store, scope, proof, context, _event(first, 2, "released", reserve.amount,
                                                        reservation_id="request-1"))
        assert history(store, BUYER, MONTH, first.finding_id) == before
        assert _write(store, scope, proof, context, reserve)["digest"] == saved["digest"]
        with pytest.raises(FiscalValidationError, match="request id conflict"):
            _write(store, scope, proof, context, reserve.model_copy(
                update={"review_reference": "different"},
            ))
        with pytest.raises(FiscalValidationError, match="optimistic version conflict"):
            _write(store, scope, proof, context, reserve.model_copy(
                update={"request_id": "stale-new-request"},
            ))
        assert reconcile(store, BUYER)["event_count"] == 2


@pytest.mark.parametrize("bound", ["MAX_LOTS", "MAX_SCAN_EVENTS"])
def test_postgres_prospective_capacity_across_competences(
    economy_database, mapping, monkeypatch, bound,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    feb = date(2026, 2, 1)
    _, jan_context = historical_issuer_context(db, scope, MONTH)
    _, feb_context = historical_issuer_context(db, scope, feb)
    first, = _federal_seed(db, scope, MONTH, [("pis", 334)], raw=b"capacity-DARF-jan")
    second, = _federal_seed(
        db, scope, feb, [("pis", 334)], receipt="capacity-feb", raw=b"capacity-DARF-feb",
    )
    monkeypatch.setattr(ledger, bound, 1)
    with db.economy(scope) as store:
        _write(store, scope, proof, jan_context, first)
        before = reconcile(store, BUYER)
        assert reconcile(store, BUYER, feb)["event_count"] == 0
        with pytest.raises(FiscalValidationError, match="prospective .*bound"):
            _write(store, scope, proof, feb_context, second)
        assert store.record(TABLE, journal_id(BUYER, second.finding_id)) is None
        assert reconcile(store, BUYER) == before
    # At the next exact bound both competences remain independently readable.
    monkeypatch.setattr(ledger, bound, 2)
    with db.economy(scope) as store:
        _write(store, scope, proof, feb_context, second)
        assert reconcile(store, BUYER)["event_count"] == 2
        assert reconcile(store, BUYER, MONTH)["event_count"] == 1
        assert reconcile(store, BUYER, feb)["event_count"] == 1


@pytest.mark.parametrize("bound", ["MAX_LOTS", "MAX_SCAN_EVENTS"])
def test_postgres_last_capacity_slot_is_serialized(economy_database, mapping, monkeypatch, bound):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, second, third = _federal_seed(
        db, scope, MONTH, [("pis", 100), ("pis", 110), ("pis", 124)],
    )
    monkeypatch.setattr(ledger, bound, 2)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, first)
    barrier = Barrier(2)

    def submit(command):
        barrier.wait(timeout=20)
        try:
            with db.economy(scope) as store:
                _write(store, scope, proof, context, command)
            return True
        except FiscalValidationError as exc:
            assert "prospective" in str(exc) and "bound" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (second, third)))
    assert sorted(results) == [False, True]
    with db.economy(scope) as store:
        report = reconcile(store, BUYER)
        assert report["lot_count"] == report["event_count"] == 2
        for command, committed in zip((second, third), results, strict=True):
            key = journal_id(BUYER, command.finding_id)
            assert (store.record(TABLE, key) is not None) == committed


def test_postgres_capacity_slot_released_after_rollback(economy_database, mapping, monkeypatch):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, second = _federal_seed(db, scope, MONTH, [("pis", 150), ("pis", 184)])
    monkeypatch.setattr(ledger, "MAX_LOTS", 2)
    monkeypatch.setattr(ledger, "MAX_SCAN_EVENTS", 2)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, first)
        before = reconcile(store, BUYER)
    with pytest.raises(RuntimeError, match="induced rollback"), db.economy(scope) as store:
        _write(store, scope, proof, context, second)
        assert reconcile(store, BUYER)["event_count"] == 2
        raise RuntimeError("induced rollback")
    with db.economy(scope) as store:
        assert reconcile(store, BUYER) == before
        assert store.record(TABLE, journal_id(BUYER, second.finding_id)) is None
        _write(store, scope, proof, context, second)
        assert reconcile(store, BUYER)["event_count"] == 2


@pytest.mark.parametrize("sizes,key,movements,bounds,error", [
    ((), "new", 1, (1, 1, 1), None),
    ((1,), "new", 1, (1, 2, 2), "lot bound"),
    ((1,), "existing", 1, (1, 2, 2), None),
    ((1,), "existing", 1, (1, 1, 2), "history exceeds event bound"),
    ((1,), "existing", 1, (1, 2, 1), "reconciliation event bound"),
    ((1, 2), "existing", 1, (2, 3, 4), None),
    ((1, 2), "existing", 1, (2, 3, 3), "reconciliation event bound"),
    ((1, 2), "new", 1, (3, 3, 4), None),
    ((1, 2), "new", 1, (2, 3, 4), "lot bound"),
    ((1, 2), "new", 1, (3, 3, 3), "reconciliation event bound"),
    ((2,), "existing", 2, (1, 4, 4), None),
    ((2,), "existing", 2, (1, 3, 4), "history exceeds event bound"),
    ((2,), "existing", 2, (1, 4, 3), "reconciliation event bound"),
    ((1,), "existing", 0, (2, 2, 2), "movement count"),
    ((1,), "existing", -1, (2, 2, 2), "movement count"),
    ((1,), "existing", True, (2, 2, 2), "movement count"),
])
def test_prospective_capacity_uses_verified_global_journals(sizes, key, movements, bounds, error):
    # The authority has already verified contents; this unit tests only cardinality.
    # Deliberately place the second lot in another competence.
    dates = (MONTH, date(2026, 2, 1))
    journals = {
        ("existing" if i == 0 else "second", dates[i].isoformat()): (
            State(), [{} for _ in range(size)],
        )
        for i, size in enumerate(sizes)
    }
    verified = ledger.VerifiedRecoveryScope([], journals)
    kwargs = dict(
        key=key, period=MONTH, movements=movements,
        max_lots=bounds[0], max_events=bounds[1], max_scan_events=bounds[2],
    )
    if error:
        with pytest.raises(FiscalValidationError, match=error):
            ledger._require_write_capacity(verified, **kwargs)
    else:
        assert ledger._require_write_capacity(verified, **kwargs) is None
    assert tuple(len(rows) for _, rows in verified.journals.values()) == sizes


def test_postgres_per_lot_capacity_preserves_history_and_replay(
    economy_database, mapping, monkeypatch,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, = _federal_seed(db, scope, MONTH, [("pis", 334)])
    monkeypatch.setattr(ledger, "MAX_EVENTS", 2)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, first)
        reserve = _event(first, 1, "reserved", Amount(principal_cents=10, selic_cents=1))
        _write(store, scope, proof, context, reserve)
        before = history(store, BUYER, MONTH, first.finding_id)
        with pytest.raises(FiscalValidationError, match="optimistic version conflict"):
            _write(store, scope, proof, context, _event(first, 2, "released", reserve.amount,
                                                        reservation_id="request-1"))
        assert _write(store, scope, proof, context, reserve)["replay"] is True
        assert history(store, BUYER, MONTH, first.finding_id) == before
        assert reconcile(store, BUYER)["event_count"] == 2


def test_postgres_last_event_slot_in_distinct_existing_lots(
    economy_database, mapping, monkeypatch,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    first, second = _federal_seed(db, scope, MONTH, [("pis", 150), ("pis", 184)])
    monkeypatch.setattr(ledger, "MAX_LOTS", 2)
    monkeypatch.setattr(ledger, "MAX_SCAN_EVENTS", 3)
    with db.economy(scope) as store:
        for command in (first, second):
            _write(store, scope, proof, context, command)
    barrier = Barrier(2)

    def submit(command):
        move = _event(command, 1, "reserved", Amount(principal_cents=10, selic_cents=1))
        barrier.wait(timeout=20)
        try:
            with db.economy(scope) as store:
                _write(store, scope, proof, context, move)
            return True
        except FiscalValidationError as exc:
            assert "prospective case reconciliation event bound" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (first, second)))
    assert sorted(results) == [False, True]
    with db.economy(scope) as store:
        result = reconcile(store, BUYER)
        assert result["lot_count"] == 2 and result["event_count"] == 3
        for command, committed in zip((first, second), results, strict=True):
            events = history(store, BUYER, MONTH, command.finding_id)["events"]
            assert len(events) == 1 + int(committed)
