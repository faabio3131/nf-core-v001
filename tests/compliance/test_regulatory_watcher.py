from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kordena_fiscal.compliance import (
    CapabilityReadinessService,
    FiscalActionCapability,
    FiscalCapabilityLevel,
    JurisdictionCapabilityMatrix,
    JurisdictionCapabilityRule,
    RegulatoryObservationStatus,
    RegulatoryProposalStatus,
    RegulatoryReviewDecisionKind,
    RegulatoryWatcherConflictError,
    RegulatoryWatcherNotFoundError,
    RegulatoryWatcherService,
    TechnicalValidationMode,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalEnvironment,
)

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
PUBLISHED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
EFFECTIVE = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
RJ = BrazilianJurisdiction("RJ")
SOURCE_SHA_A = "a" * 64
SOURCE_SHA_B = "b" * 64
TESTS_SHA = "c" * 64


class _Clock:
    def now(self) -> datetime:
        return NOW


def _service() -> RegulatoryWatcherService:
    return RegulatoryWatcherService(clock=_Clock())


def _observe(
    service: RegulatoryWatcherService,
    *,
    observation_id: str = "obs-sp-001",
    jurisdiction: BrazilianJurisdiction = SP,
    source_sha256: str = SOURCE_SHA_A,
):
    return service.observe(
        observation_id=observation_id,
        source_reference="https://example.invalid/normative/evidence-001",
        source_sha256=source_sha256,
        jurisdiction=jurisdiction,
        subject="nfe.schema.update",
        summary="Synthetic normative evidence for governed watcher certification.",
        published_at=PUBLISHED,
        effective_from=EFFECTIVE,
    )


def test_observation_preserves_provenance_effective_date_and_status() -> None:
    service = _service()

    observation = _observe(service)

    assert observation.observation_id == "obs-sp-001"
    assert observation.source_sha256 == SOURCE_SHA_A
    assert observation.jurisdiction == SP
    assert observation.published_at == PUBLISHED
    assert observation.effective_from == EFFECTIVE
    assert observation.observed_at == NOW
    assert observation.status is RegulatoryObservationStatus.OBSERVED
    assert service.observations == (observation,)


def test_duplicate_observation_fails_closed() -> None:
    service = _service()
    _observe(service)

    with pytest.raises(RegulatoryWatcherConflictError, match="already exists"):
        _observe(service)


def test_proposal_requires_all_observations_to_be_triaged() -> None:
    service = _service()
    _observe(service)

    with pytest.raises(RegulatoryWatcherConflictError, match="triaged"):
        service.propose(
            proposal_id="proposal-001",
            observation_ids=("obs-sp-001",),
            jurisdiction=SP,
            subject="nfe.schema.update",
            summary="Candidate change must remain review-only.",
            required_tests=("schema-contract",),
            document_kind=FiscalDocumentKind.NFE,
            current_rule_version=1,
        )


def test_triaged_observation_can_create_non_executable_pending_proposal() -> None:
    service = _service()
    _observe(service)
    triaged = service.triage("obs-sp-001")

    proposal = service.propose(
        proposal_id="proposal-001",
        observation_ids=(triaged.observation_id,),
        jurisdiction=SP,
        subject="nfe.schema.update",
        summary="Candidate change must remain review-only.",
        required_tests=("schema-contract", "regression-master"),
        document_kind=FiscalDocumentKind.NFE,
        current_rule_version=7,
    )

    assert triaged.status is RegulatoryObservationStatus.TRIAGED
    assert proposal.status is RegulatoryProposalStatus.PENDING_REVIEW
    assert proposal.current_rule_version == 7
    assert proposal.required_tests == ("schema-contract", "regression-master")
    assert proposal.executable is False


def test_approval_requires_named_reviewer_and_tests_evidence_but_remains_non_executable() -> None:
    service = _service()
    _observe(service)
    service.triage("obs-sp-001")
    proposal = service.propose(
        proposal_id="proposal-approve",
        observation_ids=("obs-sp-001",),
        jurisdiction=SP,
        subject="nfe.schema.update",
        summary="Human-reviewed candidate only.",
        required_tests=("schema-contract",),
    )

    reviewed, decision = service.review(
        proposal_id=proposal.proposal_id,
        reviewer_id="human-fiscal-reviewer",
        decision=RegulatoryReviewDecisionKind.APPROVE,
        tests_evidence_sha256=TESTS_SHA,
        reason_code="evidence.accepted",
    )

    assert reviewed.status is RegulatoryProposalStatus.APPROVED
    assert reviewed.executable is False
    assert decision.reviewer_id == "human-fiscal-reviewer"
    assert decision.tests_evidence_sha256 == TESTS_SHA
    assert decision.decision is RegulatoryReviewDecisionKind.APPROVE
    assert service.decisions == (decision,)


def test_rejection_is_explicit_and_duplicate_review_is_rejected() -> None:
    service = _service()
    _observe(service)
    service.triage("obs-sp-001")
    proposal = service.propose(
        proposal_id="proposal-reject",
        observation_ids=("obs-sp-001",),
        jurisdiction=SP,
        subject="nfe.schema.update",
        summary="Candidate rejected after governed review.",
        required_tests=("schema-contract",),
    )

    reviewed, _ = service.review(
        proposal_id=proposal.proposal_id,
        reviewer_id="human-fiscal-reviewer",
        decision=RegulatoryReviewDecisionKind.REJECT,
        tests_evidence_sha256=TESTS_SHA,
        reason_code="evidence.insufficient",
    )

    assert reviewed.status is RegulatoryProposalStatus.REJECTED
    with pytest.raises(RegulatoryWatcherConflictError, match="already been reviewed"):
        service.review(
            proposal_id=proposal.proposal_id,
            reviewer_id="second-reviewer",
            decision=RegulatoryReviewDecisionKind.APPROVE,
            tests_evidence_sha256=TESTS_SHA,
            reason_code="late.override",
        )


def test_conflicting_sources_are_recorded_explicitly_not_hidden() -> None:
    service = _service()
    first = _observe(service, observation_id="obs-sp-a", source_sha256=SOURCE_SHA_A)
    second = _observe(service, observation_id="obs-sp-b", source_sha256=SOURCE_SHA_B)

    conflict = service.record_conflict(
        conflict_id="conflict-sp-001",
        observation_ids=(first.observation_id, second.observation_id),
        reason_code="effective_date.conflict",
    )

    assert conflict.observation_ids == ("obs-sp-a", "obs-sp-b")
    assert conflict.reason_code == "effective_date.conflict"
    assert service.conflicts == (conflict,)


def test_mixed_jurisdiction_proposal_fails_closed() -> None:
    service = _service()
    _observe(service, observation_id="obs-sp", jurisdiction=SP)
    _observe(service, observation_id="obs-rj", jurisdiction=RJ, source_sha256=SOURCE_SHA_B)
    service.triage("obs-sp")
    service.triage("obs-rj")

    with pytest.raises(RegulatoryWatcherConflictError, match="jurisdiction mismatch"):
        service.propose(
            proposal_id="proposal-mixed",
            observation_ids=("obs-sp", "obs-rj"),
            jurisdiction=SP,
            subject="nfe.schema.update",
            summary="Cross-jurisdiction mutation must fail closed.",
            required_tests=("regression-master",),
        )



def test_proposal_cannot_launder_evidence_from_another_normative_subject() -> None:
    service = _service()
    first = _observe(service, observation_id="obs-sp-original")
    service.triage(first.observation_id)

    with pytest.raises(RegulatoryWatcherConflictError, match="subject mismatch"):
        service.propose(
            proposal_id="proposal-wrong-subject",
            observation_ids=(first.observation_id,),
            jurisdiction=SP,
            subject="nfse.tax.update",
            summary="Unrelated evidence must not justify tax decisions.",
            required_tests=("schema-contract",),
        )
    assert service.proposals == ()


def test_missing_observation_and_proposal_raise_explicit_not_found() -> None:
    service = _service()

    with pytest.raises(RegulatoryWatcherNotFoundError, match="observation"):
        service.triage("missing-observation")
    with pytest.raises(RegulatoryWatcherNotFoundError, match="proposal"):
        service.get_proposal("missing-proposal")


def test_approved_watcher_proposal_does_not_mutate_central_readiness_authority() -> None:
    rule = JurisdictionCapabilityRule(
        rule_id="sp-nfe-watcher-stability",
        version=1,
        state_code="SP",
        document_kind=FiscalDocumentKind.NFE,
        environment=FiscalEnvironment.HOMOLOGATION,
        capability_level=FiscalCapabilityLevel.HOMOLOGATION_READY,
        validation_mode=TechnicalValidationMode.STRICT_REJECTION,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        source_normative="certified baseline before watcher",
        capabilities=frozenset(
            {FiscalActionCapability.ISSUE, FiscalActionCapability.QUERY}
        ),
    )
    readiness = CapabilityReadinessService(JurisdictionCapabilityMatrix((rule,)))
    query = {
        "jurisdiction": SP,
        "document_kind": FiscalDocumentKind.NFE,
        "environment": FiscalEnvironment.HOMOLOGATION,
        "instant": NOW,
    }
    before = readiness.query(**query)

    service = _service()
    _observe(service)
    service.triage("obs-sp-001")
    proposal = service.propose(
        proposal_id="proposal-no-auto-apply",
        observation_ids=("obs-sp-001",),
        jurisdiction=SP,
        subject="nfe.schema.update",
        summary="Approved proposal still requires a separate governed implementation path.",
        required_tests=("schema-contract", "regression-master"),
        document_kind=FiscalDocumentKind.NFE,
        current_rule_version=1,
    )
    approved, _ = service.review(
        proposal_id=proposal.proposal_id,
        reviewer_id="human-fiscal-reviewer",
        decision=RegulatoryReviewDecisionKind.APPROVE,
        tests_evidence_sha256=TESTS_SHA,
        reason_code="review.complete",
    )

    after = readiness.query(**query)
    assert approved.status is RegulatoryProposalStatus.APPROVED
    assert approved.executable is False
    assert after == before
    assert not hasattr(service, "apply")
    assert not hasattr(service, "promote")
    assert not hasattr(service, "mutate_readiness")
