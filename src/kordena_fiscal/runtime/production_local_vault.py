"""Production Worker composition with the local signing vault instead of GSM.

Same scoped handler and claim selection as production_gsm (webhook delivery only,
HOMOLOGATION fiscal scope) but the signing secret comes from LocalSigningVault.
Every value is operator-pinned in the environment; nothing is learned from data.
"""
from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable, Mapping

from kordena_fiscal.contingency.outbox import OutboxClaimSelection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.secrets import (
    SecretReference,
    SecretResolutionError,
    SecretResolver,
    SecretScope,
)
from kordena_fiscal.vault.local_signing_vault import (
    MIN_SECRET_BYTES,
    LocalSigningVault,
    LocalVaultSignatureSecretBackend,
)

from .config import RuntimeConfigurationError, RuntimeEnvironment, RuntimeSettings
from .secret_manager import build_gsm_worker_webhook_dependencies
from .worker_composition import (
    DELIVER_WEBHOOK_OPERATION,
    ScopedWorkerHandlerComposition,
    build_canonical_worker_handlers,
)

MODE = "scoped-production-local-vault-v1"
PREFIX = "NFCORE_WORKER_LOCAL_VAULT_"
_REF_RE = re.compile(r"sec_[A-Za-z0-9_-]{8,120}\Z")
_FIELDS = ("DIR", "KEY_BASE64", "TENANT_ID", "UNIT_ID", "HOST_NAMESPACE",
           "DESTINATION_ID", "SIGNING_REFERENCE", "SIGNING_VERSION", "PROVIDER_ID")


def local_vault_config(
    source: Mapping[str, str],
) -> tuple[LocalSigningVault, SecretReference, SecretScope, str, str, str]:
    try:
        if source.get("NFCORE_ENVIRONMENT") != "production":
            raise ValueError
        if any(not source.get(PREFIX + field, "").strip() for field in _FIELDS):
            raise ValueError
        values = {field: source[PREFIX + field].strip() for field in _FIELDS}
        if "*" in (values["TENANT_ID"], values["UNIT_ID"], values["HOST_NAMESPACE"],
                   values["DESTINATION_ID"]):
            raise ValueError
        if not _REF_RE.fullmatch(values["SIGNING_REFERENCE"]):
            raise ValueError
        key = base64.b64decode(values["KEY_BASE64"], validate=True)
        vault = LocalSigningVault(directory=values["DIR"], master_key=key)
        reference = SecretReference(values["SIGNING_REFERENCE"], int(values["SIGNING_VERSION"]))
        scope = SecretScope(values["TENANT_ID"], values["UNIT_ID"], "webhook-signing")
    except (KeyError, ValueError, TypeError, binascii.Error, SecretResolutionError):
        raise RuntimeConfigurationError("production local vault configuration denied") from None
    return (vault, reference, scope, values["PROVIDER_ID"], values["HOST_NAMESPACE"],
            values["DESTINATION_ID"])


def production_local_vault_worker_handler_factory(
    environ: Mapping[str, str],
) -> Callable[[PostgresFiscalDatabase, RuntimeSettings], ScopedWorkerHandlerComposition]:
    if environ.get(PREFIX + "MODE") != MODE:
        raise RuntimeConfigurationError("production Worker local vault mode denied")
    vault, reference, scope, provider, namespace, destination = local_vault_config(environ)

    def build(
        database: PostgresFiscalDatabase, settings: RuntimeSettings,
    ) -> ScopedWorkerHandlerComposition:
        if settings.environment is not RuntimeEnvironment.PRODUCTION:
            raise RuntimeConfigurationError("local vault Worker requires production")
        resolver = SecretResolver(
            LocalVaultSignatureSecretBackend(vault, provider_id=provider),
            environment="production",
        )
        try:
            with resolver.resolve(reference, scope=scope) as material:
                if len(material.reveal()) < MIN_SECRET_BYTES:
                    raise RuntimeConfigurationError("signing material too weak")
        except SecretResolutionError:
            raise RuntimeConfigurationError("local vault signing secret unavailable") from None
        webhook = build_gsm_worker_webhook_dependencies(
            resolver=resolver, reference=reference, scope=scope, destination_id=destination,
        )
        selection = OutboxClaimSelection(
            scope=ExecutionScope(
                tenant_id=scope.tenant_id, unit_id=scope.unit_id or "",
                host_namespace=namespace, environment=FiscalEnvironment.HOMOLOGATION,
                correlation_id="production-worker-webhook-claim",
            ),
            operations=frozenset({DELIVER_WEBHOOK_OPERATION}),
        )
        return ScopedWorkerHandlerComposition(
            handlers=build_canonical_worker_handlers(uow_factory=database, webhook=webhook),
            claim_selection=selection,
        )

    return build
