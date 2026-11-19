"""Reviewed Barueri PMB004 connected to the shared NFCore fiscal application.

Barueri accepts asynchronous fixed-width remittances, not an immediately
authorized NFS-e. The canonical application owns RPS numbering, durable state,
protocol archive and recovery. This adapter introduces no second persistence.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.gateway.barueri_official_cancel_return import (
    BarueriCancellationEvidence,
    verify_barueri_cancellation_return,
    verify_barueri_substitution_return,
)
from kordena_fiscal.gateway.barueri_official_invoice_xml import (
    retrieve_barueri_original_invoice_xml,
)
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
    parse_barueri_official_return_file,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriPmb004HomologationTransport,
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts
from .sp4_municipal_provider_bridges import (
    Sp4BridgeAuthority,
    build_barueri_reviewed_ports,
)


def _verify_return(
    batch: BarueriRpsBatch, receipt: BarueriReceipt,
) -> BarueriConvertedNfseEvidence:
    return parse_barueri_official_return_file(batch=batch, receipt=receipt)


def _fetch_invoice_xml(evidence: BarueriConvertedNfseEvidence) -> bytes:
    return retrieve_barueri_original_invoice_xml(evidence=evidence)


@dataclass(frozen=True, slots=True)
class BarueriTrustedRuntimePorts:
    """Complete operator-reviewed PMB004 dependencies, with canonical identity."""

    transport: BarueriPmb004HomologationTransport
    build_remittance: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], BarueriRpsBatch
    ]
    verify_fixed_width_rps_identity: Callable[
        [Sp4OriginalRps, BarueriRpsBatch], None
    ]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]
    interpret_official_result: Callable[
        [BarueriReceipt, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ]
    retrieve_official_invoice_xml: Callable[
        [BarueriConvertedNfseEvidence], bytes
    ] = _fetch_invoice_xml
    validate_return_file: Callable[
        [BarueriRpsBatch, BarueriReceipt], BarueriConvertedNfseEvidence
    ] = _verify_return
    decode_official_invoice: Callable[
        [bytes, Sp4OriginalRps], Sp4VerifiedInvoice
    ] | None = None
    prepare_cancellation_event: Callable[
        [
            NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice,
            str, str, str, datetime, str | None,
            NfseAuthorizationRequest | None, Sp4OriginalRps | None,
            str | None,
        ],
        BarueriRpsBatch,
    ] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transport, BarueriPmb004HomologationTransport):
            raise FiscalValidationError("Barueri requires approved municipal transport")
        if not all(callable(field) for field in (
            self.build_remittance, self.verify_fixed_width_rps_identity,
            self.fiscal_issuer_policy, self.validate_prepared_rps,
            self.verify_official_invoice_xml, self.interpret_official_result,
            self.retrieve_official_invoice_xml, self.validate_return_file,
        )):
            raise FiscalValidationError("Barueri fiscal review ports are incomplete")
        if (self.decode_official_invoice is None) != (self.prepare_cancellation_event is None):
            raise FiscalValidationError("Barueri event ports must be configured together")
        if self.decode_official_invoice is not None and not all(callable(port) for port in (
            self.decode_official_invoice, self.prepare_cancellation_event,
        )):
            raise FiscalValidationError("Barueri event ports require reviewed implementations")

    @property
    def supports_events(self) -> bool:
        return self.decode_official_invoice is not None

    def submit_cancellation_event(self, batch: BarueriRpsBatch) -> BarueriReceipt:
        if not self.supports_events:
            raise FiscalValidationError("Barueri cancellation ports are not configured")
        return self.transport.submit(batch, binding_operation="cancel")

    def query_cancellation_event(
        self, batch: BarueriRpsBatch, issued: Sp4VerifiedInvoice,
        protocol: str | None, submitted_on: date,
        replacement_request: NfseAuthorizationRequest | None = None,
        replacement_source: Sp4OriginalRps | None = None,
    ) -> BarueriCancellationEvidence | None:
        """Read-only recovery of one original event; never resend PMB004 files."""
        if not self.supports_events or not isinstance(batch, BarueriRpsBatch):
            raise FiscalValidationError("Barueri cancellation recovery is not configured")
        return_name: str | None = None
        if protocol is not None:
            state = self.transport.status(batch=batch, protocol=protocol)
            if (
                state.operation != "NFeLoteStatusArquivo" or state.code != "OK200"
                or state.remittance_protocol not in (None, protocol)
            ):
                raise FiscalValidationError("Barueri event protocol disagrees with municipality")
            if state.situation not in (None, "1"):
                return None
            return_name = state.return_file_name
        else:
            matches = []
            for situation in ("-2", "-1", "0", "1", "2"):
                listing = self.transport.list_on_date(
                    batch=batch, situation=situation, submitted_on=submitted_on,
                )
                if listing.operation != "NFeLoteListarArquivos" or listing.code != "OK200":
                    raise FiscalValidationError("Barueri event listing is not official")
                for entry in listing.listed_files:
                    if entry.original_file_name != batch.file_name:
                        continue
                    if (
                        entry.remittance != batch.remittance
                        or entry.situation != situation or entry.validation_only
                    ):
                        raise FiscalValidationError("Ambiguous Barueri event listing")
                    matches.append(entry)
            if len(matches) > 1:
                raise FiscalValidationError("Duplicate municipal cancellation events detected")
            if not matches or matches[0].situation != "1":
                return None
            return_name = matches[0].return_file_name
        if not return_name:
            return None
        receipt = self.transport.download(batch=batch, file_name=return_name)
        if (
            receipt.operation != "NFeLoteBaixarArquivo" or receipt.code != "OK200"
            or receipt.return_file_name not in (None, return_name)
            or not receipt.downloaded_file
            or (protocol is not None and receipt.remittance_protocol not in (None, protocol))
        ):
            raise FiscalValidationError("Barueri event file does not match remittance")
        if (replacement_request is None) != (replacement_source is None):
            raise FiscalValidationError("Barueri substitute requires its own approved RPS")
        if replacement_request is None:
            return verify_barueri_cancellation_return(
                event=batch, issued=issued, receipt=receipt,
            )
        assert replacement_source is not None
        replacement_batch = self.build_remittance(
            replacement_request, replacement_source,
        )
        self.verify_fixed_width_rps_identity(
            replacement_source, replacement_batch,
        )
        proof = verify_barueri_substitution_return(
            event=batch, issued=issued, replacement_batch=replacement_batch,
            receipt=receipt,
        )
        new_note = proof.replacement_return
        if new_note is None:
            raise FiscalValidationError("Barueri new note is absent from return")
        official_xml = self.retrieve_official_invoice_xml(new_note)
        verified_new = Sp4VerifiedInvoice(
            issuer_cnpj=replacement_source.issuer_cnpj,
            issuer_ibge=replacement_source.issuer_ibge,
            competence_date=replacement_source.competence_date,
            rps_number=replacement_source.rps_number,
            rps_series=replacement_source.rps_series,
            gross_amount=replacement_source.gross_amount,
            invoice_number=new_note.note_number,
            verification_code=new_note.verification_code,
            invoice_reference=new_note.access_key,
            authorized_xml=official_xml,
        )
        self.verify_official_invoice_xml(verified_new)
        return replace(proof, replacement_invoice=verified_new)

    def attach(self, application: FiscalApplicationService) -> Sp4ReviewedMunicipalPorts:
        if not isinstance(application, FiscalApplicationService):
            raise FiscalValidationError("Barueri needs the canonical fiscal application")
        authority = Sp4BridgeAuthority(
            load_original_rps=lambda scope, document_id: application.load_sp4_original_rps(
                scope, document_id,
            ),
            fiscal_issuer_policy=self.fiscal_issuer_policy,
            validate_prepared_rps=self.validate_prepared_rps,
            verify_official_invoice_xml=self.verify_official_invoice_xml,
        )
        return build_barueri_reviewed_ports(
            authority=authority,
            transport=self.transport,
            build_remittance=self.build_remittance,
            verify_fixed_width_rps_identity=self.verify_fixed_width_rps_identity,
            load_approved_remittance_protocol=application.load_barueri_remittance_protocol,
            interpret_official_result=self.interpret_official_result,
            validate_return_file=self.validate_return_file,
            retrieve_official_invoice_xml=self.retrieve_official_invoice_xml,
            load_original_submission_date=application.load_barueri_submission_date,
        )


def build_barueri_trusted_transport(
    *,
    application: FiscalApplicationService,
    vault: EncryptedA1Vault,
    validate_pmb004: Callable[[bytes], None],
) -> BarueriPmb004HomologationTransport:
    """Use the same tenant-scoped provider binding and A1 Vault as the Portal."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(vault, EncryptedA1Vault)
        or not callable(validate_pmb004)
    ):
        raise FiscalValidationError("Barueri requires canonical A1 and PMB004 validator")

    class CanonicalResolver:
        def resolve_provider_id(
            self, *, scope: ExecutionScope,
            document_kind: FiscalDocumentKind,
            jurisdiction: BrazilianJurisdiction,
            operation: str,
        ) -> str:
            return application.resolve_configured_provider_id(
                scope=scope,
                document_kind=document_kind,
                jurisdiction=jurisdiction,
                operation=operation,
            )

    return BarueriPmb004HomologationTransport(
        provider_resolver=CanonicalResolver(),
        resolve_certificate=lambda scope, cnpj: vault.resolve(
            scope=scope, issuer_cnpj=cnpj,
        ),
        validate_pmb004=validate_pmb004,
    )
