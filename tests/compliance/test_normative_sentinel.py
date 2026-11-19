from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest

from kordena_fiscal.compliance.normative_sentinel import (
    assess_normative_drift,
    assess_pinned_normative_bytes,
)
from kordena_fiscal.compliance.rtc import (
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaselineError,
)

ORIGINAL = b"reviewed artifact, revision 1"
CHANGED = b"changed artifact, unidentified revision"


def _pin() -> RegulatoryArtifactPin:
    return RegulatoryArtifactPin(
        artifact_id="example-schema",
        kind=RegulatoryArtifactKind.SCHEMA,
        version="1.0",
        published_on=date(2026, 1, 1),
        source_reference="https://example.invalid/schema",
        checksum_sha256=sha256(ORIGINAL).hexdigest(),
    )


def test_unchanged_bytes_require_no_drift_review_but_no_official_approval() -> None:
    pin = _pin()
    result = assess_normative_drift(pin, ORIGINAL)
    assert result.artifact_id == pin.artifact_id
    assert result.pinned_version == pin.version
    assert result.pinned_sha256 == pin.checksum_sha256 == result.observed_sha256
    assert not result.review_required
    assert not result.official_provenance_verified
    assert not result.fiscal_production_approved


def test_changed_bytes_require_review_and_leave_original_pin_intact() -> None:
    pin = _pin()
    result = assess_normative_drift(pin, CHANGED)
    assert result.review_required
    assert result.observed_sha256 == sha256(CHANGED).hexdigest()
    assert result.pinned_sha256 == sha256(ORIGINAL).hexdigest()
    assert pin == _pin()
    assert not result.official_provenance_verified
    assert not result.fiscal_production_approved
    with pytest.raises(RegulatoryBaselineError, match="digest mismatch"):
        assess_pinned_normative_bytes(pin, CHANGED)
    assert assess_pinned_normative_bytes(pin, ORIGINAL).integrity_verified


def test_drift_detection_rejects_unpinned_artifact() -> None:
    with pytest.raises(RegulatoryBaselineError, match="checksum_sha256"):
        assess_normative_drift(replace(_pin(), checksum_sha256=None), CHANGED)


def test_drift_detection_rejects_missing_bytes() -> None:
    with pytest.raises(RegulatoryBaselineError, match="non-empty bytes"):
        assess_normative_drift(_pin(), b"")
