"""Human-approved Barueri cancel/substitution and read-only event reconciliation.

These operations use the same canonical FiscalApplicationService, archived
source RPS, A1 transport, lifecycle, Portal permissions and tenant scope.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.persistence.ports import (
    PersistenceConflictError,
    PersistenceStateError,
)

from .barueri_operational_composition import BarueriTrustedRuntimePorts
from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler

_CANCEL = frozenset({
    "unit_id", "environment", "document_id", "human_approval",
    "reason_code", "cancellation_reason",
})
_REPLACE = frozenset({
    "unit_id", "environment", "original_id", "replacement_id",
    "human_approval", "cancellation_reason",
    "substitution_justification_code",
})
_RECOVER = frozenset({"unit_id", "environment", "document_id"})


def build_barueri_event_handlers(
    *, application: FiscalApplicationService,
    reviewed: BarueriTrustedRuntimePorts,
    retention: RetentionPolicyMetadata,
) -> Mapping[str, FiscalOperationHandler]:
    """Attach one governed asynchronous event path to the existing dispatcher."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(reviewed, BarueriTrustedRuntimePorts)
        or not reviewed.supports_events
        or not isinstance(retention, RetentionPolicyMetadata)
    ):
        raise ValueError("Barueri requires reviewed A1 event authority and shared UoW")
    decoder = reviewed.decode_official_invoice
    prepare_event = reviewed.prepare_cancellation_event
    assert decoder is not None and prepare_event is not None

    def approved_original(
        scope: ExecutionScope, document_id: str, replacement_id: str | None = None,
    ) -> None:
        try:
            application.preflight_barueri_nfse_cancellation(
                scope=scope, document_id=document_id,
                replacement_id=replacement_id, decode_official_invoice=decoder,
            )
        except (PersistenceStateError, PersistenceConflictError):
            # A duplicate, stale, cross-unit or already finalized event is
            # a rejected user request; it must not surface as an HTTP 500.
            raise FiscalValidationError(
                "Barueri event requires an authorized original and current scope"
            ) from None

    def check(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
        *, replacement: bool,
    ) -> None:
        expected = _REPLACE if replacement else _CANCEL
        reason = payload.get("cancellation_reason")
        if (
            not isinstance(key, str) or not 0 < len(key.strip()) <= 256
            or set(payload) != expected
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 180
            or any(ord(ch) < 32 for ch in reason)
        ):
            raise FiscalValidationError("Human-reviewed Barueri event required")
        if replacement:
            original_id = payload.get("original_id")
            replacement_id = payload.get("replacement_id")
            if (
                not isinstance(original_id, str)
                or not original_id.strip()
                or not isinstance(replacement_id, str)
                or not replacement_id.strip()
                or original_id == replacement_id
            ):
                raise FiscalValidationError("Barueri replacement needs two distinct documents")
            if payload.get("substitution_justification_code") not in (
                "1", "2", "3", "4", "5", "9",
            ):
                raise FiscalValidationError("Barueri v4.4 justification code required")
            approved_original(scope, original_id, replacement_id)
        else:
            document_id = payload.get("document_id")
            if (
                not isinstance(document_id, str) or not document_id.strip()
                or payload.get("reason_code") not in ("01", "02")
            ):
                raise FiscalValidationError("Barueri cancellation reason code invalid")
            approved_original(scope, document_id)

    def cancel_preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        check(scope, payload, key, replacement=False)

    def cancel(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        cancel_preflight(scope, payload, key)
        outcome = application.cancel_prepared_barueri_nfse(
            scope=scope, document_id=str(payload["document_id"]),
            decode_official_invoice=decoder, prepare_event=prepare_event,
            submit_event=reviewed.submit_cancellation_event,
            reason_code=str(payload["reason_code"]),
            cancellation_reason=str(payload["cancellation_reason"]),
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "status": outcome.lifecycle.state.value,
            "municipality_ibge": "3505708",
            "event_archive_id": outcome.archive_reference,
            "protocol": outcome.protocol,
            "official_fiscal_confirmation": False,
            "recovery_required": outcome.recovery_required,
        }

    def substitute_preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        check(scope, payload, key, replacement=True)

    def substitute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        substitute_preflight(scope, payload, key)
        outcome = application.cancel_prepared_barueri_nfse(
            scope=scope, document_id=str(payload["original_id"]),
            replacement_id=str(payload["replacement_id"]),
            decode_official_invoice=decoder, prepare_event=prepare_event,
            submit_event=reviewed.submit_cancellation_event,
            reason_code="03", cancellation_reason=str(payload["cancellation_reason"]),
            substitution_justification_code=str(
                payload["substitution_justification_code"]
            ),
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "original_id": str(payload["original_id"]),
            "replacement_id": str(payload["replacement_id"]),
            "original_status": outcome.lifecycle.state.value,
            "replacement_status": "transmitting",
            "municipality_ibge": "3505708",
            "event_archive_id": outcome.archive_reference,
            "protocol": outcome.protocol,
            "official_fiscal_confirmation": False,
            "next_action": "reconcileBarueriNfseCancellation",
        }

    def recovery_preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        if (
            set(payload) != _RECOVER
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or not isinstance(payload.get("document_id"), str)
            or not payload["document_id"].strip()
        ):
            raise FiscalValidationError("Barueri event lookup requires tenant-scoped document")

    def reconcile(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        recovery_preflight(scope, payload, key)
        outcome = application.reconcile_barueri_nfse_cancellation(
            scope=scope, document_id=str(payload["document_id"]),
            decode_official_invoice=decoder,
            query_official_event=reviewed.query_cancellation_event,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "status": outcome.lifecycle.state.value,
            "municipality_ibge": "3505708",
            "event_archive_id": outcome.archive_reference,
            "protocol": outcome.protocol,
            "official_fiscal_confirmation": not outcome.recovery_required,
            "recovery_required": outcome.recovery_required,
            "replay": outcome.replay,
        }

    return {
        "cancelBarueriNfse": PreflightFiscalOperationHandler(
            cancel, cancel_preflight,
        ),
        "substituteBarueriNfse": PreflightFiscalOperationHandler(
            substitute, substitute_preflight,
        ),
        "reconcileBarueriNfseCancellation": PreflightFiscalOperationHandler(
            reconcile, recovery_preflight,
        ),
    }
