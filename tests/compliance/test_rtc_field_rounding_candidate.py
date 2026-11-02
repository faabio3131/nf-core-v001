"""No production rounding rules are provided: all rates/policies are synthetic."""
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from kordena_fiscal.compliance.rtc import (
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_calculation_preview import (
    calculate_pinned_rtc_field_rounding_candidate,
)
from kordena_fiscal.domain import FiscalValidationError


def _fixture(*, mode: str = "ROUND_HALF_UP", quantum: str = "0.0001"):
    payload = json.dumps(
        {
            "schema_version": 1,
            "artifact_id": "RTC-ROUND-TEST",
            "artifact_version": "SYNTHETIC-v1",
            "field_name": "pAliqEfet",
            "quantum": quantum,
            "rounding_mode": mode,
        },
        sort_keys=True,
    ).encode("utf-8")
    artifact = RegulatoryArtifactPin(
        artifact_id="RTC-ROUND-TEST",
        kind=RegulatoryArtifactKind.TECHNICAL_NOTE,
        version="SYNTHETIC-v1",
        published_on=date(2026, 1, 1),
        source_reference="synthetic-test-only",
        effective_from=date(2026, 1, 1),
        checksum_sha256=sha256(payload).hexdigest(),
    )
    baseline = RegulatoryBaseline(
        baseline_id="synthetic-rounding-policy",
        version=1,
        captured_at=datetime(2026, 9, 1, tzinfo=UTC),
        artifacts=(artifact,),
    )
    return baseline, payload


def _round(**kwargs: object):
    baseline, payload = _fixture()
    fields: dict[str, object] = {
        "baseline": baseline,
        "artifact_id": "RTC-ROUND-TEST",
        "policy_payload": payload,
        "field_name": "pAliqEfet",
        "amount": Decimal("1.23445"),
        "instant": datetime(2026, 9, 1, tzinfo=UTC),
    }
    fields.update(kwargs)
    return calculate_pinned_rtc_field_rounding_candidate(**fields)  # type: ignore[arg-type]


def test_rounding_candidate_is_not_fiscally_authoritative() -> None:
    rounded = _round()
    assert rounded.unrounded == Decimal("1.23445")
    assert rounded.candidate == Decimal("1.2345")
    assert rounded.authoritative is False
    assert rounded.technical_note_version == "SYNTHETIC-v1"


def test_rounding_policy_explicitly_controls_tie_break() -> None:
    baseline, payload = _fixture(mode="ROUND_HALF_EVEN")
    rounded = _round(baseline=baseline, policy_payload=payload)
    assert rounded.candidate == Decimal("1.2344")


@pytest.mark.parametrize("bad_field", ["vFoo", "pRedAliq", "", None])
def test_rounding_candidate_rejects_unsupported_fields(bad_field: object) -> None:
    with pytest.raises(RegulatoryBaselineError, match="unsupported RTC rounding field"):
        _round(field_name=bad_field)


def test_rounding_candidate_denies_tampered_bytes() -> None:
    _, different = _fixture(mode="ROUND_HALF_EVEN")
    with pytest.raises(RegulatoryBaselineError):
        _round(policy_payload=different)


def test_rounding_candidate_denies_unpublished_or_unpinned_note() -> None:
    baseline, payload = _fixture()
    late = replace(baseline.artifacts[0], effective_from=date(2026, 10, 1))
    with pytest.raises(RegulatoryBaselineError, match="not published/effective"):
        _round(baseline=replace(baseline, artifacts=(late,)), policy_payload=payload)
    with pytest.raises(RegulatoryBaselineError):
        _round(baseline=replace(baseline, artifacts=(replace(late, checksum_sha256=None),)))


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("NaN"), "1.25", None])
def test_rounding_candidate_denies_invalid_amount(bad: object) -> None:
    with pytest.raises(FiscalValidationError, match="nonnegative finite Decimal"):
        _round(amount=bad)


def test_rounding_candidate_denies_policy_field_or_version_conflict() -> None:
    baseline, payload = _fixture()
    changed = payload.replace(b"pAliqEfet", b"vIBSUF")
    tampered = replace(baseline.artifacts[0], checksum_sha256=sha256(changed).hexdigest())
    with pytest.raises(RegulatoryBaselineError, match="field mismatch"):
        _round(baseline=replace(baseline, artifacts=(tampered,)), policy_payload=changed)
    changed_version = replace(baseline.artifacts[0], version="other")
    with pytest.raises(RegulatoryBaselineError, match="artifact mismatch"):
        _round(baseline=replace(baseline, artifacts=(changed_version,)), policy_payload=payload)
