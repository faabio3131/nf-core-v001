"""Santana Simpliss cancellation/substitution through one canonical fiscal runtime.

No second API, no browser-signed events, no provider spoofing. All provider
POSTs are preceded by durable application lifecycle/idempotency claims.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SantanaSimplissHomologationGateway,
)

from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler

_CANCEL = frozenset({
    "unit_id", "environment", "document_id", "human_approval",
    "reason_code", "reason_description",
})
_SUBSTITUTE = frozenset({
    "unit_id", "environment", "original_id", "replacement_id",
    "human_approval", "reason_code", "reason_description",
})


def build_santana_event_handlers(
    *, application: FiscalApplicationService,
    gateway: SantanaSimplissHomologationGateway,
    retention: RetentionPolicyMetadata,
) -> Mapping[str, FiscalOperationHandler]:
    """Activate both reviewed operations only when the canonical A1 event port exists."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(gateway, SantanaSimplissHomologationGateway)
        or not gateway.supports_events
        or not isinstance(retention, RetentionPolicyMetadata)
    ):
        raise ValueError("Santana events need canonical scoped A1/application authority")

    def validate(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
        *, replacement: bool,
    ) -> None:
        expected = _SUBSTITUTE if replacement else _CANCEL
        reasons = {"01", "02", "03", "04", "05", "99"} if replacement else {
            "1", "2", "9",
        }
        description = payload.get("reason_description")
        if (
            not isinstance(key, str) or not 8 <= len(key.strip()) <= 256
            or set(payload) != expected
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or payload.get("reason_code") not in reasons
            or (description is not None and not isinstance(description, str))
            or (
                description is not None
                and (
                    not 15 <= len(description.strip()) <= 255
                    or any(ord(char) < 32 for char in description)
                )
            )
            or (not replacement and description is None)
        ):
            raise FiscalValidationError("Approved scoped Santana fiscal event required")
        if replacement:
            original_id = payload.get("original_id")
            new_id = payload.get("replacement_id")
            if (
                not isinstance(original_id, str) or not original_id.strip()
                or not isinstance(new_id, str) or not new_id.strip()
                or original_id == new_id
            ):
                raise FiscalValidationError("Santana substitution requires two documents")
            application.preflight_santana_nfse_substitution(
                scope=scope, original_id=original_id, replacement_id=new_id,
            )
        else:
            document_id = payload.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                raise FiscalValidationError("Santana original fiscal document is missing")
            application.preflight_santana_nfse_cancellation(
                scope=scope, document_id=document_id,
            )

    def preflight_cancel(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        validate(scope, payload, key, replacement=False)

    def cancel(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        preflight_cancel(scope, payload, key)
        assert key is not None
        outcome = application.cancel_prepared_santana_nfse(
            scope=scope, document_id=str(payload["document_id"]),
            reason_code=str(payload["reason_code"]),
            reason_description=str(payload["reason_description"]),
            approval_reference=key, gateway=gateway,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": str(payload["document_id"]),
            "status": outcome.lifecycle.state.value,
            "municipality_ibge": SANTANA_IBGE,
            "entry_id": outcome.archive_reference,
            "official_fiscal_confirmation": True,
        }

    def preflight_substitute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        validate(scope, payload, key, replacement=True)

    def substitute(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        preflight_substitute(scope, payload, key)
        assert key is not None
        outcome = application.substitute_prepared_santana_nfse(
            scope=scope, original_id=str(payload["original_id"]),
            replacement_id=str(payload["replacement_id"]),
            reason_code=str(payload["reason_code"]),
            reason_description=payload.get("reason_description"),
            approval_reference=key, gateway=gateway,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "original_id": str(payload["original_id"]),
            "replacement_id": str(payload["replacement_id"]),
            "original_status": outcome.original_lifecycle.state.value,
            "replacement_status": outcome.replacement_lifecycle.state.value,
            "municipality_ibge": SANTANA_IBGE,
            "entry_id": outcome.archive_reference,
            "official_fiscal_confirmation": (
                outcome.provider_result.status.value == "authorized"
            ),
            "recovery_required": outcome.recovery_required,
            "substitution_mode": "single_official_new_dps",
        }

    return {
        "cancelSantanaNfse": PreflightFiscalOperationHandler(
            cancel, preflight_cancel,
        ),
        "substituteSantanaNfse": PreflightFiscalOperationHandler(
            substitute, preflight_substitute,
        ),
    }
