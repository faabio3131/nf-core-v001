"""Read-only adapter from the T01 canonical records to the T02 contract.

No browser/LLM data can enter this adapter. The authenticated portal resolves the
scope first. Only the minimal deterministic evaluation and reviewed source fields
are projected, never the raw XML, snapshot content or arbitrary stored prose.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from kordena_fiscal.domain import ExecutionScope
from kordena_fiscal.persistence.economy_store import EconomyStore

from .contracts import Capability, Evidence, EvidenceKind, stable_hash
from .economy_contract import (
    AGENTS,
    LEGAL_ORIGIN,
    ORIGIN,
    LegalCitation,
)

EconomyReader = Callable[[ExecutionScope, Capability, str], tuple[Evidence, ...]]


def read_economy_evidence(
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    scope: ExecutionScope,
    capability: Capability,
    subject_id: str,
) -> tuple[Evidence, ...]:
    """Return an exact evaluation with its linked immutable snapshot and rule.

    A newly staged record without full legal and calculation evidence is not a
    candidate. The T03/catalog and T04+ engines produce these fields, not T02.
    """
    if capability not in AGENTS:
        return ()
    with store_factory(scope) as store:
        evaluation = store.record("fm_economy_opportunities", subject_id)
        if evaluation is None:
            return ()
        if evaluation["benefit_id"] is None or evaluation["benefit_version"] is None:
            return ()
        snapshot = store.record(
            "fm_economy_snapshots", evaluation["snapshot_id"], evaluation["snapshot_version"]
        )
        rule = store.record(
            "fm_economy_benefits", evaluation["benefit_id"], evaluation["benefit_version"]
        )
    if snapshot is None or rule is None:
        return ()
    try:
        payload: dict[str, Any] = evaluation["content"]
        if (
            payload["kind"] != AGENTS[capability]
            or payload["rule_digest"] != rule["digest"]
            or payload["snapshot_digest"] != snapshot["digest"]
            or payload["rule_review_reference"] != rule["content"]["review_reference"]
            or rule["content"]["review_status"] != "reviewed"
            or payload["calculation_status"] != "deterministic"
        ):
            return ()
        competence = date.fromisoformat(snapshot["competence"])
        end = date(competence.year + (competence.month == 12), competence.month % 12 + 1, 1)
        if (
            date.fromisoformat(rule["valid_from"]) > competence
            or rule["valid_until"] is not None and date.fromisoformat(rule["valid_until"]) < end
        ):
            return ()
        raw_citations = rule["content"]["legal_citations"]
        if not isinstance(raw_citations, list) or not 1 <= len(raw_citations) <= 8:
            return ()
        citations = tuple(LegalCitation.model_validate(item) for item in raw_citations)
        if any(
            citation.review_reference != rule["content"]["review_reference"]
            or not citation.covers(competence.isoformat())
            for citation in citations
        ):
            return ()
        scope_hash = stable_hash(scope.identity_material)
        rule_ref = {
            "rule_id": str(rule["record_id"]), "rule_version": str(rule["version"]),
            "rule_digest": str(rule["digest"]), "scope_hash": scope_hash,
        }
        for key in ("engine_version", "calculation_reference"):
            if not isinstance(payload[key], str) or not 1 <= len(payload[key].strip()) <= 128:
                return ()
        facts = {
            **rule_ref, "kind": payload["kind"], "record_id": str(evaluation["record_id"]),
            "version": str(evaluation["version"]), "digest": str(evaluation["digest"]),
            "snapshot_id": str(snapshot["record_id"]), "snapshot_version": str(snapshot["version"]),
            "snapshot_digest": str(snapshot["digest"]), "competence": snapshot["competence"],
            "tax_code": rule["tax_code"], "engine_version": payload["engine_version"],
            "calculation_reference": payload["calculation_reference"],
            "estimated_cents": str(evaluation["estimated_cents"]),
        }
        return (
            Evidence(
                "economy:evaluation", EvidenceKind.ECONOMY_EVALUATION,
                scope.tenant_id, scope.unit_id, ORIGIN, facts,
            ),
            *(
                Evidence(
                    f"economy:legal:{index}", EvidenceKind.ECONOMY_LEGAL,
                    scope.tenant_id, scope.unit_id, LEGAL_ORIGIN,
                    {
                        **rule_ref,
                        **{k: str(v) if v is not None else ""
                           for k, v in citation.model_dump().items()},
                    },
                )
                for index, citation in enumerate(citations)
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return ()
