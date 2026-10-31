"""Fail-closed validation of RTC codes against a pinned, normalized catalog.

The payload is a reviewed JSON normalization of an official source. Its hash
protects the reviewed payload's integrity, but does NOT attest that the
normalization itself was faithful to the published government spreadsheet.
No rates or implicit classifications are provided by this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from kordena_fiscal.compliance.rtc import (
    ReformTaxClassificationSnapshot,
    RegulatoryArtifactKind,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_evidence import verify_regulatory_artifact_bytes


@dataclass(frozen=True, slots=True)
class VerifiedRtcClassificationCatalog:
    artifact_version: str
    allowed_pairs: frozenset[tuple[str, str]]

    def require_classification(self, snapshot: ReformTaxClassificationSnapshot) -> None:
        """Deny unknown codes, including missing classification on nonempty catalogs."""
        if not isinstance(snapshot, ReformTaxClassificationSnapshot):
            raise RegulatoryBaselineError("RTC classification snapshot required")
        if snapshot.classification_table_version != self.artifact_version:
            raise RegulatoryBaselineError("RTC classification table version mismatch")
        key = (snapshot.cst_code, snapshot.classification_code or "")
        if key not in self.allowed_pairs:
            raise RegulatoryBaselineError("unrecognized RTC CST/cClassTrib combination")
        if snapshot.presumed_credit_code is not None:
            raise RegulatoryBaselineError(
                "RTC cCredPres requires an independently verified credit catalog"
            )


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject JSON key collisions rather than silently accepting last-write wins."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RegulatoryBaselineError("duplicate RTC normalized catalog JSON key")
        result[key] = value
    return result


def load_verified_rtc_classification_catalog(
    baseline: RegulatoryBaseline,
    artifact_payload: bytes,
    *,
    artifact_id: str = "IBSCBS-CCLASSTRIB",
) -> VerifiedRtcClassificationCatalog:
    """Load reviewed normalized rows after exact digest and baseline pin validation.

    The caller remains responsible for independent official-source validation
    and human approval of the normalized mapping before production use.
    """
    if not isinstance(baseline, RegulatoryBaseline):
        raise RegulatoryBaselineError("regulatory baseline is required")
    artifact = baseline.artifact(artifact_id)
    if artifact.kind is not RegulatoryArtifactKind.CLASSIFICATION_TABLE:
        raise RegulatoryBaselineError("RTC artifact must be a classification table")
    verify_regulatory_artifact_bytes(artifact, artifact_payload)
    try:
        raw = json.loads(artifact_payload, object_pairs_hook=_unique_json_keys)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RegulatoryBaselineError("RTC normalized catalog must be JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "artifact_id", "artifact_version", "records",
    }:
        raise RegulatoryBaselineError("invalid RTC normalized catalog schema")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise RegulatoryBaselineError("RTC normalized catalog schema version mismatch")
    if raw["artifact_id"] != artifact.artifact_id:
        raise RegulatoryBaselineError("RTC normalized catalog identity mismatch")
    if raw["artifact_version"] != artifact.version:
        raise RegulatoryBaselineError("RTC normalized catalog version mismatch")
    rows = raw["records"]
    if not isinstance(rows, list) or not rows:
        raise RegulatoryBaselineError("RTC normalized catalog requires records")
    pairs: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"cst", "cclass_trib"}:
            raise RegulatoryBaselineError("invalid RTC classification row shape")
        cst, classification = row["cst"], row["cclass_trib"]
        if (
            not isinstance(cst, str)
            or len(cst) != 3
            or not cst.isascii()
            or not cst.isdigit()
            or not isinstance(classification, str)
            or len(classification) != 6
            or not classification.isascii()
            or not classification.isdigit()
        ):
            raise RegulatoryBaselineError("invalid RTC CST/cClassTrib code format")
        pairs.append((cst, classification))
    if len(set(pairs)) != len(pairs):
        raise RegulatoryBaselineError("duplicate RTC CST/cClassTrib pair")
    return VerifiedRtcClassificationCatalog(artifact.version, frozenset(pairs))
