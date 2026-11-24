"""Read-only T10 projection across versioned, company-scoped benefit catalogs."""
from __future__ import annotations

from datetime import date
from typing import Any

from kordena_fiscal.application import federal_benefits_service as federal
from kordena_fiscal.application import state_benefits_service as state
from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.federal_benefits import FACTS_SCHEMA as FEDERAL_FACTS
from kordena_fiscal.tax.state_benefits import FACTS_SCHEMA as STATE_FACTS

ISS_FACTS = "nfcore.municipal-iss-facts/v1"
ISS_RULE = "nfcore.municipal-iss-rule/v1"


def municipal_search(
    store: EconomyStore, snapshot: dict[str, Any], municipality: str, month: date,
) -> dict[str, Any]:
    facts = snapshot["content"]
    if (facts.get("municipality_ibge_code") != municipality
            or facts.get("review_status") != "reviewed" or facts.get("schema_version") != ISS_FACTS
            or not isinstance(facts.get("assessments"), dict)):
        return {"status": "insufficient_basis", "results": [], "coverage_truncated": False}
    rows, truncated = store.municipal_benefit_candidates(
        jurisdiction=municipality, competence=month, schema_version=ISS_RULE,
    )
    results = []
    needs_review = False
    for row in rows:
        rule = row["content"]
        assessment = facts["assessments"].get(row["record_id"])
        if rule.get("review_status") != "reviewed" or rule.get("schema_version") != ISS_RULE:
            needs_review = True
            continue
        try:
            citation = LegalCitation.model_validate(rule["citation"])
            if (citation.act != row["normative_reference"]
                    or citation.valid_from != row["valid_from"]
                    or citation.valid_until != row["valid_until"]
                    or citation.review_reference != rule["review_reference"]
                    or not citation.covers(month.isoformat())
                    or citation.published_on > month.isoformat()
                    or row["jurisdiction"] != municipality or row["tax_code"] != "ISS"
                    or rule["modality"] not in {"exemption", "rate_reduction", "base_reduction"}):
                needs_review = True
                continue
            if (not isinstance(assessment, dict) or assessment.get("criteria_verified") is not True
                    or assessment.get("rule_digest") != row["digest"]
                    or assessment.get("iss_incidence_ibge_code") != municipality
                    or assessment.get("modality") != rule["modality"]
                    or not isinstance(assessment.get("review_reference"), str)
                    or not assessment["review_reference"].strip()):
                needs_review = True
                continue
            before = assessment.get("ordinary_iss_cents")
            after = assessment.get("incentivized_iss_cents")
            estimated = None
            if before is not None or after is not None:
                if type(before) is not int or type(after) is not int or not 0 <= after <= before:
                    needs_review = True
                    continue
                estimated = before - after
            results.append({
                "status": "potential", "benefit_id": row["record_id"],
                "benefit_version": row["version"], "benefit_digest": row["digest"],
                "snapshot_id": snapshot["record_id"], "snapshot_version": snapshot["version"],
                "snapshot_digest": snapshot["digest"], "municipality_ibge_code": municipality,
                "modality": rule["modality"], "legal_act": citation.act,
                "legal_source_references": [citation.source_url], "citation": citation.model_dump(),
                "fact_review_reference": assessment["review_reference"],
                "estimated_cents": estimated,
            })
        except (ValueError, TypeError, KeyError):
            needs_review = True
    return {"status": "review_required" if needs_review or truncated else
            "advisory" if results else "no_reviewed_catalog",
            "results": results, "coverage_truncated": truncated}


def scan_benefits(
    store: EconomyStore, issuer: str, municipality: str | None, month: date,
    verify_federal: federal.IssuerVerifier, verify_state: state.IssuerVerifier,
) -> dict[str, Any]:
    opportunities: list[dict[str, Any]] = []
    coverage = {}
    for source, schema in (("federal", FEDERAL_FACTS), ("state", STATE_FACTS),
                           ("municipal", ISS_FACTS)):
        facts = store.unique_monthly_snapshot(issuer, month, schema)
        if facts is None or (source == "municipal" and not municipality):
            coverage[source] = {"status": "insufficient_basis", "coverage_truncated": False}
            continue
        if source == "municipal":
            assert municipality is not None
            report = municipal_search(store, facts, municipality, month)
        elif source == "state":
            report = state.search_state_benefits(
                store, snapshot_id=facts["record_id"], snapshot_version=facts["version"],
                verify_issuer=verify_state,
            )
        else:
            report = federal.search_federal_benefits(
                store, snapshot_id=facts["record_id"], snapshot_version=facts["version"],
                verify_issuer=verify_federal,
            )
        coverage[source] = {k: report[k] for k in ("status", "coverage_truncated")}
        opportunities.extend({**item, "source": source} for item in report["results"]
                             if item["status"] == "potential")
    opportunities.sort(key=lambda item: (
        item["estimated_cents"] is None, -(item["estimated_cents"] or 0),
        item["source"], item["benefit_id"],
    ))
    return {"schema_version": "nfcore.opportunity-radar/v1", "competence": month.isoformat(),
            "coverage": coverage, "opportunities": opportunities, "advisory_only": True,
            "eligibility_certified": False, "issuance_authorized": False}
