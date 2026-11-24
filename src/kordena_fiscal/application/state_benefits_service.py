"""T09 state benefits use the existing T01 immutable, tenant-scoped economy store.

Both read and import paths require canonical issuer/UF, reviewed primary state
legislation, full-month validity and explicit evidence. No new fiscal authority.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from kordena_fiscal.application.issuance_terms import reviewed_issuance_terms
from kordena_fiscal.application.state_review_gate import verify_internal_review_approval
from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.tax.state_benefits import (
    ENGINE_VERSION,
    RULE_SCHEMA,
    ReviewedStateIssuer,
    assess_state_rule,
    decode_facts,
    decode_rule,
)

IssuerVerifier = Callable[[str, date], ReviewedStateIssuer]


def _evaluate(
    snapshot: dict[str, Any], benefit: dict[str, Any],
    scope_identity: tuple[str, ...], verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    try:
        competence = date.fromisoformat(snapshot["competence"])
        if competence.day != 1:
            raise FiscalValidationError("invalid monthly state competence")
        facts = decode_facts(snapshot["content"])
        rule = decode_rule(benefit["content"])
        if (
            benefit["tax_code"] != "ICMS"
            or benefit["jurisdiction"] != rule["uf"]
            or benefit["normative_reference"] != rule["state_normative_reference"]
            or date.fromisoformat(benefit["valid_from"]) != rule["valid_from_date"]
            or (
                date.fromisoformat(benefit["valid_until"])
                if benefit["valid_until"] is not None else None
            ) != rule["valid_until_date"]
        ):
            raise FiscalValidationError("state benefit persistence and policy conflict")
        citations = rule.get("legal_citations")
        if not isinstance(citations, list) or not 1 <= len(citations) <= 10:
            raise FiscalValidationError("reviewed state legal citations required")
        legal = tuple(LegalCitation.model_validate(row) for row in citations)
        official_url = rule.get("state_official_source_url")
        if not isinstance(official_url, str) or not official_url:
            raise FiscalValidationError("state primary legislation URL required")
        if not any(
            citation.source_url == official_url
            and citation.act == rule["state_normative_reference"]
            for citation in legal
        ):
            raise FiscalValidationError("verified primary state act citation required")
        if rule["legal_path"] != "state_statute" and not any(
            " ".join(citation.act.casefold().split())
            == " ".join(rule["confaz_normative_reference"].casefold().split())
            for citation in legal
        ):
            raise FiscalValidationError("exact CONFAZ legal citation required")
        if any(
            citation.review_reference != rule["review_reference"]
            or not citation.covers(competence.isoformat())
            for citation in legal
        ):
            raise FiscalValidationError("legal citation review or period incompatible")
        if facts["review_reference"] != rule["review_reference"]:
            raise FiscalValidationError("state fact and policy review references mismatch")
        issuer = verify_issuer(snapshot["issuer_cnpj"], competence)
        if (
            not isinstance(issuer, ReviewedStateIssuer)
            or issuer.scope_identity != scope_identity
            or issuer.cnpj != snapshot["issuer_cnpj"]
        ):
            raise FiscalValidationError("canonical state issuer mismatch")
        verify_internal_review_approval(
            policy=benefit["content"], facts=snapshot["content"],
            scope_identity=scope_identity, issuer_cnpj=issuer.cnpj,
            competence=competence, benefit_id=benefit["record_id"],
            benefit_version=benefit["version"],
        )
        result = assess_state_rule(rule, facts, issuer, competence)
        application = reviewed_issuance_terms(
            benefit["content"], snapshot["content"], benefit["record_id"], benefit["version"],
        )
        if application is not None and result["status"] == "potential":
            result["issuance_application"] = application[0]
        return {
            **result,
            "schema_version": ENGINE_VERSION,
            "benefit_id": benefit["record_id"],
            "benefit_version": benefit["version"],
            "benefit_digest": benefit["digest"],
            "snapshot_id": snapshot["record_id"],
            "snapshot_version": snapshot["version"],
            "snapshot_digest": snapshot["digest"],
            "uf": rule["uf"], "ibge_uf_code": None,
            "benefit_kind": rule["benefit_kind"],
            "legal_path": rule["legal_path"],
            "state_normative_reference": rule["state_normative_reference"],
            "legal_source_references": [c.source_url for c in legal],
            "review_reference": rule["review_reference"],
            "competence": competence.isoformat(),
            "scope_digest": _digest({"scope": list(scope_identity)})[1],
            "tax_reporting_authorized": False,
        }
    except FiscalValidationError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid reviewed state benefit records") from exc


def evaluate_state_benefit(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    benefit_id: str, benefit_version: int, verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    benefit = store.record("fm_economy_benefits", benefit_id, benefit_version)
    if snapshot is None or benefit is None:
        raise FiscalValidationError("state benefit or scoped facts unavailable")
    month = date.fromisoformat(snapshot["competence"])
    if store.benefit_version_at(benefit_id, month) != benefit_version:
        raise FiscalValidationError("state benefit replaced by newer version")
    return _evaluate(snapshot, benefit, store.scope_identity, verify_issuer)


def import_reviewed_state_benefit(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    competence: date, issuer: Cnpj, content: dict[str, Any],
    benefit_id: str, benefit_version: int, benefit_content: dict[str, Any],
    verify_issuer: IssuerVerifier,
    verified_source_bytes: Callable[[dict[str, Any]], int] | None = None,
) -> dict[str, Any]:
    """Validated operational import: legal bytes and signed review are required."""
    if type(competence) is not date or competence.day != 1:
        raise FiscalValidationError("invalid reviewed state import competence")
    if not isinstance(issuer, Cnpj):
        raise FiscalValidationError("invalid state issuer CNPJ")
    rule = decode_rule(benefit_content)
    if verified_source_bytes is None:
        raise FiscalValidationError("state legal source byte verifier is required")
    citations = benefit_content.get("legal_citations")
    if (
        not isinstance(citations, list) or not 1 <= len(citations) <= 10
        or not all(
            isinstance(citation, dict)
            and isinstance(citation.get("source_url"), str)
            for citation in citations
        )
    ):
        raise FiscalValidationError("invalid reviewed state source citations")
    expected_sources = len({citation["source_url"] for citation in citations})
    try:
        verified_sources = verified_source_bytes(benefit_content)
    except (OSError, ValueError, TypeError) as exc:
        raise FiscalValidationError("state legal source verification failed") from exc
    if type(verified_sources) is not int or verified_sources != expected_sources:
        raise FiscalValidationError("state legal source bytes are not all verified")
    snapshot = {
        "record_id": snapshot_id, "version": snapshot_version,
        "issuer_cnpj": issuer.value, "competence": competence.isoformat(),
        "content": content, "digest": _digest(content)[1],
    }
    benefit = {
        "record_id": benefit_id, "version": benefit_version,
        "tax_code": "ICMS", "jurisdiction": rule["uf"],
        "normative_reference": rule["state_normative_reference"],
        "valid_from": rule["valid_from_date"].isoformat(),
        "valid_until": (
            rule["valid_until_date"].isoformat()
            if rule["valid_until_date"] is not None else None
        ),
        "content": benefit_content, "digest": _digest(benefit_content)[1],
    }
    result = _evaluate(snapshot, benefit, store.scope_identity, verify_issuer)
    # Advisory transaction lock is acquired before read/append to prevent
    # competing imports from failing with a duplicate-key race.
    store.lock_state_review_import(snapshot_id, benefit_id)
    for existing, proposed in (
        (store.record("fm_economy_snapshots", snapshot_id, snapshot_version), snapshot),
        (store.record("fm_economy_benefits", benefit_id, benefit_version), benefit),
    ):
        if existing is not None and any(
            existing.get(k) != value for k, value in proposed.items()
        ):
            raise FiscalValidationError("immutable state benefit version conflict")
    if store.record("fm_economy_snapshots", snapshot_id, snapshot_version) is None:
        store.append_snapshot(
            record_id=snapshot_id, version=snapshot_version, competence=competence,
            issuer=issuer, content=content,
        )
    if store.record("fm_economy_benefits", benefit_id, benefit_version) is None:
        store.append_benefit(
            record_id=benefit_id, version=benefit_version, tax_code="ICMS",
            jurisdiction=rule["uf"],
            normative_reference=rule["state_normative_reference"],
            valid_from=rule["valid_from_date"],
            valid_until=rule["valid_until_date"], content=benefit_content,
        )
    return result


def search_state_benefits(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    verify_issuer: IssuerVerifier, limit: int = 500,
) -> dict[str, Any]:
    """State-specific filtering is SQL-backed BEFORE LIMIT, like T08 federal."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise FiscalValidationError("invalid state benefit search limit")
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    if snapshot is None:
        raise FiscalValidationError("scoped state facts unavailable")
    # Even an empty catalog requires canonical taxpayer authority. Otherwise a
    # spoofed snapshot could yield a misleading no_reviewed_catalog response.
    try:
        competence = date.fromisoformat(snapshot["competence"])
        if competence.day != 1:
            raise FiscalValidationError("invalid monthly state competence")
        facts = decode_facts(snapshot["content"])
        cnpj = snapshot["issuer_cnpj"]
        if not isinstance(cnpj, str):
            raise FiscalValidationError("invalid scoped state issuer")
    except FiscalValidationError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid scoped state facts") from exc
    canonical = verify_issuer(cnpj, competence)
    if (
        not isinstance(canonical, ReviewedStateIssuer)
        or canonical.scope_identity != store.scope_identity
        or canonical.cnpj != cnpj
        or canonical.uf != facts["uf"]
        or canonical.primary_cnae != facts["activity_cnae"]
    ):
        raise FiscalValidationError("canonical state issuer mismatch")
    rows, truncated = store.state_benefit_candidates(
        jurisdiction=facts["uf"], competence=competence,
        schema_version=RULE_SCHEMA, limit=limit,
    )
    results = []
    verified_cache: dict[tuple[str, date], ReviewedStateIssuer] = {
        (cnpj, competence): canonical,
    }

    def verified(cnpj: str, month: date) -> ReviewedStateIssuer:
        key = (cnpj, month)
        if key not in verified_cache:
            verified_cache[key] = verify_issuer(cnpj, month)
        return verified_cache[key]

    for row in rows:
        policy = row.get("content")
        if not isinstance(policy, dict) or policy.get("schema_version") != RULE_SCHEMA:
            results.append({
                "benefit_id": row["record_id"], "benefit_version": row["version"],
                "status": "review_required", "reason_codes": ["superseded_policy"],
            })
            continue
        try:
            result = _evaluate(snapshot, row, store.scope_identity, verified)
        except FiscalValidationError:
            results.append({
                "benefit_id": row["record_id"], "benefit_version": row["version"],
                "status": "review_required", "reason_codes": ["unverified_state_rule"],
            })
        else:
            results.append(result)
    statuses = ("potential", "not_applicable", "insufficient_basis", "review_required")
    counts = {status: sum(x["status"] == status for x in results)
              for status in statuses}
    return {
        "schema_version": "nfcore.state-icms-search/v1",
        "uf": facts["uf"], "snapshot_id": snapshot_id,
        "snapshot_version": snapshot_version,
        "status": (
            "review_required" if truncated or counts["review_required"]
            else "no_reviewed_catalog" if not results else "advisory"
        ),
        "counts": counts, "results": results,
        "coverage_truncated": truncated,
        "complete_state_benefit_coverage": False,
        "advisory_only": True, "human_review_required": True,
        "eligibility_certified": False, "issuance_authorized": False,
        "scope_digest": _digest({"scope": list(store.scope_identity)})[1],
    }
