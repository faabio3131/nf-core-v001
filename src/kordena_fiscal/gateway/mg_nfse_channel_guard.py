"""Negative issuer-channel eligibility gate for priority Minas Gerais municipalities.

The durable Control Plane provider binding remains the sole transmission authority.
This gate only refuses a known-ineligible SEFIN Nacional dispatch; it never
selects a provider, authorizes a city, or substitutes the municipal WSDL/API.

Sources: federal NFS-e guidance 29/10/2026; individual municipal notices
recorded in docs/NFCORE_MG_NFSE_OFFICIAL_CHANNEL_EVIDENCE_2026-11-11.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from kordena_fiscal.control_plane.mg_economic_priority_inventory import MG_ECONOMIC_WAVE_1
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalValidationError,
    TaxRegimeCode,
)

_SIMPLES_NATIONAL_MANDATORY_FROM = date(2026, 11, 1)
_FEDERAL_SOURCE = (
    "https://www.gov.br/nfse/pt-br/noticias/"
    "nfs-e-informa-diretrizes-sobre-a-obrigatoriedade-da-emissao-da-nfs-e-nacional-"
    "para-optantes-do-simples-nacional"
)


@dataclass(frozen=True, slots=True)
class MgNationalIssuerRule:
    """Municipal evidence of an exclusive national issuer, not a provider binding."""

    municipality_ibge: str
    effective_competence_from: date
    municipal_source: str


# Only municipalities where the official local evidence explicitly describes
# national emission for the relevant taxpayers. Other cities remain denied for
# non-Simples until a regime/competence-specific contract is verified.
_EXCLUSIVE_CHANNELS = (
    (
        "3106705", date(2026, 1, 1),
        "https://www.betim.mg.gov.br/portal/noticias/0/3/14975/"
        "prefeitura-de-betim-chama-a-atencao-para-novo-padrao-de-emissao-de-notas-fiscais",
    ),
    (
        "3136702", date(2026, 9, 1),
        "https://nfse.pjf.mg.gov.br/ComunicadoNfseNacional.html",
    ),
    (
        "3167202", date(2026, 1, 1),
        "https://ibs.setelagoas.mg.gov.br/nfse.html",
    ),
    (
        "3144805", date(2026, 1, 1),
        "https://novalima.mg.gov.br/inicio/noticias/nova_lima_adere_ao_padrao_naciona"
        "l_da_nota_fiscal_de_servicos_eletronica_nfs_e",
    ),
    (
        "3104007", date(2026, 1, 1),
        "https://araxa.mg.gov.br/noticia/8610/prefeitura-de-araxa-orienta-prestadores"
        "-de-servico-sobre-nova-forma-de-emitir-nota-fiscal-em-2026",
    ),
    (
        "3148004", date(2026, 1, 1),
        "https://www.patosdeminas.mg.gov.br/portal/secretarias-paginas/76/nfs-e-nacional/",
    ),
    (
        "3118007", date(2026, 1, 1),
        "https://www.congonhas.mg.gov.br/index.php/congonhas-adota-novo-modelo-nacion"
        "al-de-emissao-da-nota-fiscal-de-servicos-eletronica-nfs-e/",
    ),
)

MG_NATIONAL_CHANNEL_RULES = MappingProxyType({
    ibge: MgNationalIssuerRule(ibge, from_date, source)
    for ibge, from_date, source in _EXCLUSIVE_CHANNELS
})
_MG_W1_CODES = frozenset(item.municipality_ibge for item in MG_ECONOMIC_WAVE_1)
# BH municipal notice (11/08/2026) confirms ME/EPP Simples already required
# the National emitter in BH since the November 2025 competence.
# https://prefeitura.pbh.gov.br/fazenda/bhiss/avisos?page=1
_MG_EARLY_SIMPLES_CUTOFFS = MappingProxyType({
    "3106200": date(2025, 11, 1),
})

if len(MG_NATIONAL_CHANNEL_RULES) != len(_EXCLUSIVE_CHANNELS):
    raise ValueError("Duplicate municipality in national issuer channel contract")
if not frozenset(MG_NATIONAL_CHANNEL_RULES).issubset(_MG_W1_CODES):
    raise ValueError("National issuer channel evidence outside selected MG-W1 scope")


def require_mg_national_channel_eligibility(
    *,
    jurisdiction: BrazilianJurisdiction,
    tax_regime: TaxRegimeCode,
    competence_date: date,
) -> None:
    """Refuse incompatible national issuance before certificate access or network I/O.

    No approval is implied on success: exact durable unit/operation binding,
    valid A1, official XSD+XMLDSig, municipal tax evidence, and SEFIN response
    are independent required gates.
    """
    if not isinstance(jurisdiction, BrazilianJurisdiction):
        raise FiscalValidationError("Issuer jurisdiction is required")
    if not isinstance(tax_regime, TaxRegimeCode):
        raise FiscalValidationError("Issuer tax regime is required")
    if not isinstance(competence_date, date):
        raise FiscalValidationError("Service competence is required")
    if jurisdiction.state_code != "MG":
        return
    municipality = jurisdiction.municipality_ibge_code
    if municipality not in _MG_W1_CODES:
        # Not a hardcoded national list or substitute for approved bindings:
        # other municipalities continue through the canonical Control Plane.
        return

    # MEI has its own long-standing federal national-emitter obligation.
    if tax_regime is TaxRegimeCode.MEI:
        return
    if tax_regime in (
        TaxRegimeCode.SIMPLES_NACIONAL,
        TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
    ):
        cutoff = _MG_EARLY_SIMPLES_CUTOFFS.get(
            municipality, _SIMPLES_NATIONAL_MANDATORY_FROM
        )
        if competence_date >= cutoff:
            return
    exclusive = MG_NATIONAL_CHANNEL_RULES.get(municipality)
    if exclusive is not None and competence_date >= exclusive.effective_competence_from:
        return
    raise FiscalValidationError(
        "Emissor Nacional NFS-e nao comprovado para municipio, regime e competencia; "
        "exige contrato do emissor municipal ou evidencia oficial de elegibilidade"
    )
