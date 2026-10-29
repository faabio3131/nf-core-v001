"""Shared NF-e/NFC-e preparation; existing NFC-e public entry points stay compatible."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.documents import CanonicalFiscalDocument
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalValidationError,
)
from kordena_fiscal.gateway import (
    AuthorizationRequest,
    AuthorizationResult,
    AuthorizationStatus,
    FiscalGatewayClient,
)
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    FiscalStateMachine,
    FiscalStateSnapshot,
    IdempotencyCoordinator,
    IssuanceAttempt,
    IssuanceAttemptStatus,
    build_issuance_key,
    build_request_fingerprint,
)
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    FiscalSequenceManager,
)
from kordena_fiscal.runtime.observability import MetricsRegistry
from kordena_fiscal.security import (
    CertificateReference,
    FiscalSigningService,
    SignatureEnvelope,
    SigningRequest,
)
from kordena_fiscal.xml import (
    AccessKeyInput,
    NfceXmlPayload,
    NfeAccessKey,
    XmlValidationResult,
    build_access_key,
)

if TYPE_CHECKING:
    from kordena_fiscal.application.service import FiscalApplicationService


class NfceIssuanceContractError(FiscalDomainError):
    """Raised when an injected NFC-e adapter violates the orchestration contract."""


class NfceNumericCodeProvider(Protocol):
    """Produce cNF without forcing a randomness policy into the generic Core."""

    def code_for(
        self,
        document: CanonicalFiscalDocument,
        attempt: IssuanceAttempt,
        number: FiscalNumberReservation,
    ) -> int: ...


class NfceXmlBuilder(Protocol):
    """Map the canonical document to one NFC-e XML payload for a fixed access key."""

    def build(
        self,
        document: CanonicalFiscalDocument,
        access_key: NfeAccessKey,
    ) -> NfceXmlPayload: ...


class NfceXmlValidator(Protocol):
    """Validate an NFC-e payload against the approved schema bundle."""

    def validate(self, payload: NfceXmlPayload) -> XmlValidationResult: ...


class NfceSignedXmlAssembler(Protocol):
    """Embed a verified signature envelope into the XML transport artifact."""

    def assemble(
        self,
        payload: NfceXmlPayload,
        signature: SignatureEnvelope,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class _XmlInvoiceIssuanceCommand:
    """Common validated preparation inputs, specialized by document family."""

    _document_kind: ClassVar[FiscalDocumentKind]

    document: CanonicalFiscalDocument
    series: int
    certificate: CertificateReference
    signing_algorithm: str
    emission_type: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.document, CanonicalFiscalDocument):
            raise FiscalValidationError("document must be CanonicalFiscalDocument")
        if self.document.document_kind is not self._document_kind:
            raise FiscalValidationError(
                f"issuance command accepts only {self._document_kind.name} documents"
            )
        if not isinstance(self.series, int) or isinstance(self.series, bool):
            raise FiscalValidationError("series must be an integer")
        if self.series < 0 or self.series > 999:
            raise FiscalValidationError("series must be between 0 and 999")
        if not isinstance(self.emission_type, int) or isinstance(self.emission_type, bool):
            raise FiscalValidationError("emission_type must be an integer")
        if self.emission_type < 1 or self.emission_type > 9:
            raise FiscalValidationError("emission_type must be between 1 and 9")
        if not isinstance(self.certificate, CertificateReference):
            raise FiscalValidationError("certificate must be CertificateReference")
        algorithm = self.signing_algorithm.strip()
        if not algorithm:
            raise FiscalValidationError("signing_algorithm must not be blank")
        if len(algorithm) > 256:
            raise FiscalValidationError("signing_algorithm exceeds max length 256")
        object.__setattr__(self, "signing_algorithm", algorithm)
        self.certificate.assert_usable(self.document.scope, self.document.issued_at)


class NfceIssuanceCommand(_XmlInvoiceIssuanceCommand):
    """Prepare only a model-65 NFC-e document."""

    __slots__ = ()
    _document_kind = FiscalDocumentKind.NFCE


class NfeIssuanceCommand(_XmlInvoiceIssuanceCommand):
    """Prepare only a model-55 NF-e document."""

    __slots__ = ()
    _document_kind = FiscalDocumentKind.NFE


@dataclass(frozen=True, slots=True)
class NfceIssuanceResult:
    """Outcome without retaining private key material or raw signed XML."""

    attempt: IssuanceAttempt
    replay: bool
    number_reservation: FiscalNumberReservation | None = None
    access_key: NfeAccessKey | None = None
    xml_validation: XmlValidationResult | None = None
    signature: SignatureEnvelope | None = None
    signed_xml_sha256: str | None = None
    authorization: AuthorizationResult | None = None
    lifecycle: FiscalStateSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, IssuanceAttempt):
            raise FiscalValidationError("attempt must be IssuanceAttempt")
        if not isinstance(self.replay, bool):
            raise FiscalValidationError("replay must be bool")
        fresh_artifacts = (
            self.number_reservation,
            self.access_key,
            self.xml_validation,
            self.signature,
            self.signed_xml_sha256,
            self.authorization,
            self.lifecycle,
        )
        if self.replay:
            if any(value is not None for value in fresh_artifacts):
                raise FiscalValidationError("replay result cannot expose new issuance artifacts")
            return
        if any(value is None for value in fresh_artifacts):
            raise FiscalValidationError(
                "fresh issuance result requires all orchestration artifacts"
            )
        assert self.authorization is not None
        assert self.lifecycle is not None
        if self.authorization.status is AuthorizationStatus.AUTHORIZED:
            if self.attempt.status is not IssuanceAttemptStatus.AUTHORIZED:
                raise FiscalValidationError("authorized gateway result must authorize the attempt")
            if self.lifecycle.state is not FiscalDocumentState.AUTHORIZED:
                raise FiscalValidationError("authorized gateway result must end AUTHORIZED")
        elif self.authorization.status is AuthorizationStatus.REJECTED:
            if self.attempt.status is not IssuanceAttemptStatus.REJECTED:
                raise FiscalValidationError("rejected gateway result must reject the attempt")
            if self.lifecycle.state is not FiscalDocumentState.REJECTED:
                raise FiscalValidationError("rejected gateway result must end REJECTED")
        else:
            if self.attempt.status is not IssuanceAttemptStatus.RESERVED:
                raise FiscalValidationError("pending gateway result must keep attempt RESERVED")
            if self.lifecycle.state is not FiscalDocumentState.TRANSMITTING:
                raise FiscalValidationError("pending gateway result must remain TRANSMITTING")


class _XmlInvoiceIssuanceOrchestrator:
    """One preparation pipeline for both electronic-invoice models."""

    _document_kind: ClassVar[FiscalDocumentKind]

    def __init__(
        self,
        *,
        idempotency: IdempotencyCoordinator | None = None,
        numbering: FiscalSequenceManager | None = None,
        application: FiscalApplicationService | None = None,
        archive_retention: RetentionPolicyMetadata | None = None,
        numeric_code_provider: NfceNumericCodeProvider,
        xml_builder: NfceXmlBuilder,
        xml_validator: NfceXmlValidator,
        signing: FiscalSigningService,
        signed_xml_assembler: NfceSignedXmlAssembler,
        gateway: FiscalGatewayClient,
        state_machine: FiscalStateMachine | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        if application is None:
            if idempotency is None or numbering is None or archive_retention is not None:
                raise FiscalValidationError("legacy issuance requires idempotency and numbering")
        elif idempotency is not None or numbering is not None or archive_retention is None:
            raise FiscalValidationError("durable issuance requires one authority and retention")
        self._application = application
        self._archive_retention = archive_retention
        self._metrics = metrics
        self._idempotency = idempotency
        self._numbering = numbering
        self._numeric_code_provider = numeric_code_provider
        self._xml_builder = xml_builder
        self._xml_validator = xml_validator
        self._signing = signing
        self._signed_xml_assembler = signed_xml_assembler
        self._gateway = gateway
        self._state_machine = state_machine or FiscalStateMachine()

    def _observe(self, metric: str, *, outcome: str) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.increment(metric, outcome=outcome)
        except Exception:
            # A telemetry failure cannot alter fiscal authorization authority.
            return

    def issue(self, command: NfceIssuanceCommand | NfeIssuanceCommand) -> XmlInvoiceIssuanceResult:
        if not isinstance(command, (NfceIssuanceCommand, NfeIssuanceCommand)):
            raise FiscalValidationError("a validated electronic-invoice command is required")
        document = command.document
        if document.document_kind is not self._document_kind:
            raise FiscalValidationError("orchestrator does not match document family")
        model = (
            ElectronicInvoiceModel.NFE
            if document.document_kind is FiscalDocumentKind.NFE
            else ElectronicInvoiceModel.NFCE
        )
        family = "NF-e" if model is ElectronicInvoiceModel.NFE else "NFC-e"
        if self._application is not None:
            durable = self._application.reserve_issuance(
                scope=document.scope,
                key=build_issuance_key(document),
                request_fingerprint=build_request_fingerprint(document),
                document_id=document.document_id,
                created_at=document.issued_at,
            )
            idempotency_reservation = durable.reservation
        else:
            assert self._idempotency is not None
            idempotency_reservation = self._idempotency.begin(document)
        if idempotency_reservation.replay:
            return XmlInvoiceIssuanceResult(
                attempt=idempotency_reservation.attempt,
                replay=True,
            )

        attempt = idempotency_reservation.attempt
        lifecycle = FiscalStateSnapshot.initial(document.document_id, document.issued_at)
        lifecycle = self._transition(
            lifecycle,
            FiscalDocumentState.VALIDATING,
            document,
            f"{family} issuance validation started",
        )

        if self._application is not None:
            number = self._application.reserve_number(
                FiscalSequenceKey.from_scope(document.scope, model=model, series=command.series)
            )
        else:
            assert self._numbering is not None
            number = self._numbering.reserve(document.scope, model=model, series=command.series)
        numeric_code = self._numeric_code_provider.code_for(document, attempt, number)
        if not isinstance(numeric_code, int) or isinstance(numeric_code, bool):
            raise NfceIssuanceContractError("numeric-code provider must return an integer")

        municipality_code = document.issuer.address.jurisdiction.municipality_ibge_code
        if municipality_code is None:
            raise NfceIssuanceContractError("issuer municipality IBGE code is required")
        access_key = build_access_key(
            AccessKeyInput(
                state_ibge_code=municipality_code[:2],
                issued_at=document.issued_at,
                issuer_cnpj=document.issuer.cnpj,
                model=model,
                series=command.series,
                invoice_number=number.number,
                emission_type=command.emission_type,
                numeric_code=numeric_code,
            )
        )

        payload = self._xml_builder.build(document, access_key)
        if not isinstance(payload, NfceXmlPayload):
            raise NfceIssuanceContractError("XML builder must return NfceXmlPayload")
        if payload.access_key != access_key:
            raise NfceIssuanceContractError("XML builder returned a different access key")
        validation = self._xml_validator.validate(payload)
        if not isinstance(validation, XmlValidationResult):
            raise NfceIssuanceContractError("XML validator must return XmlValidationResult")
        expected_xml_digest = hashlib.sha256(payload.xml).hexdigest()
        if validation.xml_sha256 != expected_xml_digest:
            raise NfceIssuanceContractError("XML validator returned a mismatched XML digest")

        lifecycle = self._transition(
            lifecycle,
            FiscalDocumentState.READY_TO_SIGN,
            document,
            f"{family} XML validated",
        )
        lifecycle = self._transition(
            lifecycle,
            FiscalDocumentState.SIGNING,
            document,
            f"{family} XML signing started",
        )
        signature = self._signing.sign(
            SigningRequest(
                scope=document.scope,
                certificate=command.certificate,
                payload=payload.xml,
                algorithm=command.signing_algorithm,
                signing_time=document.issued_at,
                purpose="nfe_xml" if model is ElectronicInvoiceModel.NFE else "nfce_xml",
            )
        )
        signed_xml = self._signed_xml_assembler.assemble(payload, signature)
        if not isinstance(signed_xml, bytes) or not signed_xml:
            raise NfceIssuanceContractError("signed XML assembler must return non-empty bytes")
        if signed_xml == payload.xml:
            raise NfceIssuanceContractError("signed XML assembler returned the unsigned payload")
        NfceXmlPayload(access_key=access_key, xml=signed_xml)
        signed_xml_sha256 = hashlib.sha256(signed_xml).hexdigest()

        if self._application is not None:
            assert self._archive_retention is not None
            request = AuthorizationRequest(
                scope=document.scope,
                access_key=access_key,
                signed_xml=signed_xml,
                idempotency_key=attempt.key,
                request_fingerprint=attempt.request_fingerprint,
            )
            self._application.persist_prepared_authorization(
                document_id=document.document_id,
                request=request,
                occurred_at=document.issued_at,
                retention=self._archive_retention,
            )
            try:
                outcome = self._application.authorize_prepared_document(
                    document_id=document.document_id,
                    request=request,
                    gateway=self._gateway,
                    occurred_at=document.issued_at,
                )
            except Exception:
                self._observe("nfcore_provider_errors_total", outcome="error")
                raise
            if outcome.replay:
                return XmlInvoiceIssuanceResult(attempt=outcome.attempt, replay=True)
            assert isinstance(outcome.provider_result, AuthorizationResult)
            authorization = outcome.provider_result
            attempt, lifecycle = outcome.attempt, outcome.lifecycle
            if authorization.status is not AuthorizationStatus.PENDING:
                self._observe(
                    "nfcore_fiscal_authorizations_finalized_total",
                    outcome=authorization.status.value,
                )
            if authorization.status is AuthorizationStatus.REJECTED:
                self._observe("nfcore_fiscal_rejections_total", outcome="rejected")
        else:
            assert self._idempotency is not None
            lifecycle = self._transition(
                lifecycle,
                FiscalDocumentState.READY_TO_TRANSMIT,
                document,
                f"signed {family} transport artifact prepared",
            )
            lifecycle = self._transition(
                lifecycle,
                FiscalDocumentState.TRANSMITTING,
                document,
                f"{family} authorization requested",
            )
            try:
                authorization = self._gateway.authorize(
                    AuthorizationRequest(
                        scope=document.scope,
                        access_key=access_key,
                        signed_xml=signed_xml,
                        idempotency_key=attempt.key,
                        request_fingerprint=attempt.request_fingerprint,
                    )
                )
            except Exception:
                self._observe("nfcore_provider_errors_total", outcome="error")
                raise

            if authorization.status is AuthorizationStatus.AUTHORIZED:
                protocol_reference = authorization.protocol_reference
                if protocol_reference is None:
                    raise NfceIssuanceContractError(
                        "authorized result is missing protocol reference"
                    )
                lifecycle = self._transition(
                    lifecycle,
                    FiscalDocumentState.AUTHORIZED,
                    document,
                    f"{family} authorization confirmed",
                )
                attempt = self._idempotency.mark_authorized(
                    attempt.key,
                    attempt.generation,
                    protocol_reference,
                )
                self._observe("nfcore_fiscal_authorizations_finalized_total", outcome="authorized")
            elif authorization.status is AuthorizationStatus.REJECTED:
                rejection_code = authorization.rejection_code
                rejection_message = authorization.rejection_message
                if rejection_code is None or rejection_message is None:
                    raise NfceIssuanceContractError("rejected result is missing rejection metadata")
                rejection_reason = f"{rejection_code}: {rejection_message}"
                lifecycle = self._transition(
                    lifecycle,
                    FiscalDocumentState.REJECTED,
                    document,
                    rejection_reason,
                )
                attempt = self._idempotency.mark_rejected(
                    attempt.key,
                    attempt.generation,
                    rejection_reason,
                )
                self._observe("nfcore_fiscal_rejections_total", outcome="rejected")
                self._observe("nfcore_fiscal_authorizations_finalized_total", outcome="rejected")

        return XmlInvoiceIssuanceResult(
            attempt=attempt,
            replay=False,
            number_reservation=number,
            access_key=access_key,
            xml_validation=validation,
            signature=signature,
            signed_xml_sha256=signed_xml_sha256,
            authorization=authorization,
            lifecycle=lifecycle,
        )

    def _transition(
        self,
        snapshot: FiscalStateSnapshot,
        target: FiscalDocumentState,
        document: CanonicalFiscalDocument,
        reason: str,
    ) -> FiscalStateSnapshot:
        if self._application is not None:
            return self._application.transition_lifecycle(
                document.document_id,
                target,
                occurred_at=document.issued_at,
                reason=reason,
                correlation_id=document.scope.correlation_id,
            )
        return self._state_machine.transition(
            snapshot,
            target,
            occurred_at=document.issued_at,
            reason=reason,
            correlation_id=document.scope.correlation_id,
        )


class NfceIssuanceOrchestrator(_XmlInvoiceIssuanceOrchestrator):
    """NFC-e entry point using the shared preparation pipeline."""

    _document_kind = FiscalDocumentKind.NFCE


class NfeIssuanceOrchestrator(_XmlInvoiceIssuanceOrchestrator):
    """NF-e entry point using the same validated and durable preparation pipeline."""

    _document_kind = FiscalDocumentKind.NFE


# Backward compatible result name; one result contract for both XML families.
XmlInvoiceIssuanceResult = NfceIssuanceResult
NfeIssuanceResult = NfceIssuanceResult
