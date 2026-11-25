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
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _setup, _xml, fixture
from test_t16_unused_credits import BUYER, batch, bind_book, evidence
from test_t17_tax_recovery import _bundle, _review, _t16

from kordena_fiscal.application.credit_ledger import (
    ReviewedMovement,
    history,
    journal_id,
    post_movement,
    reconcile,
)
from kordena_fiscal.application.historical_audit import TABLE, import_month
from kordena_fiscal.application.tax_recovery import import_recovery
from kordena_fiscal.application.unused_credits import import_credits
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.tax.credit_ledger import Amount, Command, State, transition
from kordena_fiscal.tax.historical_audit import Month
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
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    key = journal_id(BUYER, finding)

    def post(store, command, as_of=TODAY):
        return post_movement(
            store, BUYER, _reviewed(scope, command), context=context, as_of=as_of
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
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)

    def post(store, command, day):
        return post_movement(
            store, BUYER, _reviewed(scope, command), context=context, as_of=day
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
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    with db.economy(scope) as store:
        post_movement(store, BUYER, _reviewed(scope, _bound(finding, digest)),
                      context=context, as_of=TODAY)
    barrier = Barrier(2)

    def reserve(number):
        command = _bound(finding, digest, 1, "reserved", 200, request_id=f"race-{number}")
        barrier.wait(timeout=20)
        try:
            with db.economy(scope) as store:
                post_movement(store, BUYER, _reviewed(scope, command),
                              context=context, as_of=TODAY)
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
                                 context=context, as_of=TODAY)

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
    _, context = historical_issuer_context(db, scope, MONTH)
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    finding, digest = _seed(db, scope, context, as_of=today)
    reviewed = _reviewed(scope, _bound(finding, digest))
    changed = reviewed.model_dump()
    changed["command"]["amount"]["principal_cents"] = 1
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="reviewed movement differs"):
            post_movement(store, BUYER, ReviewedMovement.model_validate(changed),
                          context=context, as_of=today)
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
    result = subprocess.run([*args, "--history", finding], env=env,
                            capture_output=True, text=True, check=True)
    assert len(json.loads(result.stdout)["events"]) == 1
    result = subprocess.run([*args, "--report"], env=env | {"NFCORE_ENVIRONMENT": "production"},
                            capture_output=True, text=True)
    assert result.returncode == 2 and not result.stdout


def test_postgres_new_source_cannot_reallocate_an_active_lot(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    with db.economy(scope) as store:
        post_movement(
            store, BUYER, _reviewed(scope, _bound(finding, digest)),
            context=context, as_of=TODAY,
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
                          context=context, as_of=TODAY)
        cancel = _bound(finding, digest, 1, "reversed")
        post_movement(store, BUYER, _reviewed(scope, cancel), context=context, as_of=TODAY)
        post_movement(store, BUYER, _reviewed(scope, candidate), context=context, as_of=TODAY)
        result = reconcile(store, BUYER)
        assert result["lot_count"] == 2
        assert result["by_tax"]["icms"]["available"]["principal_cents"] == 334
        assert result["by_tax"]["icms"]["reversed"]["principal_cents"] == 334


def test_postgres_forged_postings_fail_closed_on_replay(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    finding, digest = _seed(db, scope, context)
    key = journal_id(BUYER, finding)
    with db.economy(scope) as store:
        result = post_movement(
            store, BUYER, _reviewed(scope, _bound(finding, digest)),
            context=context, as_of=TODAY,
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
