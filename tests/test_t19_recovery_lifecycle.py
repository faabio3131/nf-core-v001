# ruff: noqa: F811 -- imported pytest fixtures requested by name.
"""T19 sandbox state machine and real PostgreSQL/T18 reconciliation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from threading import Barrier

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _setup
from test_t16_unused_credits import BUYER, evidence
from test_t18_credit_ledger import _federal_seed, _reviewed, _write

from kordena_fiscal.application import credit_ledger as ledger
from kordena_fiscal.application.credit_ledger import history, post_movement, reconcile
from kordena_fiscal.application.recovery_lifecycle import (
    RecoveryCaseService,
    ReviewedEvent,
    case_key,
    report,
)
from kordena_fiscal.application.unused_credits import verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.tax.credit_ledger import Amount, Command
from kordena_fiscal.tax.recovery_lifecycle import Event, Terms, alert, plan

NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 15, tzinfo=UTC)


def _session(db, scope, role=PortalRole.ACCOUNTANT, step_up=True):
    hasher = ScryptPasswordHasher()
    account = HumanAccount(
        "t19-test-actor", "t19@example.test", hasher.hash("Synthetic-test-Password-123"),
        scope.tenant_id, role, frozenset({scope.unit_id}),
    )
    identity = HumanIdentityService(
        accounts=InMemoryHumanAccountRepository((account,)),
        sessions=InMemoryWebSessionRepository(), password_hasher=hasher,
    )
    issued = identity.issue_session(account, now=NOW)
    service = RecoveryCaseService(db, identity, lambda *_: step_up, clock=lambda: NOW)
    return service, issued.session_token, issued.csrf_token


def _case(command, kind="compensation", case_id="a" * 64, **changes):
    return Terms.model_validate({
        "case_id": case_id, "competence": command.competence,
        "finding_id": command.finding_id, "tax": command.tax, "kind": kind,
        "route": "perdcomp", "amount": command.amount.model_dump(),
        "target_reference": f"target-{case_id}", "legal_reference": "reviewed-sandbox",
    } | changes)


def _event(scope, command, terms, version, action, **changes):
    source = action in {"request", "transmit", "release"}
    due = action in {"request", "transmit", "reject", "deny", "reverse", "approve"}
    event = Event.model_validate({
        "terms": terms.model_dump(), "expected_version": version, "action": action,
        "request_id": f"request-{version}", "opinion_reference": "synthetic-opinion",
        "professional_reference": "synthetic-accountant",
        "evidence_reference": f"{terms.case_id}-{version}",
        "due_on": (TODAY + timedelta(days=20)).isoformat() if due else None,
        "source_version": command.recovery_version if source else None,
        "source_digest": command.recovery_digest if source else None,
    } | changes)
    raw = json.dumps({
        "scope": list(scope.identity_material), "issuer_cnpj": BUYER.value,
        "simulation_only": True, "event": event.model_dump(),
    }, sort_keys=True).encode()
    return ReviewedEvent.model_validate({"event": event.model_dump(), "evidence": evidence(raw)})


def _fixture(db, mapping, kind="compensation"):
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    command, = _federal_seed(db, scope, MONTH, [("pis", 334)])
    with db.economy(scope) as store:
        _write(store, scope, proof, context, command)
    return scope, command, _case(command, kind=kind)


def _run(service, token, csrf, scope, command, terms, version, action, **changes):
    return service.execute(
        token, csrf, scope.unit_id, _event(scope, command, terms, version, action, **changes)
    )


def test_pure_transition_and_deadline():
    command = Command.model_validate({
        "competence": MONTH.isoformat(), "finding_id": "b" * 64, "tax": "pis",
        "recovery_version": 1, "recovery_digest": "c" * 64, "expected_version": 0,
        "request_id": "request", "movement": "identified", "review_reference": "review",
        "amount": {"principal_cents": 334, "selic_cents": 37},
    })
    terms = _case(command, kind="restitution")
    event = Event.model_validate({
        "terms": terms.model_dump(), "action": "pay", "expected_version": 3,
        "request_id": "pay", "opinion_reference": "review",
        "professional_reference": "accountant", "evidence_reference": "payment",
    })
    assert plan("granted", event) == ("paid", ("restituted",))
    with pytest.raises(FiscalValidationError, match="invalid recovery case transition"):
        plan("transmitted", event)
    assert alert("requested", TODAY.isoformat(), TODAY)["days_remaining"] == 0
    assert alert("requested", TODAY.isoformat(), TODAY + timedelta(days=1))["severity"] == (
        "overdue"
    )
    assert alert("paid", TODAY.isoformat(), TODAY) is None
    assert alert("requested", (TODAY + timedelta(days=31)).isoformat(), TODAY) is None


@pytest.mark.parametrize("kind", ["compensation", "restitution"])
def test_postgres_complete_lifecycle_and_reversal(economy_database, mapping, kind):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping, kind)
    service, token, csrf = _session(db, scope)

    def run(version, action):
        return _run(service, token, csrf, scope, cmd, terms, version, action)

    first = run(0, "request")
    assert first["status"] == "requested"
    with pytest.raises(FiscalValidationError, match="invalid recovery case transition"):
        run(1, "approve")
    assert run(1, "reject")["status"] == "requested"
    transmitted = run(2, "transmit")
    assert transmitted["status"] == "transmitted"
    replay = run(0, "request")
    assert replay["digest"] == first["digest"] and replay["replay"] is True
    assert replay["status"] == "requested" and replay["current_status"] == "transmitted"
    with db.economy(scope) as store:
        balances = reconcile(store, BUYER)["by_tax"]["pis"]
        if kind == "compensation":
            assert balances["compensated"] == cmd.amount.model_dump()
        else:
            assert balances["reserved"] == cmd.amount.model_dump()
    approved = run(3, "approve")
    if kind == "restitution":
        assert approved["status"] == "granted"
        with db.economy(scope) as store:
            assert reconcile(store, BUYER)["by_tax"]["pis"]["reserved"] == (
                cmd.amount.model_dump()
            )
        assert run(4, "pay")["status"] == "paid"
        with db.economy(scope) as store:
            assert reconcile(store, BUYER)["by_tax"]["pis"]["restituted"] == (
                cmd.amount.model_dump()
            )
        version = 5
    else:
        assert approved["status"] == "homologated"
        version = 4
    assert run(version, "reverse")["status"] == "reversed"
    assert run(version + 1, "release")["status"] == "released"
    data = service.read(token, csrf, scope.unit_id, MONTH)
    assert data["cases"][0]["status"] == "released"
    assert data["cases"][0]["version"] == version + 2
    assert data["ledger"]["by_tax"]["pis"]["available"] == cmd.amount.model_dump()
    assert data["credit_recognized"] is False and data["realized_cents"] is None


@pytest.mark.parametrize("kind", ["compensation", "restitution"])
def test_postgres_denial_quarantine_invalidate(economy_database, mapping, kind):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping, kind)
    service, token, csrf = _session(db, scope)
    for version, action in enumerate(("request", "transmit", "deny")):
        _run(service, token, csrf, scope, cmd, terms, version, action)
    data = service.read(token, csrf, scope.unit_id, MONTH)
    assert data["cases"][0]["status"] == "denied"
    assert data["cases"][0]["alert"]["severity"] == "due_soon"
    assert data["ledger"]["by_tax"]["pis"]["reserved"] == cmd.amount.model_dump()
    assert data["ledger"]["by_tax"]["pis"]["available"]["principal_cents"] == 0
    result = _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")
    assert result["status"] == "invalidated"
    data = service.read(token, csrf, scope.unit_id, MONTH)
    assert data["ledger"]["by_tax"]["pis"]["reversed"] == cmd.amount.model_dump()
    assert data["ledger"]["by_tax"]["pis"]["reserved"]["principal_cents"] == 0


def test_postgres_rollback_and_no_standalone_case_mutation(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    original = EconomyStore.append_snapshot

    def fail(self, **kwargs):
        if kwargs["record_id"].startswith("recovery-case-"):
            raise RuntimeError("induced case persistence failure")
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(EconomyStore, "append_snapshot", fail)
        with pytest.raises(RuntimeError, match="induced"):
            _run(service, token, csrf, scope, cmd, terms, 0, "request")
    with db.economy(scope) as store:
        assert store.record("fm_economy_snapshots", case_key(BUYER, terms)) is None
        assert history(store, BUYER, MONTH, cmd.finding_id)["events"][-1]["version"] == 1
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    proof = verify_credit_unit(db, scope, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    direct = Command.model_validate(cmd.model_dump() | {
        "expected_version": 2, "movement": "released", "request_id": "bypass",
        "reservation_id": f"t19-{terms.case_id}-1-1",
    })
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="T19 managed"):
            post_movement(store, BUYER, _reviewed(scope, direct),
                          context=context, as_of=TODAY, unit=proof)
    assert _run(service, token, csrf, scope, cmd, terms, 1, "cancel")["status"] == "cancelled"


def test_postgres_concurrent_reservations_and_duplicate_evidence(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    other = _case(cmd, case_id="d" * 64)
    barrier = Barrier(2)

    def submit(candidate):
        barrier.wait(timeout=20)
        try:
            _run(service, token, csrf, scope, cmd, candidate, 0, "request")
            return "committed"
        except FiscalValidationError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, (terms, other))) == ["committed", "conflict"]
    data = service.read(token, csrf, scope.unit_id, MONTH)
    assert len(data["cases"]) == 1
    won = Terms.model_validate(data["cases"][0]["terms"])
    with pytest.raises(FiscalValidationError, match="provider evidence already used"):
        _run(service, token, csrf, scope, cmd, won, 1, "reject",
             evidence_reference=f"{won.case_id}-0")
    with pytest.raises(FiscalValidationError, match="request identity conflict"):
        _run(service, token, csrf, scope, cmd, won, 0, "request",
             opinion_reference="changed-review")


def test_postgres_scope_and_canonical_lock(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    for role, step_up in ((PortalRole.OWNER, True), (PortalRole.ACCOUNTANT, False)):
        service, token, csrf = _session(db, scope, role=role, step_up=step_up)
        with pytest.raises(FiscalValidationError, match="accountant"):
            _run(service, token, csrf, scope, cmd, terms, 0, "request")
    service, token, csrf = _session(db, scope)
    with db.connection() as writer:
        writer.execute("LOCK TABLE fm_control_plane_fiscal_profiles IN ROW EXCLUSIVE MODE")
        with pytest.raises(FiscalValidationError, match="authority is changing"):
            _run(service, token, csrf, scope, cmd, terms, 0, "request")
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    for other in (
        replace(scope, tenant_id="other-tenant"),
        replace(scope, unit_id="other-unit"),
    ):
        with db.economy(other) as store:
            assert report(store, BUYER, TODAY)["cases"] == []
    for other in (
        replace(scope, host_namespace="other-host"),
        replace(scope, environment=FiscalEnvironment.PRODUCTION),
    ):
        with db.economy(other) as store:
            with pytest.raises(FiscalValidationError, match="canonical homologation"):
                report(store, BUYER, TODAY)


def test_postgres_wrong_selic_and_stale_source(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    bad = Terms.model_validate(terms.model_dump() | {
        "amount": Amount(principal_cents=334, selic_cents=0).model_dump(),
    })
    with pytest.raises(FiscalValidationError, match="SELIC"):
        _run(service, token, csrf, scope, cmd, bad, 0, "request")
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    service.clock = lambda: NOW + timedelta(days=1)
    with pytest.raises(FiscalValidationError, match="cutoff"):
        _run(service, token, csrf, scope, cmd, terms, 1, "transmit")
    assert _run(service, token, csrf, scope, cmd, terms, 1, "cancel")["status"] == "cancelled"


@pytest.mark.parametrize("match_by", ["receipt", "hash"])
def test_postgres_reconciliation_independently_rejects_cross_tax_receipt(
    economy_database, mapping, monkeypatch, match_by,
):
    """Create individually valid historical lots via a test-only bypass of the post guard."""
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    proof = verify_credit_unit(db, scope, BUYER)
    feb = date(2026, 2, 1)
    _, jan_context = historical_issuer_context(db, scope, MONTH)
    _, feb_context = historical_issuer_context(db, scope, feb)
    first, = _federal_seed(db, scope, MONTH, [("cofins", 334)], raw=b"same-DARF")
    second, = _federal_seed(
        db, scope, feb, [("pis", 334)],
        receipt="receipt-1" if match_by == "receipt" else "receipt-alias",
        raw=b"different-DARF" if match_by == "receipt" else b"same-DARF",
    )
    with db.economy(scope) as store:
        _write(store, scope, proof, jan_context, first)
        with pytest.raises(FiscalValidationError, match="another period"):
            _write(store, scope, proof, feb_context, second)
        with monkeypatch.context() as patch:
            patch.setattr(ledger, "_guard_existing_lots", lambda *args: None)
            _write(store, scope, proof, feb_context, second)
        with pytest.raises(FiscalValidationError, match="another period"):
            reconcile(store, BUYER)


@pytest.mark.parametrize("name", [" CREDIT-LEDGER-X ", " Tax-Recovery-X ", " Recovery-Case-X "])
@pytest.mark.parametrize("field", ["record_id", "opportunity_id"])
def test_postgres_legacy_reserved_prefixes_normalized(economy_database, mapping, name, field):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    args = {
        "record_id": "legacy-record", "opportunity_id": "legacy-opportunity",
        "opportunity_version": 1, "tax_code": "pis", "competence": MONTH,
        "movement": "identified", "amount_cents": 334, "evidence_reference": "synthetic",
    }
    args[field] = name
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="legacy credit entry"):
            store.append_credit_entry(**args)
