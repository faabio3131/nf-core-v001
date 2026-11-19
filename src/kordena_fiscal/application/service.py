"""Universal application service over pure domain rules and durable repositories."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    FiscalArchiveVerifier,
    RetentionPolicyMetadata,
)
from kordena_fiscal.contingency import (
    FiscalOutboxEnqueueResult,
    FiscalOutboxEntry,
    FiscalOutboxService,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    HostScope,
    SourceReference,
)
from kordena_fiscal.events import (
    FiscalInboxEntry,
    FiscalInboxReceiveResult,
    FiscalInboxService,
)
from kordena_fiscal.gateway import (
    AuthorizationRequest,
    AuthorizationResult,
    AuthorizationStatus,
    FiscalGatewayClient,
)
from kordena_fiscal.gateway.webiss_extrema_canonical import (
    ExtremaCancellationOutcome,
    ExtremaSubstitutionOutcome,
    WebissExtremaCanonicalNfseGateway,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseQueryClient,
)
from kordena_fiscal.issuance.nfse_archive import (
    NFSE_PREPARED_MEDIA_TYPE,
    decode_prepared_nfse,
    encode_prepared_nfse,
)
from kordena_fiscal.issuance.webiss_extrema_builder import (
    EXTREMA_INTENT_MEDIA_TYPE,
    ExtremaRpsIntent,
    decode_extrema_intent,
    encode_extrema_intent,
    validate_extrema_intent,
)
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    FiscalStateMachine,
    FiscalStateSnapshot,
    IdempotencyKey,
    IdempotencyReservation,
    IssuanceAttempt,
    IssuanceAttemptStatus,
)
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    FiscalSequencePolicy,
    InternalFiscalSequenceStream,
)
from kordena_fiscal.operations import (
    CancellationRequest,
    CancellationResult,
    FiscalCancellationService,
    FiscalOperationsClient,
    FiscalOperationSnapshot,
    FiscalQueryRequest,
    FiscalQueryResult,
    FiscalQueryStatus,
)
from kordena_fiscal.operations.event_archive import build_event_result_evidence
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWork,
    FiscalUnitOfWorkFactory,
    PersistenceConflictError,
    PersistenceStateError,
)
from kordena_fiscal.reconciliation import (
    FiscalReconciliationCandidate,
    FiscalReconciliationEngine,
    FiscalReconciliationResult,
)
from kordena_fiscal.runtime.observability import MetricsRegistry
from kordena_fiscal.xml import NfeAccessKey


class IssuanceResumeDisposition(StrEnum):
    """Fail-closed instruction returned after a durable idempotency reservation."""

    FRESH = "fresh"
    AUTHORIZED_REPLAY = "authorized_replay"
    REJECTED_REPLAY = "rejected_replay"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class DurableIssuanceReservation:
    reservation: IdempotencyReservation
    lifecycle: FiscalStateSnapshot
    disposition: IssuanceResumeDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.reservation, IdempotencyReservation):
            raise FiscalValidationError("reservation must be IdempotencyReservation")
        if not isinstance(self.lifecycle, FiscalStateSnapshot):
            raise FiscalValidationError("lifecycle must be FiscalStateSnapshot")
        if not isinstance(self.disposition, IssuanceResumeDisposition):
            raise FiscalValidationError("disposition must be IssuanceResumeDisposition")
        if self.lifecycle.document_id != self.reservation.attempt.document_id:
            raise FiscalValidationError("lifecycle and idempotency attempt must share document_id")


@dataclass(frozen=True, slots=True)
class DurableAuthorizationOutcome:
    """Persisted issuance state; absent provider result never means authorization."""

    attempt: IssuanceAttempt
    lifecycle: FiscalStateSnapshot
    replay: bool
    recovery_required: bool
    provider_result: AuthorizationResult | NfseAuthorizationResult | None = None


@dataclass(frozen=True, slots=True)
class DurableRecoveryOutcome:
    """Durable result of a read-only provider query, never a new issuance."""

    attempt: IssuanceAttempt
    lifecycle: FiscalStateSnapshot
    replay: bool
    recovery_required: bool
    query_result: FiscalQueryResult | None = None


@dataclass(frozen=True, slots=True)
class DurablePreparedAuthorization:
    """One provider-neutral request durably prepared before external I/O."""

    attempt: IssuanceAttempt
    lifecycle: FiscalStateSnapshot
    request: NfseAuthorizationRequest
    replay: bool


@dataclass(frozen=True, slots=True)
class DurableNfseRecoveryOutcome:
    """Durable outcome of a read-only NFS-e query; it never retransmits issuance."""

    attempt: IssuanceAttempt
    lifecycle: FiscalStateSnapshot
    replay: bool
    recovery_required: bool
    query_result: NfseAuthorizationResult | None = None


@dataclass(frozen=True, slots=True)
class DurableCancellationOutcome:
    result: CancellationResult
    lifecycle: FiscalStateSnapshot
    archive_reference: str

@dataclass(frozen=True, slots=True)
class DurableExtremaCancellationOutcome:
    result: ExtremaCancellationOutcome
    lifecycle: FiscalStateSnapshot
    archive_reference: str

@dataclass(frozen=True, slots=True)
class DurableExtremaSubstitutionOutcome:
    result: ExtremaSubstitutionOutcome
    original_lifecycle: FiscalStateSnapshot
    replacement_lifecycle: FiscalStateSnapshot
    archive_reference: str



class FiscalApplicationService:
    """Host-neutral application boundary with explicit transactional state changes.

    External provider I/O intentionally stays outside these local transactions.
    A retry of a RESERVED attempt is classified as RECOVERY_REQUIRED instead of
    being silently re-issued, which is the V2-07 crash-safety rule.
    """

    def __init__(
        self,
        uow_factory: FiscalUnitOfWorkFactory,
        *,
        state_machine: FiscalStateMachine | None = None,
        reconciliation: FiscalReconciliationEngine | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._metrics = metrics
        self._uow_factory = uow_factory
        self._state_machine = state_machine or FiscalStateMachine()
        self._reconciliation = reconciliation or FiscalReconciliationEngine()

    def resolve_configured_provider_id(
        self,
        *,
        scope: ExecutionScope,
        document_kind: FiscalDocumentKind,
        jurisdiction: BrazilianJurisdiction,
        operation: str,
    ) -> str:
        from kordena_fiscal.control_plane.commercial import DurableProviderBindingResolver

        return DurableProviderBindingResolver(self._uow_factory).resolve_provider_id(
            scope=scope,
            document_kind=document_kind,
            jurisdiction=jurisdiction,
            operation=operation,
        )

    def register_binding(self, binding: FiscalAccountBinding) -> FiscalAccountBinding:
        with self._uow_factory() as uow:
            persisted = uow.bindings.add(binding)
            uow.commit()
            return persisted

    def resolve_scope(
        self,
        host_scope: HostScope,
        *,
        environment: FiscalEnvironment,
        correlation_id: str,
    ) -> ExecutionScope:
        with self._uow_factory() as uow:
            try:
                binding = uow.bindings.resolve(host_scope)
            except PersistenceStateError as exc:
                raise FiscalValidationError(
                    "exact durable fiscal binding is required for host scope"
                ) from exc
            return binding.to_execution_scope(
                environment=environment,
                correlation_id=correlation_id,
            )

    def receive_inbox_event(
        self,
        *,
        scope: ExecutionScope,
        producer: str,
        event_id: str,
        event_type: str,
        payload: bytes,
        occurred_at: datetime,
        received_at: datetime,
        causation_id: str | None = None,
        idempotency_key: str | None = None,
        processing_operation: str | None = None,
    ) -> FiscalInboxReceiveResult:
        """Atomically persist one inbound event before any application processing."""

        with self._uow_factory() as uow:
            result = FiscalInboxService(uow.inbox).receive(
                scope=scope,
                producer=producer,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
                received_at=received_at,
                causation_id=causation_id,
                idempotency_key=idempotency_key,
            )
            if processing_operation is not None:
                persisted = result.entry
                FiscalOutboxService(uow.outbox).enqueue(
                    scope=persisted.scope,
                    operation=processing_operation,
                    deduplication_key=persisted.entry_id,
                    payload=persisted.entry_id.encode("ascii"),
                    created_at=persisted.received_at,
                )
            uow.commit()
            return result

    def begin_inbox_processing(
        self,
        entry_id: str,
        *,
        expected_version: int,
    ) -> FiscalInboxEntry:
        with self._uow_factory() as uow:
            entry = uow.inbox.begin_processing(
                entry_id,
                expected_version=expected_version,
            )
            uow.commit()
            return entry

    def complete_inbox_event(
        self,
        entry_id: str,
        *,
        expected_version: int,
        processed_at: datetime,
        outcome_reference: str | None = None,
    ) -> FiscalInboxEntry:
        with self._uow_factory() as uow:
            entry = uow.inbox.mark_processed(
                entry_id,
                expected_version=expected_version,
                processed_at=processed_at,
                outcome_reference=outcome_reference,
            )
            uow.commit()
            return entry

    def reject_inbox_event(
        self,
        entry_id: str,
        *,
        expected_version: int,
        processed_at: datetime,
        error: str,
    ) -> FiscalInboxEntry:
        with self._uow_factory() as uow:
            entry = uow.inbox.mark_rejected(
                entry_id,
                expected_version=expected_version,
                processed_at=processed_at,
                error=error,
            )
            uow.commit()
            return entry

    def get_inbox_event(self, entry_id: str) -> FiscalInboxEntry | None:
        with self._uow_factory() as uow:
            return uow.inbox.get(entry_id)

    def reserve_issuance(
        self,
        *,
        key: IdempotencyKey,
        request_fingerprint: str,
        document_id: str,
        created_at: datetime,
        scope: ExecutionScope,
    ) -> DurableIssuanceReservation:
        """Atomically persist issuance authority before any provider side effect."""

        if not isinstance(scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        with self._uow_factory() as uow:
            reservation = uow.idempotency.reserve(key, request_fingerprint, document_id)
            attempt = reservation.attempt
            lifecycle = uow.lifecycle.get(attempt.document_id)
            if lifecycle is None:
                if reservation.replay:
                    raise PersistenceStateError(
                        "idempotency replay has no durable lifecycle authority"
                    )
                lifecycle = FiscalStateSnapshot.initial(attempt.document_id, created_at)
                uow.lifecycle.add(lifecycle, scope=scope)
            else:
                uow.lifecycle.assert_scope(attempt.document_id, scope)
                if not reservation.replay:
                    raise PersistenceConflictError("document_id already belongs to an issuance")
            disposition = self._disposition(reservation)
            uow.commit()
            return DurableIssuanceReservation(
                reservation=reservation,
                lifecycle=lifecycle,
                disposition=disposition,
            )

    @staticmethod
    def _disposition(reservation: IdempotencyReservation) -> IssuanceResumeDisposition:
        if not reservation.replay:
            return IssuanceResumeDisposition.FRESH
        status = reservation.attempt.status
        if status is IssuanceAttemptStatus.AUTHORIZED:
            return IssuanceResumeDisposition.AUTHORIZED_REPLAY
        if status is IssuanceAttemptStatus.REJECTED:
            return IssuanceResumeDisposition.REJECTED_REPLAY
        return IssuanceResumeDisposition.RECOVERY_REQUIRED

    def transition_lifecycle(
        self,
        document_id: str,
        target: FiscalDocumentState,
        *,
        occurred_at: datetime,
        reason: str,
        correlation_id: str,
    ) -> FiscalStateSnapshot:
        """Apply domain transition first, then persist with optimistic concurrency."""

        with self._uow_factory() as uow:
            current = uow.lifecycle.get(document_id)
            if current is None:
                raise PersistenceStateError("fiscal lifecycle does not exist")
            updated = self._state_machine.transition(
                current,
                target,
                occurred_at=occurred_at,
                reason=reason,
                correlation_id=correlation_id,
            )
            uow.lifecycle.save(updated, expected_version=current.version)
            uow.commit()
            return updated

    def finalize_authorized(
        self,
        *,
        key: IdempotencyKey,
        generation: int,
        document_id: str,
        result_reference: str,
        occurred_at: datetime,
        reason: str,
        correlation_id: str,
        archive_entry: FiscalArchiveEntry | None = None,
    ) -> FiscalStateSnapshot:
        """Atomically couple terminal issuance and authenticated XML evidence."""

        with self._uow_factory() as uow:
            attempts = uow.idempotency.attempts(key)
            if (
                not attempts
                or attempts[-1].document_id != document_id
                or attempts[-1].generation != generation
            ):
                raise PersistenceStateError("finalization does not match durable issuance")
            current = uow.lifecycle.get(document_id)
            if current is None:
                raise PersistenceStateError("fiscal lifecycle does not exist")
            updated = self._state_machine.transition(
                current,
                FiscalDocumentState.AUTHORIZED,
                occurred_at=occurred_at,
                reason=reason,
                correlation_id=correlation_id,
            )
            if archive_entry is not None:
                if (archive_entry.document_reference != document_id
                    or archive_entry.kind is not FiscalArchiveKind.AUTHORIZED_XML):
                    raise PersistenceStateError("authorized XML archive is invalid")
                uow.lifecycle.assert_scope(document_id, archive_entry.scope)
                uow.archive.append(archive_entry)
            uow.idempotency.mark_authorized(key, generation, result_reference)
            uow.lifecycle.save(updated, expected_version=current.version)
            uow.commit()
            return updated

    def finalize_rejected(
        self,
        *,
        key: IdempotencyKey,
        generation: int,
        document_id: str,
        rejection_reason: str,
        occurred_at: datetime,
        correlation_id: str,
    ) -> FiscalStateSnapshot:
        """Atomically couple terminal rejection and idempotency result."""

        with self._uow_factory() as uow:
            attempts = uow.idempotency.attempts(key)
            if (
                not attempts
                or attempts[-1].document_id != document_id
                or attempts[-1].generation != generation
            ):
                raise PersistenceStateError("finalization does not match durable issuance")
            current = uow.lifecycle.get(document_id)
            if current is None:
                raise PersistenceStateError("fiscal lifecycle does not exist")
            updated = self._state_machine.transition(
                current,
                FiscalDocumentState.REJECTED,
                occurred_at=occurred_at,
                reason=rejection_reason,
                correlation_id=correlation_id,
            )
            uow.idempotency.mark_rejected(key, generation, rejection_reason)
            uow.lifecycle.save(updated, expected_version=current.version)
            uow.commit()
            return updated

    def persist_prepared_authorization(
        self,
        *,
        document_id: str,
        request: AuthorizationRequest,
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
    ) -> FiscalArchiveEntry:
        """Atomically preserve the signed transport request and mark it ready.

        Called only by trusted preparation after schema/signature validation.
        This artifact is not an authorized XML and contains no private key.
        """
        content = json.dumps(
            {
                "access_key": request.access_key.value,
                "idempotency_key": request.idempotency_key.value,
                "request_fingerprint": request.request_fingerprint,
                "signed_xml": base64.b64encode(request.signed_xml).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        entry = FiscalArchiveEntry.build(
            scope=request.scope,
            document_reference=document_id,
            kind=FiscalArchiveKind.OTHER,
            content=content,
            media_type="application/vnd.nfcore.prepared-xml.v1+json",
            archived_at=occurred_at,
            retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, request.scope)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                not attempts
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or attempts[-1].status is not IssuanceAttemptStatus.RESERVED
            ):
                raise PersistenceStateError("prepared request does not match durable issuance")
            current = uow.lifecycle.get(document_id)
            if current is None or current.state is not FiscalDocumentState.SIGNING:
                raise PersistenceStateError("preparation requires signing lifecycle")
            ready = self._state_machine.transition(
                current,
                FiscalDocumentState.READY_TO_TRANSMIT,
                occurred_at=occurred_at,
                reason="signed transport request archived",
                correlation_id=request.scope.correlation_id,
            )
            persisted = uow.archive.append(entry)
            uow.lifecycle.save(ready, expected_version=current.version)
            uow.commit()
            return persisted

    def prepare_nfse_authorization(
        self,
        document: NfseCanonicalDocument,
        *,
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
        extrema_intent_builder: Callable[
            [FiscalNumberReservation], ExtremaRpsIntent
        ] | None = None,
        extrema_rps_series: int | None = None,
    ) -> DurablePreparedAuthorization:
        """Atomically reserve, validate and archive one provider-neutral NFS-e request."""
        if not isinstance(document, NfseCanonicalDocument):
            raise FiscalValidationError("document must be NfseCanonicalDocument")
        if not isinstance(retention, RetentionPolicyMetadata):
            raise FiscalValidationError("retention must be RetentionPolicyMetadata")
        request = NfseAuthorizationRequest.build(document)
        if (extrema_intent_builder is None) != (extrema_rps_series is None):
            raise FiscalValidationError(
                "WebISS intent builder and RPS numbering series must be supplied together"
            )
        if extrema_intent_builder is not None and not callable(extrema_intent_builder):
            raise FiscalValidationError("WebISS RPS builder must be trusted and callable")
        entry = FiscalArchiveEntry.build(
            scope=document.scope,
            document_reference=document.document_id,
            kind=FiscalArchiveKind.OTHER,
            content=encode_prepared_nfse(request),
            media_type=NFSE_PREPARED_MEDIA_TYPE,
            archived_at=occurred_at,
            retention=retention,
        )
        with self._uow_factory() as uow:
            reservation = uow.idempotency.reserve(
                request.idempotency_key,
                request.request_fingerprint,
                document.document_id,
            )
            attempt = reservation.attempt
            current = uow.lifecycle.get(document.document_id)
            if reservation.replay:
                if current is None:
                    raise PersistenceStateError("NFS-e replay has no durable lifecycle")
                uow.lifecycle.assert_scope(document.document_id, document.scope)
                prepared = self._load_prepared_from_uow(uow, document.scope, document.document_id)
                if not isinstance(prepared, NfseAuthorizationRequest):
                    raise PersistenceStateError("durable request is not NFS-e")
                prior_intents = [
                    archived.content
                    for archived in uow.archive.list_for_document(
                        document.scope, document.document_id,
                    )
                    if archived.media_type == EXTREMA_INTENT_MEDIA_TYPE
                ]
                if len(prior_intents) > 1 or bool(prior_intents) != (
                    extrema_intent_builder is not None
                ):
                    raise PersistenceConflictError(
                        "WebISS fiscal intent cannot change after idempotency reservation"
                    )
                uow.commit()
                return DurablePreparedAuthorization(attempt, current, prepared, True)
            if current is not None:
                raise PersistenceConflictError("document_id already belongs to an issuance")
            municipal_entry: FiscalArchiveEntry | None = None
            if extrema_intent_builder is not None:
                assert extrema_rps_series is not None
                if (
                    not isinstance(extrema_rps_series, int)
                    or isinstance(extrema_rps_series, bool)
                    or not 0 <= extrema_rps_series <= 99_999
                ):
                    raise FiscalValidationError("Invalid scoped Extrema RPS series")
                if (
                    document.scope.environment is not FiscalEnvironment.HOMOLOGATION
                    or not document.scope.host_namespace
                    or document.issuer.address.jurisdiction.municipality_ibge_code
                    != "3125101"
                ):
                    raise FiscalValidationError(
                        "Atomic RPS reservation requires scoped Extrema homologation"
                    )
                key = FiscalSequenceKey.from_scope(
                    document.scope,
                    model=InternalFiscalSequenceStream.NFSE_RPS,
                    series=extrema_rps_series,
                )
                numbered = uow.sequences.reserve_next(
                    key, FiscalSequencePolicy(max_number=999_999_999_999_999),
                )
                approved_intent = extrema_intent_builder(numbered)
                validate_extrema_intent(request, approved_intent)
                municipal_entry = FiscalArchiveEntry.build(
                    scope=document.scope,
                    document_reference=document.document_id,
                    kind=FiscalArchiveKind.OTHER,
                    content=encode_extrema_intent(approved_intent),
                    media_type=EXTREMA_INTENT_MEDIA_TYPE,
                    archived_at=occurred_at,
                    retention=retention,
                )
            current = FiscalStateSnapshot.initial(document.document_id, document.issued_at)
            uow.lifecycle.add(current, scope=document.scope)
            for target, reason in (
                (FiscalDocumentState.VALIDATING, "NFS-e canonical validation started"),
                (FiscalDocumentState.READY_TO_SIGN, "NFS-e provider-neutral request validated"),
                (FiscalDocumentState.SIGNING, "NFS-e provider preparation started"),
                (FiscalDocumentState.READY_TO_TRANSMIT, "NFS-e canonical request archived"),
            ):
                updated = self._state_machine.transition(
                    current,
                    target,
                    occurred_at=occurred_at,
                    reason=reason,
                    correlation_id=document.scope.correlation_id,
                )
                uow.lifecycle.save(updated, expected_version=current.version)
                current = updated
            uow.archive.append(entry)
            if municipal_entry is not None:
                uow.archive.append(municipal_entry)
            uow.commit()
            return DurablePreparedAuthorization(attempt, current, request, False)

    def load_extrema_rps_intent(
        self, scope: ExecutionScope, document_id: str,
    ) -> ExtremaRpsIntent:
        """Recover the original immutable municipal RPS intent and reserved number.

        The request and provider-specific intent are read from the same scoped
        archival transaction. An ambiguous or unprepared request fails closed.
        """
        with self._uow_factory() as uow:
            prepared = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(prepared, NfseAuthorizationRequest):
                raise PersistenceStateError("Prepared document is not an NFS-e issuance")
            entries = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type == EXTREMA_INTENT_MEDIA_TYPE
            ]
            if len(entries) != 1:
                raise PersistenceStateError("WebISS requires exactly one prepared RPS intent")
            return decode_extrema_intent(entries[0].content, scope=scope, request=prepared)

    def load_prepared_authorization(
        self, scope: ExecutionScope, document_id: str
    ) -> AuthorizationRequest:
        """Resolve a current prepared XML request from the scoped durable archive."""
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, AuthorizationRequest):
                raise PersistenceStateError("prepared request is not NF-e/NFC-e XML")
            return request

    def load_prepared_nfse_authorization(
        self, scope: ExecutionScope, document_id: str
    ) -> NfseAuthorizationRequest:
        """Recover one validated NFS-e request after process restart."""
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("prepared request is not NFS-e")
            return request

    def load_prepared_document_authorization(
        self, scope: ExecutionScope, document_id: str
    ) -> AuthorizationRequest | NfseAuthorizationRequest:
        """Resolve exactly one prepared request without guessing its fiscal family."""
        with self._uow_factory() as uow:
            return self._load_prepared_from_uow(uow, scope, document_id)

    @staticmethod
    def _load_prepared_from_uow(
        uow: FiscalUnitOfWork, scope: ExecutionScope, document_id: str
    ) -> AuthorizationRequest | NfseAuthorizationRequest:
        uow.lifecycle.assert_scope(document_id, scope)
        matches: list[AuthorizationRequest | NfseAuthorizationRequest] = []
        for entry in uow.archive.list_for_document(scope, document_id):
            if entry.kind is not FiscalArchiveKind.OTHER:
                continue
            try:
                if entry.media_type == "application/vnd.nfcore.prepared-xml.v1+json":
                    data = json.loads(entry.content)
                    if (
                        not isinstance(data, dict)
                        or set(data)
                        != {"access_key", "idempotency_key", "request_fingerprint", "signed_xml"}
                        or not all(isinstance(value, str) for value in data.values())
                    ):
                        raise ValueError("invalid prepared request shape")
                    request: AuthorizationRequest | NfseAuthorizationRequest = AuthorizationRequest(
                        scope=scope,
                        access_key=NfeAccessKey(data["access_key"]),
                        idempotency_key=IdempotencyKey(data["idempotency_key"]),
                        request_fingerprint=data["request_fingerprint"],
                        signed_xml=base64.b64decode(data["signed_xml"], validate=True),
                    )
                elif entry.media_type == NFSE_PREPARED_MEDIA_TYPE:
                    request = decode_prepared_nfse(entry.content, scope=scope)
                else:
                    continue
            except (ValueError, TypeError, FiscalValidationError) as exc:
                raise PersistenceStateError("invalid archived prepared request") from exc
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                attempts
                and attempts[-1].document_id == document_id
                and attempts[-1].request_fingerprint == request.request_fingerprint
            ):
                matches.append(request)
        if len(matches) != 1:
            raise PersistenceStateError("one current prepared request is required")
        return matches[0]

    def authorize_prepared_document(
        self,
        *,
        document_id: str,
        request: AuthorizationRequest | NfseAuthorizationRequest,
        gateway: FiscalGatewayClient | NfseGatewayClient,
        occurred_at: datetime,
    ) -> DurableAuthorizationOutcome:
        """Claim one prepared attempt durably, then call the validated gateway once.

        Preparation/numbering/signing must already have persisted READY_TO_TRANSMIT.
        A timeout, incompatible response, crash or failed final commit leaves the
        claim TRANSMITTING: subsequent calls require reconciliation, never resend.
        External I/O runs outside the database transaction.
        """
        if isinstance(request, AuthorizationRequest):
            if not isinstance(gateway, FiscalGatewayClient):
                raise FiscalValidationError("XML authorization requires FiscalGatewayClient")
            scope = request.scope
        elif isinstance(request, NfseAuthorizationRequest):
            if not isinstance(gateway, NfseGatewayClient):
                raise FiscalValidationError("NFS-e authorization requires NfseGatewayClient")
            if document_id != request.document.document_id:
                raise FiscalValidationError("NFS-e document identity does not match")
            scope = request.document.scope
        else:
            raise FiscalValidationError("a validated authorization request is required")

        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if not attempts:
                raise PersistenceStateError("durable issuance reservation is required")
            attempt = attempts[-1]
            if (
                attempt.document_id != document_id
                or attempt.request_fingerprint != request.request_fingerprint
            ):
                raise PersistenceStateError("authorization does not match durable issuance")
            current = uow.lifecycle.get(document_id)
            if current is None:
                raise PersistenceStateError("fiscal lifecycle does not exist")
            if attempt.status is not IssuanceAttemptStatus.RESERVED:
                return DurableAuthorizationOutcome(attempt, current, True, False)
            if current.state is FiscalDocumentState.TRANSMITTING:
                return DurableAuthorizationOutcome(attempt, current, True, True)
            if current.state is not FiscalDocumentState.READY_TO_TRANSMIT:
                raise PersistenceStateError("issuance is not ready to transmit")
            transmitting = self._state_machine.transition(
                current,
                FiscalDocumentState.TRANSMITTING,
                occurred_at=occurred_at,
                reason="durable provider dispatch claim",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(transmitting, expected_version=current.version)
            uow.commit()

        if isinstance(request, AuthorizationRequest) and isinstance(gateway, FiscalGatewayClient):
            result: AuthorizationResult | NfseAuthorizationResult = gateway.authorize(request)
        else:
            assert isinstance(request, NfseAuthorizationRequest)
            assert isinstance(gateway, NfseGatewayClient)
            result = gateway.authorize(request)
        if result.status is AuthorizationStatus.AUTHORIZED:
            reference = (
                result.protocol_reference
                if isinstance(result, AuthorizationResult)
                else result.invoice_reference
            )
            assert reference is not None  # Validated by the canonical gateway boundary.
            xml_evidence = (
                FiscalArchiveEntry.build(
                    scope=scope, document_reference=document_id,
                    kind=FiscalArchiveKind.AUTHORIZED_XML,
                    content=result.authorized_xml, media_type="application/xml",
                    archived_at=occurred_at,
                    retention=RetentionPolicyMetadata(
                        policy_id="nfcore-fiscal-archive", policy_version=1
                    ),
                )
                if result.authorized_xml is not None else None
            )
            self.finalize_authorized(
                archive_entry=xml_evidence,
                key=attempt.key,
                generation=attempt.generation,
                document_id=document_id,
                result_reference=reference,
                occurred_at=occurred_at,
                reason="provider authorization confirmed",
                correlation_id=scope.correlation_id,
            )
        elif result.status is AuthorizationStatus.REJECTED:
            assert result.rejection_code is not None
            self.finalize_rejected(
                key=attempt.key,
                generation=attempt.generation,
                document_id=document_id,
                rejection_reason=result.rejection_code,
                occurred_at=occurred_at,
                correlation_id=scope.correlation_id,
            )
        with self._uow_factory() as uow:
            latest = uow.idempotency.attempts(attempt.key)[-1]
            lifecycle = uow.lifecycle.get(document_id)
            assert lifecycle is not None
            return DurableAuthorizationOutcome(
                latest,
                lifecycle,
                False,
                latest.status is IssuanceAttemptStatus.RESERVED,
                result,
            )

    def reconcile_prepared_authorization(
        self,
        *,
        scope: ExecutionScope,
        document_id: str,
        client: FiscalOperationsClient,
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
    ) -> DurableRecoveryOutcome:
        """Recover an uncertain XML authorization from a validated provider query.

        A missing/pending/cancelled result cannot authorize, reject or resend.
        The normalized query evidence and confirmed authorization commit together.
        """
        if not isinstance(client, FiscalOperationsClient):
            raise FiscalValidationError("recovery requires FiscalOperationsClient")
        request = self.load_prepared_authorization(scope, document_id)
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            attempt = uow.idempotency.attempts(request.idempotency_key)[-1]
            if (
                attempt.document_id != document_id
                or attempt.request_fingerprint != request.request_fingerprint
            ):
                raise PersistenceConflictError("prepared issuance changed before provider query")
            current = uow.lifecycle.get(document_id)
            if current is None:
                raise PersistenceStateError("fiscal lifecycle does not exist")
            if attempt.status is not IssuanceAttemptStatus.RESERVED:
                return DurableRecoveryOutcome(attempt, current, True, False)
            if current.state is not FiscalDocumentState.TRANSMITTING:
                raise PersistenceStateError("recovery requires an uncertain transmission")

        result = client.query(FiscalQueryRequest(scope=scope, access_key=request.access_key))
        evidence = FiscalArchiveEntry.build(
            scope=scope,
            document_reference=document_id,
            kind=FiscalArchiveKind.PROVIDER_RESPONSE,
            content=json.dumps(
                {
                    "operation": "authorization_recovery_query",
                    "access_key": result.access_key.value,
                    "status": result.status.value,
                    "protocol_reference": result.protocol_reference,
                    "provider_request_id": result.provider_request_id,
                    "provider_name": result.provider.provider_name,
                    "adapter_version": result.provider.adapter_version,
                    "observed_at": occurred_at.isoformat(),
                    "idempotency_key": attempt.key.value,
                    "generation": attempt.generation,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            media_type="application/vnd.nfcore.authorization-recovery.v1+json",
            archived_at=occurred_at,
            retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.idempotency.attempts(attempt.key)[-1]
            current = uow.lifecycle.get(document_id)
            if (
                current is None
                or latest.document_id != document_id
                or latest.generation != attempt.generation
                or latest.request_fingerprint != attempt.request_fingerprint
            ):
                raise PersistenceConflictError("issuance changed during provider query")
            if latest.status is not IssuanceAttemptStatus.RESERVED:
                if result.status is FiscalQueryStatus.AUTHORIZED and (
                    latest.status is not IssuanceAttemptStatus.AUTHORIZED
                    or latest.result_reference != result.protocol_reference
                ):
                    raise PersistenceConflictError(
                        "provider query conflicts with terminal issuance"
                    )
                return DurableRecoveryOutcome(latest, current, True, False, result)
            if current.state is not FiscalDocumentState.TRANSMITTING:
                raise PersistenceConflictError("transmission changed during provider query")
            if result.status is FiscalQueryStatus.AUTHORIZED:
                assert result.protocol_reference is not None
                updated = self._state_machine.transition(
                    current,
                    FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at,
                    reason="provider query confirmed authorization",
                    correlation_id=scope.correlation_id,
                )
                latest = uow.idempotency.mark_authorized(
                    attempt.key, attempt.generation, result.protocol_reference
                )
                uow.lifecycle.save(updated, expected_version=current.version)
                current = updated
            uow.archive.append(evidence)
            uow.commit()
            return DurableRecoveryOutcome(
                latest,
                current,
                False,
                latest.status is IssuanceAttemptStatus.RESERVED,
                result,
            )

    def reconcile_prepared_nfse_authorization(
        self,
        *,
        scope: ExecutionScope,
        document_id: str,
        client: NfseQueryClient,
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
    ) -> DurableNfseRecoveryOutcome:
        """Recover uncertain NFS-e state through a validated read-only query."""
        if not isinstance(client, NfseQueryClient):
            raise FiscalValidationError("NFS-e recovery requires NfseQueryClient")
        request = self.load_prepared_nfse_authorization(scope, document_id)
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if not attempts:
                raise PersistenceStateError("durable NFS-e issuance is required")
            attempt = attempts[-1]
            current = uow.lifecycle.get(document_id)
            if (
                current is None
                or attempt.document_id != document_id
                or attempt.request_fingerprint != request.request_fingerprint
            ):
                raise PersistenceConflictError("prepared NFS-e changed before provider query")
            if attempt.status is not IssuanceAttemptStatus.RESERVED:
                return DurableNfseRecoveryOutcome(attempt, current, True, False)
            if current.state is not FiscalDocumentState.TRANSMITTING:
                raise PersistenceStateError("NFS-e recovery requires an uncertain transmission")

        result = client.query(request)
        evidence = FiscalArchiveEntry.build(
            scope=scope,
            document_reference=document_id,
            kind=FiscalArchiveKind.PROVIDER_RESPONSE,
            content=json.dumps(
                {
                    "operation": "nfse_authorization_recovery_query",
                    "status": result.status.value,
                    "invoice_reference": result.invoice_reference,
                    "verification_code": result.verification_code,
                    "rejection_code": result.rejection_code,
                    "provider_request_id": result.provider_request_id,
                    "provider_name": result.provider.provider_name,
                    "adapter_version": result.provider.adapter_version,
                    "observed_at": occurred_at.isoformat(),
                    "idempotency_key": attempt.key.value,
                    "generation": attempt.generation,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            media_type="application/vnd.nfcore.nfse-recovery.v1+json",
            archived_at=occurred_at,
            retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.idempotency.attempts(attempt.key)[-1]
            current = uow.lifecycle.get(document_id)
            if (
                current is None
                or latest.document_id != document_id
                or latest.generation != attempt.generation
                or latest.request_fingerprint != attempt.request_fingerprint
            ):
                raise PersistenceConflictError("NFS-e issuance changed during provider query")
            if latest.status is not IssuanceAttemptStatus.RESERVED:
                terminal_reference = result.invoice_reference
                if result.status is AuthorizationStatus.AUTHORIZED and (
                    latest.status is not IssuanceAttemptStatus.AUTHORIZED
                    or latest.result_reference != terminal_reference
                ):
                    raise PersistenceConflictError(
                        "NFS-e provider query conflicts with terminal issuance"
                    )
                if result.status is AuthorizationStatus.REJECTED and (
                    latest.status is not IssuanceAttemptStatus.REJECTED
                    or latest.rejection_reason != result.rejection_code
                ):
                    raise PersistenceConflictError(
                        "NFS-e provider query conflicts with terminal rejection"
                    )
                return DurableNfseRecoveryOutcome(latest, current, True, False, result)
            if current.state is not FiscalDocumentState.TRANSMITTING:
                raise PersistenceConflictError("NFS-e transmission changed during provider query")
            if result.status is AuthorizationStatus.AUTHORIZED:
                assert result.invoice_reference is not None
                if result.authorized_xml is not None:
                    uow.archive.append(FiscalArchiveEntry.build(
                        scope=scope, document_reference=document_id,
                        kind=FiscalArchiveKind.AUTHORIZED_XML,
                        content=result.authorized_xml, media_type="application/xml",
                        archived_at=occurred_at, retention=retention,
                    ))
                updated = self._state_machine.transition(
                    current,
                    FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at,
                    reason="NFS-e provider query confirmed authorization",
                    correlation_id=scope.correlation_id,
                )
                latest = uow.idempotency.mark_authorized(
                    attempt.key, attempt.generation, result.invoice_reference
                )
                uow.lifecycle.save(updated, expected_version=current.version)
                current = updated
            elif result.status is AuthorizationStatus.REJECTED:
                assert result.rejection_code is not None
                updated = self._state_machine.transition(
                    current,
                    FiscalDocumentState.REJECTED,
                    occurred_at=occurred_at,
                    reason=result.rejection_code,
                    correlation_id=scope.correlation_id,
                )
                latest = uow.idempotency.mark_rejected(
                    attempt.key, attempt.generation, result.rejection_code
                )
                uow.lifecycle.save(updated, expected_version=current.version)
                current = updated
            uow.archive.append(evidence)
            uow.commit()
            return DurableNfseRecoveryOutcome(
                latest,
                current,
                False,
                latest.status is IssuanceAttemptStatus.RESERVED,
                result,
            )

    @staticmethod
    def _validate_cancellation_from_uow(
        uow: FiscalUnitOfWork, document_id: str, request: CancellationRequest
    ) -> FiscalStateSnapshot:
        prepared = FiscalApplicationService._load_prepared_from_uow(
            uow, request.scope, document_id
        )
        if (
            not isinstance(prepared, AuthorizationRequest)
            or prepared.access_key != request.access_key
        ):
            raise FiscalValidationError("cancellation key does not match the prepared document")
        attempts = uow.idempotency.attempts(prepared.idempotency_key)
        if (
            not attempts or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
            or attempts[-1].result_reference != request.authorization_protocol
        ):
            raise FiscalValidationError("cancellation protocol does not match authorization")
        lifecycle = uow.lifecycle.get(document_id)
        if lifecycle is None or lifecycle.state is not FiscalDocumentState.AUTHORIZED:
            raise FiscalValidationError("document is not available for a new cancellation")
        return lifecycle

    def validate_prepared_cancellation(
        self, document_id: str, request: CancellationRequest
    ) -> None:
        with self._uow_factory() as uow:
            self._validate_cancellation_from_uow(uow, document_id, request)

    def cancel_prepared_document(
        self, *, document_id: str, request: CancellationRequest,
        client: FiscalOperationsClient, archive_retention: RetentionPolicyMetadata,
        occurred_at: datetime,
    ) -> DurableCancellationOutcome:
        """Persist a claim before I/O, then atomically save evidence and lifecycle.

        Timeout/crash leaves CANCEL_REQUESTED; it never authorizes another dispatch.
        Portal receipt replay is handled by its existing durable claim authority.
        """
        if (
            not isinstance(request, CancellationRequest)
            or not isinstance(client, FiscalOperationsClient)
            or not isinstance(archive_retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError(
                "cancellation requires a valid request, client and retention"
            )
        cancellation = FiscalCancellationService(client, self._state_machine)
        with self._uow_factory() as uow:
            current = self._validate_cancellation_from_uow(uow, document_id, request)
            requested = cancellation.prepare(
                lifecycle=current, occurred_at=occurred_at,
                correlation_id=request.scope.correlation_id,
            )
            uow.lifecycle.save(requested, expected_version=current.version)
            uow.commit()

        result = client.cancel(request)
        evidence = build_event_result_evidence(
            result, archived_at=occurred_at, retention=archive_retention
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, request.scope)
            latest = uow.lifecycle.get(document_id)
            if latest != requested:
                raise PersistenceConflictError("cancellation lifecycle changed during provider I/O")
            outcome = cancellation.complete(
                requested=requested, result=result, occurred_at=occurred_at,
                correlation_id=request.scope.correlation_id,
            )
            archived = uow.archive.append(evidence)
            if outcome.lifecycle != requested:
                uow.lifecycle.save(outcome.lifecycle, expected_version=requested.version)
            uow.commit()
        return DurableCancellationOutcome(result, outcome.lifecycle, archived.entry_id)

    def preflight_extrema_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
    ) -> None:
        """Read-only check, before committing the portal fiscal intent."""
        request = self.load_prepared_nfse_authorization(scope, document_id)
        self.load_extrema_rps_intent(scope, document_id)
        if (
            request.document.issuer.address.jurisdiction.municipality_ibge_code
            != "3125101"
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
        ):
            raise FiscalValidationError("Extrema cancellation is not configured for this scope")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current is None or current.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceStateError("Original NFS-e must have confirmed authorization")
            items = [
                x for x in uow.archive.list_for_document(scope, document_id)
                if x.kind is FiscalArchiveKind.AUTHORIZED_XML
                and x.media_type == "application/xml"
            ]
            if len(items) != 1:
                raise PersistenceStateError("Original authorized municipal XML is missing")
            FiscalArchiveVerifier().verify_entry(items[0])

    def preflight_extrema_nfse_substitution(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
    ) -> None:
        """Verify original authorization and replacement readiness without mutations."""
        if original_id == replacement_id:
            raise FiscalValidationError("Substitution requires two different fiscal documents")
        original = self.load_prepared_nfse_authorization(scope, original_id)
        replacement = self.load_prepared_nfse_authorization(scope, replacement_id)
        self.load_extrema_rps_intent(scope, original_id)
        self.load_extrema_rps_intent(scope, replacement_id)
        if (
            original.document.issuer.cnpj != replacement.document.issuer.cnpj
            or original.document.issuer.address.jurisdiction
            != replacement.document.issuer.address.jurisdiction
            or original.document.issuer.address.jurisdiction.municipality_ibge_code
            != "3125101"
        ):
            raise FiscalValidationError("Substitution must preserve issuer and municipality")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            previous = uow.lifecycle.get(original_id)
            fresh = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                previous is None
                or previous.state is not FiscalDocumentState.AUTHORIZED
                or fresh is None
                or fresh.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or len(attempts) != 1
                or attempts[0].document_id != replacement_id
                or attempts[0].request_fingerprint != replacement.request_fingerprint
                or attempts[0].status is not IssuanceAttemptStatus.RESERVED
            ):
                raise PersistenceStateError(
                    "Substitution requires authorized original and untransmitted replacement"
                )
            entries = [
                x for x in uow.archive.list_for_document(scope, original_id)
                if x.kind is FiscalArchiveKind.AUTHORIZED_XML
                and x.media_type == "application/xml"
            ]
            if len(entries) != 1:
                raise PersistenceStateError("Original authorized XML required for substitution")
            FiscalArchiveVerifier().verify_entry(entries[0])

    def substitute_prepared_extrema_nfse(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
        cancellation_code: str, gateway: WebissExtremaCanonicalNfseGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableExtremaSubstitutionOutcome:
        """Commit two lifecycle claims before ONE atomic provider substitution POST.

        A delivery timeout leaves old CANCEL_REQUESTED and new TRANSMITTING;
        never issue a second replacement automatically. Local finalization
        commits BOTH documents and original provider evidence atomically.
        """
        if (
            not isinstance(gateway, WebissExtremaCanonicalNfseGateway)
            or not isinstance(scope, ExecutionScope)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
        ):
            raise FiscalValidationError("Invalid WebISS substitution dependencies")
        self.preflight_extrema_nfse_substitution(
            scope=scope, original_id=original_id, replacement_id=replacement_id,
        )
        original = self.load_prepared_nfse_authorization(scope, original_id)
        replacement = self.load_prepared_nfse_authorization(scope, replacement_id)
        with self._uow_factory() as uow:
            matches = [
                x.content for x in uow.archive.list_for_document(scope, original_id)
                if x.kind is FiscalArchiveKind.AUTHORIZED_XML
                and x.media_type == "application/xml"
            ]
            if len(matches) != 1:
                raise PersistenceStateError("Original replacement XML changed")
            authorized_xml = matches[0]
        signed, original_number = gateway.prepare_substitution(
            original=original, replacement=replacement, original_xml=authorized_xml,
            cancellation_code=cancellation_code,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            before_original = uow.lifecycle.get(original_id)
            before_replacement = uow.lifecycle.get(replacement_id)
            if (
                before_original is None
                or before_original.state is not FiscalDocumentState.AUTHORIZED
                or before_replacement is None
                or before_replacement.state is not FiscalDocumentState.READY_TO_TRANSMIT
            ):
                raise PersistenceConflictError("Concurrent WebISS replacement request")
            claim_old = self._state_machine.transition(
                before_original, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="official Extrema substitution claim",
                correlation_id=scope.correlation_id,
            )
            claim_new = self._state_machine.transition(
                before_replacement, FiscalDocumentState.TRANSMITTING,
                occurred_at=occurred_at, reason="official Extrema replacement claim",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim_old, expected_version=before_original.version)
            uow.lifecycle.save(claim_new, expected_version=before_replacement.version)
            uow.commit()

        result = gateway.submit_substitution(
            original=original, replacement=replacement, envelope=signed,
            original_number=original_number,
        )
        event = FiscalArchiveEntry.build(
            scope=scope, document_reference=original_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=result.xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            old = uow.lifecycle.get(original_id)
            new = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                old != claim_old or new != claim_new
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.RESERVED
                or attempts[0].document_id != replacement_id
                or attempts[0].request_fingerprint != replacement.request_fingerprint
            ):
                raise PersistenceConflictError("Concurrent fiscal update after substitution")
            final_old = self._state_machine.transition(
                old,
                FiscalDocumentState.CANCELLED
                if result.confirmed else FiscalDocumentState.AUTHORIZED,
                occurred_at=occurred_at,
                reason="WebISS substitution accepted"
                if result.confirmed else "WebISS substitution rejected",
                correlation_id=scope.correlation_id,
            )
            final_new = self._state_machine.transition(
                new,
                FiscalDocumentState.AUTHORIZED
                if result.confirmed else FiscalDocumentState.REJECTED,
                occurred_at=occurred_at,
                reason="WebISS replacement authorized"
                if result.confirmed else "WebISS replacement rejected",
                correlation_id=scope.correlation_id,
            )
            if result.confirmed:
                assert result.invoice_reference is not None
                uow.idempotency.mark_authorized(
                    replacement.idempotency_key,
                    attempts[0].generation, result.invoice_reference,
                )
                uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=replacement_id,
                    kind=FiscalArchiveKind.AUTHORIZED_XML,
                    content=result.xml, media_type="application/xml",
                    archived_at=occurred_at, retention=retention,
                ))
            else:
                assert result.rejection_code is not None
                uow.idempotency.mark_rejected(
                    replacement.idempotency_key,
                    attempts[0].generation, result.rejection_code,
                )
            uow.lifecycle.save(final_old, expected_version=old.version)
            uow.lifecycle.save(final_new, expected_version=new.version)
            archived = uow.archive.append(event)
            uow.commit()
        return DurableExtremaSubstitutionOutcome(
            result=result, original_lifecycle=final_old,
            replacement_lifecycle=final_new,
            archive_reference=archived.entry_id,
        )

    def cancel_prepared_extrema_nfse(
        self, *, scope: ExecutionScope, document_id: str, cancellation_code: str,
        gateway: WebissExtremaCanonicalNfseGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableExtremaCancellationOutcome:
        """Cancel an authorized Extrema NFS-e exactly once; never blindly resend.

        Validate the archived official XML, sign from the original issuer,
        commit CANCEL_REQUESTED before SOAP I/O, then atomically archive
        the official answer and final lifecycle. An ambiguous POST remains
        CANCEL_REQUESTED and must be consulted; no automatic retry is allowed.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or not isinstance(gateway, WebissExtremaCanonicalNfseGateway)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
        ):
            raise FiscalValidationError("Invalid scoped Extrema cancellation dependencies")
        request = self.load_prepared_nfse_authorization(scope, document_id)
        self.load_extrema_rps_intent(scope, document_id)
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            lifecycle = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                lifecycle is None
                or lifecycle.state is not FiscalDocumentState.AUTHORIZED
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[0].document_id != document_id
                or attempts[0].request_fingerprint != request.request_fingerprint
            ):
                raise PersistenceStateError(
                    "Extrema cancellation requires one original authorized fiscal document"
                )
            snapshots = [
                entry for entry in uow.archive.list_for_document(scope, document_id)
                if entry.kind is FiscalArchiveKind.AUTHORIZED_XML
                and entry.media_type == "application/xml"
            ]
            if len(snapshots) != 1:
                raise PersistenceStateError("Original municipal XML evidence is unavailable")
            FiscalArchiveVerifier().verify_entry(snapshots[0])
            original_xml = snapshots[0].content

        envelope, original_number = gateway.prepare_cancellation(
            request=request, authorized_xml=original_xml,
            cancellation_code=cancellation_code,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current is None or current.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Extrema cancellation was already requested")
            claim = self._state_machine.transition(
                current, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="official Extrema cancellation claim",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=current.version)
            uow.commit()

        # No automatic retry. Any network/parse error leaves CANCEL_REQUESTED.
        result = gateway.submit_cancellation(
            request=request, envelope=envelope, original_number=original_number,
        )
        archive_entry = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=result.xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current is None or current != claim:
                raise PersistenceConflictError("Extrema cancellation changed during delivery")
            target = (
                FiscalDocumentState.CANCELLED if result.confirmed
                else FiscalDocumentState.AUTHORIZED
            )
            final = self._state_machine.transition(
                current, target, occurred_at=occurred_at,
                reason=(
                    "municipal cancellation confirmed" if result.confirmed
                    else "municipal cancellation rejected"
                ),
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=current.version)
            archived = uow.archive.append(archive_entry)
            uow.commit()
        return DurableExtremaCancellationOutcome(
            result=result, lifecycle=final, archive_reference=archived.entry_id,
        )

    def reserve_number(
        self,
        key: FiscalSequenceKey,
        policy: FiscalSequencePolicy | None = None,
    ) -> FiscalNumberReservation:
        with self._uow_factory() as uow:
            reservation = uow.sequences.reserve_next(key, policy or FiscalSequencePolicy())
            uow.commit()
            return reservation

    def enqueue_outbox(self, entry: FiscalOutboxEntry) -> FiscalOutboxEnqueueResult:
        with self._uow_factory() as uow:
            result = uow.outbox.enqueue(entry)
            uow.commit()
            return result

    def archive(self, entry: FiscalArchiveEntry) -> FiscalArchiveEntry:
        with self._uow_factory() as uow:
            result = uow.archive.append(entry)
            uow.commit()
            return result

    def reconcile_operation(
        self,
        operation: FiscalOperationSnapshot,
        candidates: tuple[FiscalReconciliationCandidate, ...],
    ) -> FiscalReconciliationResult:
        result = self._reconciliation.reconcile_operation(operation, candidates)
        with self._uow_factory() as uow:
            uow.reconciliations.save(result)
            uow.commit()
        if self._metrics is not None:
            try:
                self._metrics.increment(
                    "nfcore_fiscal_reconciliation_total", outcome=result.status.value
                )
            except Exception:
                # Metrics must never invalidate already committed fiscal state.
                pass
        return result

    def get_reconciliation(
        self,
        scope: ExecutionScope,
        source: SourceReference,
    ) -> FiscalReconciliationResult | None:
        with self._uow_factory() as uow:
            return uow.reconciliations.get(scope, source)
