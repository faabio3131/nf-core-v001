"""São Paulo NFS-e R16 routing via the EXISTING durable Control Plane authority.

The static catalog is advisory only and never authorizes provider transmission.
The canonical DurableProviderBindingResolver performs the actual exact-match
lookup by tenant, unit, environment, kind, issuer jurisdiction and operation.
No second authorization state, persistence, or fiscal gateway is introduced.

Municipal (São Paulo city) routing guard -- Simples Nacional / Emissor Nacional
--------------------------------------------------------------------------------
The São Paulo Secretaria Municipal da Fazenda made the national NFS-e emitter
(Emissor Nacional, https://www.gov.br/nfse) mandatory for Simples Nacional
taxpayers as of 2026-09-01 (and for self-employed/liberal professionals as of
2026-08-01); see https://prefeitura.sp.gov.br/web/fazenda/w/usoemissornacional.
From that date, the legacy municipal webservice (`lotenfe.asmx` /
`nfews.prefeitura.sp.gov.br/lotenfe.asmx`, built by
`gateway/nfse_paulistana_envelope.py`) only serves consultation and
retroactive issuance for Simples Nacional issuers -- NOT new issuance.

``ensure_municipal_sp_transport_permitted`` is a structural fail-closed guard,
not a routing decision: it does not pick a provider, does not call the
Emissor Nacional, and is not wired into any production transmission path
today (none exists yet for Nota Paulistana). Any future transport client for
the municipal webservice MUST call it before submitting, so a Simples
Nacional issuer can never be silently routed to a webservice that can no
longer accept new issuance for that regime.
"""
from __future__ import annotations

from datetime import UTC, datetime

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
)
from kordena_fiscal.gateway.provider import (
    ProviderOperation,
    ProviderSelectionResolver,
    UnsupportedProviderError,
)
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

# Published by the São Paulo Secretaria Municipal da Fazenda; see the module
# docstring. This is a sourced regulatory date, not an engineering estimate.
SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM = datetime(2026, 9, 1, tzinfo=UTC)


class MunicipalTransportNotPermittedError(UnsupportedProviderError):
    """Raised when the legacy São Paulo webservice cannot accept new issuance."""


def ensure_municipal_sp_transport_permitted(
    federal_income_tax_regime: FederalIncomeTaxRegime,
    *,
    issuer_ibge_code: str,
    as_of: datetime,
) -> None:
    """Fail closed before any new-issuance call to the legacy SP webservice.

    Only São Paulo city (IBGE 3550308) is affected by this specific municipal
    deadline; other SP municipalities are untouched by this guard. A Simples
    Nacional issuer on or after the mandatory date must be routed to the
    Emissor Nacional instead -- this function never does that routing itself,
    it only refuses the legacy path so a caller cannot reach it by omission.
    """
    if issuer_ibge_code != "3550308":
        return
    if as_of.tzinfo is None:
        raise UnsupportedProviderError("as_of must be timezone-aware")
    if (
        federal_income_tax_regime is FederalIncomeTaxRegime.SIMPLES_NACIONAL
        and as_of >= SIMPLES_NACIONAL_EMISSOR_NACIONAL_MANDATORY_FROM
    ):
        raise MunicipalTransportNotPermittedError(
            "Simples Nacional issuers in São Paulo city must use the national "
            "NFS-e emitter (Emissor Nacional) for new issuance on or after "
            "2026-09-01; the legacy municipal webservice no longer accepts it"
        )

# Candidate migration/UX catalog: NOT approved municipal provider bindings.
# Source: executive research candidates; current municipal contracts require
# independent official verification before creating any durable provider binding.
SP_MUNICIPAL_CANDIDATES: dict[str, tuple[str, tuple[str, ...]]] = {
    "3505708": ("Barueri", ("barueri-proprio",)),
    "3550308": ("São Paulo", ("nota-paulistana", "nfse-nacional")),
    "3509502": ("Campinas", ("dsf", "nfse-nacional")),
    "3552205": ("Sorocaba", ("dsf", "nfse-nacional")),
    "3518800": ("Guarulhos", ("ginfes", "nfse-nacional")),
    "3548500": ("Santos", ("ginfes", "nfse-nacional")),
    "3548807": ("São Caetano do Sul", ("ginfes", "nfse-nacional")),
    "3525904": ("Jundiaí", ("ginfes", "nfse-nacional")),
    "3552502": ("Suzano", ("ginfes", "nfse-nacional")),
    "3547304": ("Santana de Parnaíba", ("smarapd", "municipal-proprio")),
    "3534401": ("Osasco", ("sigiss", "betha", "e-receita", "nfse-nacional")),
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
