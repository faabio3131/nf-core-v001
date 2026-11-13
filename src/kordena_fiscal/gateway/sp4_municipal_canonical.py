"""Canonical authorization boundary shared by four DISTINCT SP municipal providers.

The transport family for each municipality is explicit and injected; this
module never invents a WSDL/XSD, taxpayer credentials or official invoice.
Only a source-correlated, schema-verified municipal invoice can be authorized.
External municipal adapters must construct the typed outcome from their
current official contract, never merely from SOAP HTTP 200 or batch protocol.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import (
    AuthorizationStatus,
    GatewayProviderMetadata,
)
from kordena_fiscal.gateway.municipal_sp_routing import (
    classify_sp_national_nfse_eligibility,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
)

SP4_MUNICIPAL_PROVIDERS = MappingProxyType({
    "cajamar-geisweb-homologation": "3509205",
    "barueri-pmb004-homologation": "3505708",
    "osasco-rtc-homologation": "3534401",
    "jundiai-giss-v2-homologation": "3525904",
})


class Sp4CanonicalMunicipalError(FiscalValidationError):
    """Fail-closed tax validation without reflecting municipal credentials."""


def _label(value: str, name: str, max_chars: int = 128) -> str:
    if type(value) is not str or not 0 < len(value) <= max_chars:
        raise Sp4CanonicalMunicipalError(f"Invalid {name}")
    if any(ord(char) < 32 for char in value):
        raise Sp4CanonicalMunicipalError(f"Unsafe {name}")
    return value


@dataclass(frozen=True, slots=True)
class Sp4OriginalRps:
    """Immutable RPS identity already reserved and persisted by the application."""

    scope: ExecutionScope
    document_id: str
    request_fingerprint: str
    issuer_cnpj: Cnpj
    issuer_ibge: str
    competence_date: date
    rps_number: str
    rps_series: str
    gross_amount: Decimal
    # Immutable, issuer-scoped lot/remittance identifier allocated and
    # persisted BEFORE POST. GeisWeb needs it for read-only lot recovery;
    # Barueri must reuse the same remittance for status/download.
    municipal_batch_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ExecutionScope)
            or not isinstance(self.issuer_cnpj, Cnpj)
            or type(self.competence_date) is not date
            or type(self.gross_amount) is not Decimal
            or not self.gross_amount.is_finite()
            or self.gross_amount < 0
            or self.gross_amount * 100
            != (self.gross_amount * 100).to_integral_value()
        ):
            raise Sp4CanonicalMunicipalError("Original municipal RPS is incomplete")
        _label(self.document_id, "document ID")
        _label(self.request_fingerprint, "fingerprint", 64)
        if len(self.request_fingerprint) != 64 or any(
            x not in "0123456789abcdef" for x in self.request_fingerprint
        ):
            raise Sp4CanonicalMunicipalError("Invalid immutable document fingerprint")
        if self.issuer_ibge not in SP4_MUNICIPAL_PROVIDERS.values():
            raise Sp4CanonicalMunicipalError("Unknown SP4 RPS issuer")
        _label(self.rps_number, "RPS number", 32)
        # Barueri PMB004 permits a blank original RPS series (PDF field
        # optional); all other municipal adapters require an explicit series.
        if self.rps_series == "" and self.issuer_ibge == "3505708":
            pass
        else:
            _label(self.rps_series, "RPS series", 16)
        if self.municipal_batch_id is not None:
            _label(self.municipal_batch_id, "municipal batch ID", 32)
            if (
                not self.municipal_batch_id.isascii()
                or not self.municipal_batch_id.isdecimal()
                or int(self.municipal_batch_id) < 1
            ):
                raise Sp4CanonicalMunicipalError("Invalid durable municipal batch ID")


@dataclass(frozen=True, slots=True)
class Sp4VerifiedInvoice:
    """Source-correlated invoice proof, accepted only after official XML verification."""

    issuer_cnpj: Cnpj
    issuer_ibge: str
    competence_date: date
    rps_number: str
    rps_series: str
    gross_amount: Decimal
    invoice_number: str
    verification_code: str
    invoice_reference: str
    authorized_xml: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.issuer_cnpj, Cnpj)
            or self.issuer_ibge not in SP4_MUNICIPAL_PROVIDERS.values()
            or type(self.competence_date) is not date
            or type(self.gross_amount) is not Decimal
            or not self.gross_amount.is_finite()
            or self.gross_amount < 0
            or self.gross_amount * 100
            != (self.gross_amount * 100).to_integral_value()
            or type(self.authorized_xml) is not bytes
            or not 0 < len(self.authorized_xml) <= 2_097_152
        ):
            raise Sp4CanonicalMunicipalError("Official NFS-e proof is malformed")
        for value, name in (
            (self.rps_number, "RPS number"),
            (self.invoice_number, "invoice number"),
            (self.verification_code, "verification code"),
            (self.invoice_reference, "invoice reference"),
        ):
            _label(value, name, 128)
        if self.rps_series != "" or self.issuer_ibge != "3505708":
            _label(self.rps_series, "RPS series", 16)


@dataclass(frozen=True, slots=True)
class Sp4ProviderOutcome:
    """Normalized provider response, not an arbitrary HTTP success indicator."""

    status: AuthorizationStatus
    provider_request_id: str | None = None
    official_invoice: Sp4VerifiedInvoice | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AuthorizationStatus):
            raise Sp4CanonicalMunicipalError("Invalid municipal operation result status")
        if self.provider_request_id is not None:
            _label(self.provider_request_id, "provider request ID", 128)
        if self.status is AuthorizationStatus.AUTHORIZED:
            if self.official_invoice is None or any(
                (self.rejection_code, self.rejection_message)
            ):
                raise Sp4CanonicalMunicipalError("Municipal invoice needs official proof")
        elif self.status is AuthorizationStatus.REJECTED:
            if (
                self.official_invoice is not None
                or self.rejection_code is None
                or self.rejection_message is None
            ):
                raise Sp4CanonicalMunicipalError("Municipal rejection needs an official reason")
            _label(self.rejection_code, "rejection code", 64)
            _label(self.rejection_message, "rejection message", 512)
        elif self.official_invoice is not None or any(
            (self.rejection_code, self.rejection_message)
        ):
            raise Sp4CanonicalMunicipalError("Unresolved municipality cannot assert fiscal proof")


class Sp4MunicipalCanonicalGateway:
    """Opt-in bridge from durable fiscal intent to provider-specific typed ports.

    This class implements NfseGateway and NfseQueryGateway and is compatible
    with NfseGatewayClient/NfseQueryClient in the existing canonical runtime.
    It never allocates a new RPS or retries ambiguous submissions. Each city's
    builder/transport/receipt verifier is an independent required port.
    """

    def __init__(
        self, *,
        provider_id: str,
        resolver: ProviderSelectionResolver,
        load_original_rps: Callable[[ExecutionScope, str], Sp4OriginalRps],
        municipal_issuer_policy: Callable[[NfseAuthorizationRequest], None],
        validate_prepared_rps: Callable[[Sp4OriginalRps], None],
        submit_prepared_rps: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
        ],
        query_original_rps: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
        ],
        verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None],
    ) -> None:
        if provider_id not in SP4_MUNICIPAL_PROVIDERS:
            raise Sp4CanonicalMunicipalError("SP4 provider must have reviewed identity")
        if not callable(getattr(resolver, "resolve_provider_id", None)) or not all(
            callable(port) for port in (
                load_original_rps, municipal_issuer_policy,
                validate_prepared_rps, submit_prepared_rps,
                query_original_rps, verify_official_invoice_xml,
            )
        ):
            raise Sp4CanonicalMunicipalError(
                "SP4 requires trusted canonical, municipal and official proof ports"
            )
        self._provider_id = provider_id
        self._ibge = SP4_MUNICIPAL_PROVIDERS[provider_id]
        self._resolver = resolver
        self._load = load_original_rps
        self._policy = municipal_issuer_policy
        self._preflight = validate_prepared_rps
        self._submit = submit_prepared_rps
        self._query = query_original_rps
        self._verify = verify_official_invoice_xml
        self._metadata = GatewayProviderMetadata(provider_id, "sp4-governed-2026-v1")

    def _original(
        self, request: NfseAuthorizationRequest, operation: str,
    ) -> Sp4OriginalRps:
        if not isinstance(request, NfseAuthorizationRequest):
            raise Sp4CanonicalMunicipalError("Canonical NFS-e request required")
        doc = request.document
        scope = doc.scope
        jurisdiction = doc.issuer.address.jurisdiction
        if (
            scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not scope.host_namespace
            or jurisdiction.state_code != "SP"
            or jurisdiction.municipality_ibge_code != self._ibge
            or type(doc.issuer.tax_regime) is not TaxRegimeCode
            or type(doc.competence_date) is not date
        ):
            raise Sp4CanonicalMunicipalError("SP4 issuer/municipality or environment mismatch")
        try:
            classify_sp_national_nfse_eligibility(
                issuer_jurisdiction=jurisdiction,
                tax_regime=doc.issuer.tax_regime,
                competence_date=doc.competence_date,
            )
        except FiscalValidationError:
            pass
        else:
            raise Sp4CanonicalMunicipalError(
                "Issuer must use National NFS-e for service competence"
            )
        # Additional municipal regulation is required for old competences,
        # ordinary corporate regimes and special ISS classifications.
        self._policy(request)
        selected = self._resolver.resolve_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", self._ibge),
            operation=operation,
        )
        if selected != self._provider_id:
            raise Sp4CanonicalMunicipalError(
                "SP4 provider binding does not match the fiscal operation"
            )
        original = self._load(scope, doc.document_id)
        if not isinstance(original, Sp4OriginalRps) or (
            original.scope.identity_partition_key != scope.identity_partition_key
            or original.scope.environment != scope.environment
            or original.document_id != doc.document_id
            or original.request_fingerprint != request.request_fingerprint
            or original.issuer_cnpj != doc.issuer.cnpj
            or original.issuer_ibge != self._ibge
            or original.competence_date != doc.competence_date
            or original.gross_amount != doc.totals.gross_amount.amount
        ):
            raise Sp4CanonicalMunicipalError(
                "Durable original RPS does not match canonical fiscal document"
            )
        self._preflight(original)
        return original

    def _result(
        self, request: NfseAuthorizationRequest,
        original: Sp4OriginalRps, outcome: Sp4ProviderOutcome, *,
        read_only: bool,
    ) -> NfseAuthorizationResult:
        if not isinstance(outcome, Sp4ProviderOutcome):
            raise Sp4CanonicalMunicipalError(
                "Municipal transport did not return a canonical result"
            )
        status = outcome.status
        invoice = outcome.official_invoice
        if status is AuthorizationStatus.AUTHORIZED:
            if invoice is None or (
                invoice.issuer_cnpj != original.issuer_cnpj
                or invoice.issuer_ibge != original.issuer_ibge
                or invoice.competence_date != original.competence_date
                or invoice.rps_number != original.rps_number
                or invoice.rps_series != original.rps_series
                or invoice.gross_amount != original.gross_amount
            ):
                raise Sp4CanonicalMunicipalError(
                    "Official municipal invoice disagrees with persisted original RPS"
                )
            # The injected official XSD/receipt-signature proof is mandatory.
            # Never promote status on an unverified raw SOAP/CSV/GISS response.
            self._verify(invoice)
        elif read_only:
            # A failed/not-found consultation cannot prove a previous fiscal
            # POST was rejected and must never authorize retransmission.
            status = AuthorizationStatus.PENDING
        return NfseAuthorizationResult(
            status=status,
            scope=request.document.scope,
            document_id=original.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=self._metadata,
            provider_request_id=outcome.provider_request_id,
            invoice_reference=invoice.invoice_reference if invoice is not None else None,
            invoice_number=invoice.invoice_number if invoice is not None else None,
            verification_code=invoice.verification_code if invoice is not None else None,
            authorized_xml=invoice.authorized_xml if invoice is not None else None,
            rejection_code=(
                outcome.rejection_code if status is AuthorizationStatus.REJECTED else None
            ),
            rejection_message=(
                outcome.rejection_message if status is AuthorizationStatus.REJECTED else None
            ),
        )

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        original = self._original(request, "authorize")
        outcome = self._submit(request, original)
        return self._result(request, original, outcome, read_only=False)

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        original = self._original(request, "query")
        outcome = self._query(request, original)
        return self._result(request, original, outcome, read_only=True)
