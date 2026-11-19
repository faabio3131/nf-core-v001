"""Governed regulatory watcher for V2-13.

The watcher records normative evidence and review workflow only. It deliberately has
no port capable of mutating capability/readiness matrices or production policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalValidationError,
)

from .normative_sentinel import assess_normative_drift
from .rtc import RegulatoryArtifactPin

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUBJECT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_SOURCE_REFERENCE = 512
_MAX_SUMMARY = 2048
_MAX_TESTS = 32


class RegulatoryWatcherError(FiscalDomainError):
    """Base error for governed watcher workflow failures."""


class RegulatoryWatcherNotFoundError(RegulatoryWatcherError):
    pass


class RegulatoryWatcherConflictError(RegulatoryWatcherError):
    pass


class RegulatoryObservationStatus(StrEnum):
    OBSERVED = "observed"
    TRIAGED = "triaged"


class RegulatoryProposalStatus(StrEnum):
    PENDING_REVIEW = "pending-review"
    APPROVED = "approved"
    REJECTED = "rejected"


class RegulatoryReviewDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RegulatoryWatcherClock(Protocol):
    def now(self) -> datetime: ...


class SystemRegulatoryWatcherClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _ID.fullmatch(normalized):
        raise FiscalValidationError(f"{field_name} must be a bounded safe identifier")
    return normalized


def _sha256(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise FiscalValidationError(f"{field_name} must be 64 lowercase hex chars")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _bounded_text(value: str, field_name: str, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise FiscalValidationError(f"{field_name} exceeds max length {maximum}")
    return normalized


@dataclass(frozen=True, slots=True)
class RegulatoryObservation:
    observation_id: str
    source_reference: str
    source_sha256: str
    jurisdiction: BrazilianJurisdiction
    subject: str
    summary: str
    published_at: datetime
    effective_from: datetime | None
    observed_at: datetime
    status: RegulatoryObservationStatus = RegulatoryObservationStatus.OBSERVED

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _identifier(self.observation_id, "observation_id"),
        )
        object.__setattr__(
            self,
            "source_reference",
            _bounded_text(
                self.source_reference,
                "source_reference",
                _MAX_SOURCE_REFERENCE,
            ),
        )
        object.__setattr__(
            self,
            "source_sha256",
            _sha256(self.source_sha256, "source_sha256"),
        )
        if not isinstance(self.jurisdiction, BrazilianJurisdiction):
            raise FiscalValidationError("jurisdiction must be BrazilianJurisdiction")
        subject = self.subject.strip().lower()
        if not _SUBJECT.fullmatch(subject):
            raise FiscalValidationError("subject must be a safe lowercase token")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(
            self,
            "summary",
            _bounded_text(self.summary, "summary", _MAX_SUMMARY),
        )
        object.__setattr__(self, "published_at", _aware(self.published_at, "published_at"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.effective_from is not None:
            object.__setattr__(
                self,
                "effective_from",
                _aware(self.effective_from, "effective_from"),
            )
        if not isinstance(self.status, RegulatoryObservationStatus):
            raise FiscalValidationError("status must be RegulatoryObservationStatus")


@dataclass(frozen=True, slots=True)
class RegulatoryConflict:
    conflict_id: str
    observation_ids: tuple[str, ...]
    reason_code: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "conflict_id", _identifier(self.conflict_id, "conflict_id"))
        normalized_ids = tuple(
            _identifier(item, "observation_id") for item in self.observation_ids
        )
        if len(normalized_ids) < 2 or len(set(normalized_ids)) != len(normalized_ids):
            raise FiscalValidationError("conflict requires at least two distinct observations")
        object.__setattr__(self, "observation_ids", normalized_ids)
        reason = self.reason_code.strip().lower()
        if not _SUBJECT.fullmatch(reason):
            raise FiscalValidationError("reason_code must be a safe lowercase token")
        object.__setattr__(self, "reason_code", reason)
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))


@dataclass(frozen=True, slots=True)
class RegulatoryChangeProposal:
    proposal_id: str
    observation_ids: tuple[str, ...]
    jurisdiction: BrazilianJurisdiction
    subject: str
    summary: str
    required_tests: tuple[str, ...]
    created_at: datetime
    document_kind: FiscalDocumentKind | None = None
    current_rule_version: int | None = None
    status: RegulatoryProposalStatus = RegulatoryProposalStatus.PENDING_REVIEW

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _identifier(self.proposal_id, "proposal_id"))
        normalized_ids = tuple(
            _identifier(item, "observation_id") for item in self.observation_ids
        )
        if not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
            raise FiscalValidationError("proposal requires distinct observation ids")
        object.__setattr__(self, "observation_ids", normalized_ids)
        if not isinstance(self.jurisdiction, BrazilianJurisdiction):
            raise FiscalValidationError("jurisdiction must be BrazilianJurisdiction")
        subject = self.subject.strip().lower()
        if not _SUBJECT.fullmatch(subject):
            raise FiscalValidationError("subject must be a safe lowercase token")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(
            self,
            "summary",
            _bounded_text(self.summary, "summary", _MAX_SUMMARY),
        )
        if len(self.required_tests) > _MAX_TESTS:
            raise FiscalValidationError("required_tests exceeds allowed size")
        tests = tuple(_identifier(item, "required_test") for item in self.required_tests)
        if not tests:
            raise FiscalValidationError("proposal requires at least one test")
        object.__setattr__(self, "required_tests", tests)
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if self.document_kind is not None and not isinstance(
            self.document_kind,
            FiscalDocumentKind,
        ):
            raise FiscalValidationError("document_kind must be FiscalDocumentKind")
        if self.current_rule_version is not None and self.current_rule_version < 1:
            raise FiscalValidationError("current_rule_version must be >= 1")
        if not isinstance(self.status, RegulatoryProposalStatus):
            raise FiscalValidationError("status must be RegulatoryProposalStatus")

    @property
    def executable(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class RegulatoryReviewDecision:
    proposal_id: str
    reviewer_id: str
    decision: RegulatoryReviewDecisionKind
    tests_evidence_sha256: str
    decided_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _identifier(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id"))
        if not isinstance(self.decision, RegulatoryReviewDecisionKind):
            raise FiscalValidationError("decision must be RegulatoryReviewDecisionKind")
        object.__setattr__(
            self,
            "tests_evidence_sha256",
            _sha256(self.tests_evidence_sha256, "tests_evidence_sha256"),
        )
        object.__setattr__(self, "decided_at", _aware(self.decided_at, "decided_at"))
        reason = self.reason_code.strip().lower()
        if not _SUBJECT.fullmatch(reason):
            raise FiscalValidationError("reason_code must be a safe lowercase token")
        object.__setattr__(self, "reason_code", reason)


class RegulatoryWatcherService:
    """In-memory governed workflow with no rule-application capability."""

    def __init__(self, *, clock: RegulatoryWatcherClock | None = None) -> None:
        self._clock = clock or SystemRegulatoryWatcherClock()
        self._observations: dict[str, RegulatoryObservation] = {}
        self._conflicts: dict[str, RegulatoryConflict] = {}
        self._proposals: dict[str, RegulatoryChangeProposal] = {}
        self._decisions: dict[str, RegulatoryReviewDecision] = {}

    def observe(
        self,
        *,
        observation_id: str,
        source_reference: str,
        source_sha256: str,
        jurisdiction: BrazilianJurisdiction,
        subject: str,
        summary: str,
        published_at: datetime,
        effective_from: datetime | None = None,
    ) -> RegulatoryObservation:
        observation = RegulatoryObservation(
            observation_id=observation_id,
            source_reference=source_reference,
            source_sha256=source_sha256,
            jurisdiction=jurisdiction,
            subject=subject,
            summary=summary,
            published_at=published_at,
            effective_from=effective_from,
            observed_at=self._clock.now(),
        )
        if observation.observation_id in self._observations:
            raise RegulatoryWatcherConflictError("observation already exists")
        self._observations[observation.observation_id] = observation
        return observation

    def observe_artifact_drift(
        self,
        *,
        observation_id: str,
        artifact: RegulatoryArtifactPin,
        observed_payload: bytes,
        jurisdiction: BrazilianJurisdiction,
        subject: str,
        claimed_published_at: datetime,
        claimed_effective_from: datetime | None = None,
    ) -> RegulatoryObservation | None:
        """Record changed bytes for human triage, never as verified legal evidence.

        Publication and effective dates are supplied claims, not inferred from
        the old pin or the fetch time. The source reference identifies the
        reviewed baseline location; this method does not authenticate retrieval.
        Unchanged bytes create no observation or executable proposal.
        """
        assessment = assess_normative_drift(artifact, observed_payload)
        if not assessment.review_required:
            return None
        return self.observe(
            observation_id=observation_id,
            source_reference=artifact.source_reference,
            source_sha256=assessment.observed_sha256,
            jurisdiction=jurisdiction,
            subject=subject,
            summary=(
                f"Unverified byte drift for artifact {assessment.artifact_id}, "
                f"pinned version {assessment.pinned_version}, "
                f"pinned SHA-256 {assessment.pinned_sha256}. "
                "Authenticate source and publication/effective dates before "
                "interpreting any legal or technical change."
            ),
            published_at=claimed_published_at,
            effective_from=claimed_effective_from,
        )

    def triage(self, observation_id: str) -> RegulatoryObservation:
        observation = self._require_observation(observation_id)
        if observation.status is RegulatoryObservationStatus.TRIAGED:
            return observation
        triaged = replace(observation, status=RegulatoryObservationStatus.TRIAGED)
        self._observations[triaged.observation_id] = triaged
        return triaged

    def record_conflict(
        self,
        *,
        conflict_id: str,
        observation_ids: tuple[str, ...],
        reason_code: str,
    ) -> RegulatoryConflict:
        for observation_id in observation_ids:
            self._require_observation(observation_id)
        conflict = RegulatoryConflict(
            conflict_id=conflict_id,
            observation_ids=observation_ids,
            reason_code=reason_code,
            recorded_at=self._clock.now(),
        )
        if conflict.conflict_id in self._conflicts:
            raise RegulatoryWatcherConflictError("conflict already exists")
        self._conflicts[conflict.conflict_id] = conflict
        return conflict

    def propose(
        self,
        *,
        proposal_id: str,
        observation_ids: tuple[str, ...],
        jurisdiction: BrazilianJurisdiction,
        subject: str,
        summary: str,
        required_tests: tuple[str, ...],
        document_kind: FiscalDocumentKind | None = None,
        current_rule_version: int | None = None,
    ) -> RegulatoryChangeProposal:
        for observation_id in observation_ids:
            observation = self._require_observation(observation_id)
            if observation.status is not RegulatoryObservationStatus.TRIAGED:
                raise RegulatoryWatcherConflictError(
                    "all proposal observations must be triaged"
                )
            if observation.jurisdiction != jurisdiction:
                raise RegulatoryWatcherConflictError("observation jurisdiction mismatch")
            if observation.subject != subject.strip().lower():
                raise RegulatoryWatcherConflictError("observation subject mismatch")
        proposal = RegulatoryChangeProposal(
            proposal_id=proposal_id,
            observation_ids=observation_ids,
            jurisdiction=jurisdiction,
            subject=subject,
            summary=summary,
            required_tests=required_tests,
            document_kind=document_kind,
            current_rule_version=current_rule_version,
            created_at=self._clock.now(),
        )
        if proposal.proposal_id in self._proposals:
            raise RegulatoryWatcherConflictError("proposal already exists")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def review(
        self,
        *,
        proposal_id: str,
        reviewer_id: str,
        decision: RegulatoryReviewDecisionKind,
        tests_evidence_sha256: str,
        reason_code: str,
    ) -> tuple[RegulatoryChangeProposal, RegulatoryReviewDecision]:
        proposal = self._require_proposal(proposal_id)
        if proposal.status is not RegulatoryProposalStatus.PENDING_REVIEW:
            raise RegulatoryWatcherConflictError("proposal has already been reviewed")
        review = RegulatoryReviewDecision(
            proposal_id=proposal.proposal_id,
            reviewer_id=reviewer_id,
            decision=decision,
            tests_evidence_sha256=tests_evidence_sha256,
            decided_at=self._clock.now(),
            reason_code=reason_code,
        )
        status = (
            RegulatoryProposalStatus.APPROVED
            if decision is RegulatoryReviewDecisionKind.APPROVE
            else RegulatoryProposalStatus.REJECTED
        )
        reviewed = replace(proposal, status=status)
        self._proposals[proposal.proposal_id] = reviewed
        self._decisions[proposal.proposal_id] = review
        return reviewed, review

    def get_observation(self, observation_id: str) -> RegulatoryObservation:
        return self._require_observation(observation_id)

    def get_proposal(self, proposal_id: str) -> RegulatoryChangeProposal:
        return self._require_proposal(proposal_id)

    @property
    def observations(self) -> tuple[RegulatoryObservation, ...]:
        return tuple(self._observations.values())

    @property
    def conflicts(self) -> tuple[RegulatoryConflict, ...]:
        return tuple(self._conflicts.values())

    @property
    def proposals(self) -> tuple[RegulatoryChangeProposal, ...]:
        return tuple(self._proposals.values())

    @property
    def decisions(self) -> tuple[RegulatoryReviewDecision, ...]:
        return tuple(self._decisions.values())

    def _require_observation(self, observation_id: str) -> RegulatoryObservation:
        key = _identifier(observation_id, "observation_id")
        try:
            return self._observations[key]
        except KeyError as exc:
            raise RegulatoryWatcherNotFoundError("observation not found") from exc

    def _require_proposal(self, proposal_id: str) -> RegulatoryChangeProposal:
        key = _identifier(proposal_id, "proposal_id")
        try:
            return self._proposals[key]
        except KeyError as exc:
            raise RegulatoryWatcherNotFoundError("proposal not found") from exc
