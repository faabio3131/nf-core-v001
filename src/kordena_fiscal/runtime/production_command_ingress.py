"""Production-only Command webhook secret resolver using canonical GSM authority.

This does not create a commercial binding, checkout or offer; activation is
explicit and fails closed without the approved API identity and matching
durable Command/secret bindings. No local HMAC or ADC production fallback.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

from google.cloud import secretmanager_v1

from kordena_fiscal.persistence.command_commercial import CommandCommercialStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.secrets import SecretReference, SecretResolver
from kordena_fiscal.vault.google_secret_manager import (
    DurableGsmReader,
    GoogleSdkSecretAccess,
    GoogleSignatureSecretBackend,
)

from .config import RuntimeConfigurationError
from .production_gsm import MODE, production_config, production_credentials

_COMMAND_MODE = "scoped-production-command-gsm-v1"
_PROVIDER = "google-secret-manager"


def production_command_resolver(
    database: PostgresFiscalDatabase,
    environ: Mapping[str, str] | None = None,
) -> SecretResolver | None:
    """Resolve only a platform-approved production Command binding.

    The key id selects a *previously configured* Command binding. The canonical
    secret binding, not environment-supplied tenant data, defines the scope.
    """
    source = os.environ if environ is None else environ
    mode = source.get("NFCORE_PRODUCTION_COMMAND_MODE", "")
    if not mode:
        if source.get("NFCORE_PRODUCTION_COMMAND_KEY_ID"):
            raise RuntimeConfigurationError("production Command ingress mode missing")
        return None
    if (
        mode != _COMMAND_MODE
        or source.get("NFCORE_ENVIRONMENT") != "production"
        or source.get("NFCORE_API_GSM_MODE") != MODE
    ):
        raise RuntimeConfigurationError("production Command ingress identity denied")
    key_id = source.get("NFCORE_PRODUCTION_COMMAND_KEY_ID", "")
    try:
        cfg = production_config(source, "API")
        stored = CommandCommercialStore(database.connection).binding(key_id)
        if stored is None:
            raise ValueError
        binding, revision = stored
        if (
            revision < 1
            or not binding.enabled
            or binding.key_id != key_id
            or binding.product_id != "nfcore"
            or binding.environment != "production"
            or binding.not_after <= datetime.now(UTC)
        ):
            raise ValueError
        reference = SecretReference(binding.secret_reference, binding.secret_version)
        with database() as uow:
            pinned = uow.secret_bindings.get(reference.reference_id)
        if (
            pinned is None
            or pinned.state != "active"
            or pinned.tenant_id != binding.scope.tenant_id
            or pinned.unit_id != binding.scope.unit_id
            or pinned.purpose != binding.scope.purpose
            or pinned.runtime_environment != "production"
            or pinned.fiscal_environment is not None
            or pinned.workload_id != "nfcore-api"
            or pinned.kind != "signature"
            or pinned.provider_id != _PROVIDER
            or pinned.canonical_version != reference.version
            or not pinned.resource.startswith(f"projects/{cfg.project}/secrets/")
            or (pinned.not_after is not None and pinned.not_after <= datetime.now(UTC))
        ):
            raise ValueError
    except Exception:
        raise RuntimeConfigurationError("production Command binding unavailable") from None

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
            workload_id="nfcore-api",
            allowed_resources=frozenset({pinned.resource}),
            project_numbers={cfg.project: cfg.project_number},
        )
        resolver = SecretResolver(
            GoogleSignatureSecretBackend(reader, provider_id=_PROVIDER),
            environment="production",
        )
        with resolver.resolve(reference, scope=binding.scope) as material:
            if len(material.reveal()) < 32:
                raise ValueError
        return resolver
    except Exception:
        raise RuntimeConfigurationError("production Command GSM material unavailable") from None
