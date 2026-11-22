"""T09 read-only internal curation reconciliation; not a fiscal release authority.

This check detects premature promotion in the research files. It neither
validates a signature nor replaces the canonical HMAC/RBAC import boundary.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from kordena_fiscal.tax.state_benefits import _UF_CODES

_DOCS = Path(__file__).resolve().parents[1] / "docs"
_QUEUE = "NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json"
_DRAFTS = "NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json"
_DOSSIERS = "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json"
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_REQUIRED_INTERNAL = (
    "full_amendment_chain_verified",
    "applicability_by_competence_verified",
    "confaz_legal_route_verified",
    "scope_and_negative_cases_legally_grounded",
    "independent_agent_counter_review_passed",
    "technical_tests_certified_for_real_act",
)


def _json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid T09 JSON object: {path.name}")
    return raw


def _index(rows: object, *, kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != 27:
        raise ValueError(f"{kind}: exactly 27 entries required")
    indexed: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError(f"{kind}: invalid record")
        uf, candidate_id = record.get("uf"), record.get("candidate_id")
        if (
            not isinstance(uf, str) or uf not in _UF_CODES or uf in indexed
            or not isinstance(candidate_id, str) or not candidate_id
            or candidate_id in ids
        ):
            raise ValueError(f"{kind}: invalid or duplicated UF/candidate")
        indexed[uf] = record
        ids.add(candidate_id)
    if set(indexed) != set(_UF_CODES):
        raise ValueError(f"{kind}: incomplete UF jurisdiction authority")
    return indexed


def audit_curation(queue: dict[str, Any], drafts: dict[str, Any],
                   dossiers: dict[str, Any]) -> dict[str, Any]:
    """Read-only: reject unauthorized promotion and report each missing gate."""
    items = _index(queue.get("work_items"), kind="curation queue")
    candidates = _index(drafts.get("candidates"), kind="draft policies")
    research = _index(dossiers.get("dossiers"), kind="normative dossiers")
    if any(
        items[uf]["candidate_id"] != candidates[uf]["candidate_id"]
        or items[uf]["candidate_id"] != research[uf]["candidate_id"]
        for uf in _UF_CODES
    ):
        raise ValueError("T09 research and canonical candidate IDs diverged")
    # The research catalog cannot itself authorize fiscal application.
    if (
        drafts.get("approved_for_eligibility") is not False
        or drafts.get("import_authorized") is not False
        or any(drafts.get(k) is not False for k in (
            "legal_source_bytes_archived", "accountant_signoff_received",
        ))
    ):
        raise ValueError("research draft claims an unsupported fiscal release")
    blocked: dict[str, list[str]] = {}
    accepted: list[str] = []
    for uf in sorted(_UF_CODES):
        item, draft, dossier = items[uf], candidates[uf], research[uf]
        if (
            draft.get("review_status") != "draft"
            or any(draft.get(k) is not False for k in (
                "approved_for_eligibility", "import_authorized",
                "eligibility_certified",
            ))
            or draft.get("source_sha256") is not None
            or draft.get("legal_reviewer") is not None
            or item.get("legally_importable") is not False
            or item.get("eligible_for_fiscal_application") is not False
            or dossier.get("import_authorized") is not False
        ):
            raise ValueError(f"{uf}: draft policy prematurely promoted")
        missing = [name for name in _REQUIRED_INTERNAL if item.get(name) is not True]
        if not isinstance(item.get("source_publication_and_original_bytes_digest"), str) or (
            _SHA256.fullmatch(item["source_publication_and_original_bytes_digest"])
            is None
        ):
            missing.append("source_publication_and_original_bytes_digest")
        if item.get("individual_concession_normative_requirement_verified") is not True:
            missing.append("individual_concession_normative_requirement_verified")
        if dossier.get("evidence_status") != "COMPLETE_RESEARCH_HUMAN_APPROVED":
            missing.append("dossier_legal_evidence_complete")
        if dossier.get("independent_counter_review") is not True:
            missing.append("independent_dossier_counter_review")
        approval = item.get("human_approval_record")
        if (
            not isinstance(approval, dict)
            or not all(
                isinstance(approval.get(k), str) and approval[k].strip()
                for k in ("reviewer", "approval_id", "approved_at", "head_sha")
            )
            or _SHA256.fullmatch(approval.get("head_sha", "")) is None
        ):
            missing.append("human_approval_record")
        # Human product approval is a separate action and must never be set
        # by this tool. The validity of a claimed receipt is checked elsewhere.
        if item.get("internal_curatorial_accepted") is True or (
            dossier.get("internal_acceptance") is True
        ):
            if missing or item.get("internal_curatorial_accepted") is not True or (
                dossier.get("internal_acceptance") is not True
            ):
                raise ValueError(f"{uf}: premature or inconsistent curation acceptance")
            accepted.append(uf)
        elif not (
            item.get("internal_curatorial_accepted") is False
            and dossier.get("internal_acceptance") is False
        ):
            raise ValueError(f"{uf}: invalid curation acceptance type")
        if missing:
            blocked[uf] = missing
    return {
        "schema_version": "nfcore.t09.internal-curation-audit/v1",
        "status": "INTERNAL_CURATORIAL_BLOCKED" if blocked else "INTERNAL_RESEARCH_RECORDED",
        "representative_ufs": len(items),
        "internally_accepted_ufs": len(accepted),
        "missing_gates_by_uf": blocked,
        "all_internal_gates_recorded": not blocked,
        "fiscal_application_authorized": False,
        "independent_review_and_human_approval_still_require_proof": True,
    }


def audit_files(root: Path = _DOCS) -> dict[str, Any]:
    return audit_curation(
        _json(root / _QUEUE),
        _json(root / _DRAFTS),
        _json(root / _DOSSIERS),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-closure", action="store_true")
    args = parser.parse_args()
    try:
        report = audit_files()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"T09 integrity or premature promotion gate: {exc}")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.require_closure and not report["all_internal_gates_recorded"]:
        parser.exit(1, "T09 curatorial closure is not certified; do not unblock T10.\n")


if __name__ == "__main__":
    main()
