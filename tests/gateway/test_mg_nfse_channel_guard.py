"""Negative channel-policy tests for the MG-W1 fiscal envelope boundary.

These tests do NOT imply national binding, production approval or tax rates.
"""
from __future__ import annotations

from datetime import date

import pytest

from kordena_fiscal.control_plane.mg_economic_priority_inventory import MG_ECONOMIC_WAVE_1
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.mg_nfse_channel_guard import (
    MG_NATIONAL_CHANNEL_RULES,
    require_mg_national_channel_eligibility,
)


def _check(municipality: str, regime: TaxRegimeCode, competence: date) -> None:
    require_mg_national_channel_eligibility(
        jurisdiction=BrazilianJurisdiction("MG", municipality),
        tax_regime=regime,
        competence_date=competence,
    )


@pytest.mark.parametrize(
    "municipality", [item.municipality_ibge for item in MG_ECONOMIC_WAVE_1],
)
@pytest.mark.parametrize(
    "regime",
    [TaxRegimeCode.SIMPLES_NACIONAL, TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT],
)
def test_all_twenty_mg_poles_apply_federal_simples_national_rule(
    municipality: str, regime: TaxRegimeCode,
) -> None:
    _check(municipality, regime, date(2026, 11, 1))
    _check(municipality, regime, date(2026, 12, 15))


@pytest.mark.parametrize(
    "municipality", [item.municipality_ibge for item in MG_ECONOMIC_WAVE_1],
)
def test_mei_national_emitter_is_not_blocked_by_municipal_emitter(
    municipality: str,
) -> None:
    _check(municipality, TaxRegimeCode.MEI, date(2026, 8, 1))


def test_only_sourced_exclusive_national_channels_allow_normal_regime() -> None:
    codes = {item.municipality_ibge for item in MG_ECONOMIC_WAVE_1}
    assert len(MG_NATIONAL_CHANNEL_RULES) == 7
    for code in codes:
        if code in MG_NATIONAL_CHANNEL_RULES:
            rule = MG_NATIONAL_CHANNEL_RULES[code]
            assert rule.municipal_source.startswith("https://")
            _check(code, TaxRegimeCode.NORMAL, date(2026, 11, 6))
        else:
            with pytest.raises(FiscalValidationError, match="municipio, regime"):
                _check(code, TaxRegimeCode.NORMAL, date(2026, 11, 6))


@pytest.mark.parametrize(
    "municipality",
    ["3118601", "3170107", "3125101", "3131703", "3170206"],
)
def test_previous_competence_never_sneaks_through_federal_rule(
    municipality: str,
) -> None:
    with pytest.raises(FiscalValidationError, match="emissor municipal"):
        _check(municipality, TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31))


def test_bh_simples_uses_earlier_municipal_national_cutover() -> None:
    """BHISS published compulsory national issuance since November 2025."""
    _check("3106200", TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31))
    _check("3106200", TaxRegimeCode.SIMPLES_NACIONAL, date(2025, 11, 1))
    with pytest.raises(FiscalValidationError):
        _check("3106200", TaxRegimeCode.SIMPLES_NACIONAL, date(2025, 10, 31))


def test_municipal_effective_competence_is_not_backdated() -> None:
    betim = MG_NATIONAL_CHANNEL_RULES["3106705"]
    _check("3106705", TaxRegimeCode.NORMAL, betim.effective_competence_from)
    with pytest.raises(FiscalValidationError):
        _check("3106705", TaxRegimeCode.NORMAL, date(2025, 12, 31))
    juiz = MG_NATIONAL_CHANNEL_RULES["3136702"]
    _check("3136702", TaxRegimeCode.NORMAL, juiz.effective_competence_from)
    with pytest.raises(FiscalValidationError):
        _check("3136702", TaxRegimeCode.NORMAL, date(2026, 8, 31))


def test_other_states_remain_with_canonical_provider_binding_authority() -> None:
    require_mg_national_channel_eligibility(
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 9, 1),
    )


def test_regime_and_competence_must_be_validated_by_domain() -> None:
    with pytest.raises(FiscalValidationError):
        require_mg_national_channel_eligibility(
            jurisdiction=BrazilianJurisdiction("MG", "3118601"),
            tax_regime="simples",  # type: ignore[arg-type]
            competence_date=date(2026, 11, 1),
        )
    with pytest.raises(FiscalValidationError):
        require_mg_national_channel_eligibility(
            jurisdiction=BrazilianJurisdiction("MG", "3118601"),
            tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
            competence_date="2026-11-01",  # type: ignore[arg-type]
        )
