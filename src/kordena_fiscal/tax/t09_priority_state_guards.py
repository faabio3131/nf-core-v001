"""T09 conservative first-pass guards for AP fish, PA ADI 3779, RR LXVII.

These are normative NEGATIVE gates, not tax-rate formulas or real grants.
Legal facts: AP Lei 3.395/2025 Annex II item 8 (Dec 3.599/2001 fish),
Dec 2.656/2026 art 5 (CONDI + SEFAZ act); PA STF ADI 3779 (2019);
RR RICMS 4.335-E/2001 Annex I art 1 LXVII (Dec 30.363-E/2021,
text through 2025-12-31). No 2026 extension may be inferred from a
CONFAZ convention without the required state implementation.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# Protect real selected acts from bypass through a generic state-statute
# policy. Synthetic generic rules have no fingerprint and remain advisory.
PROGRAM_UF = {
    "AP_FISH_3599": "AP",
    "PA_6913_ADI3779": "PA",
    "RR_LXVII_AGRO": "RR",
}
_ANCHORS = {
    "AP": ("3.599/2001", "3599/2001", "3599/01"),
    "PA": ("6.913/2006", "6913/2006", "ADI 3779"),
    "RR": ("LXVII",),
}


def expected_program(uf: str, normative_reference: str) -> str | None:
    """Exact act fingerprint, not word-level inference across UFs."""
    text = normative_reference.upper()
    anchors = _ANCHORS.get(uf, ())
    if any(anchor.upper() in text for anchor in anchors):
        return next(k for k, value in PROGRAM_UF.items() if value == uf)
    return None


def _advisory(state: str, code: str) -> dict[str, Any]:
    return {
        "status": state,
        "reason_codes": [code],
        "advisory_only": True,
        "tax_calculation_authorized": False,
        "issuance_authorized": False,
        "eligibility_certified": False,
        "approved_cents": None,
    }


def assess_priority_state_context(
    program: str, context: object, competence: date,
) -> dict[str, Any]:
    """Guard program-specific scenarios; every result is non-authoritative."""
    if program == "PA_6913_ADI3779":
        # A post-2019 historical act cannot be revived merely by flagging
        # LC160/Conv190: independent law, binding deposit and scope needed.
        return _advisory(
            "insufficient_basis",
            "pa_adi3779_original_law_invalid_successor_not_certified",
        )
    if program == "RR_LXVII_AGRO" and competence >= date(2026, 1, 1):
        return _advisory(
            "insufficient_basis",
            "rr_lxvii_2026_specific_state_extension_not_proven",
        )
    if (
        program == "AP_FISH_3599"
        and isinstance(context, dict)
        and context.get("claimed_3490_extension_for_fish") is True
    ):
        return _advisory(
            "insufficient_basis", "ap_3490_annex_does_not_extend_fish_3599",
        )
    if program == "AP_FISH_3599" and competence < date(2026, 5, 1):
        return _advisory(
            "insufficient_basis",
            "ap_2026_april_revocation_or_historical_temporality_unverified",
        )
    if not isinstance(context, dict):
        return _advisory("insufficient_basis", "priority_state_context_missing")
    if program == "AP_FISH_3599":
        for key in (
            "official_law_3395_annex_ii_item8_checked",
            "dec_2656_current_for_competence",
            "confaz_certificate_14_2018_item11_checked",
            "condi_approved_and_sefaz_individual_act",
            "act_current_scope_cnae_ncm_cfop_checked",
        ):
            if context.get(key) is not True:
                return _advisory("insufficient_basis", "ap_missing:" + key)
        if context.get("individual_act_status") != "active":
            return _advisory("insufficient_basis", "ap_individual_act_not_active")
        if context.get("original_fish_decree_3599_full_text_checked") is not True:
            return _advisory("insufficient_basis", "ap_original_decree_not_checked")
        if context.get("operation") != "first_internal_fish_sale":
            return _advisory("not_applicable", "ap_fish_operation_outside_scope")
        if context.get("buyer_industrializes_fish") is not True:
            return _advisory("not_applicable", "ap_fish_industrial_buyer_missing")
        if context.get("credit_presumed_claimed_same_operation") is not False:
            return _advisory("not_applicable", "ap_fish_credit_claim_not_this_mode")
        return _advisory("potential", "ap_fish_deferral_expert_review_only")
    if program == "RR_LXVII_AGRO":
        for key in (
            "ricms_annex_i_lxvii_2025_text_checked",
            "confaz_100_1997_2025_scope_checked",
            "state_decree_30363_2021_in_force_for_competence",
        ):
            if context.get(key) is not True:
                return _advisory("insufficient_basis", "rr_missing:" + key)
        if context.get("internal_rr_operation") is not True:
            return _advisory("not_applicable", "rr_lxvii_interstate_not_allowed")
        if context.get("input_kind_listed_in_lxvii") is not True:
            return _advisory("not_applicable", "rr_lxvii_unlisted_product")
        if context.get("simples_legal_effect_reviewed") is not True:
            return _advisory("insufficient_basis", "rr_lxvii_tax_regime_unreviewed")
        return _advisory("potential", "rr_lxvii_2025_expert_review_only")
    return _advisory("insufficient_basis", "unknown_priority_program")
