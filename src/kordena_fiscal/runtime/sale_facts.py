"""Shared parsing of reviewed fiscal sale facts; no provider authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from kordena_fiscal.documents import FiscalRecipientSnapshot
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    Cpf,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalValidationError,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.tax import (
    RecipientTaxProfile,
    TaxOperationType,
    TaxRule,
    TaxRuleOutcome,
    TaxRuleSelector,
)
from kordena_fiscal.tax.nfe_calculation import NfeRateParameters, ReviewedIcmsBenefit


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise FiscalValidationError("duplicate fiscal policy key")
        data[key] = value
    return data


def parse_sale_rule(
    data: Mapping[str, Any],
    *,
    document_kind: FiscalDocumentKind = FiscalDocumentKind.NFE,
) -> TaxRule:
    if not isinstance(data, dict):
        raise FiscalValidationError("fiscal rule must be an object")
    allowed = {
        "rule_id",
        "version",
        "selector",
        "outcome",
        "source_normative",
        "effective_from",
        "effective_to",
        "priority",
    }
    if set(data) - allowed or type(data["version"]) is not int or type(data["priority"]) is not int:
        raise FiscalValidationError("invalid or unknown fiscal rule fields")
    selector = data["selector"]
    outcome = data["outcome"]
    if not isinstance(selector, dict) or not isinstance(outcome, dict):
        raise FiscalValidationError("rule selector and outcome must be objects")
    if any(
        not isinstance(data.get(key), str)
        for key in ("rule_id", "source_normative", "effective_from")
    ):
        raise FiscalValidationError("rule identity, source and validity must be explicit")
    if any(
        not isinstance(outcome.get(key), str)
        for key in ("cfop", "icms_code", "pis_cst", "cofins_cst")
    ):
        raise FiscalValidationError("rule fiscal codes must be strings")
    rates = outcome["nfe_rates"]
    if not isinstance(rates, dict):
        raise FiscalValidationError("rate parameters must be an object")
    required_selector = {"state_code", "tax_regime", "recipient_profile", "ncm_prefix"}
    if set(selector) not in (required_selector, required_selector | {"destination_state_code"}):
        raise FiscalValidationError("invalid fiscal rule selector fields")
    if "destination_state_code" in selector and (
        not isinstance(selector["destination_state_code"], str)
        or not selector["destination_state_code"].strip()
    ):
        raise FiscalValidationError("destination state must be explicit")
    if set(outcome) - {
        "cfop",
        "icms_code",
        "pis_cst",
        "cofins_cst",
        "nfe_rates",
        "ibs_cbs_classification_code",
        "ibs_cbs_cst_code",
        "ibs_cbs_classification_table_version",
        "simples_activity_code",
    }:
        raise FiscalValidationError("unsupported fiscal rule outcome fields")
    required_rates = {"icms_rate", "pis_rate", "cofins_rate", "pis_base", "cofins_base"}
    if not required_rates <= set(rates) or set(rates) - required_rates - {
        "fcp_rate",
        "ipi_rate",
        "ipi_enquiry_code",
        "ipi_calculation_mode",
        "ipi_cst",
        "ipi_unit_amount",
        "st_rate",
        "st_mva_rate",
        "st_base_mode",
        "fcp_st_rate",
        "difal_destination_rate",
        "difal_interstate_rate",
        "difal_destination_share",
        "fcp_destination_rate",
        "rtc_uf_rate",
        "rtc_municipal_rate",
        "rtc_cbs_rate",
        "rtc_base_mode",
        "rtc_financial_mode",
        "icms_reduction_rate",
        "pis_unit_amount",
        "cofins_unit_amount",
        "rtc_uf_reduction_rate",
        "rtc_municipal_reduction_rate",
        "rtc_cbs_reduction_rate",
        "pis_other_mode",
        "cofins_other_mode",
        "icms_benefit",
    }:
        raise FiscalValidationError("unsupported fiscal calculation parameters")
    benefit = None
    if "icms_benefit" in rates:
        raw = rates["icms_benefit"]
        if not isinstance(raw, dict):
            raise FiscalValidationError("ICMS benefit must be an object")
        required = {"code", "reviewed_by", "approval_reference"}
        optional = {
            "deson_mode", "deson_rate", "deson_reason", "deduct_deson", "deferral_rate",
            "benefit_id",
        }
        if not required <= set(raw) or set(raw) - required - optional:
            raise FiscalValidationError("invalid ICMS benefit evidence fields")
        benefit = ReviewedIcmsBenefit(
            code=raw["code"], reviewed_by=raw["reviewed_by"],
            benefit_id=raw.get("benefit_id"),
            approval_reference=raw["approval_reference"],
            deson_mode=raw.get("deson_mode"),
            deson_rate=Decimal(str(raw["deson_rate"])) if "deson_rate" in raw else None,
            deson_reason=raw.get("deson_reason"), deduct_deson=raw.get("deduct_deson"),
            deferral_rate=(
                Decimal(str(raw["deferral_rate"])) if "deferral_rate" in raw else None
            ),
        )
    return TaxRule(
        rule_id=data["rule_id"],
        version=data["version"],
        source_normative=data["source_normative"],
        effective_from=datetime.fromisoformat(data["effective_from"]),
        effective_to=datetime.fromisoformat(data["effective_to"])
        if data.get("effective_to")
        else None,
        priority=data["priority"],
        selector=TaxRuleSelector(
            state_code=selector["state_code"],
            tax_regime=TaxRegimeCode(selector["tax_regime"]),
            document_kind=document_kind,
            operation_type=TaxOperationType.SALE,
            recipient_profile=RecipientTaxProfile(selector["recipient_profile"]),
            ncm_prefix=selector["ncm_prefix"],
            destination_state_code=selector.get("destination_state_code"),
        ),
        outcome=TaxRuleOutcome(
            cfop=outcome["cfop"],
            icms_code=outcome["icms_code"],
            pis_cst=outcome["pis_cst"],
            cofins_cst=outcome["cofins_cst"],
            ibs_cbs_classification_code=outcome.get("ibs_cbs_classification_code"),
            ibs_cbs_cst_code=outcome.get("ibs_cbs_cst_code"),
            ibs_cbs_classification_table_version=outcome.get(
                "ibs_cbs_classification_table_version"
            ),
            simples_activity_code=outcome.get("simples_activity_code"),
            nfe_rates=NfeRateParameters(
                Decimal(str(rates["icms_rate"])),
                Decimal(str(rates["pis_rate"])),
                Decimal(str(rates["cofins_rate"])),
                rates["pis_base"],
                rates["cofins_base"],
                Decimal(str(rates["fcp_rate"])) if "fcp_rate" in rates else None,
                Decimal(str(rates["ipi_rate"])) if "ipi_rate" in rates else None,
                rates.get("ipi_enquiry_code"),
                rates.get("ipi_calculation_mode"),
                ipi_cst=rates.get("ipi_cst"),
                ipi_unit_amount=(
                    Decimal(str(rates["ipi_unit_amount"])) if "ipi_unit_amount" in rates else None
                ),
                st_rate=Decimal(str(rates["st_rate"])) if "st_rate" in rates else None,
                st_mva_rate=Decimal(str(rates["st_mva_rate"])) if "st_mva_rate" in rates else None,
                st_base_mode=rates.get("st_base_mode"),
                fcp_st_rate=Decimal(str(rates["fcp_st_rate"])) if "fcp_st_rate" in rates else None,
                difal_destination_rate=(
                    Decimal(str(rates["difal_destination_rate"]))
                    if "difal_destination_rate" in rates
                    else None
                ),
                difal_interstate_rate=(
                    Decimal(str(rates["difal_interstate_rate"]))
                    if "difal_interstate_rate" in rates
                    else None
                ),
                difal_destination_share=(
                    Decimal(str(rates["difal_destination_share"]))
                    if "difal_destination_share" in rates
                    else None
                ),
                fcp_destination_rate=(
                    Decimal(str(rates["fcp_destination_rate"]))
                    if "fcp_destination_rate" in rates
                    else None
                ),
                rtc_uf_rate=Decimal(str(rates["rtc_uf_rate"])) if "rtc_uf_rate" in rates else None,
                rtc_municipal_rate=(
                    Decimal(str(rates["rtc_municipal_rate"]))
                    if "rtc_municipal_rate" in rates
                    else None
                ),
                rtc_cbs_rate=Decimal(str(rates["rtc_cbs_rate"]))
                if "rtc_cbs_rate" in rates
                else None,
                rtc_base_mode=rates.get("rtc_base_mode"),
                rtc_financial_mode=rates.get("rtc_financial_mode"),
                icms_reduction_rate=(
                    Decimal(str(rates["icms_reduction_rate"]))
                    if "icms_reduction_rate" in rates
                    else None
                ),
                pis_unit_amount=(
                    Decimal(str(rates["pis_unit_amount"])) if "pis_unit_amount" in rates else None
                ),
                cofins_unit_amount=(
                    Decimal(str(rates["cofins_unit_amount"]))
                    if "cofins_unit_amount" in rates
                    else None
                ),
                rtc_uf_reduction_rate=(
                    Decimal(str(rates["rtc_uf_reduction_rate"]))
                    if "rtc_uf_reduction_rate" in rates
                    else None
                ),
                rtc_municipal_reduction_rate=(
                    Decimal(str(rates["rtc_municipal_reduction_rate"]))
                    if "rtc_municipal_reduction_rate" in rates
                    else None
                ),
                rtc_cbs_reduction_rate=(
                    Decimal(str(rates["rtc_cbs_reduction_rate"]))
                    if "rtc_cbs_reduction_rate" in rates
                    else None
                ),
                pis_other_mode=rates.get("pis_other_mode"),
                cofins_other_mode=rates.get("cofins_other_mode"),
                icms_benefit=benefit,
            ),
        ),
    )


def recipient_from_review(data: Mapping[str, Any]) -> FiscalRecipientSnapshot:
    if not isinstance(data, dict):
        raise FiscalValidationError("recipient review must be an object")
    required_text = {
        "document",
        "name",
        "street",
        "number",
        "district",
        "municipality_name",
        "municipality_ibge_code",
        "state",
        "postal_code",
    }
    if any(not isinstance(data.get(key), str) for key in required_text):
        raise FiscalValidationError("recipient review requires complete string facts")
    if any(
        data.get(key) is not None and not isinstance(data[key], str)
        for key in ("complement", "state_registration")
    ):
        raise FiscalValidationError("invalid optional recipient fact")
    allowed = {
        "document",
        "name",
        "street",
        "number",
        "district",
        "municipality_name",
        "municipality_ibge_code",
        "state",
        "postal_code",
        "complement",
        "ie_indicator",
        "state_registration",
        "final_consumer",
    }
    if set(data) - allowed:
        raise FiscalValidationError("unknown recipient review fields")
    digits = re.sub(r"[.\-/]", "", data["document"])
    address = FiscalAddress(
        data["street"],
        data["number"],
        data["district"],
        data["municipality_name"],
        BrazilianJurisdiction(data["state"], data["municipality_ibge_code"]),
        data["postal_code"],
        data.get("complement") or None,
    )
    registration = data.get("state_registration")
    return FiscalRecipientSnapshot(
        Cnpj(digits) if len(digits) == 14 else Cpf(digits),
        data["name"],
        address,
        data["ie_indicator"],
        data["final_consumer"],
        StateRegistration(data["state"], registration) if registration else None,
    )
