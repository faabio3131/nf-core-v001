"""T19 case service, using T18 as its sole monetary authority.

All provider outcomes are explicit sandbox events. No network, fiscal
transmission, bank settlement or recognition of a real tax credit occurs here.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.errors import LockNotAvailable

from kordena_fiscal.application.credit_ledger import (
    ReviewedMovement,
    _guard_existing_lots,
    _historical_source,
    _post_movement,
    _replay,
    _verified_source,
    journal_id,
    reconcile,
)
from kordena_fiscal.application.unused_credits import VerifiedCreditUnit, verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanIdentityService,
    PortalPermission,
    PortalRole,
)
from kordena_fiscal.tax.credit_ledger import (
    MAX_EVENTS,
    MAX_LOTS,
    MAX_SCAN_EVENTS,
    Command,
    Movement,
)
from kordena_fiscal.tax.historical_audit import IssuerContext, Strict, closed_months
from kordena_fiscal.tax.recovery_lifecycle import (
    MAX_CASE_EVENTS,
    MAX_CASE_SCAN_EVENTS,
    MAX_CASES,
    SCHEMA,
    Event,
    Status,
    Terms,
    alert,
    plan,
)
from kordena_fiscal.tax.tax_recovery import federal_interest
from kordena_fiscal.tax.unused_credits import Evidence, _unique_fields

LOCAL = ZoneInfo("America/Sao_Paulo")
TABLE = "fm_economy_snapshots"


class ReviewedEvent(Strict):
    event: Event
    evidence: Evidence

    def verify(self, scope: tuple[str, ...], issuer: Cnpj) -> None:
        raw = self.evidence.contents()
        if len(raw) > 16384:
            raise FiscalValidationError("case evidence exceeds 16 KiB")
        try:
            observed = json.loads(raw, object_pairs_hook=_unique_fields)
        except (UnicodeError, ValueError) as exc:
            raise FiscalValidationError("invalid case evidence") from exc
        expected = {
            "scope": list(scope),
            "issuer_cnpj": issuer.value,
            "simulation_only": True,
            "event": self.event.model_dump(),
        }
        if json.dumps(observed, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise FiscalValidationError("case evidence differs from reviewed event")


def case_key(issuer: Cnpj, terms: Terms) -> str:
    return f"recovery-case-{issuer.value}-{terms.case_id}"


def _request(terms: Terms, version: int, index: int) -> str:
    return f"t19-{terms.case_id}-{version}-{index}"


def _reviewed(scope: tuple[str, ...], issuer: Cnpj, command: Command) -> ReviewedMovement:
    data = json.dumps({
        "scope": list(scope),
        "issuer_cnpj": issuer.value,
        "simulation_only": True,
        "command": command.model_dump(),
    }, sort_keys=True).encode()
    return ReviewedMovement.model_validate({
        "command": command.model_dump(),
        "review": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "data_b64": base64.b64encode(data).decode(),
        },
    })


def _scope(store: EconomyStore) -> tuple[str, ...]:
    scope = store.scope_identity
    if scope[0] != "fm-nfcore" or scope[-1] != "homologation":
        raise FiscalValidationError("recovery lifecycle requires canonical homologation")
    return scope


def _ledger_command(
    event: Event,
    previous: Command,
    version: int,
    index: int,
    movement: Movement,
    settlement: str | None,
) -> Command:
    terms = event.terms
    source = movement in {"reserved", "compensated"}
    return Command.model_validate({
        "competence": terms.competence,
        "finding_id": terms.finding_id,
        "tax": terms.tax,
        "amount": terms.amount.model_dump(),
        "request_id": _request(terms, event.expected_version + 1, index),
        "expected_version": version,
        "review_reference": event.opinion_reference,
        "movement": movement,
        "recovery_version": event.source_version if source else previous.recovery_version,
        "recovery_digest": event.source_digest if source else previous.recovery_digest,
        "reservation_id": _request(terms, 1, 1) if movement in {
            "released", "compensated", "restituted",
        } else None,
        "compensation_id": settlement if movement in {
            "compensation_reversed", "restitution_reversed",
        } else None,
    })


def _case_history(
    store: EconomyStore, issuer: Cnpj, key: str,
) -> tuple[list[dict[str, Any]], Status | None, str | None]:
    """Validate the event chain against exact, independently replayed ledger versions."""
    scope = _scope(store)
    rows = store.recovery_case_rows(key, limit=MAX_CASE_EVENTS + 1)
    if len(rows) > MAX_CASE_EVENTS:
        raise FiscalValidationError("case history exceeds supported bound")
    if not rows:
        return [], None, None
    try:
        first = ReviewedEvent.model_validate(rows[0]["content"]["reviewed"]).event
        terms = first.terms
        period = date.fromisoformat(terms.competence)
        lot = journal_id(issuer, terms.finding_id)
        _, journal = _replay(store, issuer, period, lot)
        if not journal:
            raise FiscalValidationError("case ledger missing")
        by_version = {row["version"]: row for row in journal}
        initial = Command.model_validate(journal[0]["content"]["reviewed"]["command"])
        origin = _historical_source(store, issuer, period, initial)
        status: Status | None = None
        settlement: str | None = None
        previous_digest: str | None = None
        last_day: date | None = None
        seen: set[str] = set()
        seen_evidence: set[str] = set()
        linked: set[str] = set()
        last_ledger_version = 0
        for version, row in enumerate(rows, 1):
            content = row["content"]
            reviewed = ReviewedEvent.model_validate(content["reviewed"])
            reviewed.verify(scope, issuer)
            event = reviewed.event
            day = date.fromisoformat(content["as_of"])
            closed_months(period, day)
            expected_status, movements = plan(status, event)
            if (
                row["record_id"] != key or case_key(issuer, terms) != key
                or row["version"] != version or event.expected_version != version - 1
                or row["issuer_cnpj"] != issuer.value or row["competence"] != terms.competence
                or event.terms != terms or event.request_id in seen
                or event.evidence_reference in seen_evidence
                or content["schema_version"] != SCHEMA
                or content["previous_digest"] != previous_digest
                or content["scope"] != list(scope) or content["issuer_cnpj"] != issuer.value
                or content["status"] != expected_status
                or content["simulation_only"] is not True
                or content["credit_recognized"] is not False
                or content["realized_cents"] is not None
                or content["actor_role"] != "accountant"
                or not isinstance(content["actor_id"], str) or not content["actor_id"]
                or not isinstance(content["profile_context"], dict)
                or (last_day is not None and day < last_day)
                or len(content["ledger_links"]) != len(movements)
            ):
                raise FiscalValidationError("recovery case history integrity mismatch")
            if event.source_version is not None:
                source_command = Command.model_validate(initial.model_dump() | {
                    "recovery_version": event.source_version,
                    "recovery_digest": event.source_digest,
                })
                source = _historical_source(store, issuer, period, source_command)
                if (
                    source.amount != origin.amount
                    or source.fiscal_identity != origin.fiscal_identity
                    or source.as_of != day.isoformat()
                ):
                    raise FiscalValidationError("historical case source or cutoff changed")
                _validate_amount(source.modality, source.anchor, terms, day)
            if event.action == "pay":
                _validate_amount(origin.modality, origin.anchor, terms, day)
            for index, (movement, link) in enumerate(
                zip(movements, content["ledger_links"], strict=True), 1
            ):
                ledger_version = link["version"]
                actual = by_version.get(ledger_version)
                prior = by_version.get(ledger_version - 1)
                if actual is None or prior is None or ledger_version <= last_ledger_version:
                    raise FiscalValidationError("case ledger version missing or out of order")
                previous = Command.model_validate(prior["content"]["reviewed"]["command"])
                command = _ledger_command(
                    event, previous, ledger_version - 1, index, movement, settlement
                )
                if (
                    link != {"version": ledger_version, "digest": actual["digest"]}
                    or command.model_dump() != actual["content"]["reviewed"]["command"]
                    or actual["content"]["as_of"] != day.isoformat()
                ):
                    raise FiscalValidationError("case ledger posting mismatch")
                linked.add(command.request_id)
                last_ledger_version = ledger_version
                if movement in {"compensated", "restituted"}:
                    settlement = command.request_id
            seen.add(event.request_id)
            seen_evidence.add(event.evidence_reference)
            status = expected_status
            previous_digest = row["digest"]
            last_day = day
        actual_ids = {
            row["content"]["reviewed"]["command"]["request_id"]
            for row in journal
            if row["content"]["reviewed"]["command"]["request_id"].startswith(
                f"t19-{terms.case_id}-"
            )
        }
        if actual_ids != linked:
            raise FiscalValidationError("orphan case ledger movement")
        return rows, status, settlement
    except (KeyError, TypeError, ValueError) as exc:
        raise FiscalValidationError("invalid recovery case history") from exc


def _all_cases(
    store: EconomyStore, issuer: Cnpj,
) -> list[tuple[list[dict[str, Any]], Status]]:
    ids = store.recovery_case_ids(issuer, limit=MAX_CASES + 1)
    if len(ids) > MAX_CASES:
        raise FiscalValidationError("recovery case count exceeds bound")
    result = []
    events = 0
    for key, _ in ids:
        rows, status, _ = _case_history(store, issuer, key)
        if not rows or status is None:
            raise FiscalValidationError("case history missing")
        events += len(rows)
        if events > MAX_CASE_SCAN_EVENTS:
            raise FiscalValidationError("recovery case scan exceeds event bound")
        result.append((rows, status))
    return result


def _validate_amount(modality: str, anchor: str, terms: Terms, day: date) -> None:
    if modality == "federal_undue_payment":
        projected = federal_interest(terms.amount.principal_cents, date.fromisoformat(anchor), day)
        if projected is None or terms.amount.selic_cents != projected[0]:
            raise FiscalValidationError("case principal and SELIC differ from T17 valuation")
    elif terms.amount.selic_cents != 0 or terms.route == "perdcomp":
        raise FiscalValidationError("unsupported local recovery valuation or route")


def _validate_current(
    store: EconomyStore, issuer: Cnpj, period: date, event: Event,
    context: IssuerContext, day: date, history: list[dict[str, Any]],
) -> None:
    if event.source_version is None or event.source_digest is None:
        raise FiscalValidationError("current recovery source required")
    initial = Command.model_validate(history[0]["content"]["reviewed"]["command"])
    bound = Command.model_validate(initial.model_dump() | {
        "recovery_version": event.source_version, "recovery_digest": event.source_digest,
    })
    source, findings = _verified_source(store, issuer, period, bound, context, day)
    original = _historical_source(store, issuer, period, initial)
    if source.amount != original.amount or source.fiscal_identity != original.fiscal_identity:
        raise FiscalValidationError("case source valuation or fiscal identity changed")
    _validate_amount(source.modality, source.anchor, event.terms, day)
    _guard_existing_lots(store, issuer, period, bound, source, findings)


def _apply(
    store: EconomyStore, issuer: Cnpj, reviewed: ReviewedEvent,
    context: IssuerContext, day: date, unit: VerifiedCreditUnit, actor_id: str,
    active_profile: dict[str, Any],
) -> dict[str, Any]:
    scope = _scope(store)
    unit.require(scope, issuer)
    reviewed.verify(scope, issuer)
    event, terms = reviewed.event, reviewed.event.terms
    period = date.fromisoformat(terms.competence)
    closed_months(period, day)
    key = case_key(issuer, terms)
    store.lock_accounting_issuance()
    with store.atomic_recovery_case():
        rows, status, settlement = _case_history(store, issuer, key)
        for row in rows:
            old = row["content"]["reviewed"]
            if old["event"]["request_id"] == event.request_id:
                if old != reviewed.model_dump() or row["content"]["actor_id"] != actor_id:
                    raise FiscalValidationError("case request identity conflict")
                return {
                    "version": row["version"], "digest": row["digest"], "replay": True,
                    "status": row["content"]["status"], "current_status": status,
                    "current_version": len(rows), "simulation_only": True,
                }
        if len(rows) != event.expected_version or len(rows) >= MAX_CASE_EVENTS:
            raise FiscalValidationError("case optimistic version conflict")
        if rows:
            initial = ReviewedEvent.model_validate(rows[0]["content"]["reviewed"]).event
            if initial.terms != terms or day < date.fromisoformat(rows[-1]["content"]["as_of"]):
                raise FiscalValidationError("case terms or temporal order changed")
        next_status, movements = plan(status, event)
        if event.due_on is not None and date.fromisoformat(event.due_on) < day:
            raise FiscalValidationError("new follow-up date is in the past")
        for other, other_status in _all_cases(store, issuer):
            previous = ReviewedEvent.model_validate(other[0]["content"]["reviewed"]).event
            for row in other:
                old_event = row["content"]["reviewed"]["event"]
                if old_event["evidence_reference"] == event.evidence_reference:
                    raise FiscalValidationError("case provider evidence already used")
            if previous.terms.case_id != terms.case_id and event.action == "request":
                if (
                    previous.terms.target_reference == terms.target_reference
                    and other_status not in {"cancelled", "released", "invalidated"}
                ):
                    raise FiscalValidationError("case target already in use")
        state, journal = _replay(store, issuer, period, journal_id(issuer, terms.finding_id))
        if not journal:
            raise FiscalValidationError("identified T18 lot required")
        first = Command.model_validate(journal[0]["content"]["reviewed"]["command"])
        if first.tax != terms.tax:
            raise FiscalValidationError("case tax differs from journal")
        # Do not transfer pre-existing standalone T18 reservations into a T19 case.
        if event.action == "request" and (
            any(a.total for k, a in state.reservations.items() if not k.startswith("t19-"))
            or any(
                not v.reversed and not k.startswith("t19-")
                for k, v in state.compensations.items()
            )
        ):
            raise FiscalValidationError("standalone T18 encumbrance requires reconciliation")
        if event.action in {"request", "transmit", "release"}:
            _validate_current(store, issuer, period, event, context, day, journal)
        if event.action == "pay":
            # A deferment is not a payment; recompute the fixed lot at simulated
            # settlement date. Changed valuation must not be silently realized.
            origin = _historical_source(store, issuer, period, first)
            if origin.modality == "federal_undue_payment":
                valuation = federal_interest(
                    terms.amount.principal_cents, date.fromisoformat(origin.anchor), day,
                )
                if valuation is None or valuation[0] != terms.amount.selic_cents:
                    raise FiscalValidationError("restitution settlement requires revaluation")
        links = []
        for index, movement in enumerate(movements, 1):
            last_row = journal[-1]
            previous_command = Command.model_validate(last_row["content"]["reviewed"]["command"])
            command = _ledger_command(event, previous_command, last_row["version"], index,
                                      movement, settlement)
            result = _post_movement(
                store, issuer, _reviewed(scope, issuer, command), context=context,
                as_of=day, unit=unit, managed=True,
            )
            if result["replay"]:
                raise FiscalValidationError("case posting already exists without matching event")
            links.append({"version": result["version"], "digest": result["digest"]})
            _, journal = _replay(store, issuer, period, journal_id(issuer, terms.finding_id))
        version = len(rows) + 1
        digest = store.append_snapshot(
            record_id=key, version=version, competence=period, issuer=issuer,
            content={
                "schema_version": SCHEMA, "previous_digest": rows[-1]["digest"] if rows else None,
                "scope": list(scope), "issuer_cnpj": issuer.value, "as_of": day.isoformat(),
                "reviewed": reviewed.model_dump(), "status": next_status,
                "actor_id": actor_id, "actor_role": "accountant",
                "profile_context": {"historical": context.model_dump(), "active": active_profile},
                "ledger_links": links, "simulation_only": True,
                "credit_recognized": False, "realized_cents": None,
            },
        )
        _case_history(store, issuer, key)
        return {
            "version": version, "digest": digest, "replay": False,
            "status": next_status, "current_status": next_status,
            "current_version": version, "simulation_only": True,
        }


def report(store: EconomyStore, issuer: Cnpj, today: date) -> dict[str, Any]:
    """Case and ledger reconciliation, with explicit overdue/follow-up alerts."""
    _scope(store)
    store.lock_accounting_issuance()
    cases = []
    known: dict[str, str] = {}
    for rows, status in _all_cases(store, issuer):
        last = ReviewedEvent.model_validate(rows[-1]["content"]["reviewed"]).event
        known[last.terms.case_id] = journal_id(issuer, last.terms.finding_id)
        cases.append({
            "terms": last.terms.model_dump(), "status": status, "version": len(rows),
            "digest": rows[-1]["digest"], "alert": alert(status, last.due_on, today),
            "events": rows,
        })
    ids = store.credit_journal_ids(issuer, None, limit=MAX_LOTS + 1)
    if len(ids) > MAX_LOTS:
        raise FiscalValidationError("case reconciliation lot bound exceeded")
    scanned = 0
    for key, period in ids:
        _, journal = _replay(store, issuer, date.fromisoformat(period), key)
        scanned += len(journal)
        if scanned > MAX_SCAN_EVENTS or len(journal) > MAX_EVENTS:
            raise FiscalValidationError("case reconciliation event bound exceeded")
        for row in journal:
            request = row["content"]["reviewed"]["command"]["request_id"]
            if request.startswith("t19-") and known.get(request.split("-")[1]) != key:
                raise FiscalValidationError("orphan recovery case ledger")
    return {
        "cases": cases, "ledger": reconcile(store, issuer),
        "simulation_only": True, "credit_recognized": False, "realized_cents": None,
    }


@contextmanager
def _canonical_guard(db: PostgresFiscalDatabase) -> Iterator[None]:
    """Keep the canonical identity/configuration rows and insertion predicates stable.

    SHARE locks cover updates AND inserts, including a second unit with the same
    CNPJ. Non-production only; NOWAIT fails closed rather than waiting on writers.
    Hold the guard until the restricted economy transaction commits.
    """
    with db.connection() as guard:
        try:
            guard.execute(
                "LOCK TABLE fm_control_plane_units, fm_control_plane_fiscal_profiles, "
                "fm_configuration_commands IN SHARE MODE NOWAIT"
            )
        except LockNotAvailable as exc:
            raise FiscalValidationError("canonical credit authority is changing") from exc
        yield


class RecoveryCaseService:
    """Trusted server boundary. Clients cannot supply issuer, role or profile proofs.

    Identity, step-up verifier and clock are injected by the server composition,
    not by request JSON. Tests use synthetic sessions and a deterministic clock.
    """

    def __init__(
        self, db: PostgresFiscalDatabase, identity: HumanIdentityService,
        step_up: Callable[[str, datetime], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db, self.identity, self.step_up, self.clock = db, identity, step_up, clock

    def _authority(
        self, token: str, csrf: str, unit_id: str, *, write: bool, now: datetime,
    ) -> AuthenticatedHuman:
        human = self.identity.authenticate_session(session_token=token, now=now)
        self.identity.assert_csrf(human, csrf)
        human.assert_permission(PortalPermission.AUDIT_READ, unit_id=unit_id)
        if write and (
            human.account.role is not PortalRole.ACCOUNTANT
            or human.account.unit_ids is None or unit_id not in human.account.unit_ids
            or not self.step_up(human.session_id, now)
        ):
            raise FiscalValidationError("designated accountant and recent MFA required")
        return human

    def execute(
        self, token: str, csrf: str, unit_id: str, reviewed: ReviewedEvent,
    ) -> dict[str, Any]:
        now = self.clock()
        human = self._authority(token, csrf, unit_id, write=True, now=now)
        scope = ExecutionScope(
            human.tenant_id, unit_id, FiscalEnvironment.HOMOLOGATION, "t19-case", "fm-nfcore",
        )
        period = date.fromisoformat(reviewed.event.terms.competence)
        host_namespace = scope.host_namespace
        if host_namespace is None:
            raise FiscalValidationError("canonical host namespace required")
        with _canonical_guard(self.db):
            issuer, context = historical_issuer_context(self.db, scope, period)
            with self.db() as uow:
                unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
                active = uow.control_plane.resolve_profile(
                    host_namespace=host_namespace, tenant_id=scope.tenant_id,
                    unit_id=scope.unit_id, environment=scope.environment, instant=now,
                )
            if (
                unit is None or scope.environment not in unit.enabled_environments
                or active is None or active.cnpj != issuer
                or active.scope.identity_material != scope.identity_material
            ):
                raise FiscalValidationError("active canonical credit unit required")
            proof = verify_credit_unit(self.db, scope, issuer)
            with self.db.economy(scope) as store:
                current = self._authority(token, csrf, unit_id, write=True, now=self.clock())
                if current.account != human.account or current.session_id != human.session_id:
                    raise FiscalValidationError("accounting authority changed")
                return _apply(
                    store, issuer, reviewed, context, now.astimezone(LOCAL).date(),
                    proof, human.account.account_id,
                    {"profile_id": active.profile_id, "version": active.version},
                )

    def read(
        self, token: str, csrf: str, unit_id: str, historical_period: date,
    ) -> dict[str, Any]:
        now = self.clock()
        human = self._authority(token, csrf, unit_id, write=False, now=now)
        scope = ExecutionScope(
            human.tenant_id, unit_id, FiscalEnvironment.HOMOLOGATION, "t19-read", "fm-nfcore",
        )
        with _canonical_guard(self.db):
            issuer, _ = historical_issuer_context(self.db, scope, historical_period)
            with self.db() as uow:
                unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
            if unit is None:
                raise FiscalValidationError("registered historical credit unit required")
            verify_credit_unit(self.db, scope, issuer)
            with self.db.economy(scope) as store:
                current = self._authority(token, csrf, unit_id, write=False, now=self.clock())
                if current.account != human.account or current.session_id != human.session_id:
                    raise FiscalValidationError("accounting authority changed")
                # Read historical evidence even if environment is disabled today;
                # the same scoped permissions and historical identity still apply.
                return report(store, issuer, now.astimezone(LOCAL).date())
