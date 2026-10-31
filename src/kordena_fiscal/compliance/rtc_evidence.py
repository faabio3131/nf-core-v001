"""Fail-closed integrity verification for pinned official RTC artifacts.

This validates bytes against a RegulatoryArtifactPin; it does not download,
approve, interpret or automatically activate a normative artifact.
"""

from __future__ import annotations

import hashlib
import hmac

from .rtc import RegulatoryArtifactPin, RegulatoryBaselineError


def verify_regulatory_artifact_bytes(
    artifact: RegulatoryArtifactPin,
    payload: bytes,
) -> str:
    """Return verified SHA-256 digest or reject absent/mismatching evidence.

    A successful digest only proves byte integrity relative to an approved pin,
    not the authenticity of the source, legal correctness or production readiness.
    """
    if not isinstance(artifact, RegulatoryArtifactPin):
        raise RegulatoryBaselineError("artifact must be a RegulatoryArtifactPin")
    if not isinstance(payload, bytes) or not payload:
        raise RegulatoryBaselineError("artifact payload must contain non-empty bytes")
    if artifact.checksum_sha256 is None:
        raise RegulatoryBaselineError("artifact checksum_sha256 is required for byte verification")
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, artifact.checksum_sha256):
        raise RegulatoryBaselineError("regulatory artifact SHA-256 digest mismatch")
    return digest
