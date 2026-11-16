"""Federal NFS-e eligibility for 22 SP candidates is not provider certification."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NfseNacionalHomologationGateway,
    OfficialNfseTransportError,
    require_nfse_national_issuer_eligibility,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
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


@pytest.mark.parametrize("ibge", ["3550308", "3545209", "3527306"])
@pytest.mark.parametrize(
    ("regime", "competence"),
    [
        (TaxRegimeCode.MEI, date(2023, 9, 1)),
        (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
        (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 1)),
    ],
)
def test_national_gateway_preflight_accepts_sp_federal_regimes_only_as_candidates(
    ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    """Eligibility alone cannot grant a durable provider binding or SEFIN access."""
    require_nfse_national_issuer_eligibility(
        jurisdiction=BrazilianJurisdiction("SP", ibge),
        tax_regime=regime,
        competence_date=competence,
    )


@pytest.mark.parametrize(
    ("regime", "competence"),
    [
        (TaxRegimeCode.NORMAL, date(2026, 11, 12)),
        (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31)),
        (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 10, 31)),
        (TaxRegimeCode.MEI, date(2023, 8, 31)),
    ],
)
def test_national_transport_refuses_sp_ineligible_issuer_before_a1_or_sefin(
    regime: TaxRegimeCode, competence: date,
) -> None:
    """MG's non-MG no-op must never permit an unreviewed SP fiscal POST."""
    request = Mock(spec=NfseAuthorizationRequest)
    request.document = Mock()
    request.document.scope.environment = FiscalEnvironment.HOMOLOGATION
    request.document.dps_number = 1
    request.document.issuer.address.jurisdiction = BrazilianJurisdiction(
        "SP", "3550308"
    )
    request.document.issuer.cnpj.value = "12345678000195"
    request.document.issuer.tax_regime = regime
    request.document.competence_date = competence

    resolve_certificate = Mock()
    sign_dps = Mock()
    exchange = Mock()
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=resolve_certificate,
        build_signed_dps=sign_dps,
        exchange=exchange,
    )
    with pytest.raises(OfficialNfseTransportError, match="indisponível"):
        gateway.authorize(request)
    resolve_certificate.assert_not_called()
    sign_dps.assert_not_called()
    exchange.assert_not_called()


def test_national_gateway_keeps_mg_issuer_channel_policy() -> None:
    """SP correction must not bypass the independently governed MG rule."""
    with pytest.raises(FiscalValidationError, match="municipio, regime"):
        require_nfse_national_issuer_eligibility(
            jurisdiction=BrazilianJurisdiction("MG", "3118601"),
            tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 11, 15),
        )
