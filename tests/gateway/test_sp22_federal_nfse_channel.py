"""Federal NFS-e eligibility for 22 SP candidates is not provider certification."""
from __future__ import annotations

from datetime import date

import pytest

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.municipal_sp_routing import (
    SP_MUNICIPAL_CANDIDATES,
    classify_sp_national_nfse_eligibility,
)


@pytest.mark.parametrize("ibge", SP_MUNICIPAL_CANDIDATES)
@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
    (TaxRegimeCode.MEI, date(2026, 10, 31)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 1)),
])
def test_all_22_sp_issuer_locations_classify_national_channel_without_approving_it(
    ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    result = classify_sp_national_nfse_eligibility(
        issuer_jurisdiction=BrazilianJurisdiction("SP", ibge),
        tax_regime=regime, competence_date=competence,
    )
    assert result.municipality_ibge == ibge
    assert result.channel == "nfse-national"
    assert result.requires_official_homologation
    assert result.is_runtime_authority is False


def test_policy_does_not_require_a_hardcoded_22_city_provider_allowlist() -> None:
    # The federal national regime is uniform; real bindings still fail
    # closed independently in the canonical Control Plane.
    other_sp_city = "3500105"  # Adamantina, not in the candidate list
    assert other_sp_city not in SP_MUNICIPAL_CANDIDATES
    result = classify_sp_national_nfse_eligibility(
        issuer_jurisdiction=BrazilianJurisdiction("SP", other_sp_city),
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        competence_date=date(2026, 11, 1),
    )
    assert result.is_runtime_authority is False


@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 8, 31)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 9, 1)),
    (TaxRegimeCode.NORMAL, date(2026, 11, 12)),
])
def test_federal_national_route_refuses_unverified_regime_and_historical_competence(
    regime: TaxRegimeCode, competence: date,
) -> None:
    with pytest.raises(FiscalValidationError, match="not nationally established"):
        classify_sp_national_nfse_eligibility(
            issuer_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            tax_regime=regime, competence_date=competence,
        )


def test_out_of_state_issuer_is_rejected_even_when_simples() -> None:
    with pytest.raises(FiscalValidationError, match="Invalid SP"):
        classify_sp_national_nfse_eligibility(
            issuer_jurisdiction=BrazilianJurisdiction("RJ", "3304557"),
            tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
            competence_date=date(2026, 11, 12),
        )


@pytest.mark.parametrize("regime", ["simples_nacional", None])
def test_noncanonical_tax_regime_is_rejected(regime: object) -> None:
    with pytest.raises(FiscalValidationError, match="Invalid SP"):
        classify_sp_national_nfse_eligibility(
            issuer_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            tax_regime=regime,  # type: ignore[arg-type]
            competence_date=date(2026, 11, 12),
        )
