"""Universal application service over pure domain rules and durable repositories."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from lxml import etree

from kordena_fiscal.application.cajamar_substitution_review import (
    CajamarSubstitutionReview,
    review_cajamar_substitution,
)
from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    FiscalArchiveVerifier,
    RetentionPolicyMetadata,
)
from kordena_fiscal.compliance.cajamar_municipal_legal import (
    validate_cajamar_automatic_cancellation,
)
from kordena_fiscal.compliance.osasco_municipal_legal import (
    validate_osasco_automatic_cancellation,
    validate_osasco_substitution_references,
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
    TaxRegimeCode,
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
from kordena_fiscal.gateway.barueri_official_cancel_return import (
    BarueriCancellationEvidence,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarCancellationDecision,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CAJAMAR_GEISWEB_PROVIDER
from kordena_fiscal.gateway.cajamar_geisweb_invoice_interpreter import (
    decode_cajamar_archived_invoice,
)
from kordena_fiscal.gateway.jundiai_giss_cancellation_result import (
    JundiaiGissCancellationDecision,
)
from kordena_fiscal.gateway.jundiai_giss_invoice_interpreter import (
    decode_jundiai_archived_invoice,
)
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationIntent,
    NationalNfseCancellationReceipt,
    validate_national_event_xml,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.nfse_national_query import _verify_nfse_receipt_signature
from kordena_fiscal.gateway.osasco_rtc_cancellation_builder import (
    OsascoCancellationDecision,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import OSASCO_RTC_PROVIDER_ID
from kordena_fiscal.gateway.osasco_rtc_invoice_interpreter import (
    decode_osasco_archived_full_invoice,
)
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SANTANA_PROVIDER_ID,
    SantanaSimplissHomologationGateway,
)
from kordena_fiscal.gateway.santana_simpliss_substitution import SantanaSubstitutionReview
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
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
    build_nfse_request_fingerprint,
)
from kordena_fiscal.issuance.nfse_archive import (
    NFSE_PREPARED_MEDIA_TYPE,
    decode_prepared_nfse,
    encode_prepared_nfse,
)
from kordena_fiscal.issuance.sp4_original_rps_archive import (
    SP4_ORIGINAL_RPS_MEDIA_TYPE,
    decode_sp4_original,
    encode_sp4_original,
    validate_sp4_original,
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


@dataclass(frozen=True, slots=True)
class DurableSantanaCancellationOutcome:
    lifecycle: FiscalStateSnapshot
    archive_reference: str


@dataclass(frozen=True, slots=True)
class DurableSantanaSubstitutionOutcome:
    original_lifecycle: FiscalStateSnapshot
    replacement_lifecycle: FiscalStateSnapshot
    provider_result: NfseAuthorizationResult
    archive_reference: str | None
    recovery_required: bool


@dataclass(frozen=True, slots=True)
class DurableSantanaRecoveryOutcome:
    original_lifecycle: FiscalStateSnapshot
    replacement_lifecycle: FiscalStateSnapshot | None
    archive_reference: str | None
    recovered: bool
    recovery_required: bool


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


@dataclass(frozen=True, slots=True)
class DurableCajamarCancellationOutcome:
    """Municipal cancellation result archived with its fiscal state transaction."""

    decision: CajamarCancellationDecision
    lifecycle: FiscalStateSnapshot
    archive_reference: str


@dataclass(frozen=True, slots=True)
class DurableOsascoCancellationOutcome:
    """One verified WCF cancellation response and its durable fiscal lifecycle."""

    decision: OsascoCancellationDecision
    lifecycle: FiscalStateSnapshot
    archive_reference: str


@dataclass(frozen=True, slots=True)
class DurableJundiaiCancellationOutcome:
    """One canonical UoW archived Giss cancellation with scoped lifecycle."""

    decision: JundiaiGissCancellationDecision
    lifecycle: FiscalStateSnapshot
    archive_reference: str | None


@dataclass(frozen=True, slots=True)
class DurableBarueriCancellationOutcome:
    """Asynchronous municipal event with a single original dispatch claim."""

    lifecycle: FiscalStateSnapshot
    archive_reference: str | None
    protocol: str | None
    recovery_required: bool
    replay: bool


def _nfse_rejection_archive(
    result: NfseAuthorizationResult,
    *,
    scope: ExecutionScope,
    document_id: str,
    occurred_at: datetime,
    retention: RetentionPolicyMetadata,
) -> FiscalArchiveEntry:
    """Keep complete typed rejection evidence in tenant-scoped fiscal archive.

    Raw provider messages never become HTTP/Portal status strings or logs.
    No truncation is allowed; over-limit payloads fail at the model boundary.
    """
    if result.status is not AuthorizationStatus.REJECTED:
        raise FiscalValidationError("Only rejected NFS-e can have rejection evidence")
    content = json.dumps(
        {
            "status": result.status.value,
            "provider_name": result.provider.provider_name,
            "provider_request_id": result.provider_request_id,
            "rejections": [
                {
                    "code": item.code,
                    "origin": item.origin,
                    "raw_message": item.raw_message,
                }
                for item in result.normalized_rejections()
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return FiscalArchiveEntry.build(
        scope=scope,
        document_reference=document_id,
        kind=FiscalArchiveKind.PROVIDER_RESPONSE,
        content=content,
        media_type="application/vnd.nfcore.nfse-rejection.v1+json",
        archived_at=occurred_at,
        retention=retention,
    )


def _cajamar_policy_now() -> datetime:
    """Canonical trusted server clock; injectable only in offline tests."""
    from datetime import UTC

    return datetime.now(UTC)


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

    def _complete_national_replacement_in_uow(
        self, *, uow: FiscalUnitOfWork,
        prepared: NfseAuthorizationRequest,
        authorized: bool, occurred_at: datetime,
        retention: RetentionPolicyMetadata,
    ) -> None:
        """Reconcile original state atomically with the replacement's terminal state."""
        linked = prepared.document.national_substitution
        if linked is None:
            return
        original_id = linked.original_document_id
        scope = prepared.document.scope
        uow.lifecycle.assert_scope(original_id, scope)
        state = uow.lifecycle.get(original_id)
        records = [
            item for item in uow.archive.list_for_document(scope, original_id)
            if item.kind is FiscalArchiveKind.OTHER
            and item.media_type == "application/vnd.nfcore.national-substitution-intent.v1+json"
        ]
        if (
            state is None or state.state is not FiscalDocumentState.CANCEL_REQUESTED
            or len(records) != 1
        ):
            raise PersistenceConflictError("National original substitution claim changed")
        FiscalArchiveVerifier().verify_entry(records[0])
        original = json.loads(records[0].content)
        if (
            original.get("replacement_id") != prepared.document.document_id
            or original.get("old_key") != linked.original_invoice_reference
            or original.get("approval_reference") != linked.approval_reference
            or original.get("fingerprint") != prepared.request_fingerprint
        ):
            raise PersistenceConflictError("National original substitution evidence mismatch")
        target = (
            FiscalDocumentState.CANCELLED if authorized
            else FiscalDocumentState.AUTHORIZED
        )
        updated = self._state_machine.transition(
            state, target, occurred_at=occurred_at,
            reason=(
                "National official replacement DPS authorized"
                if authorized else "National replacement DPS rejected"
            ),
            correlation_id=scope.correlation_id,
        )
        uow.lifecycle.save(updated, expected_version=state.version)
        uow.archive.append(FiscalArchiveEntry.build(
            scope=scope, document_reference=original_id,
            kind=FiscalArchiveKind.OTHER,
            content=json.dumps({
                "operation": "national_substitution_resolution",
                "original_id": original_id,
                "replacement_id": prepared.document.document_id,
                "original_key": linked.original_invoice_reference,
                "result": "authorized" if authorized else "rejected",
            }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            media_type="application/vnd.nfcore.national-substitution-resolution.v1+json",
            archived_at=occurred_at, retention=retention,
        ))

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
            if archive_entry is not None:
                prepared = self._load_prepared_from_uow(
                    uow, archive_entry.scope, document_id,
                )
                if (
                    isinstance(prepared, NfseAuthorizationRequest)
                    and prepared.document.national_substitution is not None
                ):
                    self._complete_national_replacement_in_uow(
                        uow=uow, prepared=prepared, authorized=True,
                        occurred_at=occurred_at,
                        retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
                    )
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
        archive_entry: FiscalArchiveEntry | None = None,
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
            if archive_entry is not None:
                uow.lifecycle.assert_scope(document_id, archive_entry.scope)
                if archive_entry.document_reference != document_id:
                    raise PersistenceConflictError("Rejection archive document does not match")
                uow.archive.append(archive_entry)
            if archive_entry is not None:
                prepared = self._load_prepared_from_uow(
                    uow, archive_entry.scope, document_id,
                )
                if (
                    isinstance(prepared, NfseAuthorizationRequest)
                    and prepared.document.national_substitution is not None
                ):
                    self._complete_national_replacement_in_uow(
                        uow=uow, prepared=prepared, authorized=False,
                        occurred_at=occurred_at,
                        retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
                    )
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
        sp4_original_builder: Callable[
            [NfseAuthorizationRequest, FiscalNumberReservation], Sp4OriginalRps
        ] | None = None,
        sp4_rps_series: int | None = None,
    ) -> DurablePreparedAuthorization:
        """Atomically reserve, validate and archive one provider-neutral NFS-e request."""
        if not isinstance(document, NfseCanonicalDocument):
            raise FiscalValidationError("document must be NfseCanonicalDocument")
        if not isinstance(retention, RetentionPolicyMetadata):
            raise FiscalValidationError("retention must be RetentionPolicyMetadata")
        if document.dps_number is not None:
            raise FiscalValidationError(
                "DPS serial is assigned exclusively by the durable fiscal application"
            )
        if (extrema_intent_builder is None) != (extrema_rps_series is None):
            raise FiscalValidationError(
                "WebISS intent builder and RPS numbering series must be supplied together"
            )
        if extrema_intent_builder is not None and not callable(extrema_intent_builder):
            raise FiscalValidationError("WebISS RPS builder must be trusted and callable")
        if (sp4_original_builder is None) != (sp4_rps_series is None):
            raise FiscalValidationError(
                "SP4 original RPS builder and numbering series must be supplied together"
            )
        if sp4_original_builder is not None:
            if not callable(sp4_original_builder) or extrema_intent_builder is not None:
                raise FiscalValidationError("Municipal fiscal RPS modes are exclusive")
            if (
                type(sp4_rps_series) is not int
                or not 1 <= sp4_rps_series <= 99_999
                or document.scope.environment is not FiscalEnvironment.HOMOLOGATION
                or not document.scope.host_namespace
                or document.issuer.address.jurisdiction.state_code != "SP"
                or document.issuer.address.jurisdiction.municipality_ibge_code
                not in SP4_MUNICIPAL_PROVIDERS.values()
            ):
                raise FiscalValidationError(
                    "SP4 municipal original RPS requires reviewed scope and series"
                )
        with self._uow_factory() as uow:
            if document.national_substitution is not None:
                if extrema_intent_builder is not None or sp4_original_builder is not None:
                    raise FiscalValidationError("National replacement cannot use municipal RPS")
                linked = document.national_substitution
                if uow.lifecycle.get(document.document_id) is None:
                    old = self._load_prepared_from_uow(
                        uow, document.scope, linked.original_document_id,
                    )
                    old_state = uow.lifecycle.get(linked.original_document_id)
                    old_attempts = uow.idempotency.attempts(old.idempotency_key)
                    if (
                        not isinstance(old, NfseAuthorizationRequest)
                        or old_state is None
                        or old_state.state is not FiscalDocumentState.AUTHORIZED
                        or len(old_attempts) != 1
                        or old_attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                        or old_attempts[0].result_reference != linked.original_invoice_reference
                        or old.document.issuer.cnpj != document.issuer.cnpj
                        or old.document.issuer.address.jurisdiction
                        != document.issuer.address.jurisdiction
                        or old.document.competence_date != document.competence_date
                        or old.document.service_jurisdiction != document.service_jurisdiction
                    ):
                        raise PersistenceStateError("National original is no longer replaceable")
            if extrema_intent_builder is None and sp4_original_builder is None:
                # The National DPS number and issuance reservation belong to one UoW.
                dps_serial = uow.dps_sequences.reserve(
                    document, input_fingerprint=build_nfse_request_fingerprint(document),
                )
                numbered_document = replace(
                    document, dps_series=dps_serial.series, dps_number=dps_serial.number,
                )
            else:
                # Municipal WebISS owns the RPS sequence; never allocate a DPS as well.
                numbered_document = document
            request = NfseAuthorizationRequest.build(numbered_document)
            entry = FiscalArchiveEntry.build(
                scope=document.scope,
                document_reference=document.document_id,
                kind=FiscalArchiveKind.OTHER,
                content=encode_prepared_nfse(request),
                media_type=NFSE_PREPARED_MEDIA_TYPE,
                archived_at=occurred_at,
                retention=retention,
            )
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
                prior_entries = uow.archive.list_for_document(
                    document.scope, document.document_id,
                )
                prior_intents = [
                    archived for archived in prior_entries
                    if archived.media_type == EXTREMA_INTENT_MEDIA_TYPE
                ]
                prior_originals = [
                    archived for archived in prior_entries
                    if archived.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
                ]
                if (
                    len(prior_intents) > 1
                    or bool(prior_intents) != (extrema_intent_builder is not None)
                    or len(prior_originals) > 1
                    or bool(prior_originals) != (sp4_original_builder is not None)
                ):
                    raise PersistenceConflictError(
                        "Municipal original RPS mode cannot change after reservation"
                    )
                if prior_originals:
                    decode_sp4_original(
                        prior_originals[0].content, scope=document.scope, request=prepared,
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
            elif sp4_original_builder is not None:
                assert sp4_rps_series is not None
                key = FiscalSequenceKey.from_scope(
                    document.scope,
                    model=InternalFiscalSequenceStream.NFSE_RPS,
                    series=sp4_rps_series,
                )
                municipal_ibge = document.issuer.address.jurisdiction.municipality_ibge_code
                max_number = (
                    999_999_999_999_999 if municipal_ibge == "3534401"
                    else 9_999_999 if municipal_ibge == "3505708"
                    else 99_999_999
                )
                reserved_rps = uow.sequences.reserve_next(
                    key, FiscalSequencePolicy(max_number=max_number),
                )
                original_rps = sp4_original_builder(request, reserved_rps)
                validate_sp4_original(request, original_rps, reserved_rps)
                municipal_entry = FiscalArchiveEntry.build(
                    scope=document.scope,
                    document_reference=document.document_id,
                    kind=FiscalArchiveKind.OTHER,
                    content=encode_sp4_original(request, original_rps, reserved_rps),
                    media_type=SP4_ORIGINAL_RPS_MEDIA_TYPE,
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

    def load_sp4_original_rps(
        self, scope: ExecutionScope, document_id: str,
    ) -> Sp4OriginalRps:
        """Recover SP4 original RPS from the same tenant-scoped canonical archive.

        The fiscal application is the sole loader. Transport drivers cannot
        supply alternate identity, lot, CNPJ, or original sequence authority.
        """
        with self._uow_factory() as uow:
            prepared = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(prepared, NfseAuthorizationRequest):
                raise PersistenceStateError("Original RPS requires prepared NFS-e")
            originals = [
                entry for entry in uow.archive.list_for_document(scope, document_id)
                if entry.kind is FiscalArchiveKind.OTHER
                and entry.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            if len(originals) != 1:
                raise PersistenceStateError("Exactly one original RPS archive is required")
            return decode_sp4_original(
                originals[0].content, scope=scope, request=prepared,
            )

    def load_barueri_remittance_protocol(
        self, scope: ExecutionScope, document_id: str,
    ) -> str | None:
        """Recover the municipality-issued protocol from the original durable attempt.

        A provider acknowledgement is not an authorized fiscal note. Only the
        source-bound acknowledgement from the canonical transmission is read.
        """
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if (
                not isinstance(request, NfseAuthorizationRequest)
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3505708"
            ):
                raise PersistenceStateError("Barueri original issuance is required")
            records = [
                entry for entry in uow.archive.list_for_document(scope, document_id)
                if entry.kind is FiscalArchiveKind.PROVIDER_RESPONSE
                and entry.media_type == "application/vnd.nfcore.barueri-remittance.v1+json"
            ]
            if not records:
                return None
            if len(records) != 1:
                raise PersistenceStateError("Ambiguous Barueri remittance acknowledgements")
            try:
                data = json.loads(records[0].content)
                protocol = data["provider_request_id"]
                if (
                    set(data) != {"provider_request_id", "document_id", "fingerprint"}
                    or data["document_id"] != document_id
                    or data["fingerprint"] != request.request_fingerprint
                    or not isinstance(protocol, str)
                    or not 1 <= len(protocol) <= 128
                    or not protocol.isascii()
                    or not protocol.isalnum()
                ):
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                raise PersistenceStateError(
                    "Barueri remittance acknowledgement is altered"
                ) from None
            return protocol

    def load_barueri_submission_date(
        self, scope: ExecutionScope, document_id: str,
    ) -> date | None:
        """Use the persisted first dispatch date to recover an uncertain POST."""
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if (
                not isinstance(request, NfseAuthorizationRequest)
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3505708"
            ):
                raise PersistenceStateError("Barueri original issuance is required")
            snapshot = uow.lifecycle.get(document_id)
            if snapshot is None:
                raise PersistenceStateError("Barueri fiscal lifecycle is absent")
            transmissions = [
                item.occurred_at.astimezone(ZoneInfo("America/Sao_Paulo")).date()
                for item in snapshot.history
                if item.to_state is FiscalDocumentState.TRANSMITTING
            ]
            if len(transmissions) > 1:
                raise PersistenceStateError("Ambiguous Barueri original transmission")
            return transmissions[0] if transmissions else None

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
            if (
                isinstance(request, NfseAuthorizationRequest)
                and request.document.national_substitution is not None
            ):
                linked = request.document.national_substitution
                old_id = linked.original_document_id
                uow.lifecycle.assert_scope(old_id, scope)
                old_request = self._load_prepared_from_uow(uow, scope, old_id)
                old_state = uow.lifecycle.get(old_id)
                old_attempts = uow.idempotency.attempts(old_request.idempotency_key)
                if (
                    not isinstance(old_request, NfseAuthorizationRequest)
                    or old_state is None
                    or old_state.state is not FiscalDocumentState.AUTHORIZED
                    or len(old_attempts) != 1
                    or old_attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                    or old_attempts[0].result_reference != linked.original_invoice_reference
                    or old_request.document.issuer.cnpj != request.document.issuer.cnpj
                ):
                    raise PersistenceStateError("National replacement original not authorized")
                claimed_original = self._state_machine.transition(
                    old_state, FiscalDocumentState.CANCEL_REQUESTED,
                    occurred_at=occurred_at,
                    reason="National original linked to one replacement DPS",
                    correlation_id=scope.correlation_id,
                )
                uow.lifecycle.save(claimed_original, expected_version=old_state.version)
                uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=old_id,
                    kind=FiscalArchiveKind.OTHER,
                    content=json.dumps({
                        "original_id": old_id,
                        "old_key": linked.original_invoice_reference,
                        "replacement_id": document_id,
                        "fingerprint": request.request_fingerprint,
                        "approval_reference": linked.approval_reference,
                        "reason_code": linked.reason_code,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    media_type="application/vnd.nfcore.national-substitution-intent.v1+json",
                    archived_at=occurred_at,
                    retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
                ))
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
            if (
                isinstance(request, NfseAuthorizationRequest)
                and request.document.national_substitution is not None
                and (
                    not isinstance(result, NfseAuthorizationResult)
                    or result.authorized_xml is None
                )
            ):
                raise PersistenceStateError(
                    "National replacement requires signed authorized substitute XML"
                )
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
                if isinstance(result, (AuthorizationResult, NfseAuthorizationResult))
                and result.authorized_xml is not None else None
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
                archive_entry=(
                    _nfse_rejection_archive(
                        result,
                        scope=scope,
                        document_id=document_id,
                        occurred_at=occurred_at,
                        retention=RetentionPolicyMetadata(
                            policy_id="nfcore-fiscal-archive", policy_version=1,
                        ),
                    )
                    if isinstance(result, NfseAuthorizationResult) else None
                ),
            )
        elif (
            isinstance(result, NfseAuthorizationResult)
            and result.status is AuthorizationStatus.PENDING
            and result.provider.provider_name == "barueri-pmb004-homologation"
        ):
            protocol = result.provider_request_id
            if (
                not isinstance(protocol, str)
                or not 1 <= len(protocol) <= 128
                or not protocol.isascii()
                or not protocol.isalnum()
            ):
                raise PersistenceStateError("Barueri remittance protocol is missing")
            with self._uow_factory() as uow:
                uow.lifecycle.assert_scope(document_id, scope)
                current = uow.lifecycle.get(document_id)
                current_attempts = uow.idempotency.attempts(attempt.key)
                if (
                    current is None
                    or current.state is not FiscalDocumentState.TRANSMITTING
                    or not current_attempts
                    or current_attempts[-1].generation != attempt.generation
                    or current_attempts[-1].request_fingerprint != attempt.request_fingerprint
                ):
                    raise PersistenceConflictError("Barueri transmission changed during receipt")
                previous = [
                    item for item in uow.archive.list_for_document(scope, document_id)
                    if item.kind is FiscalArchiveKind.PROVIDER_RESPONSE
                    and item.media_type == "application/vnd.nfcore.barueri-remittance.v1+json"
                ]
                if previous:
                    raise PersistenceConflictError("Barueri remittance already acknowledged")
                uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=document_id,
                    kind=FiscalArchiveKind.PROVIDER_RESPONSE,
                    content=json.dumps({
                        "provider_request_id": protocol,
                        "document_id": document_id,
                        "fingerprint": request.request_fingerprint,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    media_type="application/vnd.nfcore.barueri-remittance.v1+json",
                    archived_at=occurred_at,
                    retention=RetentionPolicyMetadata(
                        policy_id="nfcore-fiscal-archive", policy_version=1,
                    ),
                ))
                uow.commit()
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
                if (
                    request.document.national_substitution is not None
                    and result.authorized_xml is None
                ):
                    raise PersistenceStateError(
                        "National replacement recovery needs signed official NFS-e"
                    )
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
                if result.authorized_xml is not None:
                    # Atomic with the terminal state and provider query evidence;
                    # no second POST or newly allocated serial during recovery.
                    uow.archive.append(FiscalArchiveEntry.build(
                        scope=scope,
                        document_reference=document_id,
                        kind=FiscalArchiveKind.AUTHORIZED_XML,
                        content=result.authorized_xml,
                        media_type="application/xml",
                        archived_at=occurred_at,
                        retention=retention,
                    ))
                if request.document.national_substitution is not None:
                    self._complete_national_replacement_in_uow(
                        uow=uow, prepared=request, authorized=True,
                        occurred_at=occurred_at, retention=retention,
                    )
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
                uow.archive.append(_nfse_rejection_archive(
                    result,
                    scope=scope,
                    document_id=document_id,
                    occurred_at=occurred_at,
                    retention=retention,
                ))
                if request.document.national_substitution is not None:
                    self._complete_national_replacement_in_uow(
                        uow=uow, prepared=request, authorized=False,
                        occurred_at=occurred_at, retention=retention,
                    )
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

    def review_prepared_cajamar_substitution(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
        reviewed_at: datetime,
    ) -> CajamarSubstitutionReview:
        """Preflight only: Cajamar 7.311/2024 requires the official city portal.

        No SOAP substitution is manufactured; no lifecycle, RPS or numbering is
        changed. The authoritative municipal confirmation must be reviewed later.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not isinstance(reviewed_at, datetime)
            or reviewed_at.tzinfo is None
        ):
            raise FiscalValidationError("Cajamar substitution review needs scoped datetime")
        original = self.load_prepared_nfse_authorization(scope, original_id)
        candidate = self.load_prepared_nfse_authorization(scope, replacement_id)
        eligibility = review_cajamar_substitution(
            original=original, replacement=candidate, reviewed_at=reviewed_at,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            previous = uow.lifecycle.get(original_id)
            new = uow.lifecycle.get(replacement_id)
            old_attempts = uow.idempotency.attempts(original.idempotency_key)
            candidate_attempts = uow.idempotency.attempts(candidate.idempotency_key)
            if (
                previous is None
                or previous.state is not FiscalDocumentState.AUTHORIZED
                or new is None
                or new.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or not old_attempts
                or old_attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or old_attempts[-1].document_id != original_id
                or not candidate_attempts
                or candidate_attempts[-1].status is not IssuanceAttemptStatus.RESERVED
                or candidate_attempts[-1].document_id != replacement_id
            ):
                raise PersistenceStateError(
                    "Cajamar review requires an authorized original and unissued candidate"
                )
            original_archives = uow.archive.list_for_document(scope, original_id)
            candidate_archives = uow.archive.list_for_document(scope, replacement_id)
            archived_note = [
                entry for entry in original_archives
                if entry.kind is FiscalArchiveKind.AUTHORIZED_XML
                and entry.media_type == "application/xml"
            ]
            originals = [
                entry for entry in original_archives
                if entry.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            candidate_rps = [
                entry for entry in candidate_archives
                if entry.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            if (
                len(archived_note) != 1 or len(originals) != 1
                or len(candidate_rps) != 1
            ):
                raise PersistenceStateError(
                    "Cajamar review requires both original RPS and official NFS-e XML"
                )
            for entry in (archived_note[0], originals[0], candidate_rps[0]):
                FiscalArchiveVerifier().verify_entry(entry)
            persisted_rps = decode_sp4_original(
                originals[0].content, scope=scope, request=original,
            )
            decode_sp4_original(
                candidate_rps[0].content, scope=scope, request=candidate,
            )
            fiscal_note = decode_cajamar_archived_invoice(
                archived_note[0].content, persisted_rps,
            )
            if old_attempts[-1].result_reference != fiscal_note.invoice_reference:
                raise PersistenceConflictError(
                    "Cajamar original authorization and archived XML disagree"
                )
        return eligibility

    def preflight_cajamar_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str, cancellation_reason: str,
    ) -> tuple[NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice]:
        """Verify archived original RPS and authorized GeisWeb note in one scoped UoW."""
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
        ):
            raise FiscalValidationError("Cajamar cancellation requires homologation scope")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Cajamar cancellation requires prepared NFS-e")
            validate_cajamar_automatic_cancellation(
                competence=request.document.competence_date,
                reason=cancellation_reason,
                reviewed_at=_cajamar_policy_now(),
            )
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                current is None
                or current.state is not FiscalDocumentState.AUTHORIZED
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3509205"
            ):
                raise PersistenceStateError(
                    "Cancellation requires one authorized original Cajamar invoice"
                )
            originals = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            official = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(originals) != 1 or len(official) != 1:
                raise PersistenceStateError("Original RPS/authorized XML is missing")
            FiscalArchiveVerifier().verify_entry(originals[0])
            FiscalArchiveVerifier().verify_entry(official[0])
            source = decode_sp4_original(
                originals[0].content, scope=scope, request=request,
            )
            invoice = decode_cajamar_archived_invoice(official[0].content, source)
            if attempts[-1].result_reference != invoice.invoice_reference:
                raise PersistenceConflictError(
                    "Cajamar fiscal cancellation invoice reference disagrees with issuance"
                )
        binding = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="cancel",
        )
        if binding != CAJAMAR_GEISWEB_PROVIDER:
            raise FiscalValidationError("Cajamar cancellation provider binding mismatch")
        return request, source, invoice

    def cancel_prepared_cajamar_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        submit_verified_cancel: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice],
            CajamarCancellationDecision,
        ],
        cancellation_reason: str,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableCajamarCancellationOutcome:
        """One original NFS-e cancellation claim, one reviewed transport attempt.

        A transport failure leaves CANCEL_REQUESTED for investigation. Replay
        does not issue another CancelaNfse POST. Only correlated official
        response proof commits CANCELLED; a proven rejection restores AUTHORIZED.
        """
        if (
            not callable(submit_verified_cancel)
            or not isinstance(scope, ExecutionScope)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
        ):
            raise FiscalValidationError("Invalid Cajamar cancellation dependencies")
        request, original, invoice = self.preflight_cajamar_nfse_cancellation(
            scope=scope, document_id=document_id,
            cancellation_reason=cancellation_reason,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            before = uow.lifecycle.get(document_id)
            if before is None or before.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Concurrent Cajamar cancellation request")
            claim = self._state_machine.transition(
                before, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Cajamar fiscal cancellation claimed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=before.version)
            uow.commit()
        decision = submit_verified_cancel(request, original, invoice)
        if not isinstance(decision, CajamarCancellationDecision):
            raise FiscalValidationError(
                "Cajamar cancellation requires verified typed official response"
            )
        event = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=decision.response_xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.lifecycle.get(document_id)
            if latest != claim:
                raise PersistenceConflictError("Cajamar cancellation changed during delivery")
            target = (
                FiscalDocumentState.CANCELLED if decision.confirmed
                else FiscalDocumentState.AUTHORIZED
            )
            final = self._state_machine.transition(
                latest, target, occurred_at=occurred_at,
                reason=(
                    "Cajamar cancellation officially confirmed"
                    if decision.confirmed else "Cajamar cancellation officially rejected"
                ),
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=latest.version)
            entry = uow.archive.append(event)
            uow.commit()
        return DurableCajamarCancellationOutcome(
            decision=decision, lifecycle=final, archive_reference=entry.entry_id,
        )

    def preflight_barueri_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
        decode_official_invoice: Callable[
            [bytes, Sp4OriginalRps], Sp4VerifiedInvoice
        ],
        replacement_id: str | None = None,
    ) -> tuple[
        NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice,
        Sp4OriginalRps | None, NfseAuthorizationRequest | None,
    ]:
        """Approve only the original, source-correlated authorized Barueri NFS-e.

        A replacement is a different persisted, unissued RPS of the SAME issuer.
        This preflight performs no municipal I/O and never invents an invoice.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not callable(decode_official_invoice)
            or not isinstance(document_id, str)
            or not document_id.strip()
            or replacement_id == document_id
        ):
            raise FiscalValidationError("Barueri cancellation scope or source invalid")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Barueri cancellation needs prepared NFS-e")
            state = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                state is None or state.state is not FiscalDocumentState.AUTHORIZED
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3505708"
            ):
                raise PersistenceStateError("Barueri cancellation requires authorized original")
            stored = uow.archive.list_for_document(scope, document_id)
            original_entries = [
                item for item in stored
                if item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
                and item.kind is FiscalArchiveKind.OTHER
            ]
            invoices = [
                item for item in stored
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(original_entries) != 1 or len(invoices) != 1:
                raise PersistenceStateError("Barueri original RPS/official XML missing")
            verifier = FiscalArchiveVerifier()
            verifier.verify_entry(original_entries[0])
            verifier.verify_entry(invoices[0])
            original = decode_sp4_original(
                original_entries[0].content, scope=scope, request=request,
            )
            invoice = decode_official_invoice(invoices[0].content, original)
            if (
                not isinstance(invoice, Sp4VerifiedInvoice)
                or invoice.issuer_ibge != "3505708"
                or invoice.issuer_cnpj != original.issuer_cnpj
                or invoice.rps_number != original.rps_number
                or invoice.rps_series != original.rps_series
                or invoice.gross_amount != original.gross_amount
                or attempts[-1].result_reference != invoice.invoice_reference
            ):
                raise PersistenceConflictError("Barueri official invoice differs from source")
            replacement: Sp4OriginalRps | None = None
            candidate_request: NfseAuthorizationRequest | None = None
            if replacement_id is not None:
                candidate = self._load_prepared_from_uow(uow, scope, replacement_id)
                if not isinstance(candidate, NfseAuthorizationRequest):
                    raise PersistenceStateError("Barueri replacement needs prepared NFS-e")
                latest = uow.lifecycle.get(replacement_id)
                candidate_attempts = uow.idempotency.attempts(candidate.idempotency_key)
                if (
                    latest is None
                    or latest.state is not FiscalDocumentState.READY_TO_TRANSMIT
                    or not candidate_attempts
                    or candidate_attempts[-1].status is not IssuanceAttemptStatus.RESERVED
                    or candidate_attempts[-1].document_id != replacement_id
                    or candidate.document.scope.identity_partition_key
                    != original.scope.identity_partition_key
                    or candidate.document.issuer.cnpj != original.issuer_cnpj
                    or candidate.document.issuer.address.jurisdiction.municipality_ibge_code
                    != "3505708"
                ):
                    raise PersistenceStateError(
                        "Barueri replacement must be unissued by same taxpayer"
                    )
                sources = [
                    item for item in uow.archive.list_for_document(scope, replacement_id)
                    if item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
                    and item.kind is FiscalArchiveKind.OTHER
                ]
                if len(sources) != 1:
                    raise PersistenceStateError("Barueri replacement original RPS absent")
                verifier.verify_entry(sources[0])
                replacement = decode_sp4_original(
                    sources[0].content, scope=scope, request=candidate,
                )
                if candidate.document.competence_date != request.document.competence_date:
                    raise PersistenceStateError("Barueri substitute must preserve competence")
                candidate_request = candidate
        selected = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="cancel",
        )
        if selected != "barueri-pmb004-homologation":
            raise FiscalValidationError("Barueri cancellation binding is not canonical")
        return request, original, invoice, replacement, candidate_request

    def cancel_prepared_barueri_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        decode_official_invoice: Callable[
            [bytes, Sp4OriginalRps], Sp4VerifiedInvoice
        ],
        prepare_event: Callable[
            [
                NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice,
                str, str, str, datetime, str | None,
                NfseAuthorizationRequest | None, Sp4OriginalRps | None,
                str | None,
            ],
            BarueriRpsBatch,
        ],
        submit_event: Callable[[BarueriRpsBatch], BarueriReceipt],
        reason_code: str,
        cancellation_reason: str,
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
        replacement_id: str | None = None,
        substitution_justification_code: str | None = None,
    ) -> DurableBarueriCancellationOutcome:
        """Commit the cancellation claim and exact event bytes BEFORE municipal POST.

        Network uncertainty retains CANCEL_REQUESTED, allowing ONLY read-only
        reconciliation of the immutable event; no retry can send a second POST.
        """
        if (
            reason_code not in ("01", "02", "03")
            or (reason_code == "03") != (replacement_id is not None)
            or (reason_code == "03" and substitution_justification_code
                not in ("1", "2", "3", "4", "5", "9"))
            or (reason_code != "03" and substitution_justification_code is not None)
            or not isinstance(cancellation_reason, str)
            or not 1 <= len(cancellation_reason.strip()) <= 180
            or any(ord(ch) < 32 for ch in cancellation_reason)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
            or not callable(prepare_event)
            or not callable(submit_event)
        ):
            raise FiscalValidationError("Invalid reviewed Barueri cancellation intent")
        request, original, invoice, replacement, replacement_request = (
            self.preflight_barueri_nfse_cancellation(
                scope=scope, document_id=document_id,
                decode_official_invoice=decode_official_invoice,
                replacement_id=replacement_id,
            )
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            before = uow.lifecycle.get(document_id)
            if before is None or before.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Concurrent Barueri event already claimed")
            if replacement_id is not None:
                uow.lifecycle.assert_scope(replacement_id, scope)
                candidate = uow.lifecycle.get(replacement_id)
                if (
                    candidate is None
                    or candidate.state is not FiscalDocumentState.READY_TO_TRANSMIT
                ):
                    raise PersistenceConflictError("Barueri replacement changed before claim")
                # A PMB004 Type 2 reason 03 already carries the new RPS.
                # Claim its original fiscal lifecycle in the SAME transaction:
                # the regular issuance endpoint must never POST that RPS again.
                substituted_claim = self._state_machine.transition(
                    candidate, FiscalDocumentState.TRANSMITTING,
                    occurred_at=occurred_at,
                    reason="Barueri replacement RPS included in pending municipal event",
                    correlation_id=scope.correlation_id,
                )
                uow.lifecycle.save(
                    substituted_claim, expected_version=candidate.version,
                )
            reserved = uow.sequences.reserve_next(
                FiscalSequenceKey.from_scope(
                    scope, model=InternalFiscalSequenceStream.NFSE_RPS, series=1,
                ),
                FiscalSequencePolicy(max_number=9_999_999),
            )
            remittance = f"{reserved.number:011d}"
            batch = prepare_event(
                request, original, invoice, remittance, reason_code,
                cancellation_reason, occurred_at,
                replacement.rps_number if replacement is not None else None,
                replacement_request, replacement,
                substitution_justification_code,
            )
            if (
                not isinstance(batch, BarueriRpsBatch)
                or batch.remittance != remittance
                or batch.scope.identity_partition_key != scope.identity_partition_key
                or batch.issuer_cnpj != original.issuer_cnpj
                or not any(
                    row[39:40] == b"C"
                    for row in batch.rps_bytes.split(b"\r\n")
                    if row[:1] == b"2"
                )
            ):
                raise PersistenceConflictError("Barueri original event bytes disagree")
            event_data = {
                "version": 1,
                "document_id": document_id,
                "fingerprint": request.request_fingerprint,
                "reason_code": reason_code,
                "substitution_justification_code": substitution_justification_code,
                "replacement_id": replacement_id,
                "event_remittance": remittance,
                "sent_on": occurred_at.astimezone(
                    ZoneInfo("America/Sao_Paulo")
                ).date().isoformat(),
                "municipal_registration": batch.municipal_registration,
                "rps_bytes_base64": base64.b64encode(batch.rps_bytes).decode("ascii"),
            }
            event_entry = FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.OTHER,
                content=json.dumps(
                    event_data, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8"),
                media_type="application/vnd.nfcore.barueri-cancel-intent.v1+json",
                archived_at=occurred_at, retention=retention,
            )
            claim = self._state_machine.transition(
                before, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Barueri municipal event claimed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=before.version)
            stored = uow.archive.append(event_entry)
            uow.commit()
        # The intent and source identity are durable here, before any network call.
        # On timeout, leave the claim unchanged for query-only recovery.
        receipt = submit_event(batch)
        protocol = receipt.remittance_protocol if isinstance(receipt, BarueriReceipt) else None
        if (
            not isinstance(receipt, BarueriReceipt)
            or receipt.operation != "NFeLoteEnviarArquivo"
            or receipt.code != "OK200"
            or not isinstance(protocol, str)
            or not 1 <= len(protocol) <= 128
            or not protocol.isascii() or not protocol.isalnum()
        ):
            raise PersistenceStateError("Barueri cancellation returned no recoverable protocol")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.lifecycle.get(document_id)
            if latest != claim:
                raise PersistenceConflictError("Barueri event state changed during POST")
            acks = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.media_type == "application/vnd.nfcore.barueri-cancel-ack.v1+json"
            ]
            if acks:
                raise PersistenceConflictError("Barueri event protocol already recorded")
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.PROVIDER_RESPONSE,
                content=json.dumps({
                    "document_id": document_id, "event_remittance": remittance,
                    "provider_request_id": protocol,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                media_type="application/vnd.nfcore.barueri-cancel-ack.v1+json",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        return DurableBarueriCancellationOutcome(
            lifecycle=claim, archive_reference=stored.entry_id,
            protocol=protocol, recovery_required=True, replay=False,
        )

    def reconcile_barueri_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
        decode_official_invoice: Callable[
            [bytes, Sp4OriginalRps], Sp4VerifiedInvoice
        ],
        query_official_event: Callable[
            [
                BarueriRpsBatch, Sp4VerifiedInvoice, str | None, date,
                NfseAuthorizationRequest | None, Sp4OriginalRps | None,
            ],
            BarueriCancellationEvidence | None,
        ],
        occurred_at: datetime,
        retention: RetentionPolicyMetadata,
    ) -> DurableBarueriCancellationOutcome:
        """Only municipal status/list/download can finish a previously claimed event.

        The original immutable bytes and first submission date are recovered
        from the same tenant-scoped fiscal UoW. Never re-submit a cancellation.
        """
        if (
            not callable(decode_official_invoice)
            or not callable(query_official_event)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Barueri cancellation recovery ports missing")
        with self._uow_factory() as uow:
            prepared = self._load_prepared_from_uow(uow, scope, document_id)
            if (
                not isinstance(prepared, NfseAuthorizationRequest)
                or prepared.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3505708"
            ):
                raise PersistenceStateError("Barueri cancellation source is absent")
            lifecycle = uow.lifecycle.get(document_id)
            if lifecycle is None:
                raise PersistenceStateError("Barueri cancellation lifecycle absent")
            if lifecycle.state is FiscalDocumentState.CANCELLED:
                return DurableBarueriCancellationOutcome(
                    lifecycle, None, None, False, True,
                )
            if lifecycle.state is not FiscalDocumentState.CANCEL_REQUESTED:
                raise PersistenceStateError("Barueri cancellation has no durable pending claim")
            entries = uow.archive.list_for_document(scope, document_id)
            original_entries = [
                item for item in entries
                if item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
                and item.kind is FiscalArchiveKind.OTHER
            ]
            invoice_entries = [
                item for item in entries
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            event_entries = [
                item for item in entries
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type == "application/vnd.nfcore.barueri-cancel-intent.v1+json"
            ]
            acks = [
                item for item in entries
                if item.kind is FiscalArchiveKind.PROVIDER_RESPONSE
                and item.media_type == "application/vnd.nfcore.barueri-cancel-ack.v1+json"
            ]
            if (
                len(original_entries) != 1
                or len(invoice_entries) != 1
                or len(event_entries) != 1
                or len(acks) > 1
            ):
                raise PersistenceStateError("Barueri cancellation evidence is incomplete")
            verifier = FiscalArchiveVerifier()
            for item in (
                *original_entries, *invoice_entries, *event_entries, *acks,
            ):
                verifier.verify_entry(item)
            original = decode_sp4_original(
                original_entries[0].content, scope=scope, request=prepared,
            )
            invoice = decode_official_invoice(invoice_entries[0].content, original)
            if (
                not isinstance(invoice, Sp4VerifiedInvoice)
                or invoice.issuer_cnpj != original.issuer_cnpj
                or invoice.issuer_ibge != original.issuer_ibge
                or invoice.rps_number != original.rps_number
                or invoice.rps_series != original.rps_series
                or invoice.gross_amount != original.gross_amount
            ):
                raise PersistenceConflictError("Barueri archived invoice disagrees")
            try:
                raw = json.loads(event_entries[0].content)
                if not isinstance(raw, dict) or set(raw) != {
                    "version", "document_id", "fingerprint", "reason_code",
                    "substitution_justification_code", "replacement_id",
                    "event_remittance", "sent_on",
                    "municipal_registration", "rps_bytes_base64",
                } or raw["version"] != 1:
                    raise ValueError
                when = date.fromisoformat(raw["sent_on"])
                remittance = raw["event_remittance"]
                if (
                    raw["document_id"] != document_id
                    or raw["fingerprint"] != prepared.request_fingerprint
                    or raw["reason_code"] not in ("01", "02", "03")
                    or (raw["reason_code"] == "03") != (raw["replacement_id"] is not None)
                    or (raw["reason_code"] == "03"
                        and raw["substitution_justification_code"]
                        not in ("1", "2", "3", "4", "5", "9"))
                    or (raw["reason_code"] != "03"
                        and raw["substitution_justification_code"] is not None)
                    or not isinstance(remittance, str)
                    or len(remittance) != 11 or not remittance.isascii()
                    or not remittance.isdecimal()
                ):
                    raise ValueError
                batch = BarueriRpsBatch(
                    scope=scope, issuer_cnpj=original.issuer_cnpj,
                    municipal_registration=raw["municipal_registration"],
                    tax_regime=prepared.document.issuer.tax_regime,
                    competence_date=original.competence_date,
                    remittance=remittance, file_name=remittance + ".txt",
                    rps_bytes=base64.b64decode(
                        raw["rps_bytes_base64"], validate=True,
                    ),
                )
                protocol: str | None = None
                if acks:
                    acknowledged = json.loads(acks[0].content)
                    if (
                        set(acknowledged) != {
                            "document_id", "event_remittance", "provider_request_id",
                        }
                        or acknowledged["document_id"] != document_id
                        or acknowledged["event_remittance"] != remittance
                    ):
                        raise ValueError
                    protocol = acknowledged["provider_request_id"]
                    if (
                        not isinstance(protocol, str)
                        or not 1 <= len(protocol) <= 128
                        or not protocol.isascii()
                        or not protocol.isalnum()
                    ):
                        raise ValueError
            except (TypeError, KeyError, ValueError, FiscalValidationError):
                raise PersistenceStateError("Altered durable Barueri event archive") from None
            # A reason-03 event already claimed the second durable RPS before
            # POST. Recover the exact substitute from the SAME partition.
            replacement_request: NfseAuthorizationRequest | None = None
            replacement_source: Sp4OriginalRps | None = None
            replacement_id = raw["replacement_id"]
            if replacement_id is not None:
                if (
                    not isinstance(replacement_id, str)
                    or not replacement_id.strip()
                    or replacement_id == document_id
                ):
                    raise PersistenceStateError("Invalid archived substitute document")
                loaded_replacement = self._load_prepared_from_uow(
                    uow, scope, replacement_id,
                )
                if not isinstance(loaded_replacement, NfseAuthorizationRequest):
                    raise PersistenceStateError("Prepared substitute is unavailable")
                replacement_request = loaded_replacement
                replacement_state = uow.lifecycle.get(replacement_id)
                replacement_attempts = uow.idempotency.attempts(
                    replacement_request.idempotency_key,
                )
                sources = [
                    item for item in uow.archive.list_for_document(
                        scope, replacement_id,
                    )
                    if item.kind is FiscalArchiveKind.OTHER
                    and item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
                ]
                if (
                    replacement_state is None
                    or replacement_state.state is not FiscalDocumentState.TRANSMITTING
                    or not replacement_attempts
                    or replacement_attempts[-1].status
                    is not IssuanceAttemptStatus.RESERVED
                    or replacement_attempts[-1].document_id != replacement_id
                    or replacement_attempts[-1].request_fingerprint
                    != replacement_request.request_fingerprint
                    or len(sources) != 1
                ):
                    raise PersistenceStateError(
                        "Barueri replacement has no reserved transmission"
                    )
                verifier.verify_entry(sources[0])
                replacement_source = decode_sp4_original(
                    sources[0].content, scope=scope, request=replacement_request,
                )
                if (
                    replacement_source.issuer_cnpj != original.issuer_cnpj
                    or replacement_source.issuer_ibge != "3505708"
                    or replacement_source.competence_date != original.competence_date
                    or batch.rps_bytes.split(b"\r\n")[1][15:25]
                    != replacement_source.rps_number.zfill(10).encode("ascii")
                ):
                    raise PersistenceConflictError(
                        "Barueri replacement RPS does not match cancelled event"
                    )
        # Query only: either by the original persisted protocol or by the
        # exact event remittance + first transmission date after ambiguous POST.
        proof = query_official_event(
            batch, invoice, protocol, when, replacement_request, replacement_source,
        )
        if proof is None:
            return DurableBarueriCancellationOutcome(
                lifecycle, event_entries[0].entry_id,
                protocol, True, False,
            )
        if (
            not isinstance(proof, BarueriCancellationEvidence)
            or proof.event_remittance != batch.remittance
            or int(proof.invoice_number) != int(invoice.invoice_number)
        ):
            raise PersistenceConflictError("Barueri cancellation response is not source-bound")
        if (
            (replacement_source is None) != (proof.replacement_invoice is None)
            or (replacement_source is None) != (proof.replacement_return is None)
        ):
            raise PersistenceConflictError(
                "Barueri cancellation/substitution lacks independent official proof"
            )
        if replacement_source is not None:
            substitute = proof.replacement_invoice
            assert substitute is not None
            if (
                substitute.issuer_cnpj != replacement_source.issuer_cnpj
                or substitute.issuer_ibge != "3505708"
                or substitute.competence_date != replacement_source.competence_date
                or substitute.rps_number != replacement_source.rps_number
                or substitute.rps_series != replacement_source.rps_series
                or substitute.gross_amount != replacement_source.gross_amount
            ):
                raise PersistenceConflictError(
                    "Barueri substitute does not match its durable original RPS"
                )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.lifecycle.get(document_id)
            if latest != lifecycle:
                raise PersistenceConflictError("Barueri event state changed during recovery")
            if replacement_source is not None:
                assert replacement_request is not None
                assert replacement_id is not None
                assert proof.replacement_invoice is not None
                uow.lifecycle.assert_scope(replacement_id, scope)
                replacement_latest = uow.lifecycle.get(replacement_id)
                attempts = uow.idempotency.attempts(
                    replacement_request.idempotency_key,
                )
                if (
                    replacement_latest is None
                    or replacement_latest.state is not FiscalDocumentState.TRANSMITTING
                    or not attempts
                    or attempts[-1].status is not IssuanceAttemptStatus.RESERVED
                    or attempts[-1].document_id != replacement_id
                    or attempts[-1].request_fingerprint
                    != replacement_request.request_fingerprint
                    or any(
                        item.kind is FiscalArchiveKind.AUTHORIZED_XML
                        for item in uow.archive.list_for_document(scope, replacement_id)
                    )
                ):
                    raise PersistenceConflictError(
                        "Barueri replacement changed during official reconciliation"
                    )
                substitute_final = self._state_machine.transition(
                    replacement_latest, FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at,
                    reason="Barueri substitution original NFS-e officially verified",
                    correlation_id=scope.correlation_id,
                )
                uow.lifecycle.save(
                    substitute_final, expected_version=replacement_latest.version,
                )
                uow.idempotency.mark_authorized(
                    replacement_request.idempotency_key, attempts[-1].generation,
                    proof.replacement_invoice.invoice_reference,
                )
                uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=replacement_id,
                    kind=FiscalArchiveKind.AUTHORIZED_XML,
                    content=proof.replacement_invoice.authorized_xml,
                    media_type="application/xml",
                    archived_at=occurred_at, retention=retention,
                ))
            final = self._state_machine.transition(
                latest, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at,
                reason="Barueri original NFS-e cancellation officially verified",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=latest.version)
            entry = uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.FISCAL_EVENT,
                content=proof.official_return,
                media_type="text/plain; charset=ascii",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        return DurableBarueriCancellationOutcome(
            final, entry.entry_id, protocol, False, False,
        )

    def preflight_osasco_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str, cancellation_reason: str,
    ) -> tuple[NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice]:
        """Source-verified WCF cancellation: same original taxpayer and official note."""
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not isinstance(cancellation_reason, str)
            or not 1 <= len(cancellation_reason.strip()) <= 500
            or any(ord(ch) < 32 for ch in cancellation_reason)
        ):
            raise FiscalValidationError("Osasco cancellation requires reviewed reason and scope")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Osasco cancellation needs canonical NFS-e")
            validate_osasco_automatic_cancellation(
                issued_at=request.document.issued_at,
                reviewed_at=datetime.now(UTC),
            )
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                current is None or current.state is not FiscalDocumentState.AUTHORIZED
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3534401"
                or request.document.issuer.municipal_registration is None
            ):
                raise PersistenceStateError(
                    "Osasco cancellation requires one authorized original invoice"
                )
            entries = uow.archive.list_for_document(scope, document_id)
            originals = [
                e for e in entries
                if e.kind is FiscalArchiveKind.OTHER
                and e.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            invoices = [
                e for e in entries
                if e.kind is FiscalArchiveKind.AUTHORIZED_XML
                and e.media_type == "application/xml"
            ]
            if len(originals) != 1 or len(invoices) != 1:
                raise PersistenceStateError("Osasco original RPS and official XML are required")
            FiscalArchiveVerifier().verify_entry(originals[0])
            FiscalArchiveVerifier().verify_entry(invoices[0])
            original = decode_sp4_original(
                originals[0].content, scope=scope, request=request,
            )
            invoice = decode_osasco_archived_full_invoice(
                invoices[0].content, original,
            )
            if attempts[-1].result_reference != invoice.invoice_reference:
                raise PersistenceConflictError(
                    "Osasco cancellation invoice number disagrees with authorization"
                )
        provider = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="cancel",
        )
        if provider != OSASCO_RTC_PROVIDER_ID:
            raise FiscalValidationError("Osasco cancellation provider binding mismatch")
        return request, original, invoice

    def preflight_osasco_nfse_substitution(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
        cancellation_reason: str,
    ) -> tuple[NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice]:
        """Type S requires an authorized old invoice and a distinct ready replacement."""
        validate_osasco_substitution_references(original_id, replacement_id)
        request, original, invoice = self.preflight_osasco_nfse_cancellation(
            scope=scope, document_id=original_id,
            cancellation_reason=cancellation_reason,
        )
        with self._uow_factory() as uow:
            candidate = self._load_prepared_from_uow(uow, scope, replacement_id)
            if not isinstance(candidate, NfseAuthorizationRequest):
                raise PersistenceStateError("Osasco substitute needs prepared NFS-e")
            uow.lifecycle.assert_scope(replacement_id, scope)
            state = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(candidate.idempotency_key)
            if (
                state is None
                or state.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.RESERVED
                or attempts[-1].document_id != replacement_id
                or candidate.document.scope.identity_partition_key
                != original.scope.identity_partition_key
                or candidate.document.issuer.cnpj != original.issuer_cnpj
                or candidate.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3534401"
            ):
                raise PersistenceStateError(
                    "Osasco substitute must be unissued for the same taxpayer"
                )
            originals = [
                e for e in uow.archive.list_for_document(scope, replacement_id)
                if e.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            if len(originals) != 1:
                raise PersistenceStateError("Osasco substitute needs durable original RPS")
            FiscalArchiveVerifier().verify_entry(originals[0])
            decode_sp4_original(
                originals[0].content, scope=scope, request=candidate,
            )
        return request, original, invoice

    def cancel_prepared_osasco_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        submit_verified_cancel: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice, str],
            OsascoCancellationDecision,
        ],
        cancellation_reason: str,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
        replacement_id: str | None = None,
    ) -> DurableOsascoCancellationOutcome:
        """Claim before exactly one WCF POST, archive reply and reconcile outcome.

        Ambiguous/time-out leaves CANCEL_REQUESTED for read-only recovery.
        No subsequent invocation may transmit an identical or changed command.
        """
        if (
            not callable(submit_verified_cancel)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Invalid Osasco municipal cancellation authority")
        if replacement_id is not None:
            request, original, invoice = self.preflight_osasco_nfse_substitution(
                scope=scope, original_id=document_id,
                replacement_id=replacement_id,
                cancellation_reason=cancellation_reason,
            )
        else:
            request, original, invoice = self.preflight_osasco_nfse_cancellation(
                scope=scope, document_id=document_id,
                cancellation_reason=cancellation_reason,
            )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            previous = uow.lifecycle.get(document_id)
            if previous is None or previous.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Concurrent Osasco cancellation request")
            if replacement_id is not None:
                uow.lifecycle.assert_scope(replacement_id, scope)
                candidate = uow.lifecycle.get(replacement_id)
                if (
                    candidate is None
                    or candidate.state is not FiscalDocumentState.READY_TO_TRANSMIT
                ):
                    raise PersistenceConflictError("Concurrent Osasco substitution changed")
            claim = self._state_machine.transition(
                previous, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Osasco WCF cancellation claimed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=previous.version)
            uow.commit()
        # No automatic exception retry: a failed exchange may already have
        # been processed by the municipality. The durable claim survives.
        decision = submit_verified_cancel(
            request, original, invoice, cancellation_reason,
        )
        if not isinstance(decision, OsascoCancellationDecision):
            raise FiscalValidationError("Unverified Osasco cancellation transport response")
        event = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=decision.response_xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current != claim:
                raise PersistenceConflictError("Osasco cancellation changed during delivery")
            final = current
            if decision.confirmed is not None:
                final = self._state_machine.transition(
                    current,
                    (
                        FiscalDocumentState.CANCELLED if decision.confirmed
                        else FiscalDocumentState.AUTHORIZED
                    ),
                    occurred_at=occurred_at,
                    reason=(
                        "Osasco cancellation officially confirmed"
                        if decision.confirmed else "Osasco cancellation officially rejected"
                    ),
                    correlation_id=scope.correlation_id,
                )
                uow.lifecycle.save(final, expected_version=current.version)
            entry = uow.archive.append(event)
            if replacement_id is not None:
                linked = FiscalArchiveEntry.build(
                    scope=scope, document_reference=document_id,
                    kind=FiscalArchiveKind.FISCAL_EVENT,
                    content=json.dumps({
                        "municipality_ibge": "3534401",
                        "original_id": document_id,
                        "replacement_id": replacement_id,
                        "cancel_type": "S",
                        "cancel_confirmed": decision.confirmed,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    media_type="application/vnd.nfcore.osasco-substitution.v1+json",
                    archived_at=occurred_at, retention=retention,
                )
                uow.archive.append(linked)
            uow.commit()
        return DurableOsascoCancellationOutcome(
            decision=decision, lifecycle=final, archive_reference=entry.entry_id,
        )


    def preflight_jundiai_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str, reason_code: str,
    ) -> tuple[NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice]:
        """Read-only original RPS, authorization and archived Giss invoice proof."""
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or reason_code not in ("1", "2", "4")
        ):
            raise FiscalValidationError("Jundiai cancellation requires scoped approved reason")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Jundiai cancellation requires prepared NFS-e")
            uow.lifecycle.assert_scope(document_id, scope)
            state = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                state is None
                or state.state is not FiscalDocumentState.AUTHORIZED
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3525904"
            ):
                raise PersistenceStateError(
                    "Jundiai cancellation needs the original authorized fiscal invoice"
                )
            entries = uow.archive.list_for_document(scope, document_id)
            originals = [
                item for item in entries
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            invoices = [
                item for item in entries
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(originals) != 1 or len(invoices) != 1:
                raise PersistenceStateError("Jundiai original RPS and municipal XML missing")
            for entry in (originals[0], invoices[0]):
                FiscalArchiveVerifier().verify_entry(entry)
            original = decode_sp4_original(
                originals[0].content, scope=scope, request=request,
            )
            invoice = decode_jundiai_archived_invoice(
                invoices[0].content, original,
            )
            if attempts[-1].result_reference != invoice.invoice_reference:
                raise PersistenceConflictError(
                    "Jundiai original NFS-e differs from authorized fiscal attempt"
                )
        bound = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="cancel",
        )
        if bound != "jundiai-giss-v2-homologation":
            raise FiscalValidationError("Jundiai cancellation provider binding differs")
        return request, original, invoice

    def preflight_jundiai_nfse_substitution(
        self, *, scope: ExecutionScope, original_id: str,
        replacement_id: str, reason_code: str,
    ) -> tuple[NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice]:
        """Review an authorized original and a distinct unissued replacement."""
        if (
            not isinstance(original_id, str) or not original_id.strip()
            or not isinstance(replacement_id, str) or not replacement_id.strip()
            or original_id == replacement_id
        ):
            raise FiscalValidationError("Jundiai replacement needs two distinct fiscal documents")
        original_request, source, invoice = self.preflight_jundiai_nfse_cancellation(
            scope=scope, document_id=original_id, reason_code=reason_code,
        )
        with self._uow_factory() as uow:
            candidate = self._load_prepared_from_uow(uow, scope, replacement_id)
            if not isinstance(candidate, NfseAuthorizationRequest):
                raise PersistenceStateError("Jundiai replacement needs prepared NFS-e")
            uow.lifecycle.assert_scope(replacement_id, scope)
            state = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(candidate.idempotency_key)
            if (
                state is None
                or state.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.RESERVED
                or attempts[-1].document_id != replacement_id
                or candidate.document.scope.identity_partition_key
                != source.scope.identity_partition_key
                or candidate.document.issuer.cnpj != source.issuer_cnpj
                or candidate.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3525904"
            ):
                raise PersistenceStateError(
                    "Jundiai replacement needs an unissued same-issuer NFS-e"
                )
            entries = [
                item for item in uow.archive.list_for_document(scope, replacement_id)
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type == SP4_ORIGINAL_RPS_MEDIA_TYPE
            ]
            if len(entries) != 1:
                raise PersistenceStateError("Jundiai replacement has no reserved RPS")
            FiscalArchiveVerifier().verify_entry(entries[0])
            decode_sp4_original(entries[0].content, scope=scope, request=candidate)
        return original_request, source, invoice

    def cancel_prepared_jundiai_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        reason_code: str,
        submit_verified_cancel: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice, str],
            JundiaiGissCancellationDecision,
        ],
        occurred_at: datetime, retention: RetentionPolicyMetadata,
        replacement_id: str | None = None,
    ) -> DurableJundiaiCancellationOutcome:
        """Claim once before SOAP; archive only correlated official outcome."""
        if (
            not callable(submit_verified_cancel)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Jundiai cancellation needs fiscal event authority")
        if replacement_id is None:
            request, source, invoice = self.preflight_jundiai_nfse_cancellation(
                scope=scope, document_id=document_id, reason_code=reason_code,
            )
        else:
            request, source, invoice = self.preflight_jundiai_nfse_substitution(
                scope=scope, original_id=document_id, replacement_id=replacement_id,
                reason_code=reason_code,
            )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            previous = uow.lifecycle.get(document_id)
            if previous is None or previous.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Concurrent Jundiai fiscal event")
            if replacement_id is not None:
                uow.lifecycle.assert_scope(replacement_id, scope)
                successor = uow.lifecycle.get(replacement_id)
                if (
                    successor is None
                    or successor.state is not FiscalDocumentState.READY_TO_TRANSMIT
                ):
                    raise PersistenceConflictError("Jundiai replacement was already modified")
            claim = self._state_machine.transition(
                previous, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Jundiai Giss cancellation claimed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=previous.version)
            uow.commit()

        # The durable claim is committed BEFORE SOAP. Uncertain HTTP responses
        # are NOT replayed automatically and preserve CANCEL_REQUESTED.
        decision = submit_verified_cancel(request, source, invoice, reason_code)
        if not isinstance(decision, JundiaiGissCancellationDecision):
            raise FiscalValidationError("Jundiai cancellation lacks reviewed official proof")
        event = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=decision.response_xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current != claim:
                raise PersistenceConflictError("Jundiai cancellation changed during SOAP I/O")
            final = current
            if decision.confirmed is not None:
                final = self._state_machine.transition(
                    current,
                    FiscalDocumentState.CANCELLED if decision.confirmed
                    else FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at,
                    reason="Jundiai official Giss cancellation result",
                    correlation_id=scope.correlation_id,
                )
                uow.lifecycle.save(final, expected_version=current.version)
            archived = uow.archive.append(event)
            if replacement_id is not None:
                linkage = FiscalArchiveEntry.build(
                    scope=scope, document_reference=document_id,
                    kind=FiscalArchiveKind.FISCAL_EVENT,
                    content=json.dumps({
                        "municipality_ibge": "3525904",
                        "original_id": document_id,
                        "replacement_id": replacement_id,
                        "official_cancel_confirmed": decision.confirmed,
                        "replacement_must_be_issued_separately": True,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    media_type="application/vnd.nfcore.jundiai-replacement-review.v1+json",
                    archived_at=occurred_at, retention=retention,
                )
                uow.archive.append(linkage)
            uow.commit()
        return DurableJundiaiCancellationOutcome(
            decision=decision, lifecycle=final, archive_reference=archived.entry_id,
        )


    def reconcile_jundiai_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
        query_verified_cancel: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice],
            JundiaiGissCancellationDecision,
        ],
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableJundiaiCancellationOutcome:
        """Recover a claimed Giss cancellation with read-only ConsultarNfsePorRps.

        No new cancel POST, no unverified mutation and no second archive owner.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not isinstance(document_id, str) or not document_id.strip()
            or not callable(query_verified_cancel)
            or not isinstance(occurred_at, datetime)
            or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Jundiai reconciliation needs canonical fiscal scope")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("No original Jundiai fiscal document")
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                current is None
                or current.state not in (
                    FiscalDocumentState.CANCEL_REQUESTED,
                    FiscalDocumentState.CANCELLED,
                )
                or not attempts
                or attempts[-1].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[-1].document_id != document_id
                or attempts[-1].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != "3525904"
            ):
                raise PersistenceStateError(
                    "Jundiai reconciliation requires one claimed authorized original"
                )
            invoices = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(invoices) != 1:
                raise PersistenceStateError("Missing original Giss municipal XML archive")
            FiscalArchiveVerifier().verify_entry(invoices[0])
            archived_invoice_xml = invoices[0].content
            if current.state is FiscalDocumentState.CANCELLED:
                finals = [
                    item for item in uow.archive.list_for_document(scope, document_id)
                    if item.kind is FiscalArchiveKind.FISCAL_EVENT
                    and item.media_type == "application/xml"
                ]
                if not finals:
                    raise PersistenceStateError("Cancelled Jundiai NFS-e needs event evidence")
                FiscalArchiveVerifier().verify_entry(finals[-1])
                return DurableJundiaiCancellationOutcome(
                    decision=JundiaiGissCancellationDecision(
                        confirmed=True, response_xml=finals[-1].content,
                    ), lifecycle=current, archive_reference=finals[-1].entry_id,
                )
        original = self.load_sp4_original_rps(scope, document_id)
        invoice = decode_jundiai_archived_invoice(
            archived_invoice_xml, original,
        )
        if attempts[-1].result_reference != invoice.invoice_reference:
            raise PersistenceConflictError("Jundiai original invoice identity changed")
        binding = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="query",
        )
        if binding != "jundiai-giss-v2-homologation":
            raise FiscalValidationError("Jundiai cancellation recovery binding mismatch")
        decision = query_verified_cancel(request, original, invoice)
        if not isinstance(decision, JundiaiGissCancellationDecision):
            raise FiscalValidationError("Unverified Jundiai municipal recovery")
        if decision.confirmed is not True:
            return DurableJundiaiCancellationOutcome(
                decision=decision, lifecycle=current, archive_reference=None,
            )
        event = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=decision.response_xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.lifecycle.get(document_id)
            if latest != current:
                raise PersistenceConflictError("Jundiai cancellation changed during recovery")
            final = self._state_machine.transition(
                latest, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at,
                reason="Jundiai Giss cancellation confirmed by read-only RPS query",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=latest.version)
            archived = uow.archive.append(event)
            uow.commit()
        return DurableJundiaiCancellationOutcome(
            decision=decision, lifecycle=final, archive_reference=archived.entry_id,
        )


    def review_prepared_national_nfse_substitution(
        self, *, scope: ExecutionScope,
        original_id: str, replacement: NfseCanonicalDocument,
    ) -> str:
        """Verify national substitution invariants without provider I/O or new numbers."""
        if (
            not isinstance(replacement, NfseCanonicalDocument)
            or replacement.scope.identity_partition_key != scope.identity_partition_key
            or replacement.document_id == original_id
            or replacement.national_substitution is not None
        ):
            raise FiscalValidationError("Replacement must be an independent reviewed DPS")
        original, key = self.preflight_national_nfse_cancellation(
            scope=scope, document_id=original_id,
        )
        prev = original.document
        old_loc = prev.issuer.address.jurisdiction
        new_loc = replacement.issuer.address.jurisdiction
        if (
            prev.issuer.cnpj != replacement.issuer.cnpj
            or old_loc != new_loc
            or prev.competence_date != replacement.competence_date
            or prev.service_jurisdiction != replacement.service_jurisdiction
            or len(prev.services) != 1 or len(replacement.services) != 1
            or prev.services[0].national_taxation_code
            != replacement.services[0].national_taxation_code
            or prev.services[0].municipal_service_code
            != replacement.services[0].municipal_service_code
        ):
            raise FiscalValidationError("National replacement changes protected fiscal identity")
        if prev.issuer.tax_regime in {
            TaxRegimeCode.SIMPLES_NACIONAL,
            TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            TaxRegimeCode.MEI,
        }:
            if (
                prev.services[0].gross_amount != replacement.services[0].gross_amount
                or prev.service_taker != replacement.service_taker
            ):
                raise FiscalValidationError("National Simples replacement changes protected facts")
        return key

    def preflight_national_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
    ) -> tuple[NfseAuthorizationRequest, str]:
        """Load the unique signed, authorized national original in one tenant scope."""
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not scope.host_namespace
            or not isinstance(document_id, str) or not document_id.strip()
        ):
            raise FiscalValidationError("National cancellation requires scoped original")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("National original must be prepared NFS-e")
            jurisdiction = request.document.issuer.address.jurisdiction
            state = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                jurisdiction.state_code != "SP"
                or jurisdiction.municipality_ibge_code is None
                or request.document.dps_number is None
                or state is None or state.state is not FiscalDocumentState.AUTHORIZED
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[0].document_id != document_id
                or attempts[0].request_fingerprint != request.request_fingerprint
                or not isinstance(attempts[0].result_reference, str)
            ):
                raise PersistenceStateError("National original authorization is not confirmed")
            key = attempts[0].result_reference
            if (
                len(key) != 50 or not key.isascii() or not key.isdecimal()
                or not key.startswith("35")
            ):
                raise PersistenceStateError("National original official access key is invalid")
            entries = [
                entry for entry in uow.archive.list_for_document(scope, document_id)
                if entry.kind is FiscalArchiveKind.AUTHORIZED_XML
                and entry.media_type == "application/xml"
            ]
            if len(entries) != 1:
                raise PersistenceStateError("National original needs one official signed XML")
            FiscalArchiveVerifier().verify_entry(entries[0])
            root = etree.fromstring(
                entries[0].content,
                etree.XMLParser(
                    resolve_entities=False, no_network=True,
                    load_dtd=False, huge_tree=False,
                ),
            )
            ns = "{http://www.sped.fazenda.gov.br/nfse}"
            info = root.find(ns + "infNFSe")
            if (
                root.tag != ns + "NFSe" or info is None
                or info.get("Id") != "NFS" + key
                or getattr(root.getroottree().docinfo, "doctype", None)
            ):
                raise PersistenceStateError("National original signed XML identity mismatch")
            _verify_nfse_receipt_signature(root, info, "NFS" + key)
        for operation in ("authorize", "cancel"):
            provider = self.resolve_configured_provider_id(
                scope=scope, document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=jurisdiction, operation=operation,
            )
            if provider != NACIONAL_HOMOLOGATION_PROVIDER_ID:
                raise FiscalValidationError("National original provider binding mismatch")
        return request, key

    def validate_claimed_national_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
        original_key: str, approval_reference: str,
    ) -> None:
        """Recheck the durable human-approved one-shot claim before fiscal POST."""
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            state = uow.lifecycle.get(document_id)
            records = [
                entry for entry in uow.archive.list_for_document(scope, document_id)
                if entry.kind is FiscalArchiveKind.OTHER
                and entry.media_type == "application/vnd.nfcore.national-cancel-intent.v1+json"
            ]
            if (
                state is None or state.state is not FiscalDocumentState.CANCEL_REQUESTED
                or len(records) != 1
            ):
                raise PersistenceStateError("National cancellation has no unique durable claim")
            FiscalArchiveVerifier().verify_entry(records[0])
            facts = json.loads(records[0].content)
            if (
                not isinstance(facts, dict)
                or facts.get("original_id") != document_id
                or facts.get("key") != original_key
                or facts.get("approval_reference") != approval_reference
            ):
                raise PersistenceConflictError("National cancellation approval changed")

    def cancel_prepared_national_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        reason_code: str, reason_description: str, approval_reference: str,
        signed_event_xml: bytes,
        submit_verified_cancel: Callable[
            [NfseAuthorizationRequest, str, str, str, str, datetime],
            NationalNfseCancellationReceipt,
        ],
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableSantanaCancellationOutcome:
        """Commit once-only cancellation claim before calling trusted SEFIN transport."""
        if (
            not callable(submit_verified_cancel)
            or not isinstance(signed_event_xml, bytes)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
            or reason_code not in ("1", "2", "9")
            or not isinstance(reason_description, str)
            or not 15 <= len(reason_description.strip()) <= 255
            or any(ord(char) < 32 for char in reason_description)
            or not isinstance(approval_reference, str)
            or not 8 <= len(approval_reference.strip()) <= 128
            or not approval_reference.isascii()
        ):
            raise FiscalValidationError("National cancellation requires reviewed human approval")
        request, key = self.preflight_national_nfse_cancellation(
            scope=scope, document_id=document_id,
        )
        intent = NationalNfseCancellationIntent(
            scope=scope, issuer=request.document.issuer.cnpj,
            issuer_jurisdiction=request.document.issuer.address.jurisdiction,
            invoice_reference=key, human_approval_reference=approval_reference,
            signed_event_xml=signed_event_xml,
        )
        validate_national_event_xml(signed_event_xml, kind="request")
        parsed = etree.fromstring(
            signed_event_xml,
            etree.XMLParser(
                resolve_entities=False, no_network=True,
                load_dtd=False, huge_tree=False,
            ),
        )
        tag = "{http://www.sped.fazenda.gov.br/nfse}"
        cancellation = parsed.find(tag + "infPedReg/" + tag + "e101101")
        if (
            cancellation is None
            or cancellation.findtext(tag + "cMotivo") != reason_code
            or cancellation.findtext(tag + "xMotivo") != reason_description.strip()
            or intent.scope.identity_partition_key != scope.identity_partition_key
        ):
            raise FiscalValidationError("National signed event does not match approval")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current is None or current.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("National cancellation already claimed")
            claim = self._state_machine.transition(
                current, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="National cancellation durable claim 101101",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=current.version)
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.OTHER,
                content=json.dumps({
                    "original_id": document_id, "key": key,
                    "reason_code": reason_code,
                    "reason_description": reason_description.strip(),
                    "approval_reference": approval_reference,
                    "event": "101101",
                    "signed_event_sha256": hashlib.sha256(signed_event_xml).hexdigest(),
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                media_type="application/vnd.nfcore.national-cancel-intent.v1+json",
                archived_at=occurred_at, retention=retention,
            ))
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.OTHER,
                content=signed_event_xml,
                media_type="application/vnd.nfcore.national-cancel-request.v1+xml",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        # Ambiguous provider timeout deliberately leaves CANCEL_REQUESTED.
        receipt = submit_verified_cancel(
            request, key, reason_code, reason_description, approval_reference, occurred_at,
        )
        if (
            not isinstance(receipt, NationalNfseCancellationReceipt)
            or not receipt.confirmed or receipt.invoice_reference != key
        ):
            raise FiscalValidationError("National cancellation lacks verified official evidence")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current != claim:
                raise PersistenceConflictError("National cancellation state changed during POST")
            final = self._state_machine.transition(
                current, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at, reason="SEFIN signed cancellation 101101 confirmed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=current.version)
            archived = uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.FISCAL_EVENT,
                content=receipt.event_xml, media_type="application/xml",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        return DurableSantanaCancellationOutcome(final, archived.entry_id)

    def preflight_santana_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
    ) -> tuple[NfseAuthorizationRequest, str]:
        """One scoped, signed, already authorized original Simpliss invoice."""
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not isinstance(document_id, str) or not document_id.strip()
        ):
            raise FiscalValidationError("Santana cancellation needs a scoped original")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Santana original is not a prepared NFS-e")
            jurisdiction = request.document.issuer.address.jurisdiction
            state = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                jurisdiction.state_code != "SP"
                or jurisdiction.municipality_ibge_code != SANTANA_IBGE
                or state is None or state.state is not FiscalDocumentState.AUTHORIZED
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[0].document_id != document_id
                or attempts[0].request_fingerprint != request.request_fingerprint
                or not isinstance(attempts[0].result_reference, str)
            ):
                raise PersistenceStateError("Santana original authorization is not confirmed")
            key = attempts[0].result_reference
            if len(key) != 50 or not key.isascii() or not key.isdecimal():
                raise PersistenceStateError("Santana official invoice key is invalid")
            entries = [
                item for item in uow.archive.list_for_document(scope, document_id)
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(entries) != 1:
                raise PersistenceStateError("Santana original has no unique authorized XML")
            FiscalArchiveVerifier().verify_entry(entries[0])
            root = etree.fromstring(
                entries[0].content,
                etree.XMLParser(
                    resolve_entities=False, no_network=True,
                    load_dtd=False, huge_tree=False,
                ),
            )
            ns = "{http://www.sped.fazenda.gov.br/nfse}"
            info = root.find(ns + "infNFSe")
            if (
                root.tag != ns + "NFSe" or info is None
                or info.get("Id") != "NFS" + key
                or getattr(root.getroottree().docinfo, "doctype", None)
            ):
                raise PersistenceStateError("Santana original XML identity mismatches")
            _verify_nfse_receipt_signature(root, info, "NFS" + key)
        bound = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=jurisdiction, operation="cancel",
        )
        if bound != SANTANA_PROVIDER_ID:
            raise FiscalValidationError("Santana canonical cancellation binding mismatch")
        return request, key

    def cancel_prepared_santana_nfse(
        self, *, scope: ExecutionScope, document_id: str,
        reason_code: str, reason_description: str, approval_reference: str,
        gateway: SantanaSimplissHomologationGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableSantanaCancellationOutcome:
        """Durable one-shot claim before signed Simpliss event 101101 POST."""
        if (
            not isinstance(gateway, SantanaSimplissHomologationGateway)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
            or reason_code not in ("1", "2", "9")
            or not isinstance(reason_description, str)
            or not 15 <= len(reason_description.strip()) <= 255
            or any(ord(ch) < 32 for ch in reason_description)
            or not isinstance(approval_reference, str)
            or not 8 <= len(approval_reference.strip()) <= 128
        ):
            raise FiscalValidationError("Santana requires valid approved cancellation")
        request, key = self.preflight_santana_nfse_cancellation(
            scope=scope, document_id=document_id,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current is None or current.state is not FiscalDocumentState.AUTHORIZED:
                raise PersistenceConflictError("Santana cancellation already claimed")
            claim = self._state_machine.transition(
                current, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Santana event 101101 durable claim",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(claim, expected_version=current.version)
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.OTHER,
                content=json.dumps({
                    "original_id": document_id, "key": key,
                    "reason_code": reason_code,
                    "reason": reason_description.strip(),
                    "approval_reference": approval_reference,
                    "operation": "santana_cancel_101101",
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                media_type="application/vnd.nfcore.santana-cancel-intent.v1+json",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        # A timeout leaves CANCEL_REQUESTED, never a second POST.
        receipt = gateway.submit_cancellation(
            request, key, reason_code, reason_description,
            approval_reference, occurred_at,
        )
        if (
            not isinstance(receipt, NationalNfseCancellationReceipt)
            or receipt.invoice_reference != key or receipt.confirmed is not True
        ):
            raise FiscalValidationError("Unverified Simpliss cancellation receipt")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            current = uow.lifecycle.get(document_id)
            if current != claim:
                raise PersistenceConflictError("Santana cancellation changed during POST")
            final = self._state_machine.transition(
                current, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at, reason="Santana signed event confirmed",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(final, expected_version=current.version)
            archived = uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=document_id,
                kind=FiscalArchiveKind.FISCAL_EVENT,
                content=receipt.event_xml, media_type="application/xml",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        return DurableSantanaCancellationOutcome(final, archived.entry_id)

    def preflight_santana_nfse_substitution(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
    ) -> tuple[NfseAuthorizationRequest, NfseAuthorizationRequest, str]:
        """Require one authorized original and a fresh, numbered same-issuer DPS."""
        if (
            not isinstance(original_id, str) or not original_id.strip()
            or not isinstance(replacement_id, str) or not replacement_id.strip()
            or original_id == replacement_id
        ):
            raise FiscalValidationError("Santana substitution needs two distinct documents")
        original, key = self.preflight_santana_nfse_cancellation(
            scope=scope, document_id=original_id,
        )
        replacement = self.load_prepared_nfse_authorization(scope, replacement_id)
        if (
            replacement.document.issuer.cnpj != original.document.issuer.cnpj
            or replacement.document.issuer.address.jurisdiction
            != original.document.issuer.address.jurisdiction
            or replacement.document.scope.identity_partition_key
            != original.document.scope.identity_partition_key
            or replacement.document.dps_number is None
            or replacement.document.dps_number == original.document.dps_number
        ):
            raise FiscalValidationError("Santana replacement must use a new scoped DPS")
        provider = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=replacement.document.issuer.address.jurisdiction,
            operation="authorize",
        )
        if provider != SANTANA_PROVIDER_ID:
            raise FiscalValidationError("Santana replacement provider binding mismatch")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(replacement_id, scope)
            state = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                state is None
                or state.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.RESERVED
                or attempts[0].document_id != replacement_id
                or attempts[0].request_fingerprint != replacement.request_fingerprint
            ):
                raise PersistenceStateError("Santana replacement not durably reserved")
        return original, replacement, key

    def substitute_prepared_santana_nfse(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
        reason_code: str, reason_description: str | None, approval_reference: str,
        gateway: SantanaSimplissHomologationGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableSantanaSubstitutionOutcome:
        """Claim both notes before one official replacement POST, finalize atomically."""
        if (
            not isinstance(gateway, SantanaSimplissHomologationGateway)
            or not isinstance(retention, RetentionPolicyMetadata)
            or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
        ):
            raise FiscalValidationError("Invalid Santana substitution dependencies")
        _, replacement, old_key = self.preflight_santana_nfse_substitution(
            scope=scope, original_id=original_id, replacement_id=replacement_id,
        )
        review = SantanaSubstitutionReview(
            original_document_id=original_id, original_access_key=old_key,
            reason_code=reason_code, reason_description=reason_description,
            human_approval_reference=approval_reference,
        )
        def verify_original(
            checked: NfseAuthorizationRequest, checked_review: SantanaSubstitutionReview,
        ) -> None:
            if checked != replacement or checked_review != review:
                raise FiscalValidationError("Santana substitution review identity changed")
            self.preflight_santana_nfse_substitution(
                scope=scope, original_id=original_id,
                replacement_id=replacement_id,
            )

        envelope = gateway.prepare_substitution(
            replacement, review=review, verify_original=verify_original,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            old = uow.lifecycle.get(original_id)
            new = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                old is None or old.state is not FiscalDocumentState.AUTHORIZED
                or new is None or new.state is not FiscalDocumentState.READY_TO_TRANSMIT
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.RESERVED
                or attempts[0].request_fingerprint != replacement.request_fingerprint
            ):
                raise PersistenceConflictError("Concurrent Santana substitution")
            old_claim = self._state_machine.transition(
                old, FiscalDocumentState.CANCEL_REQUESTED,
                occurred_at=occurred_at, reason="Santana replacement original claim",
                correlation_id=scope.correlation_id,
            )
            new_claim = self._state_machine.transition(
                new, FiscalDocumentState.TRANSMITTING,
                occurred_at=occurred_at, reason="Santana replacement DPS claim",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(old_claim, expected_version=old.version)
            uow.lifecycle.save(new_claim, expected_version=new.version)
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=original_id,
                kind=FiscalArchiveKind.OTHER,
                content=json.dumps({
                    "original_id": original_id, "replacement_id": replacement_id,
                    "original_key": old_key,
                    "reason_code": reason_code,
                    "approval_reference": approval_reference,
                    "replacement_fingerprint": replacement.request_fingerprint,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                media_type="application/vnd.nfcore.santana-substitution-intent.v1+json",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        # POST exactly once. On uncertainty both claims remain for reconciliation.
        result = gateway.submit_substitution(replacement, envelope)
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            old_current = uow.lifecycle.get(original_id)
            new_current = uow.lifecycle.get(replacement_id)
            current_attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                old_current != old_claim or new_current != new_claim
                or len(current_attempts) != 1
                or current_attempts[0].status is not IssuanceAttemptStatus.RESERVED
                or current_attempts[0].request_fingerprint
                != replacement.request_fingerprint
            ):
                raise PersistenceConflictError("Santana substitution state changed during POST")
            entry_id: str | None = None
            if result.status is AuthorizationStatus.AUTHORIZED:
                if result.invoice_reference is None or result.authorized_xml is None:
                    raise PersistenceStateError("Santana substitute lacks signed official XML")
                final_old = self._state_machine.transition(
                    old_current, FiscalDocumentState.CANCELLED,
                    occurred_at=occurred_at, reason="Santana replacement cancelled original",
                    correlation_id=scope.correlation_id,
                )
                final_new = self._state_machine.transition(
                    new_current, FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at, reason="Santana replacement officially authorized",
                    correlation_id=scope.correlation_id,
                )
                uow.idempotency.mark_authorized(
                    replacement.idempotency_key,
                    current_attempts[0].generation, result.invoice_reference,
                )
                saved = uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=replacement_id,
                    kind=FiscalArchiveKind.AUTHORIZED_XML,
                    content=result.authorized_xml, media_type="application/xml",
                    archived_at=occurred_at, retention=retention,
                ))
                entry_id = saved.entry_id
                # Official manual: confirmed replacement cancels original atomically
                # at Simpliss. Link the two identities; never synthesize event XML.
                uow.archive.append(FiscalArchiveEntry.build(
                    scope=scope, document_reference=original_id,
                    kind=FiscalArchiveKind.FISCAL_EVENT,
                    content=json.dumps({
                        "original_id": original_id, "original_key": old_key,
                        "replacement_id": replacement_id,
                        "replacement_key": result.invoice_reference,
                        "event": "automatic_substitution",
                        "municipality_ibge": SANTANA_IBGE,
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                    media_type="application/vnd.nfcore.santana-substitution.v1+json",
                    archived_at=occurred_at, retention=retention,
                ))
            elif result.status is AuthorizationStatus.REJECTED:
                if result.rejection_code is None:
                    raise PersistenceStateError("Santana rejected substitute has no code")
                final_old = self._state_machine.transition(
                    old_current, FiscalDocumentState.AUTHORIZED,
                    occurred_at=occurred_at, reason="Santana replacement rejected",
                    correlation_id=scope.correlation_id,
                )
                final_new = self._state_machine.transition(
                    new_current, FiscalDocumentState.REJECTED,
                    occurred_at=occurred_at, reason="Santana substitution DPS rejected",
                    correlation_id=scope.correlation_id,
                )
                uow.idempotency.mark_rejected(
                    replacement.idempotency_key,
                    current_attempts[0].generation, result.rejection_code,
                )
            else:
                return DurableSantanaSubstitutionOutcome(
                    old_claim, new_claim, result, None, True,
                )
            uow.lifecycle.save(final_old, expected_version=old_current.version)
            uow.lifecycle.save(final_new, expected_version=new_current.version)
            uow.commit()
            return DurableSantanaSubstitutionOutcome(
                final_old, final_new, result, entry_id, False,
            )


    def reconcile_santana_nfse_cancellation(
        self, *, scope: ExecutionScope, document_id: str,
        gateway: SantanaSimplissHomologationGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableSantanaRecoveryOutcome:
        """Read-only reconciliation for a previously claimed event 101101.

        A missing event never permits re-POST. One signed municipal event is
        required before promotion from CANCEL_REQUESTED to CANCELLED.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or not isinstance(document_id, str) or not document_id.strip()
            or not isinstance(gateway, SantanaSimplissHomologationGateway)
            or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Invalid Santana cancellation recovery request")
        with self._uow_factory() as uow:
            request = self._load_prepared_from_uow(uow, scope, document_id)
            if not isinstance(request, NfseAuthorizationRequest):
                raise PersistenceStateError("Santana recovery requires original NFS-e")
            uow.lifecycle.assert_scope(document_id, scope)
            state = uow.lifecycle.get(document_id)
            attempts = uow.idempotency.attempts(request.idempotency_key)
            if (
                state is None
                or state.state not in (
                    FiscalDocumentState.CANCEL_REQUESTED,
                    FiscalDocumentState.CANCELLED,
                )
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                or attempts[0].document_id != document_id
                or attempts[0].request_fingerprint != request.request_fingerprint
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != SANTANA_IBGE
                or scope.environment is not FiscalEnvironment.HOMOLOGATION
            ):
                raise PersistenceStateError(
                    "Santana recovery requires one claimed, authorized original"
                )
            key = attempts[0].result_reference
            if (
                not isinstance(key, str) or len(key) != 50
                or not key.isascii() or not key.isdecimal() or not key.startswith("35")
            ):
                raise PersistenceStateError("Santana recovery access key is invalid")
            entries = uow.archive.list_for_document(scope, document_id)
            intents = [
                item for item in entries
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type
                == "application/vnd.nfcore.santana-cancel-intent.v1+json"
            ]
            invoices = [
                item for item in entries
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(intents) != 1 or len(invoices) != 1:
                raise PersistenceStateError("Santana recovery lacks original audit proofs")
            for item in (intents[0], invoices[0]):
                FiscalArchiveVerifier().verify_entry(item)
            intent = json.loads(intents[0].content)
            if (
                intent.get("operation") != "santana_cancel_101101"
                or intent.get("original_id") != document_id
                or intent.get("key") != key
            ):
                raise PersistenceStateError("Santana cancellation intent identity differs")
            if state.state is FiscalDocumentState.CANCELLED:
                events = [
                    item for item in entries
                    if item.kind is FiscalArchiveKind.FISCAL_EVENT
                    and item.media_type == "application/xml"
                ]
                if len(events) != 1:
                    raise PersistenceStateError("Santana cancelled invoice lacks event XML")
                FiscalArchiveVerifier().verify_entry(events[0])
                return DurableSantanaRecoveryOutcome(
                    state, None, events[0].entry_id, True, False,
                )
        binding = self.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation="cancel",
        )
        if binding != SANTANA_PROVIDER_ID:
            raise FiscalValidationError("Santana recovery provider binding differs")
        result = gateway.query_verified_event(
            request, original_key=key, event_code="101101",
        )
        if result is None:
            return DurableSantanaRecoveryOutcome(
                state, None, None, False, True,
            )
        archive = FiscalArchiveEntry.build(
            scope=scope, document_reference=document_id,
            kind=FiscalArchiveKind.FISCAL_EVENT,
            content=result.signed_event_xml, media_type="application/xml",
            archived_at=occurred_at, retention=retention,
        )
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(document_id, scope)
            latest = uow.lifecycle.get(document_id)
            if latest != state:
                raise PersistenceConflictError(
                    "Santana original changed during read-only cancellation query"
                )
            previous = [
                row for row in uow.archive.list_for_document(scope, document_id)
                if row.kind is FiscalArchiveKind.FISCAL_EVENT
                and row.media_type == "application/xml"
            ]
            if previous:
                raise PersistenceConflictError("Santana cancellation already archived")
            updated = self._state_machine.transition(
                latest, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at,
                reason="Santana signed cancellation confirmed by read-only event GET",
                correlation_id=scope.correlation_id,
            )
            uow.lifecycle.save(updated, expected_version=latest.version)
            saved = uow.archive.append(archive)
            uow.commit()
        return DurableSantanaRecoveryOutcome(
            updated, None, saved.entry_id, True, False,
        )


    def reconcile_santana_nfse_substitution(
        self, *, scope: ExecutionScope, original_id: str, replacement_id: str,
        gateway: SantanaSimplissHomologationGateway,
        occurred_at: datetime, retention: RetentionPolicyMetadata,
    ) -> DurableSantanaRecoveryOutcome:
        """Complete an uncertain new-DPS POST by official event and NFS-e GETs.

        The original NFS-e event 105102 contains the new key. A second signed
        official receipt must also prove the exact reserved replacement DPS and
        original key before both lifecycles can be promoted atomically.
        """
        if (
            not isinstance(scope, ExecutionScope)
            or not isinstance(original_id, str) or not original_id.strip()
            or not isinstance(replacement_id, str) or not replacement_id.strip()
            or original_id == replacement_id
            or not isinstance(gateway, SantanaSimplissHomologationGateway)
            or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
            or not isinstance(retention, RetentionPolicyMetadata)
        ):
            raise FiscalValidationError("Invalid scoped Santana substitution recovery")
        with self._uow_factory() as uow:
            original = self._load_prepared_from_uow(uow, scope, original_id)
            replacement = self._load_prepared_from_uow(uow, scope, replacement_id)
            if (
                not isinstance(original, NfseAuthorizationRequest)
                or not isinstance(replacement, NfseAuthorizationRequest)
                or original.document.issuer.cnpj != replacement.document.issuer.cnpj
                or original.document.issuer.address.jurisdiction
                != replacement.document.issuer.address.jurisdiction
                or original.document.issuer.address.jurisdiction.municipality_ibge_code
                != SANTANA_IBGE
                or original.document.scope.identity_partition_key
                != replacement.document.scope.identity_partition_key
            ):
                raise PersistenceStateError(
                    "Santana recovery requires two scoped same-issuer NFS-e documents"
                )
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            before_original = uow.lifecycle.get(original_id)
            before_replacement = uow.lifecycle.get(replacement_id)
            original_attempts = uow.idempotency.attempts(original.idempotency_key)
            replacement_attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                before_original is None or before_replacement is None
                or len(original_attempts) != 1
                or original_attempts[0].status is not IssuanceAttemptStatus.AUTHORIZED
                or original_attempts[0].request_fingerprint
                != original.request_fingerprint
                or original_attempts[0].document_id != original_id
                or len(replacement_attempts) != 1
                or replacement_attempts[0].document_id != replacement_id
                or replacement_attempts[0].request_fingerprint
                != replacement.request_fingerprint
            ):
                raise PersistenceStateError(
                    "Santana substitution recovery has inconsistent issuance attempts"
                )
            original_key = original_attempts[0].result_reference
            if (
                not isinstance(original_key, str) or len(original_key) != 50
                or not original_key.isascii() or not original_key.isdecimal()
                or not original_key.startswith("35")
            ):
                raise PersistenceStateError("Santana original fiscal key is not confirmed")
            entries = uow.archive.list_for_document(scope, original_id)
            intents = [
                item for item in entries
                if item.kind is FiscalArchiveKind.OTHER
                and item.media_type
                == "application/vnd.nfcore.santana-substitution-intent.v1+json"
            ]
            source_xml = [
                item for item in entries
                if item.kind is FiscalArchiveKind.AUTHORIZED_XML
                and item.media_type == "application/xml"
            ]
            if len(intents) != 1 or len(source_xml) != 1:
                raise PersistenceStateError(
                    "Santana substitution original proof is missing or duplicated"
                )
            for item in (intents[0], source_xml[0]):
                FiscalArchiveVerifier().verify_entry(item)
            intent = json.loads(intents[0].content)
            if (
                intent.get("original_id") != original_id
                or intent.get("original_key") != original_key
                or intent.get("replacement_id") != replacement_id
                or intent.get("replacement_fingerprint")
                != replacement.request_fingerprint
            ):
                raise PersistenceStateError("Santana substitution approval changed")
            if (
                before_original.state is FiscalDocumentState.CANCELLED
                and before_replacement.state is FiscalDocumentState.AUTHORIZED
                and replacement_attempts[0].status is IssuanceAttemptStatus.AUTHORIZED
            ):
                linked = [
                    item for item in entries
                    if item.kind is FiscalArchiveKind.FISCAL_EVENT
                    and item.media_type
                    == "application/vnd.nfcore.santana-substitution.v1+json"
                ]
                if len(linked) != 1:
                    raise PersistenceStateError("Santana terminal substitution lacks link")
                FiscalArchiveVerifier().verify_entry(linked[0])
                return DurableSantanaRecoveryOutcome(
                    before_original, before_replacement, linked[0].entry_id,
                    True, False,
                )
            if (
                before_original.state is not FiscalDocumentState.CANCEL_REQUESTED
                or before_replacement.state is not FiscalDocumentState.TRANSMITTING
                or replacement_attempts[0].status is not IssuanceAttemptStatus.RESERVED
            ):
                raise PersistenceStateError(
                    "Santana substitution recovery requires uncertain original claims"
                )
        jurisdiction = original.document.issuer.address.jurisdiction
        for operation in ("cancel", "query", "authorize"):
            configured = self.resolve_configured_provider_id(
                scope=scope, document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=jurisdiction, operation=operation,
            )
            if configured != SANTANA_PROVIDER_ID:
                raise FiscalValidationError(
                    "Santana substitution recovery provider binding differs"
                )
        event = gateway.query_verified_event(
            original, original_key=original_key, event_code="105102",
        )
        if event is None:
            return DurableSantanaRecoveryOutcome(
                before_original, before_replacement, None, False, True,
            )
        if event.replacement_access_key is None:
            raise PersistenceStateError(
                "Signed Santana substitution lacks the replacement access key"
            )
        result = gateway.query_substitution_invoice(
            replacement, replacement_key=event.replacement_access_key,
            original_key=original_key,
        )
        if (
            result.status is not AuthorizationStatus.AUTHORIZED
            or result.invoice_reference != event.replacement_access_key
            or result.authorized_xml is None
        ):
            raise PersistenceStateError("Santana substitute has no verified official note")
        with self._uow_factory() as uow:
            uow.lifecycle.assert_scope(original_id, scope)
            uow.lifecycle.assert_scope(replacement_id, scope)
            old = uow.lifecycle.get(original_id)
            new = uow.lifecycle.get(replacement_id)
            attempts = uow.idempotency.attempts(replacement.idempotency_key)
            if (
                old != before_original or new != before_replacement
                or len(attempts) != 1
                or attempts[0].status is not IssuanceAttemptStatus.RESERVED
                or attempts[0].generation != replacement_attempts[0].generation
                or attempts[0].request_fingerprint
                != replacement.request_fingerprint
            ):
                raise PersistenceConflictError(
                    "Santana substitution state changed during read-only query"
                )
            old_terminal = self._state_machine.transition(
                old, FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at,
                reason="Santana signed substitution event 105102 verified by GET",
                correlation_id=scope.correlation_id,
            )
            new_terminal = self._state_machine.transition(
                new, FiscalDocumentState.AUTHORIZED,
                occurred_at=occurred_at,
                reason="Santana replacement DPS and official NFS-e verified by GET",
                correlation_id=scope.correlation_id,
            )
            uow.idempotency.mark_authorized(
                replacement.idempotency_key, attempts[0].generation,
                event.replacement_access_key,
            )
            uow.lifecycle.save(old_terminal, expected_version=old.version)
            uow.lifecycle.save(new_terminal, expected_version=new.version)
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=replacement_id,
                kind=FiscalArchiveKind.AUTHORIZED_XML,
                content=result.authorized_xml, media_type="application/xml",
                archived_at=occurred_at, retention=retention,
            ))
            proof = uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=original_id,
                kind=FiscalArchiveKind.FISCAL_EVENT,
                content=event.signed_event_xml, media_type="application/xml",
                archived_at=occurred_at, retention=retention,
            ))
            uow.archive.append(FiscalArchiveEntry.build(
                scope=scope, document_reference=original_id,
                kind=FiscalArchiveKind.FISCAL_EVENT,
                content=json.dumps({
                    "original_id": original_id, "original_key": original_key,
                    "replacement_id": replacement_id,
                    "replacement_key": event.replacement_access_key,
                    "event": "automatic_substitution",
                    "municipality_ibge": SANTANA_IBGE,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                media_type="application/vnd.nfcore.santana-substitution.v1+json",
                archived_at=occurred_at, retention=retention,
            ))
            uow.commit()
        return DurableSantanaRecoveryOutcome(
            old_terminal, new_terminal, proof.entry_id, True, False,
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
