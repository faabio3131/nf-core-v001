"""T18 immutable, scoped journal with replay and T17 provenance.

A journal version is one atomic double-entry document in the T01 snapshot
authority. The older T01 movement primitive is not a second balance authority.
Only homologation simulations are supported; T19 owns actual lifecycle events.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from kordena_fiscal.application.historical_audit import MAX_INPUT_BYTES, TABLE
from kordena_fiscal.application.tax_recovery import (
    PAGE_SCHEMA,
    SOURCE_SCHEMA,
    _children,
    _payments,
    _verified_t16,
)
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.credit_ledger import (
    MAX_EVENTS,
    MAX_LOTS,
    MAX_SCAN_EVENTS,
    SCHEMA,
    Amount,
    Command,
    State,
    transition,
)
from kordena_fiscal.tax.historical_audit import IssuerContext, Strict, closed_months
from kordena_fiscal.tax.tax_recovery import (
    SCHEMA as RECOVERY_SCHEMA,
)
from kordena_fiscal.tax.tax_recovery import (
    RecoveryBatch,
    estimate,
    invoice_dates,
    selic_reference,
)
from kordena_fiscal.tax.unused_credits import Evidence, _unique_fields


class ReviewedMovement(Strict):
    command: Command
    review: Evidence

    def verify(self, scope: tuple[str, ...], issuer: Cnpj) -> None:
        expected = {
            "scope": list(scope),
            "issuer_cnpj": issuer.value,
            "simulation_only": True,
            "command": self.command.model_dump(),
        }
        raw = self.review.contents()
        if len(raw) > 16384:
            raise FiscalValidationError("ledger movement evidence exceeds 16 KiB")
        observed = json.loads(raw, object_pairs_hook=_unique_fields)
        if json.dumps(observed, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise FiscalValidationError("ledger reviewed movement differs from original evidence")


def journal_id(issuer: Cnpj, finding_id: str) -> str:
    # T16 identity is already SHA256(recipient/access key/item/tax). No version
    # or date of assessment in the lot key: a new T17 estimate cannot duplicate it.
    return f"credit-ledger-{issuer.value}-{finding_id}"


def _require_scope(store: EconomyStore) -> tuple[str, ...]:
    scope = store.scope_identity
    if scope[-1] != "homologation":
        raise FiscalValidationError("ledger requires non-production homologation scope")
    return scope


def _source_key(issuer: Cnpj, period: date) -> str:
    return f"tax-recovery-{issuer.value}-{period.isoformat()}"


@dataclass(frozen=True)
class SourceLot:
    amount: Amount
    as_of: str
    modality: str
    anchor: str
    receipt_id: str | None
    payment_sha256: str | None

    @property
    def fiscal_identity(self) -> tuple[str, str, str | None, str | None]:
        return self.modality, self.anchor, self.receipt_id, self.payment_sha256


def _candidate(
    issuer: Cnpj, finding: dict[str, Any], tax: str, as_of: str
) -> SourceLot:
    expected_id = hashlib.sha256(
        f"{issuer.value}/{finding['access_key']}/{finding['item']}/{finding['tax']}".encode()
    ).hexdigest()
    if (
        finding["status"] != "potential"
        or finding["credit_recognized"] is not False
        or finding["tax"] != tax
        or expected_id != finding["finding_id"]
    ):
        raise FiscalValidationError("T17 finding not eligible for simulated ledger")
    amount = Amount(
        principal_cents=finding["principal_cents"], selic_cents=finding["adjustment_cents"]
    )
    if amount.total != finding["estimated_cents"] or amount.principal_cents <= 0:
        raise FiscalValidationError("T17 amount mismatch")
    modality = finding["modality"]
    receipt = finding.get("receipt_id")
    payment = finding.get("payment")
    if modality == "federal_undue_payment":
        if (
            tax not in {"pis", "cofins"}
            or not isinstance(receipt, str)
            or not receipt
            or not isinstance(payment, dict)
            or payment["receipt_id"] != receipt
            or not isinstance(payment["sha256"], str)
        ):
            raise FiscalValidationError("federal ledger receipt provenance missing")
        payment_sha = payment["sha256"]
    elif modality == "icms_bookkeeping":
        if tax != "icms" or receipt is not None or amount.selic_cents != 0:
            raise FiscalValidationError("invalid bookkeeping ledger provenance")
        payment_sha = None
    else:
        raise FiscalValidationError("unsupported ledger modality")
    return SourceLot(amount, as_of, modality, finding["anchor"], receipt, payment_sha)


def _verified_source(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    command: Command,
    context: IssuerContext,
    as_of: date,
) -> tuple[SourceLot, list[dict[str, Any]]]:
    """Recompute current T17 from original T17/T16/T15 evidence, never trust totals."""
    row = store.record(TABLE, _source_key(issuer, period))
    if (
        row is None
        or row["version"] != command.recovery_version
        or row["digest"] != command.recovery_digest
        or row["issuer_cnpj"] != issuer.value
        or row["competence"] != period.isoformat()
    ):
        raise FiscalValidationError("current scoped T17 snapshot required")
    index = row["content"]
    if (
        index["schema_version"] != RECOVERY_SCHEMA
        or index["recipient"] != issuer.value
        or index["competence"] != period.isoformat()
        or index["as_of"] != as_of.isoformat()
        or index["issuer_context"] != context.model_dump()
        or index["selic"] != selic_reference()
        or index["advisory_only"] is not True
        or index["credit_recognized"] is not False
        or index["realized_cents"] is not None
    ):
        raise FiscalValidationError("T17 context or cutoff changed; refresh source")
    raw = b"".join(
        base64.b64decode(part["data_b64"], validate=True)
        for part in _children(store, row, "source", SOURCE_SCHEMA)
    )
    if len(raw) > MAX_INPUT_BYTES or hashlib.sha256(raw).hexdigest() != index["input_sha256"]:
        raise FiscalValidationError("T17 source digest mismatch")
    facts = RecoveryBatch.model_validate_json(raw)
    if (
        facts.competence != command.competence
        or facts.t16_version != index["t16_version"]
        or facts.t16_digest != index["t16_digest"]
    ):
        raise FiscalValidationError("T17 source binding mismatch")
    batch, findings, t16 = _verified_t16(store, issuer, period, facts, context, as_of)
    if index["historical_digest"] != t16["historical_digest"]:
        raise FiscalValidationError("T17 historical digest mismatch")
    payments = _payments(store, issuer, period, context, as_of, t16)
    computed = estimate(facts, issuer, context, as_of, findings, invoice_dates(batch), payments)
    stored = [
        finding
        for page in _children(store, row, "page", PAGE_SCHEMA)
        for finding in page["findings"]
    ]
    if computed != stored or len(stored) != index["finding_count"]:
        raise FiscalValidationError("T17 findings recomputation mismatch")
    totals: dict[str, dict[str, int]] = {}
    counts: dict[str, int] = {}
    for finding in computed:
        status = finding["status"]
        counts[status] = counts.get(status, 0) + 1
        if status == "potential":
            total = totals.setdefault(finding["tax"], {})
            for name in ("principal_cents", "adjustment_cents", "estimated_cents"):
                total[name] = total.get(name, 0) + finding[name]
    if totals != index["partial_totals_cents"] or counts != index["status_counts"]:
        raise FiscalValidationError("T17 index totals mismatch")
    matches = [item for item in computed if item["finding_id"] == command.finding_id]
    if len(matches) != 1:
        raise FiscalValidationError("T17 finding missing or ambiguous")
    return _candidate(issuer, matches[0], command.tax, as_of.isoformat()), computed


def _lot_binding(command: Command) -> tuple[str, str, str]:
    return command.competence, command.finding_id, command.tax


def _source_binding(command: Command) -> tuple[int, str]:
    return command.recovery_version, command.recovery_digest


def _historical_source(
    store: EconomyStore, issuer: Cnpj, period: date, command: Command
) -> SourceLot:
    """Verify an exact immutable T17 source for historical replay, not new eligibility."""
    row = store.record(TABLE, _source_key(issuer, period), command.recovery_version)
    if (
        row is None
        or row["digest"] != command.recovery_digest
        or row["issuer_cnpj"] != issuer.value
        or row["competence"] != period.isoformat()
        or row["content"]["schema_version"] != RECOVERY_SCHEMA
        or row["content"]["advisory_only"] is not True
        or row["content"]["credit_recognized"] is not False
        or row["content"]["realized_cents"] is not None
    ):
        raise FiscalValidationError("original ledger source missing or changed")
    matches = [
        item
        for page in _children(store, row, "page", PAGE_SCHEMA)
        for item in page["findings"]
        if item["finding_id"] == command.finding_id
    ]
    if len(matches) != 1:
        raise FiscalValidationError("historical ledger finding missing or ambiguous")
    return _candidate(issuer, matches[0], command.tax, row["content"]["as_of"])


def _replay(
    store: EconomyStore, issuer: Cnpj, period: date, key: str
) -> tuple[State, list[dict[str, Any]]]:
    scope = _require_scope(store)
    rows = store.credit_journal_rows(key, limit=MAX_EVENTS + 1)
    if len(rows) > MAX_EVENTS:
        raise FiscalValidationError("ledger history exceeds supported bound")
    state = State()
    previous: str | None = None
    binding: tuple[str, str, str] | None = None
    previous_source: tuple[int, str] | None = None
    verified_sources: dict[tuple[int, str], SourceLot] = {}
    first_source: SourceLot | None = None
    last_date: date | None = None
    for version, row in enumerate(rows, 1):
        content = row["content"]
        reviewed = ReviewedMovement.model_validate(content["reviewed"])
        command = reviewed.command
        reviewed.verify(scope, issuer)
        event_date = date.fromisoformat(content["as_of"])
        if (
            row["version"] != version
            or row["record_id"] != key
            or row["issuer_cnpj"] != issuer.value
            or row["competence"] != period.isoformat()
            or journal_id(issuer, command.finding_id) != key
            or command.competence != period.isoformat()
            or content["schema_version"] != SCHEMA
            or content["event_version"] != version
            or content["previous_digest"] != previous
            or content["scope"] != list(scope)
            or content["issuer_cnpj"] != issuer.value
            or content["simulation_only"] is not True
            or content["credit_recognized"] is not False
            or content["realized_cents"] is not None
            or (binding is not None and _lot_binding(command) != binding)
            or (last_date is not None and event_date < last_date)
        ):
            raise FiscalValidationError("ledger history integrity mismatch")
        closed_months(period, event_date)
        if binding is None:
            binding = _lot_binding(command)
        source = _source_binding(command)
        if command.movement in {"identified", "reserved", "compensated"}:
            if source not in verified_sources:
                verified_sources[source] = _historical_source(store, issuer, period, command)
            expected = command.amount if command.movement == "identified" else state.original
            verified = verified_sources[source]
            if verified.amount != expected or verified.as_of != event_date.isoformat():
                raise FiscalValidationError(
                    "historical ledger amount or cutoff differs from source"
                )
            if first_source is None:
                first_source = verified
            elif verified.fiscal_identity != first_source.fiscal_identity:
                raise FiscalValidationError("ledger fiscal identity cannot change")
        elif previous_source != source:
            raise FiscalValidationError("unwinding movement must retain last source binding")
        postings = transition(state, command)
        if postings != content["postings"] or state.projection() != content["balances"]:
            raise FiscalValidationError("ledger postings or balance projection mismatch")
        previous = row["digest"]
        last_date = event_date
        previous_source = source
    return state, rows


def _guard_existing_lots(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    command: Command,
    current: SourceLot,
    findings: list[dict[str, Any]],
) -> None:
    """Prevent reallocation of an active lot and reuse of a federal payment."""
    candidates = {item["finding_id"]: item for item in findings}
    ids = store.credit_journal_ids(
        issuer, None if current.receipt_id is not None else period, limit=MAX_LOTS + 1
    )
    if len(ids) > MAX_LOTS:
        raise FiscalValidationError("ledger overlap check exceeds supported lot bound")
    scanned = 0
    for key, competence in ids:
        if key == journal_id(issuer, command.finding_id):
            continue
        first = store.record(TABLE, key, 1)
        if first is None:
            raise FiscalValidationError("ledger lot first event missing")
        initial = Command.model_validate(first["content"]["reviewed"]["command"])
        if initial.tax != command.tax:
            continue
        other_period = date.fromisoformat(competence)
        state, rows = _replay(store, issuer, other_period, key)
        scanned += len(rows)
        if scanned > MAX_SCAN_EVENTS:
            raise FiscalValidationError("ledger overlap check exceeds event bound")
        if state.balances["reversed"] == state.original:
            continue
        original = _historical_source(store, issuer, other_period, initial)
        if other_period != period:
            if current.receipt_id is not None and original.receipt_id is not None and (
                current.receipt_id == original.receipt_id
                or current.payment_sha256 == original.payment_sha256
            ):
                raise FiscalValidationError("federal receipt already attributed to another period")
            continue
        # Every active lot of this tax must still correspond to exactly one
        # unchanged candidate in the current complete T17 recomputation.
        candidate = candidates.get(initial.finding_id)
        if candidate is None or candidate["status"] != "potential":
            raise FiscalValidationError("active ledger lot absent from current T17")
        updated = _candidate(issuer, candidate, command.tax, current.as_of)
        if (
            updated.amount != state.original
            or updated.fiscal_identity != original.fiscal_identity
        ):
            raise FiscalValidationError("active ledger lot changed in current T17")


def post_movement(
    store: EconomyStore,
    issuer: Cnpj,
    reviewed: ReviewedMovement,
    *,
    context: IssuerContext,
    as_of: date,
) -> dict[str, Any]:
    """Post one simulated movement after replaying the entire locked lot."""
    scope = _require_scope(store)
    reviewed.verify(scope, issuer)
    command = reviewed.command
    period = date.fromisoformat(command.competence)
    closed_months(period, as_of)
    key = journal_id(issuer, command.finding_id)
    # Same scoped lock as T13/T14/T15/T16/T17 snapshot mutations. No race
    # between checking the current source and publishing a journal version.
    store.lock_state_review_import(key, key)
    state, history = _replay(store, issuer, period, key)
    for row in history:
        prior = row["content"]["reviewed"]
        if prior["command"]["request_id"] == command.request_id:
            if prior != reviewed.model_dump():
                raise FiscalValidationError("ledger request id conflict")
            return {
                "version": row["version"], "digest": row["digest"], "replay": True,
                "balances": state.projection(), "simulation_only": True,
            }
    if len(history) != command.expected_version or len(history) >= MAX_EVENTS:
        raise FiscalValidationError("ledger optimistic version conflict")
    if history:
        last = Command.model_validate(history[-1]["content"]["reviewed"]["command"])
        if _lot_binding(last) != _lot_binding(command):
            raise FiscalValidationError("ledger lot identity cannot change")
        if (
            command.movement not in {"identified", "reserved", "compensated"}
            and _source_binding(last) != _source_binding(command)
        ):
            raise FiscalValidationError("unwinding movement must retain last source binding")
        if as_of < date.fromisoformat(history[-1]["content"]["as_of"]):
            raise FiscalValidationError("ledger event date moved backwards")
    if command.movement in {"identified", "reserved", "compensated"}:
        current, findings = _verified_source(store, issuer, period, command, context, as_of)
        expected = command.amount if command.movement == "identified" else state.original
        if current.amount != expected:
            raise FiscalValidationError("ledger identification differs from current T17 amount")
        if history:
            first = Command.model_validate(history[0]["content"]["reviewed"]["command"])
            original = _historical_source(store, issuer, period, first)
            if original.fiscal_identity != current.fiscal_identity:
                raise FiscalValidationError("ledger fiscal identity cannot change")
        _guard_existing_lots(store, issuer, period, command, current, findings)
    postings = transition(state, command)
    version = len(history) + 1
    projection = state.projection()
    digest = store.append_snapshot(
        record_id=key,
        version=version,
        competence=period,
        issuer=issuer,
        content={
            "schema_version": SCHEMA,
            "event_version": version,
            "previous_digest": history[-1]["digest"] if history else None,
            "scope": list(scope),
            "issuer_cnpj": issuer.value,
            "as_of": as_of.isoformat(),
            "reviewed": reviewed.model_dump(),
            "postings": postings,
            "balances": projection,
            "simulation_only": True,
            "credit_recognized": False,
            "realized_cents": None,
        },
    )
    return {
        "version": version, "digest": digest, "replay": False,
        "balances": projection, "simulation_only": True,
    }


def reconcile(
    store: EconomyStore, issuer: Cnpj, period: date | None = None
) -> dict[str, Any]:
    """Reconcile every recorded lot by tax/competence, with no silent truncation."""
    _require_scope(store)
    if period is not None and (type(period) is not date or period.day != 1):
        raise FiscalValidationError("invalid ledger reporting competence")
    store.lock_accounting_issuance()
    ids = store.credit_journal_ids(issuer, period, limit=MAX_LOTS + 1)
    if len(ids) > MAX_LOTS:
        raise FiscalValidationError("ledger report exceeds supported lot bound")
    totals: dict[str, dict[str, dict[str, int]]] = {}
    periods: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    entries = 0

    def accumulate(
        target: dict[str, dict[str, dict[str, int]]],
        tax: str,
        projection: dict[str, Any],
    ) -> None:
        bucket = target.setdefault(tax, {})
        for name in ("identified", "available", "reserved", "compensated", "reversed"):
            account = bucket.setdefault(name, {})
            for component in ("principal_cents", "selic_cents"):
                account[component] = account.get(component, 0) + projection[name][component]
                if account[component] > 2**63 - 1:
                    raise FiscalValidationError("ledger aggregate exceeds bigint range")

    for key, competence in ids:
        state, rows = _replay(store, issuer, date.fromisoformat(competence), key)
        if not rows:
            raise FiscalValidationError("ledger lot missing")
        tax = rows[0]["content"]["reviewed"]["command"]["tax"]
        projection = state.projection()
        accumulate(totals, tax, projection)
        accumulate(periods.setdefault(competence, {}), tax, projection)
        entries += len(rows)
        if entries > MAX_SCAN_EVENTS:
            raise FiscalValidationError("ledger report exceeds supported event bound")
    return {
        "by_tax": totals,
        "by_competence": periods,
        "lot_count": len(ids),
        "event_count": entries,
        "simulation_only": True,
        "historical_balances_not_current_entitlement": True,
        "credit_recognized": False,
        "realized_cents": None,
    }


def history(
    store: EconomyStore, issuer: Cnpj, period: date, finding_id: str
) -> dict[str, Any]:
    """Return the complete verified journal, not a best-effort list of movements."""
    _require_scope(store)
    store.lock_accounting_issuance()
    key = journal_id(issuer, finding_id)
    state, rows = _replay(store, issuer, period, key)
    if not rows:
        raise FiscalValidationError("ledger lot missing")
    return {
        "record_id": key,
        "events": rows,
        "balances": state.projection(),
        "simulation_only": True,
        "historical_balances_not_current_entitlement": True,
    }
