"""Human-approved Jundiaí Giss cancellation and replacement review via one API/UoW.

The web caller cannot choose a provider, bypass the original authorized note,
alter a tenant, or re-send a municipal POST after its durable claim.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError

from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler
from .jundiai_operational_composition import JundiaiTrustedRuntimePorts

_CANCEL = frozenset({
    "unit_id", "environment", "document_id", "human_approval", "reason_code",
})
_RECOVER = frozenset({"unit_id", "environment", "document_id"})
_REPLACE = frozenset({
    "unit_id", "environment", "original_id", "replacement_id",
    "human_approval", "reason_code",
})


def build_jundiai_event_handlers(
    *, application: FiscalApplicationService,
    reviewed: JundiaiTrustedRuntimePorts, retention: RetentionPolicyMetadata,
) -> Mapping[str, FiscalOperationHandler]:
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(reviewed, JundiaiTrustedRuntimePorts)
        or not reviewed.supports_events
        or not isinstance(retention, RetentionPolicyMetadata)
    ):
        raise ValueError("Jundiai requires one canonical A1 event authority")
    submit = reviewed.submit_verified_cancel
    query = reviewed.query_verified_cancel
    assert submit is not None and query is not None

    def validate(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
        *, substitution: bool,
    ) -> None:
        expected = _REPLACE if substitution else _CANCEL
        if (
            not isinstance(key, str) or not 0 < len(key.strip()) <= 256
            or set(payload) != expected
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or payload.get("reason_code") not in ("1", "2", "4")
        ):
            raise FiscalValidationError("Approved Giss cancellation intent required")
        try:
            if substitution:
                old = payload.get("original_id")
                new = payload.get("replacement_id")
                if (
                    not isinstance(old, str) or not old.strip()
                    or not isinstance(new, str) or not new.strip()
                    or old == new
                ):
                    raise FiscalValidationError(
                        "Jundiai substitution requires original and replacement notes"
                    )
                application.preflight_jundiai_nfse_substitution(
                    scope=scope, original_id=old, replacement_id=new,
                    reason_code=str(payload["reason_code"]),
                )
            else:
                doc_id = payload.get("document_id")
                if not isinstance(doc_id, str) or not doc_id.strip():
                    raise FiscalValidationError("Original Giss note ID missing")
                application.preflight_jundiai_nfse_cancellation(
                    scope=scope, document_id=doc_id,
                    reason_code=str(payload["reason_code"]),
                )
        except (PersistenceConflictError, PersistenceStateError):
            raise FiscalValidationError(
                "Jundiai fiscal event requires one authorized original in the same unit"
            ) from None

    def cancel_preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        validate(scope, payload, key, substitution=False)

    def cancel(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        cancel_preflight(scope, payload, key)
        result = application.cancel_prepared_jundiai_nfse(
            scope=scope, document_id=str(payload["document_id"]),
            reason_code=str(payload["reason_code"]),
            submit_verified_cancel=submit, occurred_at=datetime.now(UTC),
            retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "status": result.lifecycle.state.value,
            "municipality_ibge": "3525904",
            "event_archive_id": result.archive_reference,
            "official_fiscal_confirmation": result.decision.confirmed is True,
            "recovery_required": result.decision.confirmed is None,
            "rejection_code": result.decision.rejection_code,
        }

    def substitute_preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        validate(scope, payload, key, substitution=True)

    def substitute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        substitute_preflight(scope, payload, key)
        outcome = application.cancel_prepared_jundiai_nfse(
            scope=scope, document_id=str(payload["original_id"]),
            replacement_id=str(payload["replacement_id"]),
            reason_code=str(payload["reason_code"]),
            submit_verified_cancel=submit,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "original_id": str(payload["original_id"]),
            "replacement_id": str(payload["replacement_id"]),
            "original_status": outcome.lifecycle.state.value,
            "replacement_status": "ready_to_transmit" if outcome.decision.confirmed
            else "awaiting_official_cancellation",
            "municipality_ibge": "3525904",
            "event_archive_id": outcome.archive_reference,
            "official_fiscal_confirmation": outcome.decision.confirmed is True,
            "recovery_required": outcome.decision.confirmed is None,
            "next_action": "issueFiscalDocument" if outcome.decision.confirmed
            else "reviewOriginalCancellation",
            "substitution_mode": "separate_original_cancel_then_replacement_issue",
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
            raise FiscalValidationError("Jundiai recovery needs original tenant-scoped note")
        original = application.load_sp4_original_rps(
            scope, str(payload["document_id"]),
        )
        if original.issuer_ibge != "3525904":
            raise FiscalValidationError("Jundiai recovery source municipality differs")

    def reconcile(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        recovery_preflight(scope, payload, key)
        outcome = application.reconcile_jundiai_nfse_cancellation(
            scope=scope, document_id=str(payload["document_id"]),
            query_verified_cancel=query,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "municipality_ibge": "3525904",
            "status": outcome.lifecycle.state.value,
            "event_archive_id": outcome.archive_reference,
            "official_fiscal_confirmation": outcome.decision.confirmed is True,
            "recovery_required": outcome.decision.confirmed is not True,
        }

    return {
        "reconcileJundiaiNfseCancellation": PreflightFiscalOperationHandler(
            reconcile, recovery_preflight,
        ),
        "cancelJundiaiNfse": PreflightFiscalOperationHandler(
            cancel, cancel_preflight,
        ),
        "substituteJundiaiNfse": PreflightFiscalOperationHandler(
            substitute, substitute_preflight,
        ),
    }
