"""RTC-03: synthetic rows test trust and integrity, never tax correctness."""

import json
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from kordena_fiscal.compliance import (
    ReformTaxClassificationSnapshot,
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_catalog import load_verified_rtc_classification_catalog


def _payload(rows: list[dict[str, str]] | None = None) -> bytes:
    obj = {
        "schema_version": 1,
        "artifact_id": "IBSCBS-CCLASSTRIB",
        "artifact_version": "SYNTHETIC-v1",
        "records": rows if rows is not None else [
            {"cst": "000", "cclass_trib": "000001"},
        ],
    }
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def _baseline(payload: bytes, *, checksum: str | None = None) -> RegulatoryBaseline:
    return RegulatoryBaseline(
        baseline_id="synthetic-rtc-classification",
        version=1,
        captured_at=datetime(2026, 10, 30, tzinfo=UTC),
        artifacts=(
            RegulatoryArtifactPin(
                artifact_id="IBSCBS-CCLASSTRIB",
                kind=RegulatoryArtifactKind.CLASSIFICATION_TABLE,
                version="SYNTHETIC-v1",
                published_on=date(2026, 10, 30),
                source_reference="synthetic-test-only",
                checksum_sha256=checksum if checksum is not None else sha256(payload).hexdigest(),
            ),
        ),
    )


def _snapshot(cst: str = "000", code: str = "000001", version: str = "SYNTHETIC-v1"):
    return ReformTaxClassificationSnapshot(
        cst_code=cst,
        classification_code=code,
        classification_table_version=version,
    )


def test_catalog_accepts_only_exact_pinned_pair_and_table_version() -> None:
    payload = _payload()
    catalog = load_verified_rtc_classification_catalog(_baseline(payload), payload)
    catalog.require_classification(_snapshot())
    with pytest.raises(RegulatoryBaselineError, match="unrecognized"):
        catalog.require_classification(_snapshot("001", "000001"))
    with pytest.raises(RegulatoryBaselineError, match="unrecognized"):
        catalog.require_classification(_snapshot("000", "000002"))
    with pytest.raises(RegulatoryBaselineError, match="version mismatch"):
        catalog.require_classification(_snapshot(version="OUTDATED"))


def test_catalog_rejects_modified_normalized_payload() -> None:
    payload = _payload()
    changed = _payload([{"cst": "000", "cclass_trib": "000002"}])
    with pytest.raises(RegulatoryBaselineError, match="digest mismatch"):
        load_verified_rtc_classification_catalog(_baseline(payload), changed)


def test_catalog_rejects_missing_hash() -> None:
    payload = _payload()
    baseline = RegulatoryBaseline(
        baseline_id="missing-hash",
        version=1,
        captured_at=datetime(2026, 10, 30, tzinfo=UTC),
        artifacts=(
            RegulatoryArtifactPin(
                artifact_id="IBSCBS-CCLASSTRIB",
                kind=RegulatoryArtifactKind.CLASSIFICATION_TABLE,
                version="SYNTHETIC-v1",
                published_on=date(2026, 10, 30),
                source_reference="synthetic-test-only",
            ),
        ),
    )
    with pytest.raises(RegulatoryBaselineError, match="checksum_sha256 is required"):
        load_verified_rtc_classification_catalog(baseline, payload)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"cst": "000", "cclass_trib": "000001"}] * 2,
        [{"cst": "0", "cclass_trib": "000001"}],
        [{"cst": "000", "cclass_trib": "ABCDEF"}],
        [{"cst": "000", "cclass_trib": "000001", "extra": "unexpected"}],
    ],
)
def test_catalog_rejects_invalid_or_duplicate_rows(rows: list[dict[str, str]]) -> None:
    payload = _payload(rows)
    with pytest.raises(RegulatoryBaselineError):
        load_verified_rtc_classification_catalog(_baseline(payload), payload)


def test_catalog_rejects_invalid_metadata_even_when_sha_matches() -> None:
    payload = _payload()
    raw = json.loads(payload)
    raw["artifact_version"] = "DIFFERENT"
    changed = json.dumps(raw).encode("utf-8")
    with pytest.raises(RegulatoryBaselineError, match="version mismatch"):
        load_verified_rtc_classification_catalog(_baseline(changed), changed)


def test_catalog_denies_credit_code_without_separate_verified_credit_evidence() -> None:
    payload = _payload()
    catalog = load_verified_rtc_classification_catalog(_baseline(payload), payload)
    with pytest.raises(RegulatoryBaselineError, match="cCredPres"):
        catalog.require_classification(
            ReformTaxClassificationSnapshot(
                cst_code="000",
                classification_code="000001",
                classification_table_version="SYNTHETIC-v1",
                presumed_credit_code="000001",
            )
        )


def test_catalog_denies_duplicate_json_keys_even_with_matching_digest() -> None:
    payload = (
        b'{"schema_version":1,"schema_version":1,'
        b'"artifact_id":"IBSCBS-CCLASSTRIB",'
        b'"artifact_version":"SYNTHETIC-v1",'
        b'"records":[{"cst":"000","cst":"000",'
        b'"cclass_trib":"000001"}]}'
    )
    with pytest.raises(RegulatoryBaselineError, match="duplicate"):
        load_verified_rtc_classification_catalog(_baseline(payload), payload)


def test_catalog_rejects_boolean_schema_version() -> None:
    payload = _payload()
    obj = json.loads(payload)
    obj["schema_version"] = True
    malformed = json.dumps(obj).encode("utf-8")
    with pytest.raises(RegulatoryBaselineError, match="schema version"):
        load_verified_rtc_classification_catalog(_baseline(malformed), malformed)
