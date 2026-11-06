"""Fail-closed guard: Simples Nacional cannot be routed to the legacy SP webservice.

Encodes the São Paulo Secretaria Municipal da Fazenda's published mandatory
date for the Emissor Nacional (2026-09-01 for Simples Nacional). This is a
structural guard, not a provider routing decision -- see the module
docstring in ``gateway/municipal_sp_routing.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kordena_fiscal.gateway.municipal_sp_routing import (
    MunicipalTransportNotPermittedError,
    ensure_municipal_sp_transport_permitted,
)
from kordena_fiscal.gateway.provider import UnsupportedProviderError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

_SAO_PAULO_IBGE = "3550308"
_OTHER_SP_IBGE = "3509502"  # Campinas


def test_simples_nacional_blocked_on_or_after_mandatory_date() -> None:
    with pytest.raises(MunicipalTransportNotPermittedError):
        ensure_municipal_sp_transport_permitted(
            FederalIncomeTaxRegime.SIMPLES_NACIONAL,
            issuer_ibge_code=_SAO_PAULO_IBGE,
            as_of=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_simples_nacional_blocked_well_after_mandatory_date() -> None:
    with pytest.raises(MunicipalTransportNotPermittedError):
        ensure_municipal_sp_transport_permitted(
            FederalIncomeTaxRegime.SIMPLES_NACIONAL,
            issuer_ibge_code=_SAO_PAULO_IBGE,
            as_of=datetime(2026, 11, 6, tzinfo=UTC),
        )


def test_simples_nacional_permitted_before_mandatory_date() -> None:
    ensure_municipal_sp_transport_permitted(
        FederalIncomeTaxRegime.SIMPLES_NACIONAL,
        issuer_ibge_code=_SAO_PAULO_IBGE,
        as_of=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "regime", [FederalIncomeTaxRegime.LUCRO_PRESUMIDO, FederalIncomeTaxRegime.LUCRO_REAL]
)
def test_non_simples_regimes_never_blocked(regime: FederalIncomeTaxRegime) -> None:
    ensure_municipal_sp_transport_permitted(
        regime,
        issuer_ibge_code=_SAO_PAULO_IBGE,
        as_of=datetime(2027, 1, 1, tzinfo=UTC),
    )


def test_guard_is_scoped_to_sao_paulo_city_only() -> None:
    # Other SP municipalities are not affected by this specific deadline.
    ensure_municipal_sp_transport_permitted(
        FederalIncomeTaxRegime.SIMPLES_NACIONAL,
        issuer_ibge_code=_OTHER_SP_IBGE,
        as_of=datetime(2027, 1, 1, tzinfo=UTC),
    )


def test_naive_datetime_rejected() -> None:
    with pytest.raises(UnsupportedProviderError, match="timezone-aware"):
        ensure_municipal_sp_transport_permitted(
            FederalIncomeTaxRegime.SIMPLES_NACIONAL,
            issuer_ibge_code=_SAO_PAULO_IBGE,
            as_of=datetime(2026, 9, 1),  # noqa: DTZ001 -- intentional naive input under test
        )


def test_error_is_an_unsupported_provider_error() -> None:
    assert issubclass(MunicipalTransportNotPermittedError, UnsupportedProviderError)
