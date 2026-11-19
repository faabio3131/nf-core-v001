"""MG first wave is a strictly non-authoritative prioritization catalogue."""
from dataclasses import FrozenInstanceError, replace

import pytest

from kordena_fiscal.control_plane.mg_economic_priority_inventory import (
    IBGE_GDP_REFERENCE_YEAR,
    IBGE_GDP_SOURCE,
    MG_ECONOMIC_WAVE_1,
    MgMunicipalResearchState,
    mg_wave1_priority_municipality,
)
from kordena_fiscal.domain import FiscalValidationError


def test_mg_economic_wave_has_unique_top_twenty_in_rank_order() -> None:
    assert len(MG_ECONOMIC_WAVE_1) == 20
    assert tuple(item.rank_by_gdp_2023 for item in MG_ECONOMIC_WAVE_1) == tuple(range(1, 21))
    assert len({item.municipality_ibge for item in MG_ECONOMIC_WAVE_1}) == 20
    assert MG_ECONOMIC_WAVE_1[0].municipality_ibge == "3106200"
    assert MG_ECONOMIC_WAVE_1[-1].municipality_ibge == "3131703"
    assert IBGE_GDP_REFERENCE_YEAR == 2023
    assert IBGE_GDP_SOURCE.startswith("https://www.ibge.gov.br/")


def test_mg_wave_is_research_only_without_provider_or_issuance_authority() -> None:
    for municipality in MG_ECONOMIC_WAVE_1:
        assert municipality.municipality_ibge.startswith("31")
        assert municipality.research_state is MgMunicipalResearchState.RESEARCH_ONLY
        assert municipality.ibge_source_url.startswith(
            "https://www.ibge.gov.br/cidades-e-estados/mg/"
        )
        for dangerous_attribute in (
            "provider_binding_id", "endpoint_url", "issuer_channel",
            "production_approved", "homologated", "csc", "iss_rate",
        ):
            assert not hasattr(municipality, dangerous_attribute)


@pytest.mark.parametrize("code", ["", "3304557", "3100000", "not-a-code", "3106201"])
def test_unselected_municipality_fails_closed(code: str) -> None:
    with pytest.raises(FiscalValidationError, match="outside MG economic"):
        mg_wave1_priority_municipality(code)


def test_lookup_does_not_promote_a_municipality() -> None:
    item = mg_wave1_priority_municipality("3106200")
    assert item.municipality == "Belo Horizonte"
    assert item.research_state is MgMunicipalResearchState.RESEARCH_ONLY
    with pytest.raises(FrozenInstanceError):
        item.municipality = "Other"  # type: ignore[misc]


def test_ibge_mismatch_and_untrusted_evidence_rejected() -> None:
    item = mg_wave1_priority_municipality("3106200")
    with pytest.raises(FiscalValidationError):
        replace(item, municipality_ibge="3304557")
    with pytest.raises(FiscalValidationError, match="IBGE"):
        replace(item, ibge_source_url="https://evil.example.org/cidades-e-estados/mg/a")
    with pytest.raises(FiscalValidationError, match="IBGE"):
        replace(item, ibge_source_url="http://www.ibge.gov.br/cidades-e-estados/mg/a")
    with pytest.raises(FiscalValidationError, match="state"):
        replace(item, research_state="homologated")  # type: ignore[arg-type]
