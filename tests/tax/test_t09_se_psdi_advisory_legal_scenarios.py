"""PSDI conditional eligibility by exact legal mode, no tax entitlement."""
from __future__ import annotations

from datetime import date

import pytest

from kordena_fiscal.tax.se_psdi_advisory import assess_se_psdi_context

MONTH = date(2026, 11, 1)


def _context(mode="new_industry_8", **changes):
    context = {
        "mode": mode,
        "operational_mode": "reviewed_2026",
        "alese_amendments_by_competence_checked": True,
        "decree_29935_and_amendments_checked": True,
        "confaz_specific_modal_route_checked": True,
        "cdi_resolution_signed_and_published": True,
        "operation_ncm_cfop_cnae_reviewed": True,
        "state_icms_st_difal_checked": True,
        "current_simples_taxpayer": False,
        "cdi_grant_status": "active",
        "operation_authorized_by_resolution": True,
        "maintenance_and_compliance_confirmed": True,
        "cdi_cnpj_match": True,
        "grant_valid_from": "2026-01-01",
        "grant_valid_through": "2026-12-31",
        "operation": "incentivized_industrial_own_activity",
        "enterprise_type": "new",
        "new_enterprise_one_year_requirement_reviewed": True,
        "individual_cdi_resolution_percentage": "8",
    }
    context.update(changes)
    return context


@pytest.mark.parametrize("mode,changes", [
    ("new_industry_8", {}),
    ("new_industry_6_2", {
        "individual_cdi_resolution_percentage": "6.2",
        "semiarid_or_border_municipality_verified": True,
    }),
    ("new_industry_6_2", {
        "individual_cdi_resolution_percentage": "6.2",
        "cdi_relevant_project_exception_verified": True,
    }),
    ("new_industry_8", {
        "enterprise_type": "post_simples",
        "simples_disqualification_documented": True,
        "disqualified_at": "2026-02-01",
        "cdi_new_enterprise_category_accepted": True,
    }),
    ("domestic_raw_deferral", {
        "operation": "domestic_raw_material_input",
        "used_in_incentivized_industrial_process": True,
        "deferred_tax_due_at_output_acknowledged": True,
        "regulatory_credit_reversal_checked": True,
        "input_credit_accumulation": False,
        "other_fiscal_incentive_on_same_operation": False,
        "period_credit_excess_reversal_reviewed": True,
        "reversal_proportional_to_material_used": True,
        "deferred_tax_included_in_output_icms": True,
    }),
    ("domestic_raw_deferral", {
        "operation": "domestic_raw_material_input",
        "used_in_incentivized_industrial_process": True,
        "deferred_tax_due_at_output_acknowledged": True,
        "regulatory_credit_reversal_checked": True,
        "input_credit_accumulation": True,
        "export_exception_applicable": True,
    }),
])
def test_only_hypothetical_potential_not_tax_approval(mode, changes):
    result = assess_se_psdi_context(_context(mode, **changes), MONTH)
    assert result["status"] == "potential"
    assert result["advisory_only"] is True
    assert result["legal_eligibility_certified"] is False
    assert result["tax_calculation_authorized"] is False
    assert result["issuance_authorized"] is False
    assert result["rate_applied"] is None
    assert result["approved_cents"] is None


@pytest.mark.parametrize("updates,reason", [
    ({"cdi_resolution_signed_and_published": False},
     "se_psdi_missing:cdi_resolution_signed_and_published"),
    ({"confaz_specific_modal_route_checked": False},
     "se_psdi_missing:confaz_specific_modal_route_checked"),
    ({"decree_29935_and_amendments_checked": False},
     "se_psdi_missing:decree_29935_and_amendments_checked"),
    ({"current_simples_taxpayer": True}, "se_psdi_current_simples_excluded"),
    ({"cdi_grant_status": "revoked"}, "se_psdi_grant_revoked"),
    ({"cdi_grant_status": "suspended"}, "se_psdi_grant_suspended"),
    ({"cdi_grant_status": "expired"}, "se_psdi_grant_expired"),
    ({"cdi_grant_status": "denied"}, "se_psdi_grant_denied"),
    ({"cdi_cnpj_match": False}, "se_psdi_wrong_taxpayer_grant"),
    ({"maintenance_and_compliance_confirmed": False},
     "se_psdi_grant_maintenance_missing"),
    ({"operation_authorized_by_resolution": False},
     "se_psdi_operation_outside_cdi_scope"),
    ({"grant_valid_from": "2026-11-15"}, "se_psdi_not_effective_full_month"),
    ({"grant_valid_through": "2026-11-15"},
     "se_psdi_not_effective_full_month"),
    ({"operation": "interstate_sale"}, "se_psdi_operation_not_own_activity"),
    ({"individual_cdi_resolution_percentage": "6.2"},
     "se_psdi_8_not_in_cdi_resolution"),
    ({"enterprise_type": "post_simples",
      "simples_disqualification_documented": False},
     "se_psdi_9812_disqualification_unverified"),
    ({"enterprise_type": "post_simples",
      "simples_disqualification_documented": True,
      "cdi_new_enterprise_category_accepted": True,
      "disqualified_at": "2026-12-01"},
     "se_psdi_9812_disqualification_not_effective"),
    ({"new_enterprise_one_year_requirement_reviewed": False},
     "se_psdi_art4_new_enterprise_review_missing"),
])
def test_prohibition_by_normative_evidence(updates, reason):
    result = assess_se_psdi_context(_context(**updates), MONTH)
    assert result["status"] != "potential"
    assert result["reason_codes"] == [reason]
    assert result["tax_calculation_authorized"] is False


@pytest.mark.parametrize("changes,reason", [
    ({"used_in_incentivized_industrial_process": False},
     "se_psdi_raw_material_use_excluded"),
    ({"deferred_tax_due_at_output_acknowledged": False},
     "se_psdi_deferred_tax_trigger_missing"),
    ({"input_credit_accumulation": True},
     "se_psdi_art3_5b_input_credit_prohibited"),
    ({"regulatory_credit_reversal_checked": False},
     "se_psdi_art3_5b_credit_reversal_unverified"),
])
def test_9494_2024_internal_input_and_credit_guards(changes, reason):
    data = _context(
        mode="domestic_raw_deferral",
        operation="domestic_raw_material_input",
        used_in_incentivized_industrial_process=True,
        deferred_tax_due_at_output_acknowledged=True,
        regulatory_credit_reversal_checked=True,
        input_credit_accumulation=False,
        other_fiscal_incentive_on_same_operation=False,
        period_credit_excess_reversal_reviewed=True,
        reversal_proportional_to_material_used=True,
        deferred_tax_included_in_output_icms=True,
        **{k: v for k, v in changes.items() if k not in {
            "operation", "used_in_incentivized_industrial_process",
            "deferred_tax_due_at_output_acknowledged",
            "regulatory_credit_reversal_checked", "input_credit_accumulation",
        }},
    )
    data.update(changes)
    result = assess_se_psdi_context(data, MONTH)
    assert result["status"] != "potential"
    assert result["reason_codes"] == [reason]
    assert result["tax_calculation_authorized"] is False


def test_6_2_requires_distinct_cdi_approved_condition_not_any_location():
    c = _context(
        mode="new_industry_6_2",
        individual_cdi_resolution_percentage="6.2",
    )
    result = assess_se_psdi_context(c, MONTH)
    assert result["reason_codes"] == [
        "se_psdi_6_2_specific_condition_missing"
    ]


def test_missing_context_fails_closed():
    assert assess_se_psdi_context(None, MONTH)["reason_codes"] == [
        "se_psdi_context_missing"
    ]


def test_grant_legal_last_day_inclusive_is_valid_entire_november():
    r = assess_se_psdi_context(
        _context(grant_valid_through="2026-11-30"), MONTH,
    )
    assert r["status"] == "potential"
    assert r["tax_calculation_authorized"] is False


def test_wrong_context_types_are_rejected_without_crashing():
    assert assess_se_psdi_context({"mode": []}, MONTH)["status"] == (
        "not_applicable"
    )
    c = _context()
    c["cdi_grant_status"] = []
    assert assess_se_psdi_context(c, MONTH)["status"] == "insufficient_basis"


@pytest.mark.parametrize("changes,reason", [
    ({"other_fiscal_incentive_on_same_operation": True},
     "se_psdi_868_5e_non_cumulative_incentive"),
    ({"period_credit_excess_reversal_reviewed": False},
     "se_psdi_868_5c_excess_reversal_missing"),
    ({"reversal_proportional_to_material_used": False},
     "se_psdi_868_5d_proportional_reversal_missing"),
    ({"deferred_tax_included_in_output_icms": False},
     "se_psdi_868_5f_output_inclusion_missing"),
    ({"chemical_plastic_industry": True},
     "se_psdi_868_5g_annex_iii_scope_unverified"),
])
def test_decree_868_2024_negative_guards(changes, reason):
    facts = _context(
        mode="domestic_raw_deferral",
        operation="domestic_raw_material_input",
        used_in_incentivized_industrial_process=True,
        deferred_tax_due_at_output_acknowledged=True,
        regulatory_credit_reversal_checked=True,
        input_credit_accumulation=False,
        other_fiscal_incentive_on_same_operation=False,
        period_credit_excess_reversal_reviewed=True,
        reversal_proportional_to_material_used=True,
        deferred_tax_included_in_output_icms=True,
    )
    facts.update(changes)
    result = assess_se_psdi_context(facts, MONTH)
    assert result["status"] != "potential"
    assert result["reason_codes"] == [reason]
    assert result["tax_calculation_authorized"] is False


def test_decree_868_annex_iii_can_only_be_advisory_after_exact_review():
    facts = _context(
        mode="domestic_raw_deferral",
        operation="domestic_raw_material_input",
        used_in_incentivized_industrial_process=True,
        deferred_tax_due_at_output_acknowledged=True,
        regulatory_credit_reversal_checked=True,
        input_credit_accumulation=False,
        other_fiscal_incentive_on_same_operation=False,
        period_credit_excess_reversal_reviewed=True,
        reversal_proportional_to_material_used=True,
        deferred_tax_included_in_output_icms=True,
        chemical_plastic_industry=True,
        annex_iii_material_legally_classified=True,
    )
    r = assess_se_psdi_context(facts, MONTH)
    assert r["status"] == "potential"
    assert r["tax_calculation_authorized"] is False
