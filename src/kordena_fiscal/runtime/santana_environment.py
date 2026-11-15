"""Opt-in Santana Simpliss 2026 startup using canonical A1 and fiscal UoW.

The exact REST URL must be recorded in an operator-reviewed on-host manifest.
No private certificate or municipal token belongs in the manifest or Git.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveKind, FiscalArchiveVerifier
from kordena_fiscal.compliance.nfse_preaudit import nfse_preaudit
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationIntent,
    NationalNfseCancellationReceipt,
)
from kordena_fiscal.gateway.santana_simpliss_events import (
    SantanaSimplissEventTransport,
    build_signed_santana_cancellation,
    validate_santana_event_xml,
)
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SANTANA_PROVIDER_ID,
    SantanaSimplissEndpoint,
    SantanaSimplissHomologationGateway,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.lifecycle import IssuanceAttemptStatus
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .config import RuntimeConfigurationError

_ENV = "NFCORE_SANTANA_SIMPLISS_CONFIG_PATH"
_FIELDS = frozenset({
    "provider_id", "municipality_ibge", "environment",
    "manual_version", "reviewed_issue_url", "operator_reviewed",
})


def _read_reviewed_manifest(path: str) -> SantanaSimplissEndpoint:
    if not path or len(path) > 2048:
        raise RuntimeConfigurationError("Invalid reviewed Santana manifest path")
    file = Path(path)
    if (
        not file.is_absolute() or file.is_symlink() or not file.is_file()
        or not 0 < file.stat().st_size <= 16384
    ):
        raise RuntimeConfigurationError("Santana requires a local reviewed manifest")
    try:
        config: Any = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise RuntimeConfigurationError("Malformed reviewed Santana manifest") from None
    if (
        not isinstance(config, dict) or set(config) != _FIELDS
        or config.get("provider_id") != SANTANA_PROVIDER_ID
        or config.get("municipality_ibge") != SANTANA_IBGE
        or config.get("environment") != "homologation"
        or config.get("manual_version") != "1.00"
        or config.get("operator_reviewed") is not True
    ):
        raise RuntimeConfigurationError("Santana contract requires reviewed official scope")
    return SantanaSimplissEndpoint(config["reviewed_issue_url"])


def build_santana_port_builder_from_environ(
    environ: Mapping[str, str], *, vault: EncryptedA1Vault | None,
) -> Callable[[FiscalApplicationService], SantanaSimplissHomologationGateway] | None:
    source = environ.get(_ENV, "").strip()
    if not source:
        return None
    if not isinstance(vault, EncryptedA1Vault):
        raise RuntimeConfigurationError("Santana requires canonical A1 vault")
    endpoint = _read_reviewed_manifest(source)

    def build(application: FiscalApplicationService) -> SantanaSimplissHomologationGateway:
        if not isinstance(application, FiscalApplicationService):
            raise RuntimeConfigurationError("Santana needs canonical fiscal application")

        def known_key(request: NfseAuthorizationRequest) -> str | None:
            with application._uow_factory() as uow:
                uow.lifecycle.assert_scope(
                    request.document.document_id, request.document.scope,
                )
                attempts = uow.idempotency.attempts(request.idempotency_key)
                if not attempts:
                    return None
                attempt = attempts[-1]
                if (
                    attempt.status is not IssuanceAttemptStatus.AUTHORIZED
                    or attempt.document_id != request.document.document_id
                    or attempt.request_fingerprint != request.request_fingerprint
                ):
                    return None
                return attempt.result_reference

        class CanonicalSantanaResolver:
            def resolve_provider_id(
                self, *, scope: ExecutionScope,
                document_kind: FiscalDocumentKind,
                jurisdiction: BrazilianJurisdiction, operation: str,
            ) -> str:
                return application.resolve_configured_provider_id(
                    scope=scope, document_kind=document_kind,
                    jurisdiction=jurisdiction, operation=operation,
                )

        def resolve_certificate(
            scope: ExecutionScope, cnpj: str,
        ) -> EphemeralCertificateMaterial:
            return vault.resolve(scope=scope, issuer_cnpj=cnpj)

        def submit_event(
            request: NfseAuthorizationRequest, key: str, reason_code: str,
            reason_description: str, approval_reference: str,
            occurred_at: datetime,
        ) -> NationalNfseCancellationReceipt:
            scope = request.document.scope
            doc_id = request.document.document_id

            def approve(intent: NationalNfseCancellationIntent) -> None:
                if (
                    intent.scope.identity_partition_key
                    != scope.identity_partition_key
                    or intent.invoice_reference != key
                    or intent.human_approval_reference != approval_reference
                ):
                    raise FiscalValidationError("Santana event approval identity mismatch")
                with application._uow_factory() as uow:
                    uow.lifecycle.assert_scope(doc_id, scope)
                    current = uow.lifecycle.get(doc_id)
                    if current is None or current.state.value != "cancel_requested":
                        raise FiscalValidationError("Santana event is not durably claimed")
                    candidates = [
                        entry for entry in uow.archive.list_for_document(scope, doc_id)
                        if entry.kind is FiscalArchiveKind.OTHER
                        and entry.media_type
                        == "application/vnd.nfcore.santana-cancel-intent.v1+json"
                    ]
                    if len(candidates) != 1:
                        raise FiscalValidationError("Santana cancellation lacks approval evidence")
                    FiscalArchiveVerifier().verify_entry(candidates[0])
                    source = json.loads(candidates[0].content)
                    if (
                        source.get("original_id") != doc_id
                        or source.get("key") != key
                        or source.get("approval_reference") != approval_reference
                        or source.get("reason_code") != reason_code
                        or source.get("reason") != reason_description.strip()
                    ):
                        raise FiscalValidationError("Santana event audit claim mismatch")

            material = resolve_certificate(scope, request.document.issuer.cnpj.value)
            intent = build_signed_santana_cancellation(
                request=request, key=key, reason_code=reason_code,
                reason_description=reason_description,
                approval_reference=approval_reference,
                occurred_at=occurred_at, material=material,
            )
            transport = SantanaSimplissEventTransport(
                endpoint=endpoint, provider_resolver=CanonicalSantanaResolver(),
                resolve_certificate=resolve_certificate,
                approve_cancellation=approve,
                validate_signed_event=lambda xml: validate_santana_event_xml(
                    xml, kind="request",
                ),
                validate_official_event=lambda xml: validate_santana_event_xml(
                    xml, kind="response",
                ),
            )
            return transport.cancel(intent)

        return SantanaSimplissHomologationGateway(
            endpoint=endpoint,
            provider_resolver=CanonicalSantanaResolver(),
            resolve_certificate=resolve_certificate,
            build_signed_dps=build_signed_dps,
            preaudit=nfse_preaudit,
            resolve_known_key=known_key,
            submit_event=submit_event,
        )

    return build
