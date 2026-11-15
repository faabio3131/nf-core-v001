"""National NFS-e cancellation through the existing Portal and fiscal UoW.

A reviewed Portal request never supplies signed XML, A1 bytes or a provider ID.
The application claims the authorized invoice durably before a single SEFIN POST.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationHomologationTransport,
    NationalNfseCancellationIntent,
    build_signed_national_cancellation,
    validate_national_event_xml,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler

_CANCEL_FIELDS = frozenset({
    "unit_id", "environment", "document_id", "human_approval",
    "reason_code", "reason_description",
})


def build_national_event_handlers(
    *, application: FiscalApplicationService,
    certificate_vault: EncryptedA1Vault,
    provider_resolver: ProviderSelectionResolver,
    retention: RetentionPolicyMetadata,
) -> Mapping[str, FiscalOperationHandler]:
    """Register national events only when canonical fiscal authorities exist."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not callable(getattr(certificate_vault, "resolve", None))
        or not callable(getattr(provider_resolver, "resolve_provider_id", None))
        or not isinstance(retention, RetentionPolicyMetadata)
    ):
        raise ValueError("National fiscal events need governed A1/application authority")

    def preflight(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> None:
        reason = payload.get("reason_description")
        if (
            set(payload) != _CANCEL_FIELDS
            or not isinstance(key, str) or not 8 <= len(key.strip()) <= 128
            or not key.isascii()
            or payload.get("unit_id") != scope.unit_id
            or payload.get("environment") != scope.environment.value
            or payload.get("human_approval") is not True
            or payload.get("reason_code") not in ("1", "2", "9")
            or not isinstance(reason, str) or not 15 <= len(reason.strip()) <= 255
            or any(ord(char) < 32 for char in reason)
            or not isinstance(payload.get("document_id"), str)
            or not payload["document_id"].strip()
        ):
            raise FiscalValidationError("National cancellation requires human-reviewed scope")
        application.preflight_national_nfse_cancellation(
            scope=scope, document_id=str(payload["document_id"]),
        )

    def cancel(
        scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
    ) -> Mapping[str, Any]:
        preflight(scope, payload, key)
        assert key is not None
        document_id = str(payload["document_id"])

        def submit_verified_cancel(
            request: Any, original_key: str, code: str, explanation: str,
            approval: str, when: datetime,
        ) -> Any:
            def approve(intent: NationalNfseCancellationIntent) -> None:
                if (
                    intent.scope.identity_partition_key != scope.identity_partition_key
                    or intent.invoice_reference != original_key
                    or intent.issuer != request.document.issuer.cnpj
                    or intent.human_approval_reference != approval
                ):
                    raise FiscalValidationError("National event approval identity mismatch")
                application.validate_claimed_national_nfse_cancellation(
                    scope=scope, document_id=document_id,
                    original_key=original_key, approval_reference=approval,
                )

            transport = NationalNfseCancellationHomologationTransport(
                provider_resolver=provider_resolver,
                resolve_certificate=lambda s, cnpj: certificate_vault.resolve(
                    scope=s, issuer_cnpj=cnpj,
                ),
                validate_signed_event=lambda xml: validate_national_event_xml(
                    xml, kind="request",
                ),
                approve_cancellation=approve,
                validate_official_event=lambda xml: validate_national_event_xml(
                    xml, kind="response",
                ),
            )
            material = certificate_vault.resolve(
                scope=request.document.scope,
                issuer_cnpj=request.document.issuer.cnpj.value,
            )
            intent = build_signed_national_cancellation(
                request=request, key=original_key,
                reason_code=code, reason_description=explanation,
                approval_reference=approval, occurred_at=when,
                material=material,
            )
            return transport.cancel(intent)

        result = application.cancel_prepared_national_nfse(
            scope=scope, document_id=document_id,
            reason_code=str(payload["reason_code"]),
            reason_description=str(payload["reason_description"]),
            approval_reference=key, submit_verified_cancel=submit_verified_cancel,
            occurred_at=datetime.now(UTC), retention=retention,
        )
        return {
            "document_id": document_id,
            "status": result.lifecycle.state.value,
            "entry_id": result.archive_reference,
            "official_fiscal_confirmation": True,
        }

    return {"cancelNationalNfse": PreflightFiscalOperationHandler(cancel, preflight)}
