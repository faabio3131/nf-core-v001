"""Economic first wave for MG: research scope, never fiscal routing authority.

The municipality list follows the 2023 municipal GDP ranking (IBGE/SIDRA).
IBGE municipality identifiers are checked against official Cidades e Estados.
Research metadata MUST NOT be used as a provider binding or readiness signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError

IBGE_GDP_REFERENCE_YEAR = 2023
IBGE_GDP_SOURCE = (
    "https://www.ibge.gov.br/estatisticas/economicas/industria/"
    "9088-produto-interno-bruto-dos-municipios.html"
)


class MgMunicipalResearchState(StrEnum):
    """No implied authorization, endpoint, municipal contract or fiscal readiness."""

    RESEARCH_ONLY = "research_only"


@dataclass(frozen=True, slots=True)
class MgEconomicPriorityMunicipality:
    rank_by_gdp_2023: int
    municipality: str
    municipality_ibge: str
    ibge_source_url: str
    research_state: MgMunicipalResearchState = MgMunicipalResearchState.RESEARCH_ONLY

    def __post_init__(self) -> None:
        if self.rank_by_gdp_2023 < 1 or self.rank_by_gdp_2023 > 20:
            raise FiscalValidationError("MG economic first-wave rank out of scope")
        if not self.municipality.strip():
            raise FiscalValidationError("MG first-wave municipality name is required")
        if (
            len(self.municipality_ibge) != 7
            or not self.municipality_ibge.isascii()
            or not self.municipality_ibge.isdecimal()
            or not self.municipality_ibge.startswith("31")
        ):
            raise FiscalValidationError("MG municipality IBGE code must have prefix 31")
        BrazilianJurisdiction("MG", self.municipality_ibge)
        if not isinstance(self.research_state, MgMunicipalResearchState):
            raise FiscalValidationError("MG first-wave research state is not recognized")
        source = urlsplit(self.ibge_source_url)
        if (
            source.scheme != "https"
            or source.hostname != "www.ibge.gov.br"
            or not source.path.startswith("/cidades-e-estados/mg/")
            or source.username
            or source.password
            or source.query
            or source.fragment
        ):
            raise FiscalValidationError("MG municipality evidence must use public IBGE source")


# Official IBGE municipality codes; GDP ranking is a 2023 prioritization criterion,
# not a fiscal-availability statement. No provider/endpoint/rate is configured here.
_MG_TOP_20_GDP_2023: tuple[tuple[str, str, str], ...] = (
    ("Belo Horizonte", "3106200", "belo-horizonte"),
    ("Betim", "3106705", "betim"),
    ("Uberlândia", "3170206", "uberlandia"),
    ("Contagem", "3118601", "contagem"),
    ("Uberaba", "3170107", "uberaba"),
    ("Juiz de Fora", "3136702", "juiz-de-fora"),
    ("Extrema", "3125101", "extrema"),
    ("Ipatinga", "3131307", "ipatinga"),
    ("Sete Lagoas", "3167202", "sete-lagoas"),
    ("Pouso Alegre", "3152501", "pouso-alegre"),
    ("Montes Claros", "3143302", "montes-claros"),
    ("Nova Lima", "3144805", "nova-lima"),
    ("Poços de Caldas", "3151800", "pocos-de-caldas"),
    ("Varginha", "3170701", "varginha"),
    ("Divinópolis", "3122306", "divinopolis"),
    ("Araxá", "3104007", "araxa"),
    ("Governador Valadares", "3127701", "governador-valadares"),
    ("Patos de Minas", "3148004", "patos-de-minas"),
    ("Congonhas", "3118007", "congonhas"),
    ("Itabira", "3131703", "itabira"),
)

MG_ECONOMIC_WAVE_1: tuple[MgEconomicPriorityMunicipality, ...] = tuple(
    MgEconomicPriorityMunicipality(
        rank_by_gdp_2023=rank,
        municipality=name,
        municipality_ibge=ibge,
        ibge_source_url=f"https://www.ibge.gov.br/cidades-e-estados/mg/{slug}.html",
    )
    for rank, (name, ibge, slug) in enumerate(_MG_TOP_20_GDP_2023, start=1)
)

if (
    len(MG_ECONOMIC_WAVE_1) != 20
    or len({item.municipality_ibge for item in MG_ECONOMIC_WAVE_1}) != 20
):
    raise FiscalValidationError("MG first-wave municipality identifiers must be unique")


def mg_wave1_priority_municipality(municipality_ibge: str) -> MgEconomicPriorityMunicipality:
    """Return *research-only* metadata; fail closed for unselected municipalities."""
    for municipality in MG_ECONOMIC_WAVE_1:
        if municipality.municipality_ibge == municipality_ibge:
            return municipality
    raise FiscalValidationError("Municipality is outside MG economic research wave 1")
