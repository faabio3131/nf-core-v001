"""RTC-01: versioned legal-artifact integrity gate with synthetic fixtures."""

from datetime import date
from hashlib import sha256

import pytest

from kordena_fiscal.compliance import (
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_evidence import verify_regulatory_artifact_bytes

_PAYLOAD = b"synthetic official-layout fixture (not real fiscal XML)"


def _pin(checksum: str | None) -> RegulatoryArtifactPin:
    return RegulatoryArtifactPin(
        artifact_id="NT-2025.002",
        kind=RegulatoryArtifactKind.TECHNICAL_NOTE,
        version="synthetic-test-version",
        published_on=date(2026, 10, 1),
        source_reference="https://www.nfe.fazenda.gov.br/portal/",
        checksum_sha256=checksum,
    )


def test_verified_artifact_bytes_match_pinned_sha256() -> None:
    checksum = sha256(_PAYLOAD).hexdigest()
    assert verify_regulatory_artifact_bytes(_pin(checksum), _PAYLOAD) == checksum


def test_missing_checksum_fails_closed() -> None:
    with pytest.raises(RegulatoryBaselineError, match="required"):
        verify_regulatory_artifact_bytes(_pin(None), _PAYLOAD)


def test_mismatching_bytes_fail_closed() -> None:
    checksum = sha256(_PAYLOAD).hexdigest()
    with pytest.raises(RegulatoryBaselineError, match="mismatch"):
        verify_regulatory_artifact_bytes(_pin(checksum), _PAYLOAD + b"tampered")


@pytest.mark.parametrize("invalid_payload", [b"", "not bytes", None])
def test_empty_or_non_byte_artifacts_fail_closed(invalid_payload: object) -> None:
    checksum = sha256(_PAYLOAD).hexdigest()
    with pytest.raises(RegulatoryBaselineError, match="non-empty bytes"):
        verify_regulatory_artifact_bytes(_pin(checksum), invalid_payload)  # type: ignore[arg-type]


def test_invalid_pin_fails_closed() -> None:
    with pytest.raises(RegulatoryBaselineError, match="RegulatoryArtifactPin"):
        verify_regulatory_artifact_bytes(None, _PAYLOAD)  # type: ignore[arg-type]
