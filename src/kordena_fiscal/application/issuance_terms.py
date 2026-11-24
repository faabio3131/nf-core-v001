"""Exact opt-in operation terms covered by the existing signed T09 policy.

This contract does not install a rule, grant entitlement or authorize a document.
"""

from __future__ import annotations

from typing import Any

from kordena_fiscal.domain import FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.runtime.sale_facts import parse_sale_rule
from kordena_fiscal.tax.models import TaxRule

TERMS_SCHEMA = "nfcore.t14.icms-issuance-terms/v1"


def reviewed_issuance_terms(
    policy: dict[str, Any],
    facts: dict[str, Any],
    benefit_id: str,
    benefit_version: int,
) -> tuple[dict[str, Any], TaxRule] | None:
    """Validate the application terms inside the T09 HMAC-covered material."""
    if "issuance_application" not in policy:
        return None
    terms = policy["issuance_application"]
    if (
        not isinstance(terms, dict)
        or set(terms)
        != {
            "schema_version",
            "sale_rule",
            "issuer_profile_id",
            "issuer_profile_version",
            "product_id",
            "product_profile_id",
            "product_profile_version",
            "product_origin",
            "no_cumulative_cap",
            "application_reference",
        }
        or terms["schema_version"] != TERMS_SCHEMA
    ):
        raise FiscalValidationError("invalid T14 issuance terms")
    for field in ("issuer_profile_id", "product_id", "product_profile_id", "application_reference"):
        value = terms[field]
        if not isinstance(value, str) or not 1 <= len(value) <= 128 or value.strip() != value:
            raise FiscalValidationError("invalid reviewed issuance identity")
    for field in ("issuer_profile_version", "product_profile_version"):
        if type(terms[field]) is not int or terms[field] < 1:
            raise FiscalValidationError("invalid reviewed issuance version")
    if (
        type(terms["product_origin"]) is not int
        or terms["product_origin"] != 0
        or terms["no_cumulative_cap"] is not True
        or policy.get("program_id") is not None
        or policy.get("individual_concession_required") is not False
        or facts.get("evidence", {}).get("issuance_application_review")
        != terms["application_reference"]
    ):
        raise FiscalValidationError("T14 requires explicit ordinary unrestricted operation review")
    rule = parse_sale_rule(terms["sale_rule"], document_kind=FiscalDocumentKind.NFE)
    rates = rule.outcome.nfe_rates
    if rates is None or rates.icms_benefit is None:
        raise FiscalValidationError("reviewed issuance rule requires ICMS benefit")
    benefit = rates.icms_benefit
    selector = rule.selector
    cst = rule.outcome.icms_code
    kind = {"20": "base_reduction", "40": "exemption", "51": "deferral"}.get(cst)
    if (
        kind is None
        or policy.get("benefit_kind") != kind
        or policy.get("uf") not in {"SP", "MG"}
        or selector.state_code != policy["uf"]
        or selector.destination_state_code != policy["uf"]
        or facts.get("operation") != "domestic_sale"
        or selector.ncm_prefix != facts.get("operation_ncm")
        or rule.outcome.cfop != facts.get("operation_cfop")
        or not rule.outcome.cfop.startswith("5")
        or rule.source_normative != policy.get("state_normative_reference")
        or rule.version != benefit_version
        or benefit.benefit_id != benefit_id
        or benefit.approval_reference != policy.get("review_reference")
        or benefit.reviewed_by != policy.get("internal_review_approval", {}).get("reviewer_id")
        or (cst in {"20", "40"} and benefit.deson_rate is None)
        or (cst == "51" and benefit.deferral_rate is None)
        or any(
            value is not None
            for value in (
                rates.st_rate,
                rates.fcp_rate,
                rates.difal_destination_rate,
                rates.ipi_rate,
                rates.ipi_unit_amount,
                rates.rtc_uf_rate,
                rates.rtc_municipal_rate,
                rates.rtc_cbs_rate,
            )
        )
        or rule.outcome.ibs_cbs_classification_code is not None
    ):
        raise FiscalValidationError("reviewed fiscal application outside supported T14 scope")
    return terms, rule
