# ruff: noqa: F811 -- imported pytest fixtures requested by name.
"""T19 sandbox state machine and real PostgreSQL/T18 reconciliation."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from test_bling_canonical import mapping  # noqa: F401
from test_t14_authorized_issuance import economy_database  # noqa: F401
from test_t15_historical_audit import MONTH, TODAY, _setup
from test_t16_unused_credits import BUYER, evidence
from test_t18_credit_ledger import _bound, _federal_seed, _reviewed, _seed, _write

from kordena_fiscal.application import credit_ledger as ledger
from kordena_fiscal.application import recovery_lifecycle as lifecycle
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
    HumanAuthenticationError,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import HumanMfaService
from kordena_fiscal.security.totp import totp_at
from kordena_fiscal.tax.credit_ledger import Amount, Command, transition
from kordena_fiscal.tax.recovery_lifecycle import (
    Event,
    Terms,
    alert,
    managed_request_id,
    managed_request_identity,
    plan,
    validate_managed_command,
)
from kordena_fiscal.tax.tax_recovery import federal_interest

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
    due = action in {"request", "transmit", "reject", "deny", "reverse"} or (
        action == "approve" and terms.kind == "restitution"
    )
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
    assert alert("homologated", TODAY.isoformat(), TODAY + timedelta(days=1)) is None
    assert alert("transmitted", TODAY.isoformat(), TODAY)["severity"] == "due_soon"
    assert alert("granted", TODAY.isoformat(), TODAY)["severity"] == "due_soon"
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
        data = service.read(token, csrf, scope.unit_id, MONTH)
        assert data["cases"][0]["alert"] is None
        assert data["cases"][0]["events"][-1]["content"]["reviewed"]["event"]["due_on"] is None
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
    account = service.identity.authenticate_session(session_token=token, now=NOW).account
    next_day = NOW + timedelta(days=1)
    service.clock = lambda: next_day
    # The expired session must fail closed before the fiscal cutoff is checked.
    with pytest.raises(HumanAuthenticationError, match="web session is not usable"):
        _run(service, token, csrf, scope, cmd, terms, 1, "transmit")
    # Use the same canonical test identity with a newly issued session and CSRF.
    renewed = service.identity.issue_session(account, now=next_day)
    token, csrf = renewed.session_token, renewed.csrf_token
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


def test_postgres_administrative_icms_sandbox(economy_database, mapping):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    finding, digest = _seed(db, scope, context)
    command = _bound(finding, digest)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, command)
    with pytest.raises(ValueError, match="federal credit"):
        _case(command)
    terms = _case(command, route="administrative")
    with pytest.raises(ValueError, match="ICMS bookkeeping"):
        _case(command, route="administrative", kind="restitution")
    service, token, csrf = _session(db, scope)
    # Test-only bypass of Pydantic construction: application still checks the
    # authoritative source modality and rejects before any monetary posting.
    original = _event(scope, command, terms, 0, "request")
    forged_terms = terms.model_copy(update={"kind": "restitution"})
    forged_event = original.event.model_copy(update={"terms": forged_terms})
    raw = json.dumps({
        "scope": list(scope.identity_material), "issuer_cnpj": BUYER.value,
        "simulation_only": True, "event": forged_event.model_dump(),
    }, sort_keys=True).encode()
    forged = ReviewedEvent.model_construct(
        event=forged_event, evidence=type(original.evidence).model_validate(evidence(raw)),
    )
    with pytest.raises(FiscalValidationError, match="unsupported recovery modality"):
        service.execute(token, csrf, scope.unit_id, forged)
    with pytest.raises(FiscalValidationError, match="federal undue payment"):
        lifecycle._validate_payment("icms_bookkeeping", MONTH.isoformat(), forged_terms, TODAY)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    assert before["cases"] == []
    assert before["ledger"]["by_tax"]["icms"]["available"] == command.amount.model_dump()
    for version, action in enumerate(("request", "transmit", "approve")):
        result = _run(service, token, csrf, scope, command, terms, version, action)
    assert result["status"] == "homologated"
    data = service.read(token, csrf, scope.unit_id, MONTH)
    assert data["ledger"]["by_tax"]["icms"]["compensated"] == command.amount.model_dump()
    assert data["simulation_only"] is True


def test_postgres_partial_federal_principal_and_selic(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    # Derive the payment date from the immutable T17 source, not a rate guessed
    # from the journal total; verify the exact partial value independently.
    with db.economy(scope) as store:
        origin = ledger._historical_source(store, BUYER, MONTH, cmd)
    projected = federal_interest(100, date.fromisoformat(origin.anchor), TODAY)
    assert projected is not None
    partial = Amount(principal_cents=100, selic_cents=projected[0])
    terms = Terms.model_validate(terms.model_dump() | {"amount": partial.model_dump()})
    for version, action in enumerate(("request", "transmit", "approve")):
        _run(service, token, csrf, scope, cmd, terms, version, action)
    balance = service.read(token, csrf, scope.unit_id, MONTH)["ledger"]["by_tax"]["pis"]
    assert balance["compensated"] == partial.model_dump()
    assert balance["available"] == {
        "principal_cents": cmd.amount.principal_cents - partial.principal_cents,
        "selic_cents": cmd.amount.selic_cents - partial.selic_cents,
    }
    too_much = _case(cmd, case_id="f" * 64)
    with pytest.raises(FiscalValidationError, match="negative ledger component"):
        _run(service, token, csrf, scope, cmd, too_much, 0, "request")
    assert len(service.read(token, csrf, scope.unit_id, MONTH)["cases"]) == 1


def test_postgres_ambiguous_unit_fails_inside_case_service(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    _, context = historical_issuer_context(db, scope, MONTH)
    other = replace(scope, unit_id="another-unit")
    with db() as uow:
        profile = uow.control_plane.get_profile(context.profile_id, context.profile_version)
        unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        assert profile is not None and unit is not None
        uow.control_plane.add_unit(replace(unit, unit_id=other.unit_id))
        uow.control_plane.add_profile(replace(profile, profile_id="other-profile", scope=other))
        uow.commit()
    with pytest.raises(FiscalValidationError, match="ambiguous credit recipient"):
        _run(service, token, csrf, scope, cmd, terms, 0, "request")
    with db.economy(scope) as store:
        assert report(store, BUYER, TODAY)["cases"] == []


def test_postgres_forged_case_link_is_rejected(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    _run(service, token, csrf, scope, cmd, terms, 1, "transmit")
    # A valid snapshot hash alone cannot prove the event-to-ledger link.
    with db.economy(scope) as store:
        key = case_key(BUYER, terms)
        previous = store.record("fm_economy_snapshots", key)
        assert previous is not None
        fake = dict(previous["content"])
        fake["previous_digest"] = previous["digest"]
        fake["reviewed"] = _event(scope, cmd, terms, 2, "deny").model_dump()
        fake["status"] = "denied"
        # Wrong link: repeats the already consumed compensation posting.
        store.append_snapshot(record_id=key, version=3, competence=MONTH,
                              issuer=BUYER, content=fake)
    with db.economy(scope) as store:
        with pytest.raises(FiscalValidationError, match="out of order|posting mismatch"):
            report(store, BUYER, TODAY)

def test_deadlines_for_distinct_approval_kinds():
    command = Command.model_validate({
        "competence": MONTH.isoformat(), "finding_id": "b" * 64, "tax": "pis",
        "recovery_version": 1, "recovery_digest": "c" * 64, "expected_version": 0,
        "request_id": "request", "movement": "identified", "review_reference": "review",
        "amount": {"principal_cents": 334, "selic_cents": 37},
    })
    data = {
        "terms": _case(command).model_dump(), "action": "approve", "expected_version": 2,
        "request_id": "approve", "opinion_reference": "review",
        "professional_reference": "accountant", "evidence_reference": "approval",
    }
    assert plan("transmitted", Event.model_validate(data)) == ("homologated", ())
    with pytest.raises(ValueError, match="unexpected terminal deadline"):
        Event.model_validate(data | {"due_on": TODAY.isoformat()})
    data["terms"] = _case(command, kind="restitution").model_dump()
    with pytest.raises(ValueError, match="follow-up deadline required"):
        Event.model_validate(data)
    assert plan("transmitted", Event.model_validate(data | {"due_on": TODAY.isoformat()})) == (
        "granted", (),
    )


def test_postgres_capacity_preserves_replay_and_report(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    monkeypatch.setattr(lifecycle, "MAX_CASES", 2)
    monkeypatch.setattr(lifecycle, "MAX_CASE_SCAN_EVENTS", 3)
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    _run(service, token, csrf, scope, cmd, terms, 1, "cancel")
    second = _case(cmd, case_id="d" * 64)
    _run(service, token, csrf, scope, cmd, second, 0, "request")
    before = service.read(token, csrf, scope.unit_id, MONTH)
    third = _case(cmd, case_id="e" * 64)
    with pytest.raises(FiscalValidationError, match="case count exceeds bound"):
        _run(service, token, csrf, scope, cmd, third, 0, "request")
    with pytest.raises(FiscalValidationError, match="case scan exceeds event bound"):
        _run(service, token, csrf, scope, cmd, second, 1, "reject")
    assert _run(service, token, csrf, scope, cmd, second, 0, "request")["replay"] is True
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


def test_postgres_ledger_scan_capacity_before_posting(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    monkeypatch.setattr(lifecycle, "MAX_SCAN_EVENTS", 2)
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    before = service.read(token, csrf, scope.unit_id, MONTH)
    with pytest.raises(FiscalValidationError, match="case reconciliation event bound"):
        _run(service, token, csrf, scope, cmd, terms, 1, "cancel")
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


def test_postgres_restitution_revaluation_and_denial(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping, kind="restitution")
    service, token, csrf = _session(db, scope)
    for version, action in enumerate(("request", "transmit", "approve")):
        _run(service, token, csrf, scope, cmd, terms, version, action)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    assert before["cases"][0]["status"] == "granted"
    assert before["cases"][0]["alert"]["severity"] == "due_soon"
    account = service.identity.authenticate_session(session_token=token, now=NOW).account
    following_month = NOW.replace(day=28) + timedelta(days=4)
    following_month = following_month.replace(day=1)
    service.clock = lambda: following_month
    renewed = service.identity.issue_session(account, now=following_month)
    token, csrf = renewed.session_token, renewed.csrf_token
    with pytest.raises(FiscalValidationError, match="restitution settlement requires revaluation"):
        _run(service, token, csrf, scope, cmd, terms, 3, "pay")
    after = service.read(token, csrf, scope.unit_id, MONTH)
    assert after["cases"][0]["status"] == "granted"
    assert after["cases"][0]["version"] == 3
    assert after["ledger"] == before["ledger"]
    assert _run(service, token, csrf, scope, cmd, terms, 3, "deny")["status"] == "denied"
    after = service.read(token, csrf, scope.unit_id, MONTH)
    assert after["ledger"]["by_tax"]["pis"]["reserved"] == cmd.amount.model_dump()


def test_postgres_standalone_encumbrance_not_adopted(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    reserve = Command.model_validate(cmd.model_dump() | {
        "expected_version": 1, "request_id": "standalone-reserve", "movement": "reserved",
    })
    with db.economy(scope) as store:
        _write(store, scope, proof, context, reserve)
    service, token, csrf = _session(db, scope)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    with pytest.raises(FiscalValidationError, match="standalone T18 encumbrance"):
        _run(service, token, csrf, scope, cmd, terms, 0, "request")
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


def test_postgres_duplicate_target_and_past_deadline(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    with pytest.raises(FiscalValidationError, match="follow-up date is in the past"):
        _run(service, token, csrf, scope, cmd, terms, 0, "request",
             due_on=(TODAY - timedelta(days=1)).isoformat())
    assert service.read(token, csrf, scope.unit_id, MONTH)["cases"] == []
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    duplicate = _case(cmd, case_id="d" * 64, target_reference=terms.target_reference)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    with pytest.raises(FiscalValidationError, match="case target already in use"):
        _run(service, token, csrf, scope, cmd, duplicate, 0, "request")
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


def test_postgres_historical_read_after_environment_disabled(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    # Simulate a later canonical configuration change in the disposable DB.
    with db.connection() as conn:
        conn.execute(
            "UPDATE fm_control_plane_units SET enabled_environments_json=? "
            "WHERE tenant_id=? AND unit_id=?",
            (json.dumps(["production"]), scope.tenant_id, scope.unit_id),
        )
    before = service.read(token, csrf, scope.unit_id, MONTH)
    assert before["cases"][0]["status"] == "requested"
    with pytest.raises(FiscalValidationError, match="active canonical credit unit"):
        _run(service, token, csrf, scope, cmd, terms, 1, "cancel")
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


@pytest.mark.parametrize("template", [
    "T19-{case}-1-1", "t19-{case}", "t19-{case}-01-1", "t19-{case}-0-1",
    "t19-{case}-101-1", "t19-{case}-1-0", "t19-{case}-1-3", "t19-{case}-1-01",
    "t19-{case}-1-2", "t19-{case}-", "t19-{case}-1", "t19-{case}-1-",
    "t19-{case}-999-1", "t19-{case}-2-3", "t19-{case}-2-1\n",
    "t19-{case}a-1-1", "t19-{case}-١-1", "t19-{case}-2-١",
    "t19-", "T19-", "t19-1-1",
])
def test_invalid_managed_identity(template):
    with pytest.raises(FiscalValidationError, match="invalid T19 managed movement identity"):
        managed_request_identity(template.format(case="a" * 64))


@pytest.mark.parametrize("case", ["A" * 64, "a" * 63, "g" * 64])
def test_invalid_managed_digest(case):
    with pytest.raises(FiscalValidationError, match="invalid T19 managed movement identity"):
        managed_request_identity(f"t19-{case}-1-1")


def test_canonical_managed_identity_and_references():
    case = "a" * 64
    assert managed_request_identity(managed_request_id(case, 100, 2)) == (case, 100, 2)
    assert managed_request_identity("standalone-1") is None
    command = Command.model_validate({
        "competence": MONTH.isoformat(), "finding_id": "b" * 64, "tax": "pis",
        "recovery_version": 1, "recovery_digest": "c" * 64, "expected_version": 1,
        "request_id": managed_request_id(case, 2, 1), "movement": "released",
        "review_reference": "review", "reservation_id": managed_request_id("d" * 64, 1, 1),
        "amount": {"principal_cents": 334, "selic_cents": 37},
    })
    with pytest.raises(FiscalValidationError, match="invalid T19 managed movement reference"):
        validate_managed_command(command)


@pytest.mark.parametrize(("request_suffix", "movement", "reservation", "compensation", "valid"), [
    ("1-1", "reserved", None, None, True),
    ("2-1", "compensated", "1-1", None, True),
    ("3-1", "compensation_reversed", None, "2-1", True),
    ("4-1", "released", "1-1", None, True),
    ("4-2", "reversed", None, None, True),
    ("4-1", "restituted", "1-1", None, True),
    ("5-1", "restitution_reversed", None, "4-1", True),
    ("1-1", "identified", None, None, False),
    ("2-1", "reserved", None, None, False),
    ("1-1", "released", "1-1", None, False),
    ("4-1", "reversed", None, None, False),
    ("4-2", "released", "1-1", None, False),
    ("2-1", "released", "other-case", None, False),
    ("3-1", "compensation_reversed", None, "other-case", False),
    ("3-1", "compensation_reversed", None, "4-1", False),
    ("3-1", "compensation_reversed", None, "3-1", False),
    ("3-1", "compensation_reversed", None, "1-1", False),
    ("3-1", "compensation_reversed", None, "2-2", False),
    ("3-1", "released", "2-1", None, False),
    ("standalone", "released", "1-1", None, False),
    ("2-1", "released", "standalone", None, False),
    ("standalone", "restituted", "standalone", None, False),
    ("standalone", "restitution_reversed", None, "standalone", False),
    ("standalone", "released", "malformed", None, False),
    ("2-1", "released", "malformed", None, False),
])
def test_managed_command_matrix(request_suffix, movement, reservation, compensation, valid):
    case = "a" * 64

    def resolve(value):
        if value is None or value == "standalone":
            return value
        if value == "other-case":
            return managed_request_id("b" * 64, 1, 1)
        if value == "malformed":
            return f"T19-{case}-1-1"
        return f"t19-{case}-{value}"

    command = Command.model_validate({
        "competence": MONTH.isoformat(), "finding_id": "b" * 64, "tax": "pis",
        "recovery_version": 1, "recovery_digest": "c" * 64, "expected_version": 1,
        "request_id": resolve(request_suffix), "movement": movement, "review_reference": "review",
        "reservation_id": resolve(reservation), "compensation_id": resolve(compensation),
        "amount": {"principal_cents": 334, "selic_cents": 37},
    })
    if valid:
        assert validate_managed_command(command) == managed_request_identity(command.request_id)
    else:
        with pytest.raises(FiscalValidationError, match="T19 managed"):
            validate_managed_command(command)


@pytest.mark.parametrize("template", [
    "T19-{case}-1-1", "t19-{case}", "t19-{case}-01-1",
    "t19-{case}-101-1", "t19-{case}-1-3",
])
def test_postgres_invalid_managed_writer_and_forged_history(economy_database, mapping, template):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    forged = Command.model_validate(cmd.model_dump() | {
        "expected_version": 1, "request_id": template.format(case=terms.case_id),
        "movement": "reserved",
    })
    key = ledger.journal_id(BUYER, cmd.finding_id)
    with db.economy(scope) as store:
        before = history(store, BUYER, MONTH, cmd.finding_id)
        with pytest.raises(FiscalValidationError, match="invalid T19 managed movement identity"):
            ledger._post_movement(
                store, BUYER, _reviewed(scope, forged), context=context,
                as_of=TODAY, unit=proof, managed=True,
            )
        assert history(store, BUYER, MONTH, cmd.finding_id) == before
        # Bypass only the application writer to simulate valid-hash corrupt persistence.
        state, rows = ledger._replay(store, BUYER, MONTH, key)
        content = dict(rows[-1]["content"])
        content.update({
            "event_version": 2, "previous_digest": rows[-1]["digest"],
            "reviewed": _reviewed(scope, forged).model_dump(),
            "postings": transition(state, forged), "balances": state.projection(),
        })
        store.append_snapshot(record_id=key, version=2, competence=MONTH,
                              issuer=BUYER, content=content)
    with db.economy(scope) as store:
        for operation in (
            lambda: report(store, BUYER, TODAY),
            lambda: reconcile(store, BUYER),
            lambda: reconcile(store, BUYER, MONTH),
            lambda: history(store, BUYER, MONTH, cmd.finding_id),
        ):
            with pytest.raises(
                FiscalValidationError, match="invalid T19 managed movement identity",
            ):
                operation()


def test_postgres_canonical_managed_orphan_rejected(economy_database, mapping):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    forged = Command.model_validate(cmd.model_dump() | {
        "expected_version": 1, "request_id": managed_request_id(terms.case_id, 1, 1),
        "movement": "reserved",
    })
    with db.economy(scope) as store:
        ledger._post_movement(
            store, BUYER, _reviewed(scope, forged), context=context,
            as_of=TODAY, unit=proof, managed=True,
        )
    with db.economy(scope) as store:
        for operation in (
            lambda: report(store, BUYER, TODAY),
            lambda: reconcile(store, BUYER),
            lambda: reconcile(store, BUYER, MONTH),
            lambda: history(store, BUYER, MONTH, cmd.finding_id),
        ):
            with pytest.raises(FiscalValidationError, match="orphan recovery case ledger"):
                operation()


def _multiple_lots(db, mapping, claims):
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    commands = _federal_seed(db, scope, MONTH, [("pis", cents) for cents in claims])
    with db.economy(scope) as store:
        for command in commands:
            _write(store, scope, proof, context, command)
    return scope, commands, context, proof


def _partial_case(store, command, case_id):
    source = ledger._historical_source(store, BUYER, MONTH, command)
    valuation = federal_interest(10, date.fromisoformat(source.anchor), TODAY)
    assert valuation is not None
    return _case(command, case_id=case_id, amount={
        "principal_cents": 10, "selic_cents": valuation[0],
    })


def _orphan(store, scope, command, terms, context, proof):
    key = ledger.journal_id(BUYER, command.finding_id)
    _, rows = ledger._replay(store, BUYER, MONTH, key)
    forged = Command.model_validate(command.model_dump() | {
        "expected_version": len(rows), "request_id": managed_request_id(terms.case_id, 1, 1),
        "movement": "reserved", "amount": terms.amount.model_dump(),
    })
    # Intentionally bypass only the internal lifecycle caller in this fixture.
    # The journal remains valid, but no corresponding case event is published.
    return ledger._post_movement(
        store, BUYER, _reviewed(scope, forged), context=context,
        as_of=TODAY, unit=proof, managed=True,
    )


def _snapshots(store):
    # The synthetic fixture has far fewer than 500 records. All returned rows
    # are compared, including the immutable case and ledger versions/digests.
    rows = store.records("fm_economy_snapshots", limit=500)
    assert len(rows) < 500
    return sorted(rows, key=lambda row: (row["record_id"], row["version"]))


def test_postgres_orphan_blocks_every_write_and_replay(economy_database, mapping):
    db = economy_database
    scope, commands, context, proof = _multiple_lots(db, mapping, [100, 110, 124])
    first, second, third = commands
    with db.economy(scope) as store:
        orphan = _partial_case(store, first, "a" * 64)
        other = _partial_case(store, first, "b" * 64)
        duplicate = _partial_case(store, second, orphan.case_id)
        existing = _partial_case(store, third, "c" * 64)
    service, token, csrf = _session(db, scope)
    _run(service, token, csrf, scope, third, existing, 0, "request")
    with db.economy(scope) as store:
        _orphan(store, scope, first, orphan, context, proof)
        before = _snapshots(store)
    # All requests are otherwise valid and have adequate unencumbered amounts.
    for cmd, terms, version, action in (
        (first, other, 0, "request"), (second, duplicate, 0, "request"),
        (third, existing, 1, "transmit"), (third, existing, 1, "reject"),
        (third, existing, 0, "request"),
    ):
        with pytest.raises(FiscalValidationError, match="orphan recovery case ledger"):
            _run(service, token, csrf, scope, cmd, terms, version, action)
        with db.economy(scope) as store:
            assert _snapshots(store) == before
    with db.economy(scope) as store:
        # The second lot has no T19 movement: a lot-local guard is not sufficient.
        standalone = Command.model_validate(second.model_dump() | {
            "expected_version": 1, "request_id": "standalone-reserve",
            "movement": "reserved", "amount": other.amount.model_dump(),
        })
        for command in (standalone, second):
            with pytest.raises(FiscalValidationError, match="orphan recovery case ledger"):
                post_movement(store, BUYER, _reviewed(scope, command), context=context,
                              as_of=TODAY, unit=proof)
        assert _snapshots(store) == before
        for command in commands:
            with pytest.raises(FiscalValidationError, match="orphan recovery case ledger"):
                history(store, BUYER, MONTH, command.finding_id)


def _corrupt_managed_link(db, mapping, axis):
    """Persist a valid-hash mismatch, never patch the production verifier."""
    scope, commands, context, proof = _multiple_lots(db, mapping, [150, 184])
    first, second = commands
    with db.economy(scope) as store:
        terms = _partial_case(store, first, "a" * 64)
        other = _partial_case(store, first, "b" * 64)
        other_lot = _partial_case(store, second, terms.case_id)
    service, token, csrf = _session(db, scope)
    if axis == "lot-duplicate":
        _run(service, token, csrf, scope, first, terms, 0, "request")
        with db.economy(scope) as store:
            _orphan(store, scope, second, other_lot, context, proof)
    elif axis == "lot-moved":
        _run(service, token, csrf, scope, first, other, 0, "request")
        with db.economy(scope) as store:
            link = _orphan(store, scope, second, other_lot, context, proof)
            template = store.record("fm_economy_snapshots", case_key(BUYER, other), 1)
            assert template is not None
            content = dict(template["content"])
            content["reviewed"] = _event(scope, first, terms, 0, "request").model_dump()
            content["ledger_links"] = [{"version": link["version"], "digest": link["digest"]}]
            key = case_key(BUYER, terms)
            digest = store.append_snapshot(record_id=key, version=1, competence=MONTH,
                                           issuer=BUYER, content=content)
            assert store.record("fm_economy_snapshots", key, 1)["digest"] == digest
    else:
        _run(service, token, csrf, scope, first, terms, 0, "request")
        _run(service, token, csrf, scope, first, terms, 1, "transmit")
        if axis == "version":
            _run(service, token, csrf, scope, first, other, 0, "request")
        with db.economy(scope) as store:
            key = case_key(BUYER, terms)
            previous = store.record("fm_economy_snapshots", key, 2)
            assert previous is not None
            event = _event(scope, first, terms, 2, "deny")
            lot = ledger.journal_id(BUYER, first.finding_id)
            _, journal = ledger._replay(store, BUYER, MONTH, lot)
            if axis == "version":
                # Existing, strictly increasing version, but another case's posting.
                link = journal[-1]
            else:
                assert axis == "digest"
                # The correct next posting exists; only its event's link is wrong.
                prior = Command.model_validate(journal[-1]["content"]["reviewed"]["command"])
                command = lifecycle._ledger_command(
                    event.event, prior, journal[-1]["version"], 1, "compensation_reversed",
                    managed_request_id(terms.case_id, 2, 1),
                )
                link = ledger._post_movement(
                    store, BUYER, _reviewed(scope, command), context=context,
                    as_of=TODAY, unit=proof, managed=True,
                )
            assert link["version"] > previous["content"]["ledger_links"][-1]["version"]
            content = dict(previous["content"])
            content.update({
                "previous_digest": previous["digest"], "reviewed": event.model_dump(),
                "status": "denied", "ledger_links": [{
                    "version": link["version"],
                    "digest": link["digest"] if axis == "version" else "f" * 64,
                }],
            })
            digest = store.append_snapshot(record_id=key, version=3, competence=MONTH,
                                           issuer=BUYER, content=content)
            assert store.record("fm_economy_snapshots", key, 3)["digest"] == digest
    return scope, first, service, token, csrf


@pytest.mark.parametrize("axis", ["lot-duplicate", "lot-moved", "version", "digest"])
def test_postgres_rejects_exact_managed_link_mismatches(economy_database, mapping, axis):
    db = economy_database
    scope, command, service, token, csrf = _corrupt_managed_link(db, mapping, axis)
    reason = "orphan recovery case ledger|case ledger posting mismatch"
    with db.economy(scope) as store:
        before = _snapshots(store)
        for operation in (
            lambda: report(store, BUYER, TODAY),
            lambda: reconcile(store, BUYER),
            lambda: reconcile(store, BUYER, MONTH),
            lambda: history(store, BUYER, MONTH, command.finding_id),
        ):
            with pytest.raises(FiscalValidationError, match=reason):
                operation()
        assert _snapshots(store) == before
    with pytest.raises(FiscalValidationError, match=reason):
        service.read(token, csrf, scope.unit_id, MONTH)


def test_postgres_cli_real_session_mfa_and_input_gates(
    economy_database, mapping, monkeypatch, tmp_path,
):
    db = economy_database
    db.initialize(enable_mfa=True)
    scope = _setup(db, mapping, BUYER)
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    finding, digest = _seed(db, scope, context, as_of=today)
    cmd = _bound(finding, digest)
    with db.economy(scope) as store:
        _write(store, scope, proof, context, cmd, today)
    terms = _case(cmd, route="administrative")
    reviewed = _event(scope, cmd, terms, 0, "request",
                      due_on=(today + timedelta(days=20)).isoformat())
    payload = tmp_path / "case.json"
    payload.write_text(reviewed.model_dump_json(), encoding="utf-8")
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 65537)
    hasher = ScryptPasswordHasher()
    account = HumanAccount(
        "t19-cli-actor", "t19-cli@example.test", hasher.hash("Synthetic-CLI-Password-123"),
        scope.tenant_id, PortalRole.ACCOUNTANT, frozenset({scope.unit_id}),
    )
    db.human_accounts().save(account)
    identity = HumanIdentityService(
        accounts=db.human_accounts(), sessions=db.web_sessions(), password_hasher=hasher,
    )
    issued = identity.issue_session(account, now=now)
    session = identity.authenticate_session(session_token=issued.session_token, now=now)
    monkeypatch.setenv("NFCORE_HUMAN_MFA", "enabled")
    monkeypatch.setenv("NFCORE_HUMAN_MFA_KEY_BASE64", base64.b64encode(os.urandom(32)).decode())
    mfa = HumanMfaService.from_environ(db.human_mfa)
    assert mfa is not None
    enrollment = mfa.start_enrollment(account, now)
    encoded = enrollment.secret_base32
    secret = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    recovery_codes = mfa.confirm_enrollment(account, totp_at(secret, now), now)
    cli = Path(__file__).parents[1] / "scripts/nfcore_recovery_lifecycle.py"
    args = [sys.executable, str(cli), "--unit", scope.unit_id]
    env = os.environ | {
        "NFCORE_ENVIRONMENT": "test", "DATABASE_URL": db._dsn,
        "NFCORE_T19_SESSION_TOKEN": issued.session_token,
        "NFCORE_T19_CSRF_TOKEN": issued.csrf_token,
    }

    def invoke(arguments, **overrides):
        return subprocess.run(
            [*args, *arguments], env=env | overrides, capture_output=True,
            text=True, check=False, timeout=90,
        )

    for arguments, overrides in (
        (["--post", str(payload)], {"NFCORE_ENVIRONMENT": "production"}),
        (["--post", str(payload)], {"NFCORE_ECONOMY_ENABLED": "false"}),
        (["--post", str(payload)], {"NFCORE_HUMAN_MFA": "disabled"}),
        (["--post", str(payload)], {}),
        (["--post", str(oversized)], {}),
        (["--post", str(payload), "--competence", "2026-02-01"], {}),
        (["--post", str(payload)], {"NFCORE_T19_CSRF_TOKEN": "invalid"}),
    ):
        result = invoke(arguments, **overrides)
        assert result.returncode == 2 and not result.stdout
        assert issued.session_token not in result.stderr
        assert issued.csrf_token not in result.stderr
    result = invoke(["--report", "--competence", MONTH.isoformat()])
    result.check_returncode()
    assert json.loads(result.stdout)["cases"] == []
    mfa.step_up(account, session.session_id, recovery_codes[0], datetime.now(UTC))
    result = invoke(["--post", str(payload)])
    result.check_returncode()
    assert json.loads(result.stdout)["status"] == "requested"
    result = invoke(["--report", "--competence", MONTH.isoformat()])
    result.check_returncode()
    data = json.loads(result.stdout)
    assert data["cases"][0]["status"] == "requested"
    assert data["ledger"]["by_tax"]["icms"]["reserved"] == cmd.amount.model_dump()


@pytest.mark.parametrize("bound", ["MAX_EVENTS", "MAX_SCAN_EVENTS"])
def test_postgres_capacity_preflights_complete_managed_plan(
    economy_database, mapping, monkeypatch, bound,
):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    for version, action in enumerate(("request", "transmit", "deny")):
        _run(service, token, csrf, scope, cmd, terms, version, action)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    assert before["ledger"]["event_count"] == 4
    monkeypatch.setattr(ledger, bound, 5)
    original = lifecycle._post_movement
    attempts = []

    def track(*args, **kwargs):
        attempts.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "_post_movement", track)
    # Invalidate needs two T18 movements; one remaining slot is insufficient.
    with pytest.raises(FiscalValidationError, match="prospective .*event bound"):
        _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")
    assert attempts == []
    assert service.read(token, csrf, scope.unit_id, MONTH) == before
    assert _run(service, token, csrf, scope, cmd, terms, 2, "deny")["replay"] is True
    monkeypatch.setattr(ledger, bound, 6)
    result = _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")
    assert result["status"] == "invalidated" and len(attempts) == 2
    after = service.read(token, csrf, scope.unit_id, MONTH)
    assert after["ledger"]["event_count"] == 6
    assert _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")["replay"] is True
    assert service.read(token, csrf, scope.unit_id, MONTH) == after


def test_postgres_capacity_allows_no_posting_case_event(economy_database, mapping, monkeypatch):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    monkeypatch.setattr(ledger, "MAX_SCAN_EVENTS", 2)
    _run(service, token, csrf, scope, cmd, terms, 0, "request")
    result = _run(service, token, csrf, scope, cmd, terms, 1, "reject")
    assert result["status"] == "requested"
    before = service.read(token, csrf, scope.unit_id, MONTH)
    assert before["ledger"]["event_count"] == 2
    with pytest.raises(FiscalValidationError, match="prospective .*event bound"):
        _run(service, token, csrf, scope, cmd, terms, 2, "transmit")
    assert _run(service, token, csrf, scope, cmd, terms, 1, "reject")["replay"] is True
    assert service.read(token, csrf, scope.unit_id, MONTH) == before


def test_postgres_capacity_rollback_of_second_managed_posting(
    economy_database, mapping, monkeypatch,
):
    db = economy_database
    scope, cmd, terms = _fixture(db, mapping)
    service, token, csrf = _session(db, scope)
    for version, action in enumerate(("request", "transmit", "deny")):
        _run(service, token, csrf, scope, cmd, terms, version, action)
    monkeypatch.setattr(ledger, "MAX_SCAN_EVENTS", 6)
    before = service.read(token, csrf, scope.unit_id, MONTH)
    original = EconomyStore.append_snapshot

    def fail(self, **kwargs):
        if kwargs["record_id"].startswith("credit-ledger-") and kwargs["version"] == 6:
            raise RuntimeError("induced second posting failure")
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(EconomyStore, "append_snapshot", fail)
        with pytest.raises(RuntimeError, match="second posting"):
            _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")
    assert service.read(token, csrf, scope.unit_id, MONTH) == before
    result = _run(service, token, csrf, scope, cmd, terms, 3, "invalidate")
    assert result["status"] == "invalidated"
    assert service.read(token, csrf, scope.unit_id, MONTH)["ledger"]["event_count"] == 6


@pytest.mark.parametrize(
    "principal,first_principal,residual,error",
    [
        (334, 1, 1, "SELIC residual requires revised partition"),
        (10, 5, -1, "negative ledger component: SELIC"),
        (334, 100, 0, None),
    ],
)
def test_postgres_selic_residual_is_visible_and_final_reserve_is_atomic(
    economy_database, mapping, principal, first_principal, residual, error,
):
    db = economy_database
    scope = _setup(db, mapping, BUYER)
    _, context = historical_issuer_context(db, scope, MONTH)
    proof = verify_credit_unit(db, scope, BUYER)
    command, = _federal_seed(db, scope, MONTH, [("pis", principal)])
    with db.economy(scope) as store:
        _write(store, scope, proof, context, command)
        origin = ledger._historical_source(store, BUYER, MONTH, command)
    anchor = date.fromisoformat(origin.anchor)

    def terms_for(part, case_id):
        projected = federal_interest(part, anchor, TODAY)
        assert projected is not None
        return _case(command, case_id=case_id, amount={
            "principal_cents": part, "selic_cents": projected[0],
        })

    service, token, csrf = _session(db, scope)
    first = terms_for(first_principal, "a" * 64)
    last = terms_for(principal - first_principal, "b" * 64)
    _run(service, token, csrf, scope, command, first, 0, "request")
    before = service.read(token, csrf, scope.unit_id, MONTH)
    diagnostic, = before["selic_reconciliation"]
    assert diagnostic["signed_residual_cents"] == residual
    assert diagnostic["source_digest"] == command.recovery_digest
    assert diagnostic["has_managed_movements"] is True
    assert diagnostic["status"] == ("balanced" if residual == 0 else "valuation_difference")
    if error is not None:
        with pytest.raises(FiscalValidationError, match=error):
            _run(service, token, csrf, scope, command, last, 0, "request")
        assert service.read(token, csrf, scope.unit_id, MONTH) == before
        assert _run(service, token, csrf, scope, command, first, 0, "request")["replay"]
        assert service.read(token, csrf, scope.unit_id, MONTH) == before
        _run(service, token, csrf, scope, command, first, 1, "cancel")
        restored = service.read(token, csrf, scope.unit_id, MONTH)
        assert restored["selic_reconciliation"][0]["status"] == "balanced"
        whole = terms_for(principal, "c" * 64)
        _run(service, token, csrf, scope, command, whole, 0, "request")
    else:
        _run(service, token, csrf, scope, command, last, 0, "request")
    after = service.read(token, csrf, scope.unit_id, MONTH)
    diagnostic, = after["selic_reconciliation"]
    assert diagnostic["available_principal_cents"] == 0
    assert diagnostic["available_selic_cents"] == 0
    assert diagnostic["status"] == "balanced"
    balance = after["ledger"]["by_tax"]["pis"]
    assert balance["reserved"] == command.amount.model_dump()


def test_postgres_standalone_residual_uses_persisted_memory_and_is_scope_local(
    economy_database, mapping, monkeypatch,
):
    db = economy_database
    scope, command, _ = _fixture(db, mapping)
    with db.economy(scope) as store:
        before = report(store, BUYER, TODAY)
    diagnostic, = before["selic_reconciliation"]
    assert diagnostic["status"] == "balanced"
    assert diagnostic["expected_selic_cents"] == command.amount.selic_cents
    assert diagnostic["has_managed_movements"] is False
    monkeypatch.setattr("kordena_fiscal.tax.tax_recovery.monthly_selic", lambda: {})
    with db.economy(scope) as store:
        assert report(store, BUYER, TODAY) == before
    with db.economy(replace(scope, tenant_id="other-tenant")) as store:
        assert report(store, BUYER, TODAY)["selic_reconciliation"] == []
