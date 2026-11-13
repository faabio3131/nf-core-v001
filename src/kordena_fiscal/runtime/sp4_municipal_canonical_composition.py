"""Opt-in composition of SP4 municipal fiscal adapters into the existing runtime.

No municipality is enabled by catalog lookup, WSDL discovery or env flag.
The caller injects the official city builder, signed schema validation,
authenticated transport and result proof for EACH explicitly reviewed city.
The canonical persisted provider resolver remains the sole binding authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from kordena_fiscal.domain import ExecutionScope
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4CanonicalMunicipalError,
    Sp4MunicipalCanonicalGateway,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseGatewayClient,
    NfseQueryClient,
)


@dataclass(frozen=True, slots=True)
class Sp4ReviewedMunicipalPorts:
    """All city-specific authoritative ports, without raw certificate contents."""

    load_original_rps: Callable[[ExecutionScope, str], Sp4OriginalRps]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    submit_official_rps: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
    ]
    query_official_rps: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
    ]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]


def build_sp4_canonical_clients(
    *,
    canonical_resolver: ProviderSelectionResolver,
    configured_municipalities: Mapping[str, Sp4ReviewedMunicipalPorts],
    canonical_rps_loader: Callable[[ExecutionScope, str], Sp4OriginalRps] | None = None,
) -> tuple[Mapping[str, NfseGatewayClient], Mapping[str, NfseQueryClient]]:
    """Build separate issuance/recovery maps for opt-in canonical runtime.

    A partial list is valid for safe, staged deployment; it never silently
    enables an unreviewed municipality or an auto-discovered provider.
    """
    if not callable(getattr(canonical_resolver, "resolve_provider_id", None)):
        raise Sp4CanonicalMunicipalError("SP4 requires canonical durable binding resolver")
    if not isinstance(configured_municipalities, Mapping):
        raise Sp4CanonicalMunicipalError("SP4 requires explicit reviewed provider map")
    if canonical_rps_loader is not None and not callable(canonical_rps_loader):
        raise Sp4CanonicalMunicipalError("SP4 original RPS loader must be canonical")
    authorization: dict[str, NfseGatewayClient] = {}
    recovery: dict[str, NfseQueryClient] = {}
    for provider_id, city in configured_municipalities.items():
        if provider_id not in SP4_MUNICIPAL_PROVIDERS:
            raise Sp4CanonicalMunicipalError("Unknown SP4 municipal provider")
        if not isinstance(city, Sp4ReviewedMunicipalPorts):
            raise Sp4CanonicalMunicipalError("Municipal ports are not reviewed")
        adapter = Sp4MunicipalCanonicalGateway(
            provider_id=provider_id,
            resolver=canonical_resolver,
            load_original_rps=(
                canonical_rps_loader if canonical_rps_loader is not None
                else city.load_original_rps
            ),
            municipal_issuer_policy=city.fiscal_issuer_policy,
            validate_prepared_rps=city.validate_prepared_rps,
            submit_prepared_rps=city.submit_official_rps,
            query_original_rps=city.query_official_rps,
            verify_official_invoice_xml=city.verify_official_invoice_xml,
        )
        authorization[provider_id] = NfseGatewayClient(adapter)
        recovery[provider_id] = NfseQueryClient(adapter)
    return MappingProxyType(authorization), MappingProxyType(recovery)
