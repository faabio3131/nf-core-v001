"""RTC-04 candidate tests use only synthetic bytes and do not certify tax law."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from kordena_fiscal.compliance.rtc import (
    ReformTaxClassificationSnapshot,
    ReformTaxComponent,
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_calculation_preview import calculate_evidenced_rtc_preview
from kordena_fiscal.compliance.rtc_catalog import (
    load_verified_rtc_classification_catalog,
)
from kordena_fiscal.domain import FiscalValidationError, Money


def _json_bytes(obj: dict[str, object]) -> bytes:
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def _setup(
    *,
    rate_percent: object = "1.25",
    component: object = "cbs",
    quantum: object = "0.01",
    rounding_mode: object = "ROUND_HALF_UP",
) -> tuple[RegulatoryBaseline, bytes, object, ReformTaxClassificationSnapshot]:
    classification_bytes = _json_bytes({
        "schema_version": 1, "artifact_id": "IBSCBS-CCLASSTRIB",
        "artifact_version": "SYNTHETIC-1",
        "records": [{"cst": "000", "cclass_trib": "000001"}],
    })
    rate_bytes = _json_bytes({
        "schema_version": 1, "artifact_id": "RTC-RATE-TEST",
        "artifact_version": "SYNTHETIC-1",
        "component": component, "rate_percent": rate_percent,
        "quantum": quantum, "rounding_mode": rounding_mode,
    })
    baseline = RegulatoryBaseline(
        baseline_id="synthetic-only",
        version=1,
        captured_at=datetime(2026, 10, 31, tzinfo=UTC),
        artifacts=(
            RegulatoryArtifactPin(
                artifact_id="RTC-RATE-TEST",
                kind=RegulatoryArtifactKind.RATE_TABLE,
                version="SYNTHETIC-1",
                published_on=date(2026, 10, 31),
                source_reference="synthetic-fixture-not-official",
                checksum_sha256=sha256(rate_bytes).hexdigest(),
            ),
            RegulatoryArtifactPin(
                artifact_id="IBSCBS-CCLASSTRIB",
                kind=RegulatoryArtifactKind.CLASSIFICATION_TABLE,
                version="SYNTHETIC-1",
                published_on=date(2026, 10, 31),
                source_reference="synthetic-fixture-not-official",
                checksum_sha256=sha256(classification_bytes).hexdigest(),
            ),
        ),
    )
    catalog = load_verified_rtc_classification_catalog(baseline, classification_bytes)
    classification = ReformTaxClassificationSnapshot(
        cst_code="000", classification_code="000001",
        classification_table_version="SYNTHETIC-1",
    )
    return baseline, rate_bytes, catalog, classification


def _preview(
    baseline: RegulatoryBaseline,
    payload: bytes,
    catalog: object,
    classification: ReformTaxClassificationSnapshot,
    *,
    amount: str = "123.45",
):
    return calculate_evidenced_rtc_preview(
        baseline=baseline,
        rate_artifact_id="RTC-RATE-TEST",
        rate_payload=payload,
        catalog=catalog,  # type: ignore[arg-type]
        classification=classification,
        tax_base=Money(Decimal(amount)),
    )


def test_synthetic_preview_uses_decimal_and_pinned_classification() -> None:
    baseline, payload, catalog, classification = _setup()
    result = _preview(baseline, payload, catalog, classification)
    assert result.component is ReformTaxComponent.CBS
    assert result.nominal_rate_percent == Decimal("1.25")
    assert result.tax_amount.amount == Decimal("1.54")
    assert result.classification == classification


@pytest.mark.parametrize(
    ("rate", "reason"),
    [("NaN", "finite"), ("Infinity", "finite"), ("-1", "outside"), ("101", "outside"),
     (1.25, "exact decimal string"), ("oops", "not a Decimal")],
)
def test_invalid_rates_fail_closed(rate: object, reason: str) -> None:
    b, payload, c, cl = _setup(rate_percent=rate)
    with pytest.raises(RegulatoryBaselineError, match=reason):
        _preview(b, payload, c, cl)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [("component", "random_tax", "component"), ("quantum", "0.1", "quantum"),
     ("rounding_mode", "ROUND_DOWN", "rounding")],
)
def test_unapproved_calculation_modes_fail_closed(
    field: str, value: str, reason: str
) -> None:
    kwargs = {field: value}
    b, payload, c, cl = _setup(**kwargs)
    with pytest.raises(RegulatoryBaselineError, match=reason):
        _preview(b, payload, c, cl)


def test_rate_bytes_tampering_fails_digest() -> None:
    b, payload, c, cl = _setup()
    tampered = payload.replace(b"1.25", b"2.25")
    with pytest.raises(RegulatoryBaselineError, match="digest mismatch"):
        _preview(b, tampered, c, cl)


def test_catalog_mutation_fails_closed() -> None:
    b, payload, c, cl = _setup()
    forged = replace(c, artifact_version="FORGED")
    with pytest.raises(RegulatoryBaselineError, match="pinned artifact"):
        _preview(b, payload, forged, cl)


def test_wrong_classification_fails_closed() -> None:
    b, payload, c, cl = _setup()
    mismatch = replace(cl, classification_code="999999")
    with pytest.raises(RegulatoryBaselineError, match="unrecognized"):
        _preview(b, payload, c, mismatch)


def test_negative_base_denied() -> None:
    b, payload, c, cl = _setup()
    with pytest.raises(FiscalValidationError, match="non-negative"):
        _preview(b, payload, c, cl, amount="-1.00")


def test_missing_pin_denied() -> None:
    b, payload, c, cl = _setup()
    missing = replace(b, artifacts=b.artifacts[1:])
    with pytest.raises(RegulatoryBaselineError):
        _preview(missing, payload, c, cl)


def test_rounding_mode_is_selected_by_artifact_not_caller() -> None:
    b1, p1, c1, cl1 = _setup(rate_percent="0.5", rounding_mode="ROUND_HALF_UP")
    b2, p2, c2, cl2 = _setup(rate_percent="0.5", rounding_mode="ROUND_HALF_EVEN")
    assert _preview(b1, p1, c1, cl1, amount="1.00").tax_amount.amount == Decimal("0.01")
    assert _preview(b2, p2, c2, cl2, amount="1.00").tax_amount.amount == Decimal("0.00")
