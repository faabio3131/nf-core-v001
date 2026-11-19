"""Reviewed RTC NFS-e *legal obligation* schedule, never XML/tax authority.

Source of legal deadlines: Ato Conjunto RFB/CGIBS 4/2026, amended by
Ato Conjunto RFB/CGIBS 7, 11 Nov 2026 (DOU 13 Nov 2026).
The National NFS-e portal confirms the revised dates:
https://www.gov.br/nfse/pt-br/noticias/cgnfs-e-informa-ato-conjunto-rfb-cgibs-no-7-2026-atualiza-o-cronograma-de-obrigatoriedade-de-emissao-da-nfs-e-para-ibs-e-cbs/

This table is deliberately passed through the EXISTING RtcEmissionPolicyResolver.
It does not infer taxpayer category from a service code and it does not make
future XSD, NT009 or tax amounts "authorized". Technical mode is pinned to
the CGNFS-e's 29 Oct 2026 ADN toleration notice; it must be reassessed before
fiscal production promotion.
"""
from __future__ import annotations

from datetime import UTC, datetime

from kordena_fiscal.domain import FiscalDocumentKind, TaxRegimeCode

from .rtc import (
    LegalObligationStatus,
    RtcEmissionPolicyResolver,
    RtcEmissionPolicyRule,
    RtcNfseSupplyCategory,
    TechnicalValidationMode,
)

ACT_7_2026_SOURCE = (
    "https://www.in.gov.br/en/web/dou/-/"
    "ato-conjunto-rfb/cgibs-n-7-de-11-de-novembro-de-2026-744148934"
)
TECHNICAL_TOLERANCE_SOURCE = (
    "https://www.gov.br/nfse/pt-br/noticias/"
    "nfs-e-nacional-confira-oas-rientacoes-sobre-leiaute-em-producao-"
    "regras-de-preenchimento-de-ibs-cbs-e-status-da-nota-tecnica-009"
)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


# This is a *legal obligation schedule* for reviewed NFS-e categories only.
# Effective 2026-11-13 law: general taxable services remain 2026-10-01;
# a/b/c moved to March 2027; e/f/g/h moved to January 2027.
# Optantes do Simples Nacional d-h: January 2027; a-c: March 2027.
_NORMAL_DEADLINES = {
    RtcNfseSupplyCategory.ISS_GENERAL_D: _utc(2026, 10, 1),
    RtcNfseSupplyCategory.DIGITAL_PLATFORM_A: _utc(2027, 3, 1),
    RtcNfseSupplyCategory.ISS_SOFTWARE_B: _utc(2027, 3, 1),
    RtcNfseSupplyCategory.ISS_TRANSPORT_C: _utc(2027, 3, 1),
    RtcNfseSupplyCategory.INTANGIBLE_E: _utc(2027, 1, 1),
    RtcNfseSupplyCategory.CONDOMINIUM_F: _utc(2027, 1, 1),
    RtcNfseSupplyCategory.LEASE_G: _utc(2027, 1, 1),
    RtcNfseSupplyCategory.OTHER_H: _utc(2027, 1, 1),
}
_SIMPLES_DEADLINES = {
    category: (
        _utc(2027, 3, 1)
        if category in {
            RtcNfseSupplyCategory.DIGITAL_PLATFORM_A,
            RtcNfseSupplyCategory.ISS_SOFTWARE_B,
            RtcNfseSupplyCategory.ISS_TRANSPORT_C,
        } else _utc(2027, 1, 1)
    )
    for category in RtcNfseSupplyCategory
}


def rtc_nfse_act7_2026_policy() -> RtcEmissionPolicyResolver:
    """Resolve a reviewed category/regime/date; no generic or MEI fallback.

    Legal requirement and *technical* rejection are independent. The National
    ADN does not reject absence of IBSCBS by itself in the 29 Oct release, but
    legally applicable obligations cannot be inferred as 'not required'.
    """
    rules: list[RtcEmissionPolicyRule] = []
    for regime in (
        TaxRegimeCode.NORMAL,
        TaxRegimeCode.SIMPLES_NACIONAL,
        TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
    ):
        schedule = (
            _NORMAL_DEADLINES if regime is TaxRegimeCode.NORMAL
            else _SIMPLES_DEADLINES
        )
        for category, deadline in schedule.items():
            identity = f"rtc-2026-act7-nfse-{regime.value}-{category.value}"
            for obligation, start, end in (
                (LegalObligationStatus.DEFERRED, _utc(2026, 8, 1), deadline),
                (LegalObligationStatus.REQUIRED, deadline, None),
            ):
                rules.append(RtcEmissionPolicyRule(
                    rule_id=f"{identity}-{obligation.value}",
                    version=1,
                    document_kind=FiscalDocumentKind.NFSE,
                    effective_from=start,
                    effective_to=end,
                    obligation=obligation,
                    validation_mode=TechnicalValidationMode.TOLERANT,
                    source_normative=ACT_7_2026_SOURCE,
                    tax_regime=regime,
                    nfse_supply_category=category,
                ))
    return RtcEmissionPolicyResolver(tuple(rules))
