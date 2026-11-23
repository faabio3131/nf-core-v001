"""Sergipe PSDI normative pre-triage: NO entitlement or ICMS amount.

Grounding: ALESE Lei 3.140/1991 compilation §§3, 5, 5-B, 10, 17, 31;
art.4 §3 (Lei 9.812/2025), art.8; Lei 9.943/2026.
Decreto 29.935/2014 art.5 and Decs 820/868/2024 need temporal cotejo.
This is a fail-closed prerequisite for a separately signed reviewed state rule,
NOT an executable fiscal concession or real benefit calculator.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

MODES = frozenset({"new_industry_8", "new_industry_6_2", "domestic_raw_deferral"})


def _advisory(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason_codes": [reason],
        "advisory_only": True,
        "legal_eligibility_certified": False,
        "tax_calculation_authorized": False,
        "issuance_authorized": False,
        "rate_applied": None,
        "approved_cents": None,
    }


def assess_se_psdi_context(context: object, competence: date) -> dict[str, Any]:
    """Only synthetic conditional 'potential' after ALL input evidence gates."""
    if not isinstance(context, dict):
        return _advisory("insufficient_basis", "se_psdi_context_missing")
    mode = context.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        return _advisory("not_applicable", "se_psdi_modality_unverified")
    if competence.year < 1991 or competence.year > 2100:
        return _advisory("not_applicable", "se_psdi_competence_out_of_scope")

    # Any unsupported legal route must block the entire fiscal profile.
    for key in (
        "alese_amendments_by_competence_checked",
        "decree_29935_and_amendments_checked",
        "confaz_specific_modal_route_checked",
        "cdi_resolution_signed_and_published",
        "operation_ncm_cfop_cnae_reviewed",
        "state_icms_st_difal_checked",
    ):
        if context.get(key) is not True:
            return _advisory("insufficient_basis", f"se_psdi_missing:{key}")

    if context.get("current_simples_taxpayer") is not False:
        return _advisory("not_applicable", "se_psdi_current_simples_excluded")
    if context.get("cdi_grant_status") != "active":
        status = context.get("cdi_grant_status")
        if isinstance(status, str) and status in {"revoked", "suspended", "expired", "denied"}:
            return _advisory("insufficient_basis", f"se_psdi_grant_{status}")
        return _advisory("insufficient_basis", "se_psdi_active_grant_missing")
    if context.get("operation_authorized_by_resolution") is not True:
        return _advisory("not_applicable", "se_psdi_operation_outside_cdi_scope")
    if context.get("maintenance_and_compliance_confirmed") is not True:
        return _advisory("insufficient_basis", "se_psdi_grant_maintenance_missing")
    if context.get("cdi_cnpj_match") is not True:
        return _advisory("insufficient_basis", "se_psdi_wrong_taxpayer_grant")
    try:
        start = date.fromisoformat(context["grant_valid_from"])
        last = date.fromisoformat(context["grant_valid_through"])
    except (KeyError, TypeError, ValueError):
        return _advisory("insufficient_basis", "se_psdi_grant_dates_missing")
    next_month = date(competence.year + (competence.month == 12),
                      competence.month % 12 + 1, 1)
    if start > competence or last < next_month - timedelta(days=1):
        # A monthly status cannot infer an intramonth legal concession.
        return _advisory("not_applicable", "se_psdi_not_effective_full_month")
    if context.get("operational_mode") != "reviewed_2026":
        return _advisory("insufficient_basis", "se_psdi_context_version_missing")

    if mode == "domestic_raw_deferral":
        if context.get("operation") != "domestic_raw_material_input":
            return _advisory("not_applicable", "se_psdi_not_internal_raw_input")
        if context.get("used_in_incentivized_industrial_process") is not True:
            return _advisory("not_applicable", "se_psdi_raw_material_use_excluded")
        if context.get("deferred_tax_due_at_output_acknowledged") is not True:
            return _advisory("insufficient_basis", "se_psdi_deferred_tax_trigger_missing")
        if (context.get("input_credit_accumulation") is True
                and context.get("export_exception_applicable") is not True):
            return _advisory("not_applicable", "se_psdi_art3_5b_input_credit_prohibited")
        # Dec. 868/2024 art. 5 §§5-C to 5-G: do not stack incentives;
        # excess input credits are reversed per period/industrial consumption.
        if context.get("other_fiscal_incentive_on_same_operation") is not False:
            return _advisory(
                "not_applicable", "se_psdi_868_5e_non_cumulative_incentive",
            )
        if context.get("period_credit_excess_reversal_reviewed") is not True:
            return _advisory(
                "insufficient_basis", "se_psdi_868_5c_excess_reversal_missing",
            )
        if context.get("reversal_proportional_to_material_used") is not True:
            return _advisory(
                "insufficient_basis", "se_psdi_868_5d_proportional_reversal_missing",
            )
        if context.get("deferred_tax_included_in_output_icms") is not True:
            return _advisory(
                "insufficient_basis", "se_psdi_868_5f_output_inclusion_missing",
            )
        if context.get("chemical_plastic_industry") is True and (
            context.get("annex_iii_material_legally_classified") is not True
        ):
            return _advisory(
                "not_applicable", "se_psdi_868_5g_annex_iii_scope_unverified",
            )
        if context.get("regulatory_credit_reversal_checked") is not True:
            return _advisory("insufficient_basis", "se_psdi_art3_5b_credit_reversal_unverified")
        return _advisory("potential", "se_psdi_domestic_raw_deferral_expert_review")

    if context.get("operation") != "incentivized_industrial_own_activity":
        return _advisory("not_applicable", "se_psdi_operation_not_own_activity")
    if context.get("enterprise_type") not in {"new", "post_simples"}:
        return _advisory("not_applicable", "se_psdi_8_or_6_2_requires_new_industry")
    if context.get("enterprise_type") == "post_simples":
        if (context.get("simples_disqualification_documented") is not True
                or context.get("cdi_new_enterprise_category_accepted") is not True):
            return _advisory("insufficient_basis", "se_psdi_9812_disqualification_unverified")
        try:
            disqualified_at = date.fromisoformat(context["disqualified_at"])
        except (ValueError, TypeError, KeyError):
            return _advisory("insufficient_basis", "se_psdi_9812_disqualification_date_missing")
        if disqualified_at > competence:
            return _advisory("not_applicable", "se_psdi_9812_disqualification_not_effective")
    elif context.get("new_enterprise_one_year_requirement_reviewed") is not True:
        return _advisory("insufficient_basis", "se_psdi_art4_new_enterprise_review_missing")
    if mode == "new_industry_6_2":
        if (context.get("semiarid_or_border_municipality_verified") is not True
                and context.get("cdi_relevant_project_exception_verified") is not True):
            return _advisory("not_applicable", "se_psdi_6_2_specific_condition_missing")
        if context.get("individual_cdi_resolution_percentage") != "6.2":
            return _advisory("insufficient_basis", "se_psdi_6_2_not_in_cdi_resolution")
    elif context.get("individual_cdi_resolution_percentage") != "8":
        return _advisory("insufficient_basis", "se_psdi_8_not_in_cdi_resolution")
    return _advisory("potential", "se_psdi_industry_expert_review_required")
