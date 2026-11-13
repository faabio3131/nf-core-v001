"""São Paulo capital legacy emitter: CGSN 191/2026 and competence cutoff.

The 01/09/2026 date was explicitly revoked; 01/11/2026 is the ME/EPP
Simples effective competence. Tests never grant municipal authorization.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from kordena_fiscal.gateway.municipal_sp_routing import (
    SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM,
    MunicipalTransportNotPermittedError,
    ensure_municipal_sp_transport_permitted,
)
from kordena_fiscal.gateway.provider import UnsupportedProviderError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

_SAO_PAULO_IBGE = "3550308"
_OTHER_SP_IBGE = "3509502"  # Campinas


def _guard(
    competence: date, *,
    regime: FederalIncomeTaxRegime = FederalIncomeTaxRegime.SIMPLES_NACIONAL,
    issuer: str = _SAO_PAULO_IBGE,
    when: datetime | None = None,
) -> None:
    ensure_municipal_sp_transport_permitted(
        regime,
        issuer_ibge_code=issuer,
        competence_date=competence,
        as_of=when if when is not None else datetime(2026, 11, 12, 12, tzinfo=UTC),
    )


def test_2026_11_01_is_authoritative_me_epp_simples_cutoff() -> None:
    assert SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM == date(2026, 11, 1)


@pytest.mark.parametrize("competence", [
    date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 30),
    date(2026, 10, 31),
])
def test_legacy_city_route_not_rejected_for_pre_november_competence(
    competence: date,
) -> None:
    # This guard is a *negative-only* gate, not provider or fiscal approval.
    _guard(competence)


@pytest.mark.parametrize("competence", [
    date(2026, 11, 1), date(2026, 11, 12), date(2027, 1, 1),
])
def test_national_emitter_required_for_me_epp_simples_competence_from_november(
    competence: date,
) -> None:
    with pytest.raises(MunicipalTransportNotPermittedError, match="2026-11-01"):
        _guard(competence)


def test_retroactive_october_competence_not_incorrectly_blocked_by_december_clock() -> None:
    _guard(date(2026, 10, 31), when=datetime(2026, 12, 15, tzinfo=UTC))


@pytest.mark.parametrize("regime", [
    FederalIncomeTaxRegime.LUCRO_PRESUMIDO,
    FederalIncomeTaxRegime.LUCRO_REAL,
])
def test_non_simples_not_blocked_by_cgsn_me_epp_cutoff(
    regime: FederalIncomeTaxRegime,
) -> None:
    _guard(date(2027, 1, 1), regime=regime)


def test_city_specific_guard_does_not_claim_provider_approval_elsewhere() -> None:
    # All-SP federal Simples routing is separately governed; returning from
    # this city-specific guard never authorizes an external transport.
    _guard(date(2027, 1, 1), issuer=_OTHER_SP_IBGE)


@pytest.mark.parametrize(
    "invalid_competence",
    [None, "2026-11-01", datetime(2026, 11, 1, tzinfo=UTC)],
)
def test_missing_or_unreviewed_competence_fails_closed(invalid_competence: object) -> None:
    with pytest.raises(UnsupportedProviderError, match="reviewed"):
        ensure_municipal_sp_transport_permitted(
            FederalIncomeTaxRegime.SIMPLES_NACIONAL,
            issuer_ibge_code=_SAO_PAULO_IBGE,
            competence_date=invalid_competence,  # type: ignore[arg-type]
            as_of=datetime(2026, 11, 12, tzinfo=UTC),
        )


def test_naive_execution_clock_rejected() -> None:
    with pytest.raises(UnsupportedProviderError, match="timezone-aware"):
        _guard(date(2026, 11, 12), when=datetime(2026, 11, 12))  # noqa: DTZ001


def test_invalid_regime_rejected() -> None:
    with pytest.raises(UnsupportedProviderError, match="reviewed"):
        ensure_municipal_sp_transport_permitted(
            "unknown",  # type: ignore[arg-type]
            issuer_ibge_code=_SAO_PAULO_IBGE,
            competence_date=date(2026, 11, 1),
            as_of=datetime(2026, 11, 12, tzinfo=UTC),
        )


def test_error_type_preserves_unsupported_provider_contract() -> None:
    assert issubclass(MunicipalTransportNotPermittedError, UnsupportedProviderError)
