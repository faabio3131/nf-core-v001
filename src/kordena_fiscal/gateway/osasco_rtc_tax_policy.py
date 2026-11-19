"""Osasco RTC facts bridge from the canonical NFS-e motor, never a second tax engine.

The municipal RTC vocabulary (NBS, ClassTrib, IndOperacao) is provided only
through an explicitly reviewed, dated fiscal policy. No city/ISS/tax field is
guessed or filled from browser-supplied or provider-supplied defaults.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from kordena_fiscal.domain import FiscalAddress, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_issue_builder import (
    OsascoReviewedCartorioValues,
    OsascoRtcRecipient,
    OsascoRtcTaxFields,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_CENT = Decimal("0.01")


class OsascoReviewedTaxPolicyError(FiscalValidationError):
    """The canonical fiscal calculation has no reviewed Osasco RTC translation."""


@dataclass(frozen=True, slots=True)
class OsascoReviewedRtcPolicy:
    """Versioned Osasco-specific classification, not an alternative tax calculation."""

    source_normative: str
    rule_version: int
    effective_from: date
    effective_through: date | None
    municipal_service_code: str
    national_taxation_code: str
    activity: str
    class_trib: str
    nbs_code: str
    incidence_location: str
    operation_indicator: str
    service_city: str
    service_city_ibge: str
    service_state: str
    recipient_street_type: str
    iss_rate: Decimal
    pis: Decimal
    cofins: Decimal
    csll: Decimal
    income_tax: Decimal
    inss: Decimal
    other_taxes: Decimal
    # Per-city flag from reviewed municipal WCF guidance, never inferred from
    # the fact that the HTTPS host happens to be the homologation environment.
    test_only: bool
    no_iss_incidence: bool = False
    additional_info: str = ""
    pis_own: Decimal = Decimal("0")
    cofins_own: Decimal = Decimal("0")
    cartorio_values: OsascoReviewedCartorioValues | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_normative, str)
            or not 1 <= len(self.source_normative.strip()) <= 512
            or type(self.rule_version) is not int
            or self.rule_version <= 0
            or type(self.effective_from) is not date
            or (
                self.effective_through is not None and (
                    type(self.effective_through) is not date
                    or self.effective_through < self.effective_from
                )
            )
            or not isinstance(self.test_only, bool)
            or not isinstance(self.no_iss_incidence, bool)
        ):
            raise OsascoReviewedTaxPolicyError("Unversioned or incomplete Osasco fiscal policy")
        for amount in (
            self.iss_rate, self.pis, self.cofins, self.csll,
            self.income_tax, self.inss, self.other_taxes,
            self.pis_own, self.cofins_own,
        ):
            if (
                not isinstance(amount, Decimal)
                or not amount.is_finite()
                or amount < 0
            ):
                raise OsascoReviewedTaxPolicyError("Osasco tax field must have reviewed amount")
        if (
            self.cartorio_values is not None
            and not isinstance(self.cartorio_values, OsascoReviewedCartorioValues)
        ):
            raise OsascoReviewedTaxPolicyError("Unreviewed Osasco notary deductions")
        if self.iss_rate > 5:
            raise OsascoReviewedTaxPolicyError("ISS municipal rate is outside supported range")


def reviewed_osasco_rtc_fields(
    request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    policy: OsascoReviewedRtcPolicy,
) -> OsascoRtcTaxFields:
    """Translate one already audited canonical document with explicit legal policy."""
    if (
        not isinstance(request, NfseAuthorizationRequest)
        or not isinstance(original, Sp4OriginalRps)
        or not isinstance(policy, OsascoReviewedRtcPolicy)
        or original.issuer_ibge != "3534401"
    ):
        raise OsascoReviewedTaxPolicyError("Osasco requires reviewed canonical issuance")
    document = request.document
    issuer = document.issuer
    if (
        document.scope.identity_partition_key != original.scope.identity_partition_key
        or document.document_id != original.document_id
        or request.request_fingerprint != original.request_fingerprint
        or issuer.cnpj != original.issuer_cnpj
        or issuer.address.jurisdiction.municipality_ibge_code != "3534401"
        or issuer.municipal_registration is None
        or issuer.tax_regime is not TaxRegimeCode.NORMAL
        or document.competence_date != original.competence_date
        or not policy.effective_from <= document.competence_date
        or (
            policy.effective_through is not None
            and document.competence_date > policy.effective_through
        )
        or len(document.services) != 1
    ):
        raise OsascoReviewedTaxPolicyError("Osasco taxpayer, registration or policy period invalid")
    item = document.services[0]
    if (
        item.source_normative != policy.source_normative
        or item.rule_version != policy.rule_version
        or item.municipal_service_code != policy.municipal_service_code
        or item.national_taxation_code != policy.national_taxation_code
        or document.service_jurisdiction.municipality_ibge_code != policy.service_city_ibge
        or document.service_jurisdiction.state_code != policy.service_state
        or item.gross_amount.amount != original.gross_amount
    ):
        raise OsascoReviewedTaxPolicyError("Canonical service and reviewed RTC policy diverge")
    taxable = item.taxable_amount.amount
    if taxable <= 0 or (
        taxable * policy.iss_rate / Decimal(100)
    ).quantize(_CENT, rounding=ROUND_HALF_UP) != item.iss_amount.amount:
        raise OsascoReviewedTaxPolicyError("ISS result conflicts with reviewed Osasco rate")
    taker = document.service_taker
    if (
        taker is None or taker.tax_id is None
        or not isinstance(taker.address, FiscalAddress)
        or not taker.legal_name
        or policy.no_iss_incidence
    ):
        raise OsascoReviewedTaxPolicyError("Domestic recipient and reviewed ISS required")
    address = taker.address
    recipient = OsascoRtcRecipient(
        tax_id=taker.tax_id.value, name=taker.legal_name,
        street=address.street, street_type=policy.recipient_street_type,
        number=address.number, neighborhood=address.district,
        postal_code=address.postal_code,
        city=address.municipality_name,
        city_ibge=address.jurisdiction.municipality_ibge_code or "",
        state=address.jurisdiction.state_code,
    )
    return OsascoRtcTaxFields(
        activity=policy.activity, class_trib=policy.class_trib,
        nbs_code=policy.nbs_code, incidence_location=policy.incidence_location,
        operation_indicator=policy.operation_indicator,
        service_city=policy.service_city, service_city_ibge=policy.service_city_ibge,
        service_state=policy.service_state, recipient=recipient,
        iss_rate=policy.iss_rate, iss_withheld=item.iss_withheld,
        no_iss_incidence=policy.no_iss_incidence,
        pis=policy.pis, cofins=policy.cofins, csll=policy.csll,
        income_tax=policy.income_tax, inss=policy.inss,
        other_taxes=policy.other_taxes, additional_info=policy.additional_info,
        pis_own=policy.pis_own, cofins_own=policy.cofins_own,
        cartorio_values=policy.cartorio_values,
        test_only=policy.test_only,
    )


def build_osasco_reviewed_tax_resolver(
    resolve_policy: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], OsascoReviewedRtcPolicy
    ],
) -> Callable[[NfseAuthorizationRequest, Sp4OriginalRps], OsascoRtcTaxFields]:
    """A policy port must supply facts; this layer will never invent RTC tags."""
    if not callable(resolve_policy):
        raise OsascoReviewedTaxPolicyError("Osasco reviewed tax policy port is required")

    def resolve(
        request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> OsascoRtcTaxFields:
        return reviewed_osasco_rtc_fields(request, original, resolve_policy(request, original))

    return resolve
