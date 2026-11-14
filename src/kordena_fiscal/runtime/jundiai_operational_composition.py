"""Reviewed Jundiaí GissOnline 2.04 ports on the canonical SP4 fiscal runtime.

The application owns the persisted original RPS, scoped provider binding,
tenant permissions and fiscal lifecycle. This composition only injects signed
municipal serialization, official validation, A1-backed transport and proof.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    BrazilianJurisdiction, ExecutionScope, FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissHomologationTransport, JundiaiGissWsdlContract,
    JundiaiSignedOperation,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps, Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts
from .sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority, build_jundiai_reviewed_ports,
)


@dataclass(frozen=True, slots=True)
class JundiaiTrustedRuntimePorts:
    """All taxpayer-specific Jundiaí ports must be supplied as a single review."""

    transport: JundiaiGissHomologationTransport
    build_signed_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], JundiaiSignedOperation
    ]
    verify_signed_rps_identity: Callable[[Sp4OriginalRps, bytes], None]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]

    def __post_init__(self) -> None:
        if not isinstance(self.transport, JundiaiGissHomologationTransport) or not all(
            callable(port) for port in (
                self.build_signed_operation, self.verify_signed_rps_identity,
                self.fiscal_issuer_policy, self.validate_prepared_rps,
                self.verify_official_invoice_xml,
            )
        ):
            raise FiscalValidationError("Jundiai reviewed Giss runtime ports incomplete")

    def attach(self, application: FiscalApplicationService) -> Sp4ReviewedMunicipalPorts:
        """Bind ONLY the canonical application loader; never use local tenant state."""
        if not isinstance(application, FiscalApplicationService):
            raise FiscalValidationError("Jundiai requires canonical fiscal application")
        authority = Sp4BridgeAuthority(
            load_original_rps=application.load_sp4_original_rps,
            fiscal_issuer_policy=self.fiscal_issuer_policy,
            validate_prepared_rps=self.validate_prepared_rps,
            verify_official_invoice_xml=self.verify_official_invoice_xml,
        )
        return build_jundiai_reviewed_ports(
            authority=authority, transport=self.transport,
            build_signed_operation=self.build_signed_operation,
            verify_signed_rps_identity=self.verify_signed_rps_identity,
        )


def build_jundiai_trusted_transport(
    *, application: FiscalApplicationService,
    vault: EncryptedA1Vault,
    contract_for_method: Callable[[str], JundiaiGissWsdlContract],
    validate_signed_xml: Callable[[bytes, str, str], None],
) -> JundiaiGissHomologationTransport:
    """Resolve persisted provider binding and A1 from existing authorities."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(vault, EncryptedA1Vault)
        or not callable(contract_for_method)
        or not callable(validate_signed_xml)
    ):
        raise FiscalValidationError("Jundiai needs reviewed contracts and canonical A1")

    class CanonicalResolver:
        def resolve_provider_id(
            self, *, scope: ExecutionScope,
            document_kind: FiscalDocumentKind,
            jurisdiction: BrazilianJurisdiction, operation: str,
        ) -> str:
            return application.resolve_configured_provider_id(
                scope=scope, document_kind=document_kind,
                jurisdiction=jurisdiction, operation=operation,
            )

    return JundiaiGissHomologationTransport(
        resolver=CanonicalResolver(),
        resolve_certificate=lambda scope, cnpj: vault.resolve(
            scope=scope, issuer_cnpj=cnpj,
        ),
        contract_for_method=contract_for_method,
        validate_signed_xml=validate_signed_xml,
    )
