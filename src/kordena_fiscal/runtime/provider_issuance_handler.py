"""Opt-in adapter from the canonical fiscal path to durable prepared issuance.

The resolver is supplied by trusted composition and loads a prepared, validated
request from the existing preparation/signing authority. Browser payloads never
supply signed XML, provider selection, certificate material or final outcomes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import (
    DurableNfseRecoveryOutcome,
    DurableRecoveryOutcome,
    FiscalApplicationService,
)
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.gateway import AuthorizationRequest, FiscalGatewayClient
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseGatewayClient,
    NfseQueryClient,
)
from kordena_fiscal.operations import FiscalOperationsClient
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError

from .fiscal_runtime import FiscalOperationHandler

PreparedIssuanceResolver = Callable[
    [ExecutionScope, str], AuthorizationRequest | NfseAuthorizationRequest
]


@dataclass(frozen=True, slots=True)
class _PreparedOperationHandler:
    execute: FiscalOperationHandler
    preflight: Callable[[ExecutionScope, Mapping[str, Any], str | None], None]

    def __call__(
        self, scope: ExecutionScope, payload: Mapping[str, Any], key: str | None
    ) -> Mapping[str, Any]:
        return self.execute(scope, payload, key)


def _document_reference(payload: Mapping[str, Any], key: str | None) -> str:
    if set(payload) - {"document_id", "unit_id", "environment"}:
        raise FiscalValidationError("operation accepts only a prepared document reference")
    document_id = payload.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        raise FiscalValidationError("document_id is required")
    if not isinstance(key, str) or not key.strip():
        raise FiscalValidationError("HTTP idempotency key is required")
    return document_id


def build_provider_issuance_handler(
    application: FiscalApplicationService,
    *,
    resolve_prepared: PreparedIssuanceResolver,
    gateway: FiscalGatewayClient | NfseGatewayClient,
    nfse_gateway: NfseGatewayClient | None = None,
) -> FiscalOperationHandler:
    """Bind one explicitly configured document family; never enable a default provider."""

    def resolve(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None
    ) -> tuple[str, AuthorizationRequest | NfseAuthorizationRequest]:
        document_id = _document_reference(payload, key)
        request = resolve_prepared(scope, document_id)
        request_scope = (
            request.scope if isinstance(request, AuthorizationRequest) else request.document.scope
        )
        if request_scope.identity_partition_key != scope.identity_partition_key:
            raise FiscalValidationError("prepared issuance does not match execution scope")
        select_gateway(request)
        return document_id, request

    def select_gateway(
        request: AuthorizationRequest | NfseAuthorizationRequest,
    ) -> FiscalGatewayClient | NfseGatewayClient:
        if isinstance(request, NfseAuthorizationRequest):
            selected = nfse_gateway or gateway
            if not isinstance(selected, NfseGatewayClient):
                raise FiscalValidationError("NFS-e provider gateway is not configured")
            return selected
        if not isinstance(gateway, FiscalGatewayClient):
            raise FiscalValidationError("XML provider gateway is not configured")
        return gateway

    def preflight(scope: ExecutionScope, payload: Mapping[str, Any], key: str | None) -> None:
        # The trusted resolver is read-only; no preparation or provider dispatch here.
        try:
            resolve(scope, payload, key)
        except (PersistenceConflictError, PersistenceStateError) as exc:
            raise FiscalValidationError("prepared document is unavailable in this scope") from exc

    def issue(
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        document_id, request = resolve(scope, payload, idempotency_key)
        selected_gateway = select_gateway(request)
        # HTTP intent keys remain distinct from the canonical fiscal request key.
        outcome = application.authorize_prepared_document(
            document_id=document_id,
            request=request,
            gateway=selected_gateway,
            occurred_at=datetime.now(UTC),
        )
        return {
            "document_id": outcome.attempt.document_id,
            "status": outcome.lifecycle.state.value,
            "replay": outcome.replay,
            "recovery_required": outcome.recovery_required,
            "result_reference": outcome.attempt.result_reference,
            "rejection_reason": outcome.attempt.rejection_reason,
        }

    return _PreparedOperationHandler(issue, preflight)


def build_provider_reconciliation_handler(
    application: FiscalApplicationService,
    *,
    client: FiscalOperationsClient,
    archive_retention: RetentionPolicyMetadata,
    nfse_client: NfseQueryClient | None = None,
) -> FiscalOperationHandler:
    """Resolve uncertainty through the configured provider; browser supplies no outcome."""

    def preflight(scope: ExecutionScope, payload: Mapping[str, Any], key: str | None) -> None:
        document_id = _document_reference(payload, key)
        try:
            prepared = application.load_prepared_document_authorization(scope, document_id)
            if isinstance(prepared, NfseAuthorizationRequest) and not isinstance(
                nfse_client, NfseQueryClient
            ):
                raise FiscalValidationError("NFS-e recovery query is not configured")
        except (PersistenceConflictError, PersistenceStateError) as exc:
            raise FiscalValidationError("prepared document is unavailable in this scope") from exc

    def reconcile(
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        document_id = _document_reference(payload, idempotency_key)
        prepared = application.load_prepared_document_authorization(scope, document_id)
        outcome: DurableNfseRecoveryOutcome | DurableRecoveryOutcome
        if isinstance(prepared, NfseAuthorizationRequest):
            if not isinstance(nfse_client, NfseQueryClient):
                raise FiscalValidationError("NFS-e recovery query is not configured")
            outcome = application.reconcile_prepared_nfse_authorization(
                scope=scope,
                document_id=document_id,
                client=nfse_client,
                occurred_at=datetime.now(UTC),
                retention=archive_retention,
            )
            query_status = (
                outcome.query_result.status.value if outcome.query_result is not None else None
            )
        else:
            outcome = application.reconcile_prepared_authorization(
                scope=scope,
                document_id=document_id,
                client=client,
                occurred_at=datetime.now(UTC),
                retention=archive_retention,
            )
            query_status = (
                outcome.query_result.status.value if outcome.query_result is not None else None
            )
        return {
            "document_id": outcome.attempt.document_id,
            "status": outcome.lifecycle.state.value,
            "replay": outcome.replay,
            "recovery_required": outcome.recovery_required,
            "result_reference": outcome.attempt.result_reference,
            "query_status": query_status,
        }

    return _PreparedOperationHandler(reconcile, preflight)
