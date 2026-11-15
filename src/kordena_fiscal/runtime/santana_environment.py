"""Opt-in Santana Simpliss 2026 startup using canonical A1 and fiscal UoW.

The exact REST URL must be recorded in an operator-reviewed on-host manifest.
No private certificate or municipal token belongs in the manifest or Git.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.compliance.nfse_preaudit import nfse_preaudit
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SANTANA_PROVIDER_ID,
    SantanaSimplissEndpoint,
    SantanaSimplissHomologationGateway,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.lifecycle import IssuanceAttemptStatus
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

        return SantanaSimplissHomologationGateway(
            endpoint=endpoint,
            provider_resolver=application,
            resolve_certificate=lambda scope, cnpj: vault.resolve(
                scope=scope, issuer_cnpj=cnpj,
            ),
            build_signed_dps=build_signed_dps,
            preaudit=nfse_preaudit,
            resolve_known_key=known_key,
        )

    return build
