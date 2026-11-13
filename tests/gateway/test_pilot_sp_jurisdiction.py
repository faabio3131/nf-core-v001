"""Pure pilot routing tests. No calls to fiscal services."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError
from kordena_fiscal.domain.profile import TaxRegimeCode
from kordena_fiscal.gateway.pilot_sp_jurisdiction import (
    SpPilotRoute,
    require_sp_pilot_operation_policy,
    resolve_sp_pilot_route,
)
from kordena_fiscal.gateway.provider import ProviderOperation

CITIES = ("3509205", "3548708", "3550308")


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("document,channel", [
    ("nfe", "sefaz-sp-nfe"),
    ("nfce", "sefaz-sp-nfce"),
    ("nfse", "nfse-national"),
])
def test_all_pilot_documents(city: str, document: str, channel: str) -> None:
    route = resolve_sp_pilot_route(
        jurisdiction=BrazilianJurisdiction("SP", city),
        document=document,
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        competence_date=date(2026, 11, 4),
    )
    assert route.channel == channel
    assert route.municipality_ibge_code == city
    assert route.requires_external_homologation


@pytest.mark.parametrize("regime", [
    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
    TaxRegimeCode.MEI,
])
def test_other_simples_variants_route_national(regime: TaxRegimeCode) -> None:
    assert resolve_sp_pilot_route(
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        document="nfse",
        tax_regime=regime,
        competence_date=date(2026, 11, 4),
    ).channel == "nfse-national"


@pytest.mark.parametrize("city", CITIES)
def test_historical_service_competence_denied(city: str) -> None:
    with pytest.raises(FiscalValidationError):
        resolve_sp_pilot_route(
            jurisdiction=BrazilianJurisdiction("SP", city),
            document="nfse",
            tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
            competence_date=date(2026, 10, 31),
        )


def test_normal_regime_service_denied_without_evidence() -> None:
    with pytest.raises(FiscalValidationError):
        resolve_sp_pilot_route(
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            document="nfse",
            tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 11, 4),
        )


@pytest.mark.parametrize("jurisdiction", [
    BrazilianJurisdiction("RJ", "3304557"),
    BrazilianJurisdiction("SP", "3509502"),
    BrazilianJurisdiction("SP"),
])
def test_not_approved_pilot_location_denied(jurisdiction: BrazilianJurisdiction) -> None:
    with pytest.raises(FiscalValidationError):
        resolve_sp_pilot_route(
            jurisdiction=jurisdiction, document="nfe",
            tax_regime=TaxRegimeCode.NORMAL, competence_date=date(2026, 11, 4),
        )



def _route(city: str, document: str) -> SpPilotRoute:
    return resolve_sp_pilot_route(
        jurisdiction=BrazilianJurisdiction("SP", city),
        document=document,  # type: ignore[arg-type]
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        competence_date=date(2026, 11, 4),
    )


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("document", ("nfe", "nfce"))
def test_sp_inutilization_denied_after_november_cutover(
    city: str, document: str,
) -> None:
    with pytest.raises(FiscalValidationError, match="no longer applies"):
        require_sp_pilot_operation_policy(
            route=_route(city, document),
            operation=ProviderOperation.INUTILIZE,
            requested_at=datetime(2026, 11, 4, tzinfo=UTC),
        )


@pytest.mark.parametrize("document", ("nfe", "nfce"))
def test_sp_inutilization_uses_sp_local_date_boundary(document: str) -> None:
    route = _route("3550308", document)
    # Just before midnight SP, not a proof that the provider would authorize.
    require_sp_pilot_operation_policy(
        route=route, operation=ProviderOperation.INUTILIZE,
        requested_at=datetime(2026, 11, 1, 2, 59, tzinfo=UTC),
    )
    with pytest.raises(FiscalValidationError, match="no longer applies"):
        require_sp_pilot_operation_policy(
            route=route, operation=ProviderOperation.INUTILIZE,
            requested_at=datetime(2026, 11, 1, 0, 0, tzinfo=timezone(timedelta(hours=-3))),
        )


def test_sp_nfse_inutilization_not_supported() -> None:
    with pytest.raises(FiscalValidationError, match="NFS-e"):
        require_sp_pilot_operation_policy(
            route=_route("3550308", "nfse"),
            operation=ProviderOperation.INUTILIZE,
            requested_at=datetime(2026, 11, 4, tzinfo=UTC),
        )


@pytest.mark.parametrize("operation", (ProviderOperation.QUERY, ProviderOperation.CANCEL))
def test_sp_negative_policy_does_not_assert_provider_readiness(
    operation: ProviderOperation,
) -> None:
    assert require_sp_pilot_operation_policy(
        route=_route("3509205", "nfe"),
        operation=operation,
        requested_at=datetime(2026, 11, 4, tzinfo=UTC),
    ) is None


def test_sp_operation_gate_rejects_invalid_or_naive_context() -> None:
    route = _route("3550308", "nfe")
    with pytest.raises(FiscalValidationError, match="context"):
        require_sp_pilot_operation_policy(
            route=route, operation=ProviderOperation.INUTILIZE,
            requested_at=datetime(2026, 11, 4),
        )
    with pytest.raises(FiscalValidationError, match="context"):
        require_sp_pilot_operation_policy(
            route=route, operation="inutilize",  # type: ignore[arg-type]
            requested_at=datetime(2026, 11, 4, tzinfo=UTC),
        )
    with pytest.raises(FiscalValidationError, match="context"):
        require_sp_pilot_operation_policy(
            route=SpPilotRoute("3509205", "nfe", "nfse-national"),
            operation=ProviderOperation.INUTILIZE,
            requested_at=datetime(2026, 11, 4, tzinfo=UTC),
        )


@pytest.mark.parametrize("city", CITIES)
@pytest.mark.parametrize("competence", [
    date(2023, 9, 1), date(2026, 9, 1), date(2026, 10, 31),
])
def test_mei_pilot_uses_national_from_2023_without_2026_me_epp_cutoff(
    city: str, competence: date,
) -> None:
    route = resolve_sp_pilot_route(
        jurisdiction=BrazilianJurisdiction("SP", city),
        document="nfse",
        tax_regime=TaxRegimeCode.MEI,
        competence_date=competence,
    )
    assert route.channel == "nfse-national"
    assert route.requires_external_homologation


@pytest.mark.parametrize("city", CITIES)
def test_mei_before_september_2023_fails_closed_without_legacy_contract(
    city: str,
) -> None:
    with pytest.raises(FiscalValidationError, match="explicit official eligibility"):
        resolve_sp_pilot_route(
            jurisdiction=BrazilianJurisdiction("SP", city),
            document="nfse",
            tax_regime=TaxRegimeCode.MEI,
            competence_date=date(2023, 8, 31),
        )


@pytest.mark.parametrize("regime", [
    TaxRegimeCode.SIMPLES_NACIONAL,
    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
])
def test_me_epp_pre_november_2026_not_forced_into_national(
    regime: TaxRegimeCode,
) -> None:
    with pytest.raises(FiscalValidationError, match="explicit official eligibility"):
        resolve_sp_pilot_route(
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            document="nfse",
            tax_regime=regime,
            competence_date=date(2026, 10, 31),
        )
