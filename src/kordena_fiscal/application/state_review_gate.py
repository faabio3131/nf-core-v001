"""Governed internal T09 review attestation, bound to exact fiscal context.

This HMAC is an INTERNAL approval by an authorized operator who controls the
deployment secret. It is NOT the independent accountant's external opinion.
No signing endpoint or signing helper is exposed in the production application.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date
from typing import Any

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.persistence.economy_store import _digest

REVIEW_KEY_ENV = "NFCORE_T09_INTERNAL_REVIEW_KEY"
REVIEW_SCHEMA = "nfcore.t09.internal-curatorial-approval/v1"
_REF = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/+:@-]{2,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def review_claims(
    *,
    policy: dict[str, Any],
    facts: dict[str, Any],
    scope_identity: tuple[str, ...],
    issuer_cnpj: str,
    competence: date,
    benefit_id: str,
    benefit_version: int,
) -> dict[str, Any]:
    """Build deterministic claims; approval signature is generated elsewhere."""
    citations = policy.get("legal_citations")
    if not isinstance(citations, list) or not 1 <= len(citations) <= 10:
        raise FiscalValidationError("state approval requires primary legal citations")
    digests = []
    for citation in citations:
        if not isinstance(citation, dict):
            raise FiscalValidationError("invalid state legal citation")
        value = citation.get("source_sha256")
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise FiscalValidationError("state legal citation has invalid source digest")
        digests.append(value)
    if len(set(digests)) != len(digests):
        # Duplicate source bytes must be reconciled before an approval is issued.
        raise FiscalValidationError("duplicate state legal source digest")
    policy_without_approval = {
        key: value for key, value in policy.items() if key != "internal_review_approval"
    }
    return {
        "schema_version": REVIEW_SCHEMA,
        "scope_digest": _digest({"scope": list(scope_identity)})[1],
        "issuer_cnpj": issuer_cnpj,
        "competence": competence.isoformat(),
        "benefit_id": benefit_id,
        "benefit_version": benefit_version,
        "policy_digest": _digest(policy_without_approval)[1],
        "facts_digest": _digest(facts)[1],
        "legal_source_digests": sorted(digests),
        "review_reference": policy.get("review_reference"),
    }


def verify_internal_review_approval(
    *,
    policy: dict[str, Any],
    facts: dict[str, Any],
    scope_identity: tuple[str, ...],
    issuer_cnpj: str,
    competence: date,
    benefit_id: str,
    benefit_version: int,
) -> None:
    """Fail closed unless a protected operator key signed this exact case."""
    key = os.environ.get(REVIEW_KEY_ENV, "").encode("utf-8")
    if len(key) < 32:
        raise FiscalValidationError("state internal review authority is not configured")
    receipt = policy.get("internal_review_approval")
    if not isinstance(receipt, dict) or set(receipt) != {
        "claims", "reviewer_id", "approved_at", "decision", "signature_hmac_sha256",
    }:
        raise FiscalValidationError("state internal curatorial approval is absent")
    reviewer = receipt["reviewer_id"]
    stamp = receipt["approved_at"]
    if (
        not isinstance(reviewer, str) or _REF.fullmatch(reviewer) is None
        or not isinstance(stamp, str) or not stamp
        or receipt["decision"] != "internal_curatorial_accepted"
    ):
        raise FiscalValidationError("invalid state internal approval identity or decision")
    try:
        from datetime import datetime
        reviewed_at = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise FiscalValidationError("invalid state internal approval date") from exc
    if reviewed_at.tzinfo is None:
        raise FiscalValidationError("state review timestamp must include timezone")
    claims = review_claims(
        policy=policy, facts=facts, scope_identity=scope_identity,
        issuer_cnpj=issuer_cnpj, competence=competence,
        benefit_id=benefit_id, benefit_version=benefit_version,
    )
    if receipt["claims"] != claims:
        raise FiscalValidationError("state approval claims mismatch fiscal case")
    signature = receipt["signature_hmac_sha256"]
    if not isinstance(signature, str) or _SHA256.fullmatch(signature) is None:
        raise FiscalValidationError("invalid state approval signature")
    signed = {key: receipt[key] for key in (
        "claims", "reviewer_id", "approved_at", "decision",
    )}
    canonical = json.dumps(signed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    expected = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise FiscalValidationError("state internal review signature mismatch")
