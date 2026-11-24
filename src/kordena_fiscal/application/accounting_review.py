"""T13 append-only human decisions, not a fiscal execution authority."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest

SCHEMA = "nfcore.accounting-review/v1"
MAX_VERSION = 2147483647
TABLE = "fm_economy_snapshots"
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/+:@-]{0,127}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[int, Field(ge=0, le=MAX_VERSION - 1)]


class ReviewConflict(FiscalValidationError):
    """An optimistic precondition or the decision state no longer matches."""


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ReviewTarget(ReviewModel):
    kind: Literal["benefit", "annual_comparison"]
    source: Literal["federal", "state", "municipal"] | None = None
    benefit_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_target(self) -> ReviewTarget:
        if self.kind == "benefit":
            if self.source is None or self.benefit_id is None:
                raise ValueError("benefit source and identifier are required")
        elif self.source is not None or self.benefit_id is not None:
            raise ValueError("annual comparison has no benefit")
        return self


class ReviewDecision(ReviewModel):
    decision: Literal["approved", "rejected", "revoked"]
    subject_digest: Digest
    expected_version: Version
    request_id: Identifier
    opinion_reference: Identifier
    rationale: Annotated[str, StringConstraints(min_length=10, max_length=2000)]
    professional_reference: Identifier

    @model_validator(mode="after")
    def validate_text(self) -> ReviewDecision:
        if self.rationale.strip() != self.rationale or not self.rationale.strip():
            raise ValueError("invalid rationale")
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in self.rationale):
            raise ValueError("invalid rationale")
        return self


def review_id(issuer: Cnpj, period: date, target: ReviewTarget) -> str:
    return (
        "accounting-review-"
        + _digest(
            {
                "issuer": issuer.value,
                "competence": period.isoformat(),
                "target": target.model_dump(),
            }
        )[1]
    )


def subject_digest(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    target: ReviewTarget,
    subject: dict[str, Any],
) -> str:
    return _digest(
        {
            "scope": list(store.scope_identity),
            "issuer": issuer.value,
            "competence": period.isoformat(),
            "target": target.model_dump(),
            "subject": subject,
        }
    )[1]


def _event(
    store: EconomyStore,
    row: dict[str, Any],
    key: str,
    issuer: Cnpj,
    period: date,
) -> dict[str, Any]:
    content = row["content"]
    try:
        target = ReviewTarget.model_validate(content["target"])
        command = ReviewDecision.model_validate(content["command"])
        stamp = datetime.fromisoformat(content["recorded_at"])
        if (
            row["record_id"] != key
            or review_id(issuer, period, target) != key
            or row["issuer_cnpj"] != issuer.value
            or row["competence"] != period.isoformat()
            or content["schema_version"] != SCHEMA
            or content["event_version"] != row["version"]
            or command.expected_version != row["version"] - 1
            or content["actor_role"] != "accountant"
            or content["attestation_type"] != "authenticated_human_step_up"
            or not isinstance(content["actor_id"], str)
            or not content["actor_id"].strip()
            or stamp.utcoffset() is None
            or not isinstance(content["subject"], dict)
            or command.subject_digest
            != subject_digest(
                store,
                issuer,
                period,
                target,
                content["subject"],
            )
            or any(
                content[field] != getattr(command, field)
                for field in (
                    "decision",
                    "subject_digest",
                    "request_id",
                    "opinion_reference",
                    "professional_reference",
                    "rationale",
                )
            )
        ):
            raise FiscalValidationError("invalid accounting review event")
    except (KeyError, TypeError, ValueError) as exc:
        raise FiscalValidationError("invalid accounting review event") from exc
    return {**content, "event_digest": row["digest"]}


def _history(
    store: EconomyStore,
    key: str,
    issuer: Cnpj,
    period: date,
    latest: dict[str, Any] | None,
    before_version: int | None,
) -> tuple[list[dict[str, Any]], int | None]:
    if latest is None:
        return [], None
    highest = (
        latest["version"]
        if before_version is None
        else min(
            latest["version"],
            before_version - 1,
        )
    )
    events: list[dict[str, Any]] = []
    for version in range(highest, max(0, highest - 20), -1):
        row = store.record(TABLE, key, version)
        if row is None:
            raise FiscalValidationError("accounting review history gap")
        event = _event(store, row, key, issuer, period)
        if events and events[-1]["previous_digest"] != event["event_digest"]:
            raise FiscalValidationError("accounting review chain mismatch")
        events.append(event)
    if events and events[-1]["event_version"] > 1:
        predecessor = store.record(TABLE, key, events[-1]["event_version"] - 1)
        if predecessor is None or predecessor["digest"] != events[-1]["previous_digest"]:
            raise FiscalValidationError("accounting review page boundary mismatch")
    if events and events[-1]["event_version"] == 1 and events[-1]["previous_digest"] is not None:
        raise FiscalValidationError("invalid accounting review genesis")
    return events, events[-1]["event_version"] if events and events[-1][
        "event_version"
    ] > 1 else None


def project_review(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    target: ReviewTarget,
    subject: dict[str, Any] | None,
    *,
    before_version: int | None = None,
) -> dict[str, Any]:
    key = review_id(issuer, period, target)
    digest = subject_digest(store, issuer, period, target, subject) if subject is not None else None
    latest = store.record(TABLE, key)
    event = _event(store, latest, key, issuer, period) if latest is not None else None
    history, cursor = _history(store, key, issuer, period, latest, before_version)
    status = (
        "pending"
        if event is None
        else (event["decision"] if event["subject_digest"] == digest else "stale")
    )
    if subject is None:
        status = "insufficient_basis" if event is None else "stale"
    return {
        "schema_version": SCHEMA,
        "record_id": key,
        "subject_digest": digest,
        "subject": subject,
        "current_version": latest["version"] if latest else 0,
        "status": status,
        "latest": event,
        "history": history,
        "next_before_version": cursor,
        "advisory_only": True,
        "issuance_authorized": False,
        "professional_registration_verified": False,
        "realized_cents": None,
    }


def record_decision(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    target: ReviewTarget,
    subject: dict[str, Any],
    command: ReviewDecision,
    *,
    actor_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Caller must establish authenticated accountant authority and fresh MFA."""
    if not actor_id or now.tzinfo is None or now.utcoffset() is None:
        raise FiscalValidationError("invalid accounting review actor or timestamp")
    key = review_id(issuer, period, target)
    store.lock_state_review_import(key, key)
    digest = subject_digest(store, issuer, period, target, subject)
    if digest != command.subject_digest:
        raise ReviewConflict("reviewed subject changed")
    latest = store.record(TABLE, key)
    version = latest["version"] if latest else 0
    previous = _event(store, latest, key, issuer, period) if latest is not None else None
    request = command.model_dump()
    if previous is not None and previous["request_id"] == command.request_id:
        if previous["command"] != request or previous["actor_id"] != actor_id:
            raise ReviewConflict("accounting review idempotency conflict")
        return project_review(store, issuer, period, target, subject)
    if store.accounting_review_request_version(key, command.request_id) is not None:
        raise ReviewConflict("accounting review request identifier already used")
    if version != command.expected_version or version >= MAX_VERSION:
        raise ReviewConflict("accounting review version changed")
    if previous is not None and previous["subject_digest"] == digest:
        if previous["decision"] == "approved" and command.decision != "revoked":
            raise ReviewConflict("revoke an approved review before replacing it")
        if previous["decision"] == command.decision:
            raise ReviewConflict("duplicate decision")
    if command.decision == "revoked" and (
        previous is None
        or previous["decision"] != "approved"
        or previous["subject_digest"] != digest
    ):
        raise ReviewConflict("only a current approval may be revoked")
    content = {
        "schema_version": SCHEMA,
        "event_version": version + 1,
        "decision": command.decision,
        "subject_digest": digest,
        "target": target.model_dump(),
        "subject": subject,
        "actor_id": actor_id,
        "actor_role": "accountant",
        "attestation_type": "authenticated_human_step_up",
        "recorded_at": now.astimezone(UTC).isoformat(),
        "request_id": command.request_id,
        "command": request,
        "opinion_reference": command.opinion_reference,
        "rationale": command.rationale,
        "professional_reference": command.professional_reference,
        "previous_digest": latest["digest"] if latest else None,
    }
    store.append_snapshot(
        record_id=key,
        version=version + 1,
        competence=period,
        issuer=issuer,
        content=content,
    )
    return project_review(store, issuer, period, target, subject)
