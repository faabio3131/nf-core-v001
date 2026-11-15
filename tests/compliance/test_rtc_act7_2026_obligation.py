"""Act 7/2026 obligation dates, dated source, and strict category selection."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.compliance.rtc import (
    LegalObligationStatus,
    RtcNfseSupplyCategory,
    RtcPolicyResolutionError,
    TechnicalValidationMode,
)
from kordena_fiscal.compliance.rtc_legal_schedule_2026 import (
    ACT_7_2026_SOURCE,
    rtc_nfse_act7_2026_policy,
)
from kordena_fiscal.domain import FiscalDocumentKind, FiscalValidationError, TaxRegimeCode


@pytest.mark.parametrize(
    ("regime", "category", "deadline"),
    [
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.ISS_GENERAL_D,
            datetime(2026, 10, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.ISS_SOFTWARE_B,
            datetime(2027, 3, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.DIGITAL_PLATFORM_A,
            datetime(2027, 3, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.ISS_TRANSPORT_C,
            datetime(2027, 3, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.INTANGIBLE_E,
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.CONDOMINIUM_F,
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
        (TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.LEASE_G, datetime(2027, 1, 1, tzinfo=UTC)),
        (TaxRegimeCode.NORMAL, RtcNfseSupplyCategory.OTHER_H, datetime(2027, 1, 1, tzinfo=UTC)),
        (
            TaxRegimeCode.SIMPLES_NACIONAL, RtcNfseSupplyCategory.ISS_GENERAL_D,
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.SIMPLES_NACIONAL, RtcNfseSupplyCategory.ISS_SOFTWARE_B,
            datetime(2027, 3, 1, tzinfo=UTC),
        ),
        (
            TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, RtcNfseSupplyCategory.ISS_GENERAL_D,
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
    ],
)
def test_act7_obligation_transition_on_exact_day(
    regime: TaxRegimeCode, category: RtcNfseSupplyCategory, deadline: datetime,
) -> None:
    policy = rtc_nfse_act7_2026_policy()
    def resolve(instant: datetime):
        return policy.resolve(
            document_kind=FiscalDocumentKind.NFSE,
            tax_regime=regime,
            instant=instant,
            nfse_supply_category=category,
        )
    before = resolve(deadline - timedelta(microseconds=1))
    after = resolve(deadline)
    assert before.obligation is LegalObligationStatus.DEFERRED
    assert after.obligation is LegalObligationStatus.REQUIRED
    assert before.source_normative == after.source_normative == ACT_7_2026_SOURCE
    # A technical non-rejection does not revoke a statutory obligation.
    assert before.validation_mode is TechnicalValidationMode.TOLERANT
    assert after.validation_mode is TechnicalValidationMode.TOLERANT


@pytest.mark.parametrize("regime", [
    TaxRegimeCode.NORMAL,
    TaxRegimeCode.SIMPLES_NACIONAL,
])
def test_no_browser_service_category_is_never_inferred(regime: TaxRegimeCode) -> None:
    policy = rtc_nfse_act7_2026_policy()
    with pytest.raises(RtcPolicyResolutionError):
        policy.resolve(
            document_kind=FiscalDocumentKind.NFSE,
            tax_regime=regime,
            instant=datetime(2026, 11, 15, tzinfo=UTC),
        )


def test_unknown_mei_transition_does_not_inherit_normal_rule() -> None:
    policy = rtc_nfse_act7_2026_policy()
    with pytest.raises(RtcPolicyResolutionError):
        policy.resolve(
            document_kind=FiscalDocumentKind.NFSE,
            tax_regime=TaxRegimeCode.MEI,
            instant=datetime(2027, 1, 1, tzinfo=UTC),
            nfse_supply_category=RtcNfseSupplyCategory.ISS_GENERAL_D,
        )


def test_category_cannot_be_attached_to_unrelated_document() -> None:
    policy = rtc_nfse_act7_2026_policy()
    with pytest.raises(FiscalValidationError):
        policy.resolve(
            document_kind=FiscalDocumentKind.NFE,
            tax_regime=TaxRegimeCode.NORMAL,
            instant=datetime(2027, 3, 1, tzinfo=UTC),
            nfse_supply_category=RtcNfseSupplyCategory.ISS_GENERAL_D,
        )
