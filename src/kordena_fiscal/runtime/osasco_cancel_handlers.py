"""Osasco cancellation handler on the same authorized Portal and fiscal UoW.

No caller can select a municipal provider, alter taxpayer scope, or replay a
cancellation after its state has been claimed. The web approval is explicit.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.gateway.osasco_rtc_cancellation_builder import (
    OsascoCancellationDecision,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

from .fiscal_runtime import (
    FiscalOperationHandler,
    PreflightFiscalOperationHandler,
)

_ISSUE = frozenset({
    "unit_id", "environment", "document_id",
    "human_approval", "cancellation_reason",
})


def build_osasco_cancel_handler(
    *,
    application: FiscalApplicationService,
    verified_cancel: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice, str],
        OsascoCancellationDecision,
    ],
    retention: RetentionPolicyMetadata,
) -> FiscalOperationHandler:
    """Attach an optional municipal cancellation operation to existing handlers."""
    if not callable(verified_cancel) or not isinstance(application, FiscalApplicationService):
        raise ValueError("Osasco cancellation must have verified canonical dependencies")

    def validate(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        reason = payload.get("cancellation_reason")
        if (
            not isinstance(key, str) or not 0 < len(key.strip()) <= 256
            or set(payload) != _ISSUE
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or not isinstance(payload.get("document_id"), str)
            or not str(payload["document_id"]).strip()
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 500
            or any(ord(ch) < 32 for ch in reason)
        ):
            raise FiscalValidationError("Human-reviewed Osasco cancellation required")
        application.preflight_osasco_nfse_cancellation(
            scope=scope, document_id=str(payload["document_id"]),
            cancellation_reason=reason,
        )

    def execute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        validate(scope, payload, key)
        outcome = application.cancel_prepared_osasco_nfse(
            scope=scope, document_id=str(payload["document_id"]),
            cancellation_reason=str(payload["cancellation_reason"]),
            submit_verified_cancel=verified_cancel,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "entry_id": outcome.archive_reference,
            "status": outcome.lifecycle.state.value,
            "municipality_ibge": "3534401",
            "official_fiscal_confirmation": outcome.decision.confirmed is True,
            "recovery_required": outcome.decision.confirmed is None,
            "rejection_code": outcome.decision.rejection_code,
        }

    return PreflightFiscalOperationHandler(execute, validate)


def build_osasco_substitution_handler(
    *,
    application: FiscalApplicationService,
    verified_substitute_cancel: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice, str],
        OsascoCancellationDecision,
    ],
    retention: RetentionPolicyMetadata,
) -> FiscalOperationHandler:
    """Two documents: official type-S cancellation, then normal issued replacement.

    This is NOT an atomic multi-provider substitution. The issuer may submit
    the prepared replacement only after confirmed cancellation of the original.
    """
    expected = frozenset({
        "unit_id", "environment", "original_id", "replacement_id",
        "human_approval", "cancellation_reason",
    })
    if not callable(verified_substitute_cancel):
        raise ValueError("Osasco type-S cancellation needs verified WCF dependency")

    def validate(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        reason = payload.get("cancellation_reason")
        if (
            not isinstance(key, str) or not 0 < len(key.strip()) <= 256
            or set(payload) != expected
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or not isinstance(payload.get("original_id"), str)
            or not isinstance(payload.get("replacement_id"), str)
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 500
            or any(ord(ch) < 32 for ch in reason)
        ):
            raise FiscalValidationError("Osasco substitution needs two reviewed documents")
        application.preflight_osasco_nfse_substitution(
            scope=scope, original_id=str(payload["original_id"]),
            replacement_id=str(payload["replacement_id"]),
            cancellation_reason=reason,
        )

    def execute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        validate(scope, payload, key)
        outcome = application.cancel_prepared_osasco_nfse(
            scope=scope, document_id=str(payload["original_id"]),
            replacement_id=str(payload["replacement_id"]),
            cancellation_reason=str(payload["cancellation_reason"]),
            submit_verified_cancel=verified_substitute_cancel,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "original_id": str(payload["original_id"]),
            "replacement_id": str(payload["replacement_id"]),
            "original_status": outcome.lifecycle.state.value,
            "replacement_status": "ready_to_transmit",
            "municipality_ibge": "3534401",
            "official_fiscal_confirmation": outcome.decision.confirmed is True,
            "recovery_required": outcome.decision.confirmed is None,
            "next_action": (
                "issueFiscalDocument" if outcome.decision.confirmed is True
                else "reconcileCancellation"
            ),
            "entry_id": outcome.archive_reference,
        }

    return PreflightFiscalOperationHandler(execute, validate)
