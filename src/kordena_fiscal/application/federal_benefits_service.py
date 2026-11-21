"""T08 read-only federal-benefit assessment on T01 immutable reviewed records.

Only trusted importers write. The browser supplies record IDs, never benefit
rules or tax inputs. Deterministic triage is not legal eligibility or approval.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.tax.federal_benefits import (
    ENGINE_VERSION,
    RULE_SCHEMA,
    ReviewedFederalIssuer,
    assess_federal_program,
    decode_facts,
    decode_policy,
)

IssuerVerifier = Callable[[str, date], ReviewedFederalIssuer]


def _month_end(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def _evaluate(
    snapshot: dict[str, Any], benefit: dict[str, Any],
    scope_identity: tuple[str, ...], verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    try:
        content = snapshot["content"]
        policy = benefit["content"]
        competence = date.fromisoformat(snapshot["competence"])
        if competence.day != 1:
            raise FiscalValidationError("competence must begin on first day")
        if not isinstance(content, dict) or not isinstance(policy, dict):
            raise FiscalValidationError("reviewed federal records required")
        program, allowed, cnae_scope, cnaes, ncm_scope, ncms, evidence_keys = (
            decode_policy(policy)
        )
        cnae, ncm, operation, evidence = decode_facts(content)
        if (
            benefit["jurisdiction"] != "BR"
            or benefit["tax_code"] != program.tax_code
            or benefit["normative_reference"] != program.legal_act
            or date.fromisoformat(benefit["valid_from"]) > competence
            or benefit["valid_until"] is not None
            and date.fromisoformat(benefit["valid_until"]) < _month_end(competence)
        ):
            raise FiscalValidationError("federal benefit is not valid in competence")
        citations_raw = policy["legal_citations"]
        if not isinstance(citations_raw, list) or not 1 <= len(citations_raw) <= 8:
            raise FiscalValidationError("reviewed federal legal citations required")
        citations = tuple(LegalCitation.model_validate(row) for row in citations_raw)
        if not any(c.source_url == program.official_url for c in citations):
            raise FiscalValidationError("federal benefit primary official source required")
        if any(
            c.review_reference != policy["review_reference"]
            or not c.covers(competence.isoformat())
            for c in citations
        ):
            raise FiscalValidationError("legal review reference or validity mismatch")
        issuer = verify_issuer(snapshot["issuer_cnpj"], competence)
        if (
            not isinstance(issuer, ReviewedFederalIssuer)
            or issuer.scope_identity != scope_identity
            or issuer.cnpj != snapshot["issuer_cnpj"]
            or issuer.cnae != cnae
        ):
            raise FiscalValidationError("federal issuer profile does not match canonical facts")
        result = assess_federal_program(
            program=program, competence=competence, issuer=issuer,
            activity_cnae=cnae, operation_ncm=ncm, operation=operation,
            allowed_regimes=allowed, cnae_scope=cnae_scope, allowed_cnaes=cnaes,
            ncm_scope=ncm_scope, allowed_ncms=ncms,
            required_evidence=evidence_keys, evidence=evidence,
        )
        return {
            **result,
            "schema_version": ENGINE_VERSION,
            "program_code": program.code,
            "competence": competence.isoformat(),
            "snapshot_id": snapshot["record_id"],
            "snapshot_version": snapshot["version"],
            "snapshot_digest": snapshot["digest"],
            "benefit_id": benefit["record_id"],
            "benefit_version": benefit["version"],
            "benefit_digest": benefit["digest"],
            "rule_review_reference": policy["review_reference"],
            "fact_review_reference": content["review_reference"],
            "legal_source_references": [c.source_url for c in citations],
            "scope_digest": _digest({"scope": list(scope_identity)})[1],
            # This engine is only a candidate screening; T13/T14 own human
            # approval and all authoritatively applied fiscal effects.
            "tax_calculation_authorized": False,
            "tax_reporting_authorized": False,
        }
    except FiscalValidationError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid reviewed federal benefit evidence") from exc


def evaluate_federal_benefit(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    benefit_id: str, benefit_version: int, verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    benefit = store.record("fm_economy_benefits", benefit_id, benefit_version)
    if snapshot is None or benefit is None:
        raise FiscalValidationError("scoped federal facts or benefit version unavailable")
    latest = store.record("fm_economy_benefits", benefit_id)
    if latest is not None and latest["version"] > benefit_version:
        month = date.fromisoformat(snapshot["competence"])
        # A newer policy overlapping ANY part of this competence supersedes
        # the old version for triage; partial-month revisions require review.
        if date.fromisoformat(latest["valid_from"]) < _month_end(month) and (
            latest["valid_until"] is None
            or date.fromisoformat(latest["valid_until"]) >= month
        ):
            raise FiscalValidationError("federal benefit version superseded for competence")
    return _evaluate(snapshot, benefit, store.scope_identity, verify_issuer)


def import_reviewed_federal_benefit(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    competence: date, issuer: Cnpj, content: dict[str, Any],
    benefit_id: str, benefit_version: int, benefit_content: dict[str, Any],
    verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    """Validate all inputs and replay invariants before any T01 insert.

    The source bundle is privileged, out-of-band and human-reviewed. It is not
    an endpoint for AI, browsers or arbitrary tenant-provided fiscal metadata.
    """
    if not isinstance(issuer, Cnpj) or type(competence) is not date:
        raise FiscalValidationError("invalid trusted federal import identifiers")
    program, *_ = decode_policy(benefit_content)
    valid_from = date.fromisoformat(benefit_content["valid_from"])
    valid_until = (
        date.fromisoformat(benefit_content["valid_until"])
        if benefit_content.get("valid_until") is not None else None
    )
    if valid_until is not None and valid_until <= valid_from:
        raise FiscalValidationError("invalid federal normative interval")
    snapshot = {
        "record_id": snapshot_id, "version": snapshot_version,
        "competence": competence.isoformat(), "issuer_cnpj": issuer.value,
        "content": content, "digest": _digest(content)[1],
    }
    benefit = {
        "record_id": benefit_id, "version": benefit_version,
        "tax_code": program.tax_code, "jurisdiction": "BR",
        "normative_reference": program.legal_act,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until is not None else None,
        "content": benefit_content, "digest": _digest(benefit_content)[1],
    }
    result = _evaluate(snapshot, benefit, store.scope_identity, verify_issuer)
    old_snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    old_benefit = store.record("fm_economy_benefits", benefit_id, benefit_version)
    for existing, proposed in (
        (old_snapshot, snapshot), (old_benefit, benefit),
    ):
        if existing is not None and any(existing.get(k) != value
                                        for k, value in proposed.items()):
            raise FiscalValidationError("immutable federal benefit version conflict")
    if old_snapshot is None:
        store.append_snapshot(
            record_id=snapshot_id, version=snapshot_version, competence=competence,
            issuer=issuer, content=content,
        )
    if old_benefit is None:
        store.append_benefit(
            record_id=benefit_id, version=benefit_version,
            tax_code=program.tax_code, jurisdiction="BR",
            normative_reference=program.legal_act,
            valid_from=valid_from, valid_until=valid_until, content=benefit_content,
        )
    return result



def search_federal_benefits(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    verify_issuer: IssuerVerifier, limit: int = 500,
) -> dict[str, Any]:
    """Search reviewed federal rules within the existing T01 tenant/unit partition.

    Latest version wins even if it is revoked or invalid: older policy must not
    reappear as a candidate. Never search global sources as if granted benefits.
    """
    if type(limit) is not int or not 1 <= limit <= 500:
        raise FiscalValidationError("invalid federal benefit search limit")
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    if snapshot is None:
        raise FiscalValidationError("scoped federal facts unavailable")
    rows = store.records(
        "fm_economy_benefits", limit=limit, schema_version=RULE_SCHEMA,
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        policy = row.get("content")
        if not isinstance(policy, dict) or policy.get("schema_version") != RULE_SCHEMA:
            continue
        key = str(row["record_id"])
        if key not in latest or row["version"] > latest[key]["version"]:
            latest[key] = row
    outcomes: list[dict[str, Any]] = []
    cache: dict[tuple[str, date], ReviewedFederalIssuer] = {}

    def verified(issuer: str, competence: date) -> ReviewedFederalIssuer:
        key = (issuer, competence)
        if key not in cache:
            cache[key] = verify_issuer(issuer, competence)
        return cache[key]

    for benefit in sorted(latest.values(), key=lambda b: str(b["record_id"])):
        policy = benefit["content"]
        newest = store.record("fm_economy_benefits", benefit["record_id"])
        # Do not resurrect an older rule if a newer version changed schema,
        # was revoked, or is otherwise outside the filtered search page.
        if newest is None or newest["version"] != benefit["version"]:
            outcomes.append({
                "benefit_id": benefit["record_id"], "benefit_version": benefit["version"],
                "status": "review_required", "reason_codes": ["newer_policy_not_reviewed"],
            })
            continue
        if policy.get("review_status") != "reviewed":
            outcomes.append({
                "benefit_id": benefit["record_id"], "benefit_version": benefit["version"],
                "status": "review_required", "reason_codes": ["rule_not_reviewed"],
            })
            continue
        try:
            result = _evaluate(snapshot, benefit, store.scope_identity, verified)
        except FiscalValidationError:
            outcomes.append({
                "benefit_id": benefit["record_id"], "benefit_version": benefit["version"],
                "status": "review_required", "reason_codes": ["invalid_reviewed_evidence"],
            })
        else:
            outcomes.append(result)
    counts = {
        state: sum(row["status"] == state for row in outcomes)
        for state in ("potential", "insufficient_basis", "not_applicable", "review_required")
    }
    return {
        "schema_version": "nfcore.federal-benefit-search/v1",
        "status": ("review_required" if counts["review_required"] or len(rows) == limit
                   else "no_reviewed_catalog" if not outcomes else "advisory"),
        "advisory_only": True, "issuance_authorized": False,
        "eligibility_certified": False, "complete_national_coverage": False,
        "coverage_truncated": len(rows) == limit, "review_required": True,
        "snapshot_id": snapshot_id, "snapshot_version": snapshot_version,
        "scope_digest": _digest({"scope": list(store.scope_identity)})[1],
        "counts": counts, "results": outcomes,
    }
