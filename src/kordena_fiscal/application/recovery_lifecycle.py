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
    _ledger_reader,
    _post_movement,
    _reconcile_verified,
    _replay,
    _require_write_capacity,
    _verified_source,
    _verify_managed_scope,
    journal_id,
)
from kordena_fiscal.application.recovery_integrity import (
    ReviewedEvent as ReviewedEvent,
)
from kordena_fiscal.application.recovery_integrity import (
    VerifiedRecoveryScope,
    _ledger_command,
    _scope,
    _validate_amount,
    _validate_payment,
    case_history,
)
from kordena_fiscal.application.recovery_integrity import (
    case_key as case_key,
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
)
from kordena_fiscal.tax.historical_audit import IssuerContext, closed_months
from kordena_fiscal.tax.recovery_lifecycle import (
    MAX_CASE_EVENTS,
    MAX_CASE_SCAN_EVENTS,
    MAX_CASES,
    SCHEMA,
    Event,
    Status,
    alert,
    managed_request_identity,
    plan,
)
from kordena_fiscal.tax.selic_residual import require_selic_reservation, selic_reconciliation

LOCAL = ZoneInfo("America/Sao_Paulo")
TABLE = "fm_economy_snapshots"


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


def _case_history(
    store: EconomyStore, issuer: Cnpj, key: str,
) -> tuple[list[dict[str, Any]], Status | None, str | None]:
    return case_history(store, issuer, key, _ledger_reader(), max_case_events=MAX_CASE_EVENTS)


def _verified_scope(store: EconomyStore, issuer: Cnpj) -> VerifiedRecoveryScope:
    return _verify_managed_scope(
        store, issuer, max_cases=MAX_CASES, max_case_events=MAX_CASE_EVENTS,
        max_case_scan_events=MAX_CASE_SCAN_EVENTS, max_lots=MAX_LOTS,
        max_events=MAX_EVENTS, max_scan_events=MAX_SCAN_EVENTS,
    )


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
        # Validate the full issuer scope before either an idempotent response or
        # a mutation; the same lock covers the subsequent atomic case posting.
        verified = _verified_scope(store, issuer)
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
        existing = verified.cases
        # Preserve reportability at the boundary of the append-only sandbox.
        # Check the prospective state under the same lock, before any posting.
        if not rows and len(existing) >= MAX_CASES:
            raise FiscalValidationError("recovery case count exceeds bound")
        if sum(len(other) for other, _ in existing) >= MAX_CASE_SCAN_EVENTS:
            raise FiscalValidationError("recovery case scan exceeds event bound")
        for other, other_status in existing:
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
            any(
                a.total for k, a in state.reservations.items()
                if managed_request_identity(k) is None
            )
            or any(
                not v.reversed and managed_request_identity(k) is None
                for k, v in state.compensations.items()
            )
        ):
            raise FiscalValidationError("standalone T18 encumbrance requires reconciliation")
        if event.action in {"request", "transmit", "release"}:
            _validate_current(store, issuer, period, event, context, day, journal)
        if event.action == "request" and terms.tax in {"pis", "cofins"}:
            # T17 still determines each requested amount. Never consume the last
            # principal while silently leaving SELIC, or invent a balancing cent.
            require_selic_reservation(state.balances["available"], terms.amount)
        if event.action == "pay":
            # A deferment is not a payment; recompute the fixed lot at simulated
            # settlement date. Changed valuation must not be silently realized.
            origin = _historical_source(store, issuer, period, first)
            _validate_payment(origin.modality, origin.anchor, terms, day)
        if movements:
            # Retain the existing monetary/provenance reconciliation guard.
            _reconcile_verified(store, issuer, verified)
            _require_write_capacity(
                verified, key=journal_id(issuer, terms.finding_id), period=period,
                movements=len(movements), max_lots=MAX_LOTS, max_events=MAX_EVENTS,
                max_scan_events=MAX_SCAN_EVENTS,
            )
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
        _verified_scope(store, issuer)
        return {
            "version": version, "digest": digest, "replay": False,
            "status": next_status, "current_status": next_status,
            "current_version": version, "simulation_only": True,
        }


def report(store: EconomyStore, issuer: Cnpj, today: date) -> dict[str, Any]:
    """Case and ledger reconciliation, with explicit overdue/follow-up alerts."""
    _scope(store)
    store.lock_accounting_issuance()
    verified = _verified_scope(store, issuer)
    cases = []
    for rows, status in verified.cases:
        last = ReviewedEvent.model_validate(rows[-1]["content"]["reviewed"]).event
        cases.append({
            "terms": last.terms.model_dump(), "status": status, "version": len(rows),
            "digest": rows[-1]["digest"], "alert": alert(status, last.due_on, today),
            "events": rows,
        })
    # This diagnostic is derived from the verified T18 balance and its immutable
    # original T17 valuation basis, not today's rate or a second credit ledger.
    # Include standalone federal lots too; a difference need not be rounding alone.
    residuals = []
    for (_, competence), (state, journal) in sorted(verified.journals.items()):
        first = Command.model_validate(journal[0]["content"]["reviewed"]["command"])
        if first.tax not in {"pis", "cofins"}:
            continue
        origin = _historical_source(store, issuer, date.fromisoformat(competence), first)
        if origin.modality != "federal_undue_payment":
            continue
        residuals.append({
            "finding_id": first.finding_id, "tax": first.tax, "competence": competence,
            "source_version": first.recovery_version, "source_digest": first.recovery_digest,
            "payment_date": origin.anchor, "valuation_date": origin.as_of,
            "has_managed_movements": any(
                managed_request_identity(request) is not None for request in state.seen
            ),
            **selic_reconciliation(
                state.balances["available"], date.fromisoformat(origin.anchor),
                date.fromisoformat(origin.as_of),
            ),
        })
    return {
        "cases": cases, "ledger": _reconcile_verified(store, issuer, verified),
        "selic_reconciliation": residuals,
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
