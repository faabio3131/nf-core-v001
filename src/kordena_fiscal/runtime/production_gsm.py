"""Production-only, explicitly scoped GSM composition for Contabo workloads.

No ADC discovery, network provisioning, static pilot identity, or fallback secret.
No fiscal production grant: the restricted webhook outbox claims homologation
operations until the separate fiscal production authority is certified.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from google.cloud import secretmanager_v1
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from kordena_fiscal.contingency.outbox import OutboxClaimSelection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.s2s import WebhookSecurity
from kordena_fiscal.security.secret_binding import SecretBinding
from kordena_fiscal.security.secrets import (
    SecretReference,
    SecretResolutionError,
    SecretResolver,
    SecretScope,
)
from kordena_fiscal.vault.google_secret_manager import (
    DurableGsmReader,
    GoogleSdkSecretAccess,
    GoogleSignatureSecretBackend,
)

from .config import RuntimeConfigurationError, RuntimeEnvironment, RuntimeSettings
from .secret_manager import build_gsm_worker_webhook_dependencies
from .worker_composition import (
    DELIVER_WEBHOOK_OPERATION,
    ScopedWorkerHandlerComposition,
    build_canonical_worker_handlers,
)

MODE = "scoped-production-sa-v1"
_BINDINGS_MODE = "platform-admin-v1"
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,62}\Z")
_SA_RE = re.compile(r"[a-z][a-z0-9-]{2,62}@[a-z][a-z0-9-]{4,62}\.iam\.gserviceaccount\.com\Z")
_REF_RE = re.compile(r"sec_[A-Za-z0-9_-]{8,120}\Z")
_KEY_RE = re.compile(r"[a-f0-9]{40}\Z")
_FIELDS = (
    "TENANT_ID",
    "UNIT_ID",
    "SIGNING_REFERENCE",
    "SIGNING_VERSION",
    "PROVIDER_ID",
    "RESOURCE",
    "CLOUD_VERSION",
)


@dataclass(frozen=True, slots=True)
class ProductionWorkloadIdentity:
    """Only the pinned production service account identity, no fake tenant scope."""

    role: Literal["API", "WORKER"]
    project: str
    service_account: str


@dataclass(frozen=True, slots=True)
class ProductionGsmConfig:
    role: Literal["API", "WORKER"]
    project: str
    project_number: str
    service_account: str
    scope: SecretScope
    reference: SecretReference
    provider: str
    resource: str
    cloud_version: str

    def binding(self) -> SecretBinding:
        if not isinstance(self.reference.version, int):
            raise RuntimeConfigurationError("production GSM reference version required")
        return SecretBinding(
            reference_id=self.reference.reference_id,
            tenant_id=self.scope.tenant_id,
            unit_id=self.scope.unit_id,
            purpose="webhook-signing",
            runtime_environment="production",
            fiscal_environment=None,
            provider_id=self.provider,
            workload_id=f"nfcore-{self.role.lower()}",
            kind="signature",
            canonical_version=self.reference.version,
            resource=self.resource,
            cloud_version=self.cloud_version,
        )


def production_config(
    source: Mapping[str, str],
    role: Literal["API", "WORKER"],
) -> ProductionGsmConfig:
    """Operator-pinned allowlist, never learned from payloads or ADC."""
    try:
        if source.get("NFCORE_ENVIRONMENT") != "production":
            raise ValueError
        project = source["NFCORE_GSM_PROJECT_ID"]
        allowlist = source["NFCORE_GSM_ALLOWED_PROJECTS"].split(",")
        number = source["NFCORE_GSM_PROJECT_NUMBER"]
        if (
            not _PROJECT_RE.fullmatch(project)
            or "staging" in project
            or not allowlist
            or any(not _PROJECT_RE.fullmatch(item) for item in allowlist)
            or len(allowlist) != len(set(allowlist))
            or project not in allowlist
            or not re.fullmatch(r"[1-9][0-9]{5,19}", number)
        ):
            raise ValueError
        api_sa = source["NFCORE_GSM_API_SERVICE_ACCOUNT"]
        worker_sa = source["NFCORE_GSM_WORKER_SERVICE_ACCOUNT"]
        if (
            not _SA_RE.fullmatch(api_sa)
            or not _SA_RE.fullmatch(worker_sa)
            or api_sa == worker_sa
            or not api_sa.endswith(f"@{project}.iam.gserviceaccount.com")
            or not worker_sa.endswith(f"@{project}.iam.gserviceaccount.com")
        ):
            raise ValueError
        prefix = f"NFCORE_{role}_GSM_"
        if any(not source.get(prefix + field) for field in _FIELDS):
            raise ValueError
        tenant, unit = source[prefix + "TENANT_ID"], source[prefix + "UNIT_ID"]
        if "*" in (tenant, unit) or not unit.strip():
            raise ValueError
        refid = source[prefix + "SIGNING_REFERENCE"]
        if not _REF_RE.fullmatch(refid):
            raise ValueError
        version = int(source[prefix + "SIGNING_VERSION"])
        reference = SecretReference(refid, version)
        resource = source[prefix + "RESOURCE"]
        if not re.fullmatch(
            rf"projects/{re.escape(project)}/secrets/[A-Za-z0-9_-]{{1,255}}", resource
        ):
            raise ValueError
        cloud_version = source[prefix + "CLOUD_VERSION"]
        scope = SecretScope(tenant, unit, "webhook-signing")
        provider = source[prefix + "PROVIDER_ID"]
        cfg = ProductionGsmConfig(
            role,
            project,
            number,
            api_sa if role == "API" else worker_sa,
            scope,
            reference,
            provider,
            resource,
            cloud_version,
        )
        cfg.binding()
        return cfg
    except (KeyError, ValueError, TypeError, SecretResolutionError):
        raise RuntimeConfigurationError("production GSM configuration denied") from None


def validated_binding(database: PostgresFiscalDatabase, cfg: ProductionGsmConfig) -> None:
    """Fail before loading identity unless metadata matches the fresh production DB."""
    try:
        with database() as uow:
            current = uow.secret_bindings.get(cfg.reference.reference_id)
        if (
            current is None
            or current != cfg.binding()
            or current.state != "active"
            or (current.not_after is not None and current.not_after <= datetime.now(UTC))
        ):
            raise ValueError
    except Exception:
        raise RuntimeConfigurationError("production GSM durable binding unavailable") from None


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _time(source: Mapping[str, str], name: str) -> datetime:
    parsed = datetime.fromisoformat(source[name])
    if parsed.utcoffset() is None:
        raise ValueError
    return parsed


def production_credentials(
    source: Mapping[str, str],
    cfg: ProductionGsmConfig | ProductionWorkloadIdentity,
) -> tuple[ServiceAccountCredentials, datetime]:
    """One locked-down, mounted SA identity; no ambient identity or JSON env."""
    prefix = f"NFCORE_{cfg.role}_GSM_"
    try:
        if source.get(prefix + "CREDENTIAL_JSON") or source.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise ValueError
        filename = Path(source[prefix + "CREDENTIAL_FILE"])
        info = filename.lstat()
        if (
            not filename.is_absolute()
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or not 128 <= info.st_size <= 65536
        ):
            raise ValueError
        raw = filename.read_text(encoding="utf-8")
        key = json.loads(raw, object_pairs_hook=_no_duplicates)
        if not isinstance(key, dict) or any(not isinstance(v, str) for v in key.values()):
            raise ValueError
        required = {
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "token_uri",
        }
        allowed = required | {
            "client_id",
            "auth_uri",
            "auth_provider_x509_cert_url",
            "client_x509_cert_url",
            "universe_domain",
        }
        if (
            not required.issubset(key)
            or not set(key).issubset(allowed)
            or key["type"] != "service_account"
            or key["project_id"] != cfg.project
            or key["client_email"] != cfg.service_account
            or key["token_uri"] != "https://oauth2.googleapis.com/token"
            or key.get("universe_domain", "googleapis.com") != "googleapis.com"
            or not _KEY_RE.fullmatch(source[prefix + "KEY_ID"])
            or key["private_key_id"] != source[prefix + "KEY_ID"]
        ):
            raise ValueError
        created = _time(source, prefix + "KEY_CREATED_AT")
        expiry = _time(source, prefix + "KEY_NOT_AFTER")
        now = datetime.now(UTC)
        if not (created <= now < expiry <= created + timedelta(days=90)):
            raise ValueError
        loader = cast(
            Callable[[dict[str, str]], ServiceAccountCredentials],
            ServiceAccountCredentials.from_service_account_info,
        )
        credentials = loader(key)
        return credentials, expiry
    except Exception:
        raise RuntimeConfigurationError("production GSM workload identity unavailable") from None


def production_reader(
    database: PostgresFiscalDatabase,
    source: Mapping[str, str],
    cfg: ProductionGsmConfig,
) -> DurableGsmReader:
    validated_binding(database, cfg)
    credentials, expiry = production_credentials(source, cfg)
    try:
        client = secretmanager_v1.SecretManagerServiceClient(
            credentials=credentials,
            client_options={
                "api_endpoint": "secretmanager.googleapis.com",
                "universe_domain": "googleapis.com",
            },
        )
    except Exception:
        raise RuntimeConfigurationError("production GSM SDK identity unavailable") from None
    return DurableGsmReader(
        uow_factory=database,
        access=GoogleSdkSecretAccess(client, bootstrap_not_after=expiry),
        environment="production",
        workload_id=f"nfcore-{cfg.role.lower()}",
        allowed_resources=frozenset({cfg.resource}),
        project_numbers={cfg.project: cfg.project_number},
    )


def production_worker_handler_factory(
    environ: Mapping[str, str] | None = None,
) -> Callable[[PostgresFiscalDatabase, RuntimeSettings], ScopedWorkerHandlerComposition] | None:
    source = os.environ if environ is None else environ
    mode = source.get("NFCORE_WORKER_GSM_MODE", "")
    if not mode:
        return None
    if mode != MODE:
        raise RuntimeConfigurationError("production Worker GSM mode denied")
    cfg = production_config(source, "WORKER")
    namespace = source.get("NFCORE_WORKER_GSM_HOST_NAMESPACE", "")
    destination = source.get("NFCORE_WORKER_GSM_DESTINATION_ID", "")
    if not namespace or namespace == "*" or not destination or destination == "*":
        raise RuntimeConfigurationError("production Worker dispatch scope denied")

    def build(
        database: PostgresFiscalDatabase, settings: RuntimeSettings
    ) -> ScopedWorkerHandlerComposition:
        if (
            settings.environment is not RuntimeEnvironment.PRODUCTION
            or settings.secret_backend != "external"
        ):
            raise RuntimeConfigurationError("production GSM Worker requires production/external")
        reader = production_reader(database, source, cfg)
        resolver = SecretResolver(
            GoogleSignatureSecretBackend(reader, provider_id=cfg.provider),
            environment="production",
        )
        with resolver.resolve(cfg.reference, scope=cfg.scope) as material:
            if len(material.reveal()) < 32:
                raise RuntimeConfigurationError("production GSM signing material too weak")
        webhook = build_gsm_worker_webhook_dependencies(
            resolver=resolver,
            reference=cfg.reference,
            scope=cfg.scope,
            destination_id=destination,
        )
        selection = OutboxClaimSelection(
            scope=ExecutionScope(
                tenant_id=cfg.scope.tenant_id,
                unit_id=cfg.scope.unit_id or "",
                host_namespace=namespace,
                environment=FiscalEnvironment.HOMOLOGATION,
                correlation_id="production-worker-webhook-claim",
            ),
            operations=frozenset({DELIVER_WEBHOOK_OPERATION}),
        )
        return ScopedWorkerHandlerComposition(
            handlers=build_canonical_worker_handlers(uow_factory=database, webhook=webhook),
            claim_selection=selection,
        )

    return build


def production_api_verifier(
    database: PostgresFiscalDatabase,
    environ: Mapping[str, str] | None = None,
) -> WebhookSecurity | None:
    """Optional API GSM identity probe; no staging route exposed in production."""
    source = os.environ if environ is None else environ
    mode = source.get("NFCORE_API_GSM_MODE", "")
    if not mode:
        return None
    if mode != MODE:
        raise RuntimeConfigurationError("production API GSM mode denied")
    cfg = production_config(source, "API")
    reader = production_reader(database, source, cfg)
    resolver = SecretResolver(
        GoogleSignatureSecretBackend(reader, provider_id=cfg.provider),
        environment="production",
    )
    try:
        with resolver.resolve(cfg.reference, scope=cfg.scope) as material:
            if len(material.reveal()) < 32:
                raise ValueError
    except Exception:
        raise RuntimeConfigurationError("production API GSM verifier unavailable") from None

    # This key can only verify the explicit reference and scope; no material leaks.
    class _ScopedVerifier:
        def resolve(self, key_id: str) -> bytes | None:
            if key_id != cfg.reference.reference_id:
                return None
            with resolver.resolve(cfg.reference, scope=cfg.scope) as material:
                return material.reveal()

    return WebhookSecurity(
        key_resolver=_ScopedVerifier(),
        signing_key_id=cfg.reference.reference_id,
    )


def provisionable_production_bindings(
    source: Mapping[str, str],
) -> tuple[SecretBinding, SecretBinding]:
    """Exact metadata proposed to existing platform-admin audit authority."""
    if source.get("NFCORE_PRODUCTION_GSM_BINDINGS_MODE") != _BINDINGS_MODE:
        raise RuntimeConfigurationError("production binding administration disabled")
    worker = production_config(source, "WORKER").binding()
    api = production_config(source, "API").binding()
    if worker.reference_id == api.reference_id:
        raise RuntimeConfigurationError("production GSM role references must differ")
    return worker, api
