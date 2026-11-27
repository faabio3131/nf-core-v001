"""One scoped T18/T19 integrity authority over the immutable journals and cases.

The ledger supplies its existing replay and T17 source verifier as dependencies.
This module never imports the application ledger or lifecycle service, writes data,
or recalculates a monetary balance. No verified scope survives its transaction.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.credit_ledger import Amount, Command, Movement, State
from kordena_fiscal.tax.historical_audit import Strict, closed_months
from kordena_fiscal.tax.recovery_lifecycle import (
    MAX_CASE_EVENTS,
    MAX_CASE_SCAN_EVENTS,
    MAX_CASES,
    SCHEMA,
    Event,
    Status,
    Terms,
    managed_request_id,
    managed_request_identity,
    plan,
)
from kordena_fiscal.tax.tax_recovery import federal_interest
from kordena_fiscal.tax.unused_credits import Evidence, _unique_fields


class HistoricalSource(Protocol):
    @property
    def amount(self) -> Amount: ...
    @property
    def as_of(self) -> str: ...
    @property
    def modality(self) -> str: ...
    @property
    def anchor(self) -> str: ...
    @property
    def fiscal_identity(self) -> tuple[str, str, str | None, str | None]: ...


Journal = tuple[State, list[dict[str, Any]]]


@dataclass(frozen=True)
class LedgerReader:
    replay: Callable[[EconomyStore, Cnpj, date, str], Journal]
    historical_source: Callable[[EconomyStore, Cnpj, date, Command], HistoricalSource]
    journal_id: Callable[[Cnpj, str], str]


@dataclass(frozen=True)
class VerifiedRecoveryScope:
    """Transaction-local replay results, never an independent balance authority."""

    cases: list[tuple[list[dict[str, Any]], Status]]
    journals: dict[tuple[str, str], Journal]


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
    return managed_request_id(terms.case_id, version, index)


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


def case_history(
    store: EconomyStore, issuer: Cnpj, key: str, reader: LedgerReader,
    *, max_case_events: int = MAX_CASE_EVENTS,
) -> tuple[list[dict[str, Any]], Status | None, str | None]:
    """Validate the event chain against exact, independently replayed ledger versions."""
    scope = _scope(store)
    rows = store.recovery_case_rows(key, limit=max_case_events + 1)
    if len(rows) > max_case_events:
        raise FiscalValidationError("case history exceeds supported bound")
    if not rows:
        return [], None, None
    try:
        first = ReviewedEvent.model_validate(rows[0]["content"]["reviewed"]).event
        terms = first.terms
        period = date.fromisoformat(terms.competence)
        lot = reader.journal_id(issuer, terms.finding_id)
        _, journal = reader.replay(store, issuer, period, lot)
        if not journal:
            raise FiscalValidationError("case ledger missing")
        by_version = {row["version"]: row for row in journal}
        initial = Command.model_validate(journal[0]["content"]["reviewed"]["command"])
        origin = reader.historical_source(store, issuer, period, initial)
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
                source = reader.historical_source(store, issuer, period, source_command)
                if (
                    source.amount != origin.amount
                    or source.fiscal_identity != origin.fiscal_identity
                    or source.as_of != day.isoformat()
                ):
                    raise FiscalValidationError("historical case source or cutoff changed")
                _validate_amount(source.modality, source.anchor, terms, day)
            if event.action == "pay":
                _validate_payment(origin.modality, origin.anchor, terms, day)
            for index, (movement, link) in enumerate(
                zip(movements, content["ledger_links"], strict=True), 1
            ):
                ledger_version = link["version"]
                if type(ledger_version) is not int:
                    raise FiscalValidationError("invalid case ledger link version")
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
        actual_ids: set[str] = set()
        for posting in journal:
            request_id = posting["content"]["reviewed"]["command"]["request_id"]
            identity = managed_request_identity(request_id)
            if identity is not None and identity[0] == terms.case_id:
                actual_ids.add(request_id)
        if actual_ids != linked:
            raise FiscalValidationError("orphan case ledger movement")
        return rows, status, settlement
    except FiscalValidationError:
        # Domain validation errors already describe the failed invariant.
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise FiscalValidationError("invalid recovery case history") from exc


def _validate_amount(modality: str, anchor: str, terms: Terms, day: date) -> None:
    if modality == "federal_undue_payment" and terms.tax in {"pis", "cofins"}:
        projected = federal_interest(terms.amount.principal_cents, date.fromisoformat(anchor), day)
        if projected is None or terms.amount.selic_cents != projected[0]:
            raise FiscalValidationError("case principal and SELIC differ from T17 valuation")
    elif not (
        modality == "icms_bookkeeping" and terms.tax == "icms"
        and terms.kind == "compensation" and terms.route == "administrative"
        and terms.amount.selic_cents == 0
    ):
        raise FiscalValidationError("unsupported recovery modality, kind or route")


def _validate_payment(modality: str, anchor: str, terms: Terms, day: date) -> None:
    """Only a supported federal undue payment can reach simulated restitution."""
    if (
        modality != "federal_undue_payment" or terms.tax not in {"pis", "cofins"}
        or terms.kind != "restitution"
    ):
        raise FiscalValidationError("restitution requires supported federal undue payment")
    valuation = federal_interest(terms.amount.principal_cents, date.fromisoformat(anchor), day)
    if valuation is None or valuation[0] != terms.amount.selic_cents:
        raise FiscalValidationError("restitution settlement requires revaluation")


def verify_scope(
    store: EconomyStore, issuer: Cnpj, reader: LedgerReader, *,
    max_lots: int, max_events: int, max_scan_events: int,
    max_cases: int = MAX_CASES, max_case_events: int = MAX_CASE_EVENTS,
    max_case_scan_events: int = MAX_CASE_SCAN_EVENTS,
) -> VerifiedRecoveryScope:
    """Verify the exact bijection over all competences in the locked issuer scope.

    The caller holds the existing accounting issuance lock. A local replay map
    avoids re-reading the same journal for every case. A missing case, link, lot,
    version or digest, including a valid-hash orphan, aborts the whole operation.
    Never call this between a managed posting and its case event publication.
    """
    ids = store.credit_journal_ids(issuer, None, limit=max_lots + 1)
    if len(ids) > max_lots:
        raise FiscalValidationError("case reconciliation lot bound exceeded")
    journals: dict[tuple[str, str], Journal] = {}
    actual: dict[str, tuple[str, str, int, str]] = {}
    scanned = 0
    for key, period in ids:
        state, rows = reader.replay(store, issuer, date.fromisoformat(period), key)
        if not rows:
            raise FiscalValidationError("ledger lot missing")
        scanned += len(rows)
        if scanned > max_scan_events or len(rows) > max_events:
            raise FiscalValidationError("case reconciliation event bound exceeded")
        journals[key, period] = state, rows
        for row in rows:
            request = row["content"]["reviewed"]["command"]["request_id"]
            if managed_request_identity(request) is not None:
                if request in actual:
                    raise FiscalValidationError("orphan recovery case ledger: duplicate movement")
                actual[request] = (key, period, row["version"], row["digest"])

    def replay_verified(
        source_store: EconomyStore, source_issuer: Cnpj, period: date, key: str,
    ) -> Journal:
        if source_store is not store or source_issuer != issuer:
            raise FiscalValidationError("case ledger scope mismatch")
        journal = journals.get((key, period.isoformat()))
        if journal is None:
            raise FiscalValidationError("case ledger missing")
        return journal

    verified_reader = LedgerReader(replay_verified, reader.historical_source, reader.journal_id)
    cases: list[tuple[list[dict[str, Any]], Status]] = []
    expected: dict[str, tuple[str, str, int, str]] = {}
    case_ids = store.recovery_case_ids(issuer, limit=max_cases + 1)
    if len(case_ids) > max_cases:
        raise FiscalValidationError("recovery case count exceeds bound")
    events = 0
    for key, period in case_ids:
        rows, status, _ = case_history(
            store, issuer, key, verified_reader, max_case_events=max_case_events,
        )
        if not rows or status is None:
            raise FiscalValidationError("case history missing")
        events += len(rows)
        if events > max_case_scan_events:
            raise FiscalValidationError("recovery case scan exceeds event bound")
        last = ReviewedEvent.model_validate(rows[-1]["content"]["reviewed"]).event
        lot = reader.journal_id(issuer, last.terms.finding_id)
        for row in rows:
            for index, link in enumerate(row["content"]["ledger_links"], 1):
                request = managed_request_id(last.terms.case_id, row["version"], index)
                if request in expected:
                    raise FiscalValidationError("duplicate recovery case ledger link")
                expected[request] = (lot, period, link["version"], link["digest"])
        cases.append((rows, status))
    if any(expected.get(request) != binding for request, binding in actual.items()):
        raise FiscalValidationError("orphan recovery case ledger")
    if expected.keys() != actual.keys():
        raise FiscalValidationError("missing recovery case ledger link")
    return VerifiedRecoveryScope(cases, journals)
