"""Fail-closed validation of RTC codes against a pinned, normalized catalog.

The payload is a reviewed JSON normalization of an official source. Its hash
protects the reviewed payload's integrity, but does NOT attest that the
normalization itself was faithful to the published government spreadsheet.
No rates or implicit classifications are provided by this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from kordena_fiscal.compliance.rtc import (
    ReformTaxClassificationSnapshot,
    RegulatoryArtifactKind,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_evidence import verify_regulatory_artifact_bytes
from kordena_fiscal.tax import TaxDecision, TaxRule, TaxRuleContext, TaxRuleEngine

# Local construction witness: a catalog object is not verified merely by its type.
# This protects the canonical code path against accidental unpinned synthetic data.
_VERIFIED_CATALOG_WITNESS = object()


@dataclass(frozen=True, slots=True)
class VerifiedRtcClassificationCatalog:
    artifact_version: str
    allowed_pairs: frozenset[tuple[str, str]]
    _verification_witness: (
        tuple[object, str, frozenset[tuple[str, str]]] | None
    ) = field(default=None, repr=False, compare=False)

    def _is_verified(self) -> bool:
        # Replacing a verified dataclass with different codes or version
        # must invalidate its verification provenance.
        return self._verification_witness == (
            _VERIFIED_CATALOG_WITNESS, self.artifact_version, self.allowed_pairs
        )

    def require_classification(self, snapshot: ReformTaxClassificationSnapshot) -> None:
        """Deny unknown codes, including missing classification on nonempty catalogs."""
        if not self._is_verified():
            raise RegulatoryBaselineError("RTC catalog requires pinned artifact verification")
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
    reviewed_pairs = frozenset(pairs)
    return VerifiedRtcClassificationCatalog(
        artifact.version,
        reviewed_pairs,
        _verification_witness=(
            _VERIFIED_CATALOG_WITNESS, artifact.version, reviewed_pairs
        ),
    )


def resolve_rule_with_verified_rtc_catalog(
    *,
    engine: TaxRuleEngine,
    context: TaxRuleContext,
    rules: Iterable[TaxRule],
    catalog: VerifiedRtcClassificationCatalog,
) -> tuple[TaxDecision, ReformTaxClassificationSnapshot]:
    """Bind the existing deterministic rule winner to a version-pinned RTC pair.

    No fallback classification, rate, or fiscal emission is inferred. Callers must
    supply a catalog verified from a reviewed normative artifact via the loader.
    """
    if (
        not isinstance(catalog, VerifiedRtcClassificationCatalog)
        or not catalog._is_verified()
    ):
        raise RegulatoryBaselineError("verified RTC classification catalog required")
    decision = engine.resolve(context, rules)
    outcome = decision.outcome
    if (
        outcome.ibs_cbs_cst_code is None
        or outcome.ibs_cbs_classification_code is None
        or outcome.ibs_cbs_classification_table_version is None
    ):
        raise RegulatoryBaselineError("RTC rule requires explicit CST, cClassTrib and version")
    if outcome.ibs_cbs_classification_table_version != catalog.artifact_version:
        raise RegulatoryBaselineError("RTC tax-rule classification version mismatch")
    snapshot = ReformTaxClassificationSnapshot(
        cst_code=outcome.ibs_cbs_cst_code,
        classification_code=outcome.ibs_cbs_classification_code,
        classification_table_version=outcome.ibs_cbs_classification_table_version,
    )
    catalog.require_classification(snapshot)
    return decision, snapshot


def resolve_strict_rtc_2026_incidence_candidate(
    *,
    engine: TaxRuleEngine,
    context: TaxRuleContext,
    rules: Iterable[TaxRule],
    catalog: VerifiedRtcClassificationCatalog,
) -> tuple[TaxDecision, ReformTaxClassificationSnapshot]:
    """Require a contextual, effective and versioned rule for RTC-04 analysis.

    A catalog only validates a CST/cClassTrib pair; it does not prove that the
    pair has correct legal incidence. This internal candidate is non-issuable.
    In particular a wildcard tax rule cannot justify a 2026 IBS/CBS preview.
    """
    if not isinstance(context, TaxRuleContext) or not isinstance(engine, TaxRuleEngine):
        raise RegulatoryBaselineError("canonical tax context and engine required")
    if context.instant.year != 2026:
        raise RegulatoryBaselineError("incidence candidate supports only 2026")
    # Freeze the iterable so the canonical engine and the later audit see the
    # exact same rule set, including one-shot iterators.
    candidates = tuple(rules)
    decision, snapshot = resolve_rule_with_verified_rtc_catalog(
        engine=engine, context=context, rules=candidates, catalog=catalog,
    )
    winners = [
        rule for rule in candidates
        if rule.rule_id == decision.rule_id and rule.version == decision.rule_version
    ]
    if len(winners) != 1:
        raise RegulatoryBaselineError("winning RTC rule identity must be unique")
    selector = winners[0].selector
    if (
        selector.state_code is None
        or selector.tax_regime is None
        or selector.document_kind is None
        or selector.operation_type is None
        or selector.recipient_profile is None
        or selector.ncm_prefix is None
    ):
        raise RegulatoryBaselineError(
            "RTC incidence candidate requires explicit contextual selectors"
        )
    # The selector is already evaluated by TaxRuleEngine; never independently
    # override its winning rule or its classifications with caller data.
    return decision, snapshot
