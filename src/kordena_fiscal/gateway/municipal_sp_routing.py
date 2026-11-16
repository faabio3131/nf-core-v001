"""São Paulo NFS-e R16 routing via the EXISTING durable Control Plane authority.

The static catalog is advisory only and never authorizes provider transmission.
The canonical DurableProviderBindingResolver performs the actual exact-match
lookup by tenant, unit, environment, kind, issuer jurisdiction and operation.
No second authorization state, persistence, or fiscal gateway is introduced.

Municipal (São Paulo city) routing guard -- Simples Nacional / Emissor Nacional
--------------------------------------------------------------------------------
Official São Paulo City notice updated 13/08/2026 and Resolution CGSN
191/2026 moved the ME/EPP Simples transition from 01/09/2026 to
**01/11/2026**. The legal criterion is the SERVICE COMPETENCE DATE, not
the date of HTTP request or document issuance. Municipal legacy issuance
for retrospective competences through 31/10/2026 remains permissible
subject to the complete municipal provider contract and fiscal validation.
For competences from 01/11/2026, issuance by ME/EPP Simples must use
the National NFS-e issuer regardless of the municipality's own emitter.

This guard covers the corporate Simples classification. It does not certify
the MEI or autonomous professional channel or grant any positive provider
approval. For São Paulo city the autonomous cutoff is 03/08/2026 and
requires a separate scoped taxpayer classification, not inferred here.

Sources:
https://prefeitura.sp.gov.br/web/fazenda/w/usoemissornacional
https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/simples-nacional-nfs-e-nacional-sera-obrigatoria-para-me-e-epp-a-partir-de-1o-de-novembro-de-2026

``ensure_municipal_sp_transport_permitted`` is a structural fail-closed guard,
not a routing decision: it does not pick a provider, does not call the
Emissor Nacional, and is not wired into any production transmission path
today (none exists yet for Nota Paulistana). Any future transport client for
the municipal webservice MUST call it before submitting, so a Simples
Nacional issuer can never be silently routed to a webservice that can no
longer accept new issuance for that regime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.provider import (
    ProviderOperation,
    ProviderSelectionResolver,
    UnsupportedProviderError,
)
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

# 2026-08-13 updated municipal statement and CGSN Res. 191/2026.
# UTC clock is checked for execution-safety only; competence controls
# the fiscal cutoff for new issuance, including retroactive operations.
SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM = date(2026, 11, 1)
# Keep the newer canonical SP classification name for existing callers.
SP_ME_EPP_NATIONAL_MANDATORY_COMPETENCE = SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM


class MunicipalTransportNotPermittedError(UnsupportedProviderError):
    """Raised when the legacy São Paulo webservice cannot accept new issuance."""


def ensure_municipal_sp_transport_permitted(
    federal_income_tax_regime: FederalIncomeTaxRegime,
    *,
    issuer_ibge_code: str,
    competence_date: date,
    as_of: datetime,
) -> None:
    """Block an ineligible legacy city NFS-e issue without choosing any provider.

    Fail closed on missing competence or untrusted clocks. This is a negative
    regulatory gate, not proof that municipal transport, A1, and ISS rules
    are otherwise available. Integrations MUST call it before SOAP I/O.
    """
    if (
        type(federal_income_tax_regime) is not FederalIncomeTaxRegime
        or type(competence_date) is not date
        or not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise UnsupportedProviderError(
            "SP municipal legacy requires reviewed regime, competence and timezone-aware clock"
        )
    if issuer_ibge_code != "3550308":
        return
    if (
        federal_income_tax_regime is FederalIncomeTaxRegime.SIMPLES_NACIONAL
        and competence_date >= SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM
    ):
        raise MunicipalTransportNotPermittedError(
            "São Paulo city ME/EPP Simples must use National NFS-e "
            "for competences on or after 2026-11-01 (CGSN 191/2026); "
            "retroactive services before this date require reviewed municipal eligibility"
        )


# A national NFS-e legal channel does NOT imply the National API is
# configured for this CNPJ, tenant or operation. This is only a strict
# federal eligibility classification for all SP issuer municipalities.
_MEI_NATIONAL_FROM = date(2023, 9, 1)


@dataclass(frozen=True, slots=True)
class SpNationalNfseEligibility:
    """Non-authorizing regulatory channel intent; never a provider binding."""

    municipality_ibge: str
    channel: str = "nfse-national"
    requires_official_homologation: bool = True
    is_runtime_authority: bool = False


def classify_sp_national_nfse_eligibility(
    *,
    issuer_jurisdiction: BrazilianJurisdiction,
    tax_regime: TaxRegimeCode,
    competence_date: date,
) -> SpNationalNfseEligibility:
    """Classify MEI and ME/EPP Simples only; all other cases fail closed.

    Unlike the 3-city pilot catalog, this federal rule applies to *any*
    valid SP issuer municipality. It never registers adapters or transmits
    a fiscal document, and must not be used as a proof of 22 certified cities.
    """
    if (
        not isinstance(issuer_jurisdiction, BrazilianJurisdiction)
        or issuer_jurisdiction.state_code != "SP"
        or not isinstance(issuer_jurisdiction.municipality_ibge_code, str)
        or not issuer_jurisdiction.municipality_ibge_code.startswith("35")
        or type(tax_regime) is not TaxRegimeCode
        or type(competence_date) is not date
    ):
        raise FiscalValidationError("Invalid SP National NFS-e issuer and fiscal context")
    is_mei = tax_regime is TaxRegimeCode.MEI and competence_date >= _MEI_NATIONAL_FROM
    is_simples = (
        tax_regime in (
            TaxRegimeCode.SIMPLES_NACIONAL,
            TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
        )
        and competence_date >= SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM
    )
    if not (is_mei or is_simples):
        raise FiscalValidationError(
            "SP NFS-e channel is not nationally established for this regime/competence"
        )
    return SpNationalNfseEligibility(
        municipality_ibge=issuer_jurisdiction.municipality_ibge_code,
    )


# Guarulhos migrated its non-Simples municipal emission to GissOnline V2 on
# 2026-07-01. Federal CGSN 191/2026 moves Simples ME/EPP competences from
# 2026-11-01 to Emissor Nacional, irrespective of the municipal provider.
# This is a NEGATIVE REGIME/COMPETENCE CHECK, never a provider authority.
# Official municipal vendor: https://guarulhos.giss.com.br/giss-ajuda/desenvolvedores.html
GUARULHOS_IBGE = "3518800"
GUARULHOS_GISS_V2_PROVIDER_ID = "guarulhos-giss-v2-homologation"
GUARULHOS_GISS_V2_FROM = date(2026, 7, 1)


def require_guarulhos_nfse_channel(
    *,
    issuer_jurisdiction: BrazilianJurisdiction,
    tax_regime: TaxRegimeCode,
    competence_date: date,
    provider_id: str,
) -> None:
    """Guard the SAME canonical binding against Guarulhos 2026 issuer regime.

    There is no automatic fallback: older municipal competences need an
    independently certified historical contract, while current non-Simples
    emissions still require reviewed GissOnline V2 ports and exact bindings.
    This guard never opens a web service, issues an invoice or grants RBAC.
    """
    if (
        not isinstance(issuer_jurisdiction, BrazilianJurisdiction)
        or type(tax_regime) is not TaxRegimeCode
        or type(competence_date) is not date
        or not isinstance(provider_id, str)
    ):
        raise FiscalValidationError("Guarulhos fiscal channel requires reviewed facts")
    if (
        issuer_jurisdiction.state_code != "SP"
        or issuer_jurisdiction.municipality_ibge_code != GUARULHOS_IBGE
    ):
        return
    if (
        tax_regime is TaxRegimeCode.MEI
        and competence_date >= _MEI_NATIONAL_FROM
    ) or (
        tax_regime in (
            TaxRegimeCode.SIMPLES_NACIONAL,
            TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
        )
        and competence_date >= SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM
    ):
        required = NACIONAL_HOMOLOGATION_PROVIDER_ID
    elif (
        competence_date >= GUARULHOS_GISS_V2_FROM
        and (
            tax_regime is TaxRegimeCode.NORMAL
            or tax_regime in (
                TaxRegimeCode.SIMPLES_NACIONAL,
                TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            )
        )
    ):
        required = GUARULHOS_GISS_V2_PROVIDER_ID
    else:
        raise FiscalValidationError(
            "Guarulhos pre-V2/MEI legacy channel has no certified provider contract"
        )
    if provider_id != required:
        raise FiscalValidationError(
            "Guarulhos NFS-e provider conflicts with tax regime and competence"
        )


# Candidate migration/UX catalog: NOT approved municipal provider bindings.
# Source: executive research candidates; current municipal contracts require
# independent official verification before creating any durable provider binding.
SP_MUNICIPAL_CANDIDATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "3505708": ("Barueri", ("barueri-proprio",)),
    "3550308": ("São Paulo", ("nota-paulistana", "nfse-nacional")),
    "3509502": ("Campinas", ("dsf", "nfse-nacional")),
    "3552205": ("Sorocaba", ("dsf", "nfse-nacional")),
    "3518800": ("Guarulhos", ("gissonline-v2", "nfse-nacional")),
    "3548500": ("Santos", ("ginfes", "nfse-nacional")),
    "3548807": ("São Caetano do Sul", ("ginfes", "nfse-nacional")),
    "3525904": ("Jundiaí", ("gissonline", "nfse-nacional")),
    "3552502": ("Suzano", ("ginfes", "nfse-nacional")),
    "3547304": ("Santana de Parnaíba", ("simpliss", "municipal-proprio")),
    # Prefeitura Osasco operates its own EissNfe/RTC WebService; historical
    # generic SigISS/Betha labels are not contracts and mislead onboarding.
    "3534401": ("Osasco", ("osasco-proprio-rtc", "nfse-nacional")),
    "3522505": ("Itapevi", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3525003": ("Jandira", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3528502": ("Mairiporã", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3503901": ("Arujá", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3527306": ("Louveira", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3556206": ("Valinhos", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3523909": ("Itu", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3545209": ("Salto", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3531803": ("Monte Mor", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3518701": ("Guarujá", ("sigiss", "betha", "e-receita", "nfse-nacional")),
    "3551009": ("São Vicente", ("sigiss", "betha", "e-receita", "nfse-nacional")),
}



class GovernedSpMunicipalProviderResolver:
    """Validate SP issuer IBGE, then delegate to the canonical durable resolver.

    Construction should receive Control Plane's DurableProviderBindingResolver,
    which reads persisted approved bindings and fails closed if unconfigured.
    The caller should inject this adapter into existing ProviderGatewayService
    through its provider_selector parameter; that service still validates the
    configured ProviderRegistry, provider readiness and runtime credentials.
    """

    def __init__(self, *, canonical_resolver: ProviderSelectionResolver) -> None:
        if not callable(getattr(canonical_resolver, "resolve_provider_id", None)):
            raise TypeError("Canonical provider resolver is required")
        self._canonical = canonical_resolver

    def resolve_provider_id(
        self,
        *,
        scope: ExecutionScope,
        document_kind: FiscalDocumentKind,
        jurisdiction: BrazilianJurisdiction,
        operation: str,
    ) -> str:
        if document_kind is not FiscalDocumentKind.NFSE:
            raise UnsupportedProviderError("Municipal router supports NFS-e only")
        if jurisdiction.state_code != "SP":
            raise UnsupportedProviderError("Municipal router is limited to SP")
        issuer_ibge = jurisdiction.municipality_ibge_code
        # R16: the catalog lists onboarding candidates, but must NEVER be a
        # hard-coded allowlist. A future SP city with a duly approved durable
        # provider binding must work without modifying or deploying this code.
        if issuer_ibge is None or not issuer_ibge.startswith("35"):
            raise UnsupportedProviderError("Issuer municipality requires an SP IBGE code")
        if scope.host_namespace is None:
            raise UnsupportedProviderError("A trusted host namespace is required")
        try:
            ProviderOperation(operation)
        except ValueError:
            raise UnsupportedProviderError("Unsupported fiscal operation") from None
        # NO default provider. All authorization belongs to the existing
        # scope-bound, persisted Control Plane configuration resolver.
        return self._canonical.resolve_provider_id(
            scope=scope,
            document_kind=document_kind,
            jurisdiction=jurisdiction,
            operation=operation,
        )
