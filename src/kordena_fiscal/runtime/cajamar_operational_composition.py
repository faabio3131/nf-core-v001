"""One canonical Cajamar GeisWeb composition over reviewed, scoped fiscal ports.

This is the only attachment point for Cajamar into the existing NFCore runtime.
It never provisions duplicate auth, tenant binding, state or national NFSe API.
External WSDL/XSD and taxpayer-specific A1 remain operator supplied; omission
keeps the municipal transport unconfigured and cannot create mock authorization.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
)
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarCancellationDecision,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebHomologationTransport,
    CajamarGeiswebWsdl,
    CajamarPreparedNfse,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts
from .sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_cajamar_reviewed_ports,
    build_cajamar_verified_cancellation_port,
)


@dataclass(frozen=True, slots=True)
class CajamarTrustedRuntimePorts:
    """Operator-provisioned ports: all callbacks preserve the canonical scope.

    Each callback must use a pinned current municipal contract and the same
    tenant/unit-scoped A1 authority, not a globally captured certificate.
    """

    transport: CajamarGeiswebHomologationTransport
    build_signed_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], CajamarPreparedNfse
    ]
    verify_signed_rps_identity: Callable[[Sp4OriginalRps, bytes], None]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]
    sign_cancel: Callable[[ExecutionScope, Cnpj, bytes], bytes]
    validate_signed_cancel: Callable[[ExecutionScope, Cnpj, bytes], None]
    verify_official_cancel: Callable[[ExecutionScope, Cnpj, bytes], None]

    def __post_init__(self) -> None:
        if not isinstance(self.transport, CajamarGeiswebHomologationTransport) or not all(
            callable(port) for port in (
                self.build_signed_operation,
                self.verify_signed_rps_identity,
                self.fiscal_issuer_policy,
                self.validate_prepared_rps,
                self.verify_official_invoice_xml,
                self.sign_cancel,
                self.validate_signed_cancel,
                self.verify_official_cancel,
            )
        ):
            raise ValueError("Incomplete trusted Cajamar fiscal adapter provisioning")

    def attach(
        self, application: FiscalApplicationService,
    ) -> tuple[
        Sp4ReviewedMunicipalPorts,
        Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice],
            CajamarCancellationDecision,
        ],
    ]:
        """Attach to the SAME application UoW, no additional RPS authority."""
        authority = Sp4BridgeAuthority(
            load_original_rps=lambda scope, document_id: application.load_sp4_original_rps(
                scope, document_id,
            ),
            fiscal_issuer_policy=self.fiscal_issuer_policy,
            validate_prepared_rps=self.validate_prepared_rps,
            verify_official_invoice_xml=self.verify_official_invoice_xml,
        )
        issuance = build_cajamar_reviewed_ports(
            authority=authority, transport=self.transport,
            build_signed_operation=self.build_signed_operation,
            verify_signed_rps_identity=self.verify_signed_rps_identity,
        )
        cancellation = build_cajamar_verified_cancellation_port(
            transport=self.transport, sign_cancel=self.sign_cancel,
            validate_signed_cancel=self.validate_signed_cancel,
            verify_official_cancel=self.verify_official_cancel,
        )
        return issuance, cancellation


def build_cajamar_trusted_transport(
    *,
    application: FiscalApplicationService,
    vault: EncryptedA1Vault,
    pinned_contract: CajamarGeiswebWsdl,
    validate_signed_xml: Callable[[bytes, str], None],
) -> CajamarGeiswebHomologationTransport:
    """Bind the existing durable tenant provider resolver to the canonical A1.

    The caller must establish the real WSDL/XSD fingerprint and XML validator.
    This helper never downloads municipal schemas or opens the certificate itself.
    """
    if (
        not isinstance(vault, EncryptedA1Vault)
        or not isinstance(pinned_contract, CajamarGeiswebWsdl)
        or not callable(validate_signed_xml)
    ):
        raise ValueError("Cajamar requires reviewed official contract and A1 vault")
    class _CanonicalProviderResolver:
        """Use the same application configuration UoW, never a second registry."""

        def resolve_provider_id(
            self, *, scope: ExecutionScope,
            document_kind: FiscalDocumentKind,
            jurisdiction: BrazilianJurisdiction,
            operation: str,
        ) -> str:
            return application.resolve_configured_provider_id(
                scope=scope, document_kind=document_kind,
                jurisdiction=jurisdiction, operation=operation,
            )

    return CajamarGeiswebHomologationTransport(
        resolver=_CanonicalProviderResolver(),
        resolve_certificate=lambda scope, cnpj: vault.resolve(
            scope=scope, issuer_cnpj=cnpj,
        ),
        signed_xml_validator=validate_signed_xml,
        contract=pinned_contract,
    )
