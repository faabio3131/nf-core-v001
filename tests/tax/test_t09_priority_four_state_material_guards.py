"""T09 material guards AP/PA/RR: real laws researched, synthetic cases only."""
from __future__ import annotations

from datetime import date

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.tax.state_benefits import decode_rule
from kordena_fiscal.tax.t09_priority_state_guards import (
    assess_priority_state_context,
    expected_program,
)

AP = "AP_FISH_3599"
PA = "PA_6913_ADI3779"
RR = "RR_LXVII_AGRO"


def _ap(**changes):
    context = {
        "official_law_3395_annex_ii_item8_checked": True,
        "dec_2656_current_for_competence": True,
        "confaz_certificate_14_2018_item11_checked": True,
        "condi_approved_and_sefaz_individual_act": True,
        "act_current_scope_cnae_ncm_cfop_checked": True,
        "individual_act_status": "active",
        "original_fish_decree_3599_full_text_checked": True,
        "operation": "first_internal_fish_sale",
        "buyer_industrializes_fish": True,
        "credit_presumed_claimed_same_operation": False,
    }
    context.update(changes)
    return context


def _rr(**changes):
    data = {
        "ricms_annex_i_lxvii_2025_text_checked": True,
        "confaz_100_1997_2025_scope_checked": True,
        "state_decree_30363_2021_in_force_for_competence": True,
        "internal_rr_operation": True,
        "input_kind_listed_in_lxvii": True,
        "simples_legal_effect_reviewed": True,
    }
    data.update(changes)
    return data


@pytest.mark.parametrize("prog,date_text,context,status,reason", [
    (AP, "2026-05-01", _ap(), "potential", "ap_fish_deferral_expert_review_only"),
    (AP, "2026-04-01", _ap(), "insufficient_basis",
     "ap_2026_april_revocation_or_historical_temporality_unverified"),
    (RR, "2025-12-01", _rr(), "potential",
     "rr_lxvii_2025_expert_review_only"),
    (RR, "2026-01-01", _rr(), "insufficient_basis",
     "rr_lxvii_2026_specific_state_extension_not_proven"),
    (RR, "2026-11-01", _rr(), "insufficient_basis",
     "rr_lxvii_2026_specific_state_extension_not_proven"),
    (PA, "2026-11-01", {"successor_reviewed": True},
     "insufficient_basis",
     "pa_adi3779_original_law_invalid_successor_not_certified"),
])
def test_exact_fiscal_effects_fail_closed(prog, date_text, context, status, reason):
    out = assess_priority_state_context(prog, context, date.fromisoformat(date_text))
    assert out["status"] == status
    assert out["reason_codes"] == [reason]
    assert out["tax_calculation_authorized"] is False
    assert out["eligibility_certified"] is False
    assert out["approved_cents"] is None


@pytest.mark.parametrize("change,reason", [
    ({"individual_act_status": "revoked"}, "ap_individual_act_not_active"),
    ({"condi_approved_and_sefaz_individual_act": False},
     "ap_missing:condi_approved_and_sefaz_individual_act"),
    ({"confaz_certificate_14_2018_item11_checked": False},
     "ap_missing:confaz_certificate_14_2018_item11_checked"),
    ({"buyer_industrializes_fish": False}, "ap_fish_industrial_buyer_missing"),
    ({"operation": "interstate_fish_sale"}, "ap_fish_operation_outside_scope"),
    ({"credit_presumed_claimed_same_operation": True},
     "ap_fish_credit_claim_not_this_mode"),
])
def test_ap_fish_material_fiscal_exclusions(change, reason):
    result = assess_priority_state_context(AP, _ap(**change), date(2026, 11, 1))
    assert result["status"] != "potential"
    assert result["reason_codes"] == [reason]


@pytest.mark.parametrize("change,reason", [
    ({"internal_rr_operation": False}, "rr_lxvii_interstate_not_allowed"),
    ({"input_kind_listed_in_lxvii": False}, "rr_lxvii_unlisted_product"),
    ({"simples_legal_effect_reviewed": False},
     "rr_lxvii_tax_regime_unreviewed"),
    ({"state_decree_30363_2021_in_force_for_competence": False},
     "rr_missing:state_decree_30363_2021_in_force_for_competence"),
])
def test_rr_2025_conditioned_but_no_real_entitlement(change, reason):
    result = assess_priority_state_context(RR, _rr(**change), date(2025, 12, 1))
    assert result["status"] != "potential"
    assert result["reason_codes"] == [reason]


def test_exact_old_acts_require_identity_and_cannot_be_hidden_in_generic_rule():
    assert expected_program("AP", "Decreto 3.599/2001 Pescado") == AP
    assert expected_program("PA", "Lei 6.913/2006") == PA
    assert expected_program("RR", "RICMS art 1 LXVII") == RR
    assert expected_program("SE", "Lei 6.913/2006") is None


def test_fake_2026_rr_extension_never_overrides_historical_deadline():
    fake = _rr()
    fake["alleged_extension_until"] = "2032-12-31"
    assert assess_priority_state_context(
        RR, fake, date(2026, 12, 1),
    )["reason_codes"] == [
        "rr_lxvii_2026_specific_state_extension_not_proven"
    ]


def test_pa_stf_decision_not_overridden_by_convenio_190_assertion():
    for law in ("Lei 6.913/2006", "Lei 7.485/2010"):
        outcome = assess_priority_state_context(
            PA, {"law": law, "lc160_confaz_deposit_asserted": True},
            date(2026, 11, 1),
        )
        assert outcome["status"] == "insufficient_basis"
        assert outcome["tax_calculation_authorized"] is False


@pytest.mark.parametrize("data", [None, "bad", [], 12])
def test_missing_or_invalid_state_context_is_not_potential(data):
    assert assess_priority_state_context(AP, data, date(2026, 11, 1))[
        "status"
    ] == "insufficient_basis"


def test_rule_rejects_invalid_program_registration():
    # Invalid schema must never infer a different state's authority.
    with pytest.raises(FiscalValidationError):
        decode_rule({"schema_version": "other", "program_id": AP})
