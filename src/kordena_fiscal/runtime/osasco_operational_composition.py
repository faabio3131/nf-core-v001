"""Osasco RTC WCF plugged into the existing canonical SP4 fiscal runtime.

All fiscal authorities and credentials are injected through reviewed ports;
no second database, sequence, browser credential or provider registry.
This does not activate a municipal WSDL in the executable entrypoint.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
)
from kordena_fiscal.gateway.osasco_rtc_cancellation_builder import (
    OsascoCancellationDecision,
    build_osasco_cancel_request,
    verify_osasco_cancel_reply,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoOperationReceipt,
    OsascoPreparedOperation,
    OsascoRtcHomologationTransport,
    OsascoWcfContract,
)
from kordena_fiscal.gateway.osasco_rtc_invoice_interpreter import (
    interpret_osasco_full_note_result,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.vault.contracts import SecretResolutionService

from .osasco_credentials import build_osasco_scoped_key_resolver
from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts
from .sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_osasco_reviewed_ports,
)


@dataclass(frozen=True, slots=True)
class OsascoTrustedRuntimePorts:
    """Explicit reviewed WCF dependencies, with no hardcoded secret or policy."""

    transport: OsascoRtcHomologationTransport
    build_wcf_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], OsascoPreparedOperation
    ]
    verify_wcf_rps_identity: Callable[[Sp4OriginalRps, bytes], None]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]
    interpret_official_result: Callable[
        [OsascoOperationReceipt, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ] = interpret_osasco_full_note_result
    verify_official_cancel: Callable[
        [bytes, Sp4OriginalRps, Sp4VerifiedInvoice], bool | None
    ] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transport, OsascoRtcHomologationTransport) or not all(
            callable(port) for port in (
                self.build_wcf_operation,
                self.verify_wcf_rps_identity,
                self.fiscal_issuer_policy,
                self.validate_prepared_rps,
                self.verify_official_invoice_xml,
                self.interpret_official_result,
            )
        ) or (
            self.verify_official_cancel is not None
            and not callable(self.verify_official_cancel)
        ):
            raise ValueError("Osasco requires complete reviewed municipal fiscal ports")

    def attach_verified_cancellation(
        self, application: FiscalApplicationService, *, cancel_type: str = "N",
    ) -> Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice, str],
        OsascoCancellationDecision,
    ] | None:
        """Return a municipal cancellation port only if official proof is reviewed."""
        if cancel_type not in {"N", "S"}:
            raise ValueError("Unknown Osasco official cancellation type")
        if self.verify_official_cancel is None:
            return None
        validator = self.verify_official_cancel

        def submit(
            request: NfseAuthorizationRequest, source: Sp4OriginalRps,
            issued: Sp4VerifiedInvoice, reason: str,
        ) -> OsascoCancellationDecision:
            if (
                request.document.scope.identity_partition_key
                != source.scope.identity_partition_key
                or request.document.document_id != source.document_id
                or request.request_fingerprint != source.request_fingerprint
                or request.document.issuer.cnpj != source.issuer_cnpj
            ):
                raise ValueError("Osasco cancellation differs from original")
            prepared = build_osasco_cancel_request(
                source=source, issued=issued,
                regime=request.document.issuer.tax_regime,
                cancel_type=cancel_type, reason=reason, human_approved=True,
            )
            result = self.transport.invoke(prepared)
            return verify_osasco_cancel_reply(
                receipt=result, source=source, issued=issued,
                verify_official_response=validator,
            )

        return submit

    def attach(self, application: FiscalApplicationService) -> Sp4ReviewedMunicipalPorts:
        """The same application's loader is the ONLY original-RPS authority."""
        authority = Sp4BridgeAuthority(
            load_original_rps=lambda scope, document_id: application.load_sp4_original_rps(
                scope, document_id,
            ),
            fiscal_issuer_policy=self.fiscal_issuer_policy,
            validate_prepared_rps=self.validate_prepared_rps,
            verify_official_invoice_xml=self.verify_official_invoice_xml,
        )
        return build_osasco_reviewed_ports(
            authority=authority,
            transport=self.transport,
            build_wcf_operation=self.build_wcf_operation,
            verify_wcf_rps_identity=self.verify_wcf_rps_identity,
            interpret_official_result=self.interpret_official_result,
        )


def build_osasco_trusted_transport(
    *,
    application: FiscalApplicationService,
    unit_of_work_factory: FiscalUnitOfWorkFactory,
    secrets: SecretResolutionService,
    workload_id: str,
    validate_official_request: Callable[[bytes, str], None],
    contract_for_method: Callable[[str], OsascoWcfContract],
) -> OsascoRtcHomologationTransport:
    """Bind Osasco WCF through the existing fiscal application and secret Vault.

    No credential is cached, put in a WSDL manifest or provided by the browser.
    A reviewed WSDL/XSD validator and SOAPAction mapping remain required ports.
    """
    if not all(callable(port) for port in (
        validate_official_request, contract_for_method,
    )):
        raise ValueError("Osasco requires reviewed WSDL/XSD contract ports")

    class _CanonicalProviderResolver:
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

    return OsascoRtcHomologationTransport(
        resolver=_CanonicalProviderResolver(),
        resolve_key=build_osasco_scoped_key_resolver(
            unit_of_work_factory=unit_of_work_factory,
            secrets=secrets, workload_id=workload_id,
        ),
        validated_request=validate_official_request,
        contract_for_method=contract_for_method,
    )
