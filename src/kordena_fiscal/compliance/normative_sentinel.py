"""Offline normative sentinel: checksum is not proof of official authenticity.

Delegates integrity to the canonical RTC evidence verifier. No HTTP polling,
automatic baseline promotion or approval of fiscal rules is performed.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .rtc import RegulatoryArtifactPin, RegulatoryBaselineError
from .rtc_evidence import verify_regulatory_artifact_bytes


@dataclass(frozen=True, slots=True)
class NormativeIntegrityAssessment:
    sha256: str
    integrity_verified: bool
    official_provenance_verified: bool = False
    fiscal_production_approved: bool = False


def assess_pinned_normative_bytes(
    artifact: RegulatoryArtifactPin,
    payload: bytes,
) -> NormativeIntegrityAssessment:
    digest = verify_regulatory_artifact_bytes(artifact, payload)
    return NormativeIntegrityAssessment(digest, integrity_verified=True)


@dataclass(frozen=True, slots=True)
class NormativeDriftAssessment:
    """Byte-level comparison only; no evidence of a newer legal requirement."""

    artifact_id: str
    pinned_version: str
    pinned_sha256: str
    observed_sha256: str

    @property
    def review_required(self) -> bool:
        return not hmac.compare_digest(self.pinned_sha256, self.observed_sha256)

    @property
    def official_provenance_verified(self) -> bool:
        return False

    @property
    def fiscal_production_approved(self) -> bool:
        return False


def assess_normative_drift(
    artifact: RegulatoryArtifactPin,
    observed_payload: bytes,
) -> NormativeDriftAssessment:
    """Detect changed bytes relative to an immutable, previously reviewed pin.

    Inputs are supplied by the caller; this does not fetch URLs, infer a later
    version or effective date, or mutate the baseline. A changed digest may
    indicate corruption, a retrieval error or a new publication.
    """
    if not isinstance(artifact, RegulatoryArtifactPin):
        raise RegulatoryBaselineError("artifact must be a RegulatoryArtifactPin")
    if artifact.checksum_sha256 is None:
        raise RegulatoryBaselineError("artifact checksum_sha256 is required for drift detection")
    if not isinstance(observed_payload, bytes) or not observed_payload:
        raise RegulatoryBaselineError("observed artifact must contain non-empty bytes")
    observed = hashlib.sha256(observed_payload).hexdigest()
    if hmac.compare_digest(artifact.checksum_sha256, observed):
        observed = verify_regulatory_artifact_bytes(artifact, observed_payload)
    return NormativeDriftAssessment(
        artifact_id=artifact.artifact_id,
        pinned_version=artifact.version,
        pinned_sha256=artifact.checksum_sha256,
        observed_sha256=observed,
    )
