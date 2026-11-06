"""Production-only Cakto webhook secret resolver using canonical GSM authority.

Mirrors ``production_command_ingress.py``'s governance exactly: opt-in only,
fails closed without the approved API identity and a matching durable secret
binding, and never derives, stores or guesses webhook secret material. This
module does not create the secret in Google Secret Manager nor the binding
row in ``fm_secret_bindings`` -- both must already exist, provisioned by an
operator through the existing governed admin tooling, before this resolver
can return anything other than ``None``/a configuration error.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

from google.cloud import secretmanager_v1

from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.secrets import SecretReference, SecretResolver, SecretScope
from kordena_fiscal.vault.google_secret_manager import (
    DurableGsmReader,
    GoogleSdkSecretAccess,
    GoogleSignatureSecretBackend,
)

from .config import RuntimeConfigurationError
from .production_gsm import MODE, production_config, production_credentials

_CAKTO_MODE = "scoped-production-cakto-webhook-gsm-v1"
_PROVIDER = "google-secret-manager"
_PURPOSE = "commercial-cakto-webhook"
_PLATFORM_TENANT = "nfcore-platform"
_WORKLOAD = "nfcore-api"


def production_cakto_webhook_secret(
    database: PostgresFiscalDatabase,
    environ: Mapping[str, str] | None = None,
) -> bytes | None:
    """Resolve the production Cakto webhook signature secret, fail-closed.

    Absent configuration (no mode, no reference) returns ``None`` and leaves
    the ``/webhooks/cakto`` route disabled, exactly as it is today. A
    configured reference must match a previously approved, active secret
    binding scoped to this exact purpose/workload/environment; any mismatch
    raises instead of silently disabling or guessing. The returned ``bytes``
    is a short-lived materialization used once at process composition time --
    rotation requires a redeploy, matching ``compose_cakto_commercial_runtime``'s
    existing static ``webhook_secret: bytes`` contract.
    """
    source = os.environ if environ is None else environ
    mode = source.get("NFCORE_PRODUCTION_CAKTO_WEBHOOK_MODE", "")
    reference_id = source.get("NFCORE_PRODUCTION_CAKTO_WEBHOOK_REFERENCE", "")
    if not mode and not reference_id:
        return None
    if (
        mode != _CAKTO_MODE
        or source.get("NFCORE_ENVIRONMENT") != "production"
        or source.get("NFCORE_API_GSM_MODE") != MODE
    ):
        raise RuntimeConfigurationError("production Cakto webhook identity denied")

    try:
        cfg = production_config(source, "API")
        version = int(source["NFCORE_PRODUCTION_CAKTO_WEBHOOK_VERSION"])
        reference = SecretReference(reference_id, version)
        scope = SecretScope(_PLATFORM_TENANT, None, _PURPOSE)
        with database() as uow:
            pinned = uow.secret_bindings.get(reference.reference_id)
        if (
            pinned is None
            or pinned.state != "active"
            or pinned.tenant_id != scope.tenant_id
            or pinned.unit_id != scope.unit_id
            or pinned.purpose != scope.purpose
            or pinned.runtime_environment != "production"
            or pinned.fiscal_environment is not None
            or pinned.workload_id != _WORKLOAD
            or pinned.kind != "signature"
            or pinned.provider_id != _PROVIDER
            or pinned.canonical_version != reference.version
            or not pinned.resource.startswith(f"projects/{cfg.project}/secrets/")
            or (pinned.not_after is not None and pinned.not_after <= datetime.now(UTC))
        ):
            raise ValueError
    except Exception:
        raise RuntimeConfigurationError(
            "production Cakto webhook binding unavailable"
        ) from None

    try:
        credentials, expiry = production_credentials(source, cfg)
        client = secretmanager_v1.SecretManagerServiceClient(
            credentials=credentials,
            client_options={
                "api_endpoint": "secretmanager.googleapis.com",
                "universe_domain": "googleapis.com",
            },
        )
        reader = DurableGsmReader(
            uow_factory=database,
            access=GoogleSdkSecretAccess(client, bootstrap_not_after=expiry),
            environment="production",
            workload_id=_WORKLOAD,
            allowed_resources=frozenset({pinned.resource}),
            project_numbers={cfg.project: cfg.project_number},
        )
        resolver = SecretResolver(
            GoogleSignatureSecretBackend(reader, provider_id=_PROVIDER),
            environment="production",
        )
        with resolver.resolve(reference, scope=scope) as material:
            secret_bytes = material.reveal()
            if len(secret_bytes) < 32:
                raise ValueError
            return secret_bytes
    except Exception:
        raise RuntimeConfigurationError(
            "production Cakto webhook GSM material unavailable"
        ) from None
