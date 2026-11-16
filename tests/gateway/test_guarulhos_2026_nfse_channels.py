"""Guarulhos 2026 regime/competence issuer split under CGSN 191/2026.

Municipality-specific source: GissOnline V2 01/07/2026; federal mandatory
national issuer for Simples competences from 01/11/2026. No guessed SOAP I/O.
"""
from __future__ import annotations

from datetime import date

import pytest

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.municipal_sp_routing import (
    GUARULHOS_GISS_V2_PROVIDER_ID,
    GUARULHOS_IBGE,
    require_guarulhos_nfse_channel,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)

_CITY = BrazilianJurisdiction("SP", GUARULHOS_IBGE)


@pytest.mark.parametrize(("regime", "competence", "provider", "accepted"), [
    (TaxRegimeCode.NORMAL, date(2026, 11, 15), GUARULHOS_GISS_V2_PROVIDER_ID, True),
    (TaxRegimeCode.NORMAL, date(2026, 11, 15), NACIONAL_HOMOLOGATION_PROVIDER_ID, False),
    (TaxRegimeCode.NORMAL, date(2026, 6, 30), GUARULHOS_GISS_V2_PROVIDER_ID, False),
    (TaxRegimeCode.NORMAL, date(2026, 7, 1), GUARULHOS_GISS_V2_PROVIDER_ID, True),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31), GUARULHOS_GISS_V2_PROVIDER_ID, True),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31), NACIONAL_HOMOLOGATION_PROVIDER_ID, False),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1), GUARULHOS_GISS_V2_PROVIDER_ID, False),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1), NACIONAL_HOMOLOGATION_PROVIDER_ID, True),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 15), NACIONAL_HOMOLOGATION_PROVIDER_ID, True),
    (TaxRegimeCode.MEI, date(2026, 11, 15), NACIONAL_HOMOLOGATION_PROVIDER_ID, True),
    (TaxRegimeCode.MEI, date(2026, 11, 15), GUARULHOS_GISS_V2_PROVIDER_ID, False),
    (TaxRegimeCode.MEI, date(2023, 8, 31), GUARULHOS_GISS_V2_PROVIDER_ID, False),
])
def test_guarulhos_current_tax_regime_and_competence_routing(
    regime: TaxRegimeCode, competence: date, provider: str, accepted: bool,
) -> None:
    if accepted:
        require_guarulhos_nfse_channel(
            issuer_jurisdiction=_CITY,
            tax_regime=regime, competence_date=competence, provider_id=provider,
        )
    else:
        with pytest.raises(FiscalValidationError, match="Guarulhos"):
            require_guarulhos_nfse_channel(
                issuer_jurisdiction=_CITY,
                tax_regime=regime, competence_date=competence, provider_id=provider,
            )


@pytest.mark.parametrize("bad", [None, "", object(), "ginfes", "jundiai-giss-v2-homologation"])
def test_guarulhos_refuses_implicit_or_foreign_provider(bad: object) -> None:
    with pytest.raises(FiscalValidationError, match="Guarulhos"):
        require_guarulhos_nfse_channel(
            issuer_jurisdiction=_CITY, tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 11, 15), provider_id=bad,  # type: ignore[arg-type]
        )


def test_guarulhos_regime_rule_never_changes_unrelated_cities() -> None:
    require_guarulhos_nfse_channel(
        issuer_jurisdiction=BrazilianJurisdiction("SP", "3527306"),
        tax_regime=TaxRegimeCode.NORMAL, competence_date=date(2026, 11, 15),
        provider_id=NACIONAL_HOMOLOGATION_PROVIDER_ID,
    )
    require_guarulhos_nfse_channel(
        issuer_jurisdiction=BrazilianJurisdiction("MG", "3106200"),
        tax_regime=TaxRegimeCode.NORMAL, competence_date=date(2026, 11, 15),
        provider_id=NACIONAL_HOMOLOGATION_PROVIDER_ID,
    )
