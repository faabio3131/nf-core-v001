"""Deterministic NF-e calculations from explicit versioned fiscal rules.

No statutory tax rates are embedded here. Unsupported regimes/groups fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.tax.rtc_group_indicators import (
    SUPPORTED_RTC_CST_GROUPS,
    require_representable_classification,
)

if TYPE_CHECKING:
    from .models import TaxDecision

_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ReviewedIcmsBenefit:
    """Evidence in an existing checksum-pinned, operator-reviewed rule.

    Not a catalogue or proof of statutory eligibility by itself.
    """

    code: str
    reviewed_by: str
    approval_reference: str
    deson_mode: str | None = None
    deson_rate: Decimal | None = None
    deson_reason: int | None = None
    deduct_deson: bool | None = None
    deferral_rate: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not re.fullmatch(
            r"[A-Z]{2}[A-Z0-9]{6}(?:[A-Z0-9]{2})?", self.code
        ):
            raise FiscalValidationError("reviewed ICMS benefit requires a UF code")
        for value in (self.reviewed_by, self.approval_reference):
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise FiscalValidationError("ICMS benefit requires explicit review evidence")
        facts = (self.deson_mode, self.deson_rate, self.deson_reason, self.deduct_deson)
        if any(v is not None for v in facts):
            if (
                self.deson_mode != "nominal_minus_due"
                or self.deson_rate is None
                or type(self.deson_reason) is not int
                or type(self.deduct_deson) is not bool
            ):
                raise FiscalValidationError("ICMS desoneration requires explicit reviewed facts")
        for rate in (self.deson_rate, self.deferral_rate):
            if rate is not None and (
                not isinstance(rate, Decimal)
                or not rate.is_finite()
                or not 0 < rate <= 100
                or rate != rate.quantize(Decimal("0.0001"))
            ):
                raise FiscalValidationError("ICMS benefit percentage must be explicit and valid")
        if self.deferral_rate is not None and any(v is not None for v in facts):
            raise FiscalValidationError("combined deferral and desoneration not supported")


@dataclass(frozen=True, slots=True)
class NfeRateParameters:
    icms_rate: Decimal
    pis_rate: Decimal
    cofins_rate: Decimal
    pis_base: Literal["net", "net_less_icms"]
    cofins_base: Literal["net", "net_less_icms"]
    fcp_rate: Decimal | None = None
    ipi_rate: Decimal | None = None
    ipi_enquiry_code: str | None = None
    ipi_calculation_mode: str | None = None
    ipi_cst: str | None = None
    ipi_unit_amount: Decimal | None = None
    st_rate: Decimal | None = None
    st_mva_rate: Decimal | None = None
    st_base_mode: str | None = None
    fcp_st_rate: Decimal | None = None
    difal_destination_rate: Decimal | None = None
    difal_interstate_rate: Decimal | None = None
    difal_destination_share: Decimal | None = None
    fcp_destination_rate: Decimal | None = None
    rtc_uf_rate: Decimal | None = None
    rtc_municipal_rate: Decimal | None = None
    rtc_cbs_rate: Decimal | None = None
    rtc_base_mode: str | None = None
    rtc_financial_mode: str | None = None
    icms_reduction_rate: Decimal | None = None
    pis_unit_amount: Decimal | None = None
    cofins_unit_amount: Decimal | None = None
    rtc_uf_reduction_rate: Decimal | None = None
    rtc_municipal_reduction_rate: Decimal | None = None
    rtc_cbs_reduction_rate: Decimal | None = None
    pis_other_mode: str | None = None
    cofins_other_mode: str | None = None
    icms_benefit: ReviewedIcmsBenefit | None = None

    def __post_init__(self) -> None:
        if self.icms_benefit is not None and not isinstance(
            self.icms_benefit, ReviewedIcmsBenefit
        ):
            raise FiscalValidationError("ICMS benefit must be immutable reviewed evidence")
        rates: tuple[Decimal, ...] = (self.icms_rate, self.pis_rate, self.cofins_rate)
        for candidate in (
            self.fcp_rate,
            self.ipi_rate,
            self.st_rate,
            self.fcp_st_rate,
            self.difal_destination_rate,
            self.difal_interstate_rate,
            self.difal_destination_share,
            self.fcp_destination_rate,
            self.rtc_uf_rate,
            self.rtc_municipal_rate,
            self.rtc_cbs_rate,
            self.icms_reduction_rate,
            self.rtc_uf_reduction_rate,
            self.rtc_municipal_reduction_rate,
            self.rtc_cbs_reduction_rate,
        ):
            if candidate is not None:
                rates += (candidate,)
        for rate in rates:
            if (
                not isinstance(rate, Decimal)
                or not rate.is_finite()
                or not 0 <= rate <= 100
                or rate != rate.quantize(Decimal("0.0001"))
            ):
                raise FiscalValidationError("explicit NF-e rates require 0 to 100 with 4 decimals")
        if self.pis_base not in {"net", "net_less_icms"} or self.cofins_base not in {
            "net",
            "net_less_icms",
        }:
            raise FiscalValidationError("explicit NF-e contribution base policy is required")
        for name, value in (
            ("PIS unit amount", self.pis_unit_amount),
            ("COFINS unit amount", self.cofins_unit_amount),
        ):
            if value is not None and (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not 0 <= value <= Decimal("9999999999.9999")
                or value != value.quantize(Decimal("0.0001"))
            ):
                raise FiscalValidationError(f"{name} requires a valid 4-decimal amount")
        if self.ipi_rate is not None and self.ipi_unit_amount is not None:
            raise FiscalValidationError("IPI cannot mix ad valorem and per-unit modes")
        ipi_taxed = self.ipi_rate is not None or self.ipi_unit_amount is not None
        ipi_non_taxed = self.ipi_cst in {"51", "52", "53", "54", "55"}
        if ipi_taxed:
            if self.ipi_enquiry_code is None:
                raise FiscalValidationError("IPI rate and legal framing must be specified together")
            expected_mode = "net_icms_excluded" if self.ipi_rate is not None else "per_taxable_unit"
            if self.ipi_calculation_mode != expected_mode:
                raise FiscalValidationError("IPI calculation mode must be explicitly reviewed")
            if self.ipi_cst not in {None, "50", "99"}:
                raise FiscalValidationError("taxed output IPI requires CST 50 or 99")
        elif ipi_non_taxed:
            if self.ipi_enquiry_code is None or self.ipi_calculation_mode != "non_taxed":
                raise FiscalValidationError(
                    "non-taxed IPI requires approved legal framing and mode"
                )
        elif any(
            v is not None for v in (self.ipi_cst, self.ipi_enquiry_code, self.ipi_calculation_mode)
        ):
            raise FiscalValidationError("IPI configuration must select a supported output CST")
        if self.ipi_unit_amount is not None and (
            not isinstance(self.ipi_unit_amount, Decimal)
            or not self.ipi_unit_amount.is_finite()
            or not 0 <= self.ipi_unit_amount <= Decimal("9999999.9999")
            or self.ipi_unit_amount != self.ipi_unit_amount.quantize(Decimal("0.0001"))
        ):
            raise FiscalValidationError("IPI per-unit amount must have 4 decimal precision")
        if self.ipi_enquiry_code is not None and (
            not isinstance(self.ipi_enquiry_code, str)
            or len(self.ipi_enquiry_code) != 3
            or not self.ipi_enquiry_code.isascii()
            or not self.ipi_enquiry_code.isdigit()
        ):
            raise FiscalValidationError("IPI legal framing must have three digits")
        st_facts = (self.st_rate, self.st_mva_rate, self.st_base_mode)
        if any(v is not None for v in st_facts) and not all(v is not None for v in st_facts):
            raise FiscalValidationError("ICMS ST requires explicit rate, MVA and base mode")
        if self.st_base_mode is not None and self.st_base_mode not in {
            "net_mva",
            "net_plus_ipi_mva",
        }:
            raise FiscalValidationError("unsupported ICMS ST calculation base")
        if self.st_mva_rate is not None and (
            not isinstance(self.st_mva_rate, Decimal)
            or not self.st_mva_rate.is_finite()
            or not 0 <= self.st_mva_rate <= 1000
            or self.st_mva_rate != self.st_mva_rate.quantize(Decimal("0.0001"))
        ):
            raise FiscalValidationError("ICMS ST MVA must be an explicit valid percentage")
        if self.fcp_st_rate is not None and self.st_rate is None:
            raise FiscalValidationError("FCP-ST requires approved ICMS ST calculation")
        difal_facts = (
            self.difal_destination_rate,
            self.difal_interstate_rate,
            self.difal_destination_share,
        )
        if any(v is not None for v in difal_facts) and not all(v is not None for v in difal_facts):
            raise FiscalValidationError(
                "DIFAL requires complete destination, origin and share rates"
            )
        if self.fcp_destination_rate is not None and self.difal_destination_rate is None:
            raise FiscalValidationError("destination FCP requires an approved DIFAL policy")
        if self.difal_interstate_rate is not None and self.difal_interstate_rate not in {
            Decimal("4"),
            Decimal("7"),
            Decimal("12"),
        }:
            raise FiscalValidationError("DIFAL interstate rate must match an authorized XML value")
        if self.difal_destination_share is not None and self.difal_destination_share != 100:
            raise FiscalValidationError("DIFAL 2026 requires full destination share")
        rtc_facts = (
            self.rtc_uf_rate,
            self.rtc_municipal_rate,
            self.rtc_cbs_rate,
            self.rtc_base_mode,
            self.rtc_financial_mode,
        )
        non_taxed = self.rtc_base_mode == "non_taxed"
        if non_taxed:
            if any(v is not None for v in rtc_facts[:3]) or self.rtc_financial_mode is None:
                raise FiscalValidationError(
                    "non-taxed RTC forbids rates and requires approved mode"
                )
        elif any(v is not None for v in rtc_facts) and not all(v is not None for v in rtc_facts):
            raise FiscalValidationError("RTC requires complete explicit 2026 calculation policy")
        if self.rtc_base_mode is not None and self.rtc_base_mode not in {
            "net",
            "net_less_icms_pis_cofins",
            "non_taxed",
        }:
            raise FiscalValidationError("unsupported RTC base mode")
        reductions = (
            self.rtc_uf_reduction_rate,
            self.rtc_municipal_reduction_rate,
            self.rtc_cbs_reduction_rate,
        )
        if any(r is not None for r in reductions) and not all(r is not None for r in reductions):
            raise FiscalValidationError("RTC reduced rates require three explicit reductions")
        if any(r is not None and r <= 0 for r in reductions):
            raise FiscalValidationError("RTC reduction must be positive")
        if self.rtc_financial_mode is not None and self.rtc_financial_mode != "informational_2026":
            raise FiscalValidationError("RTC financial mode requires a 2026 authoritative rule")


@dataclass(frozen=True, slots=True)
class NfeCalculatedTaxes:
    icms_base: Decimal
    icms_amount: Decimal
    pis_base: Decimal
    pis_amount: Decimal
    cofins_base: Decimal
    cofins_amount: Decimal
    fcp_amount: Decimal = Decimal("0.00")
    ipi_amount: Decimal = Decimal("0.00")
    ipi_base: Decimal = Decimal("0.00")
    ipi_taxable_quantity: Decimal = Decimal("0.0000")
    st_base: Decimal = Decimal("0.00")
    st_amount: Decimal = Decimal("0.00")
    fcp_st_amount: Decimal = Decimal("0.00")
    difal_base: Decimal = Decimal("0.00")
    difal_amount: Decimal = Decimal("0.00")
    fcp_destination_amount: Decimal = Decimal("0.00")
    rtc_base: Decimal = Decimal("0.00")
    rtc_ibs_uf_amount: Decimal = Decimal("0.00")
    rtc_ibs_municipal_amount: Decimal = Decimal("0.00")
    rtc_cbs_amount: Decimal = Decimal("0.00")
    contribution_taxable_quantity: Decimal = Decimal("0.0000")
    icms_deson_amount: Decimal = Decimal("0.00")
    icms_deson_deduction: Decimal = Decimal("0.00")
    icms_operation_amount: Decimal = Decimal("0.00")
    icms_deferred_amount: Decimal = Decimal("0.00")


def calculate_nfe_line(
    decision: TaxDecision,
    *,
    net_amount: Decimal,
    regime: TaxRegimeCode,
    interstate_final_consumer: bool = False,
    taxable_quantity: Decimal | None = None,
) -> NfeCalculatedTaxes:
    outcome = decision.outcome
    policy = outcome.nfe_rates
    if policy is None:
        raise FiscalValidationError(
            "winning fiscal rule has no approved NF-e calculation parameters"
        )
    if not isinstance(net_amount, Decimal) or not net_amount.is_finite() or net_amount < 0:
        raise FiscalValidationError("NF-e tax base must be finite and non-negative")
    if net_amount != net_amount.quantize(_CENT):
        raise FiscalValidationError("NF-e tax base must use cent precision")
    rtc_fields = (
        outcome.ibs_cbs_classification_code,
        outcome.ibs_cbs_cst_code,
        outcome.ibs_cbs_classification_table_version,
    )
    if any(v is not None for v in rtc_fields) and not all(v is not None for v in rtc_fields):
        raise FiscalValidationError("RTC classification, CST and table version are mandatory")
    rtc_cst = outcome.ibs_cbs_cst_code
    if (rtc_cst is None) != (policy.rtc_financial_mode is None):
        raise FiscalValidationError("RTC tax rule and calculation parameters must agree")
    reductions = (
        policy.rtc_uf_reduction_rate,
        policy.rtc_municipal_reduction_rate,
        policy.rtc_cbs_reduction_rate,
    )
    if rtc_cst is not None:
        classification = outcome.ibs_cbs_classification_code
        if (
            rtc_cst not in SUPPORTED_RTC_CST_GROUPS
            or classification is None
            or len(classification) != 6
            or not classification.isascii()
            or not classification.isdigit()
            or not classification.startswith(rtc_cst)
        ):
            raise FiscalValidationError("RTC CST and classification must be approved and aligned")
        require_representable_classification(classification)
        if not SUPPORTED_RTC_CST_GROUPS[rtc_cst]:
            if policy.rtc_base_mode != "non_taxed" or policy.rtc_uf_rate is not None:
                raise FiscalValidationError(
                    f"RTC CST {rtc_cst} forbids standard taxation groups"
                )
            if any(r is not None for r in reductions):
                raise FiscalValidationError(f"RTC CST {rtc_cst} forbids tax reductions")
        elif policy.rtc_uf_rate is None or policy.rtc_base_mode == "non_taxed":
            raise FiscalValidationError("taxed RTC requires complete approved base and rates")
        elif rtc_cst == "200" and not all(r is not None for r in reductions):
            raise FiscalValidationError("RTC CST 200 requires explicit reductions")
        elif rtc_cst == "000" and any(r is not None for r in reductions):
            raise FiscalValidationError("RTC CST 000 forbids reduced-rate groups")
    elif any(r is not None for r in reductions):
        raise FiscalValidationError("RTC reductions require an approved classification")
    code = outcome.icms_code
    simple = regime in {TaxRegimeCode.SIMPLES_NACIONAL, TaxRegimeCode.MEI}
    if simple and code not in {"102", "103", "300", "400"}:
        raise FiscalValidationError("unsupported Simples NF-e calculation group")
    if not simple and code not in {"00", "10", "20", "30", "40", "41", "50", "51", "70"}:
        raise FiscalValidationError("unsupported regular NF-e calculation group")
    benefit = policy.icms_benefit
    if benefit is not None:
        if regime is not TaxRegimeCode.NORMAL or code not in {"20", "40", "41", "51"}:
            raise FiscalValidationError("ICMS benefit CST or regime not supported")
        if (benefit.deferral_rate is not None) != (code == "51"):
            raise FiscalValidationError("CST 51 requires reviewed deferral rate")
        if any(v is not None for v in (
            policy.st_rate, policy.fcp_rate, policy.difal_destination_rate,
        )) or interstate_final_consumer:
            raise FiscalValidationError("combined ICMS benefit requires dedicated reviewed policy")
        if benefit.deson_reason is not None:
            reasons = (
                {3, 9, 10, 11, 12} if code == "20"
                else {1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 16, 90}
            )
            if code not in {"20", "40", "41"} or benefit.deson_reason not in reasons:
                raise FiscalValidationError("ICMS desoneration reason incompatible with CST")
            if code == "20" and benefit.deson_rate != policy.icms_rate:
                raise FiscalValidationError("nominal desoneration requires the reviewed ICMS rate")
    elif code == "51":
        raise FiscalValidationError("CST 51 requires reviewed benefit evidence")
    taxable_icms = code in {"00", "10", "20", "51", "70"}
    if policy.fcp_rate is not None and not taxable_icms:
        raise FiscalValidationError("FCP configuration requires taxable ICMS group")
    if code in {"20", "70"}:
        if policy.icms_reduction_rate is None or not 0 < policy.icms_reduction_rate < 100:
            raise FiscalValidationError("reduced ICMS group requires approved reduction")
    elif policy.icms_reduction_rate is not None:
        raise FiscalValidationError("ICMS reduction belongs only to CST 20/70")
    if (policy.st_rate is None) != (code not in {"10", "30", "70"}):
        raise FiscalValidationError("ICMS 10/30/70 requires ST policy and other groups forbid it")
    if interstate_final_consumer and (code != "00" or policy.difal_destination_rate is None):
        raise FiscalValidationError("interstate final consumer requires approved DIFAL for ICMS 00")
    if not interstate_final_consumer and policy.difal_destination_rate is not None:
        raise FiscalValidationError("DIFAL policy requires interstate final consumer")
    if not taxable_icms and policy.icms_rate != 0:
        raise FiscalValidationError("non-taxed ICMS group conflicts with nonzero rate")
    icms_base = (
        (net_amount * (100 - (policy.icms_reduction_rate or 0)) / 100).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        if taxable_icms
        else Decimal("0.00")
    )
    icms_operation = (icms_base * policy.icms_rate / 100).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    icms = icms_operation
    deson = deduction = deferred = Decimal("0.00")
    if benefit is not None:
        if benefit.deferral_rate is not None:
            deferred = (icms_operation * benefit.deferral_rate / 100).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
            icms -= deferred
        if benefit.deson_rate is not None:
            nominal = (net_amount * benefit.deson_rate / 100).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
            deson = nominal - icms
            if deson <= 0 or deson > net_amount:
                raise FiscalValidationError("reviewed ICMS desoneration is outside valid bounds")
            if benefit.deduct_deson:
                deduction = deson

    contribution_quantity = Decimal("0.0000")
    if (
        outcome.pis_cst == "03"
        or outcome.cofins_cst == "03"
        or (outcome.pis_cst in {"49", "99"} and policy.pis_other_mode == "per_unit")
        or (outcome.cofins_cst in {"49", "99"} and policy.cofins_other_mode == "per_unit")
    ):
        if (
            not isinstance(taxable_quantity, Decimal)
            or not taxable_quantity.is_finite()
            or taxable_quantity <= 0
            or taxable_quantity != taxable_quantity.quantize(Decimal("0.0001"))
        ):
            raise FiscalValidationError("contribution by quantity requires exact taxable quantity")
        contribution_quantity = taxable_quantity

    def contribution(
        code: str,
        rate: Decimal,
        base_policy: str,
        unit_amount: Decimal | None,
        other_mode: str | None,
    ) -> tuple[Decimal, Decimal]:
        if code in {"49", "99"}:
            if other_mode not in {"zero", "percentage", "per_unit"}:
                raise FiscalValidationError("other contributions require explicit calculation mode")
            if other_mode == "zero":
                if unit_amount is not None or rate != 0:
                    raise FiscalValidationError("zero other contribution forbids nonzero tax")
                return Decimal("0.00"), Decimal("0.00")
            if other_mode == "percentage":
                if unit_amount is not None:
                    raise FiscalValidationError("other percentage contribution forbids unit amount")
                base = net_amount - icms if base_policy == "net_less_icms" else net_amount
                return base, (base * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            if unit_amount is None or rate != 0:
                raise FiscalValidationError("other per-unit contribution requires exclusive amount")
            return Decimal("0.00"), (contribution_quantity * unit_amount).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
        if other_mode is not None:
            raise FiscalValidationError("other calculation mode requires CST 49 or 99")
        if code == "03":
            if unit_amount is None or rate != 0:
                raise FiscalValidationError("CST 03 requires exclusive approved unit amount")
            return Decimal("0.00"), (contribution_quantity * unit_amount).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
        if unit_amount is not None:
            raise FiscalValidationError("unit contribution requires CST 03 or other per-unit mode")
        if code in {"01", "02"}:
            base = net_amount - icms if base_policy == "net_less_icms" else net_amount
            return base, (base * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        if code not in {"04", "06", "07", "08", "09"}:
            raise FiscalValidationError("unsupported NF-e contribution calculation group")
        if rate != 0:
            raise FiscalValidationError("non-taxed contribution group conflicts with nonzero rate")
        return Decimal("0.00"), Decimal("0.00")

    pis_base, pis = contribution(
        outcome.pis_cst,
        policy.pis_rate,
        policy.pis_base,
        policy.pis_unit_amount,
        policy.pis_other_mode,
    )
    cofins_base, cofins = contribution(
        outcome.cofins_cst,
        policy.cofins_rate,
        policy.cofins_base,
        policy.cofins_unit_amount,
        policy.cofins_other_mode,
    )
    fcp = (icms_base * (policy.fcp_rate or 0) / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
    ipi = (net_amount * (policy.ipi_rate or 0) / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
    if policy.ipi_unit_amount is not None:
        if (
            not isinstance(taxable_quantity, Decimal)
            or not taxable_quantity.is_finite()
            or taxable_quantity <= 0
            or taxable_quantity != taxable_quantity.quantize(Decimal("0.0001"))
        ):
            raise FiscalValidationError("IPI per-unit calculation requires exact taxable quantity")
        ipi = (taxable_quantity * policy.ipi_unit_amount).quantize(_CENT, rounding=ROUND_HALF_UP)
    st_base = st_amount = fcp_st = Decimal("0.00")
    if policy.st_rate is not None:
        st_net = net_amount + (ipi if policy.st_base_mode == "net_plus_ipi_mva" else 0)
        assert policy.st_mva_rate is not None
        st_base = (st_net * (Decimal(1) + policy.st_mva_rate / 100)).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        gross_st = (st_base * policy.st_rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        st_amount = gross_st - icms
        if st_amount < 0:
            raise FiscalValidationError("ICMS ST cannot be negative; review the approved rule")
        fcp_st = (st_base * (policy.fcp_st_rate or 0) / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
    difal_base = difal_amount = fcp_destination = Decimal("0.00")
    if interstate_final_consumer:
        assert policy.difal_destination_rate is not None
        assert policy.difal_interstate_rate is not None
        difal_base = net_amount
        difference = policy.difal_destination_rate - policy.difal_interstate_rate
        if difference < 0:
            raise FiscalValidationError("DIFAL destination rate below interstate rate")
        difal_amount = (difal_base * difference / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        fcp_destination = (difal_base * (policy.fcp_destination_rate or 0) / 100).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
    rtc_base = rtc_ibs_uf = rtc_ibs_mun = rtc_cbs = Decimal("0.00")
    if policy.rtc_uf_rate is not None:
        rtc_base = (
            net_amount - icms - pis - cofins
            if policy.rtc_base_mode == "net_less_icms_pis_cofins"
            else net_amount
        )
        if rtc_base < 0:
            raise FiscalValidationError("RTC base became negative under approved exclusions")
        assert policy.rtc_municipal_rate is not None and policy.rtc_cbs_rate is not None

        def reduced_rate(rate: Decimal, reduction: Decimal | None) -> Decimal:
            return (rate * (100 - (reduction or 0)) / 100).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        rtc_ibs_uf = (
            rtc_base * reduced_rate(policy.rtc_uf_rate, policy.rtc_uf_reduction_rate) / 100
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        rtc_ibs_mun = (
            rtc_base
            * reduced_rate(policy.rtc_municipal_rate, policy.rtc_municipal_reduction_rate)
            / 100
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        rtc_cbs = (
            rtc_base * reduced_rate(policy.rtc_cbs_rate, policy.rtc_cbs_reduction_rate) / 100
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
    return NfeCalculatedTaxes(
        icms_base=icms_base,
        icms_amount=icms,
        pis_base=pis_base,
        pis_amount=pis,
        cofins_base=cofins_base,
        cofins_amount=cofins,
        fcp_amount=fcp,
        ipi_amount=ipi,
        ipi_base=net_amount if policy.ipi_rate is not None else Decimal("0.00"),
        ipi_taxable_quantity=(
            taxable_quantity
            if policy.ipi_unit_amount is not None and taxable_quantity is not None
            else Decimal("0.0000")
        ),
        st_base=st_base,
        st_amount=st_amount,
        fcp_st_amount=fcp_st,
        difal_base=difal_base,
        difal_amount=difal_amount,
        fcp_destination_amount=fcp_destination,
        rtc_base=rtc_base,
        rtc_ibs_uf_amount=rtc_ibs_uf,
        rtc_ibs_municipal_amount=rtc_ibs_mun,
        rtc_cbs_amount=rtc_cbs,
        contribution_taxable_quantity=contribution_quantity,
        icms_deson_amount=deson,
        icms_deson_deduction=deduction,
        icms_operation_amount=icms_operation if code == "51" else Decimal("0.00"),
        icms_deferred_amount=deferred,
    )
