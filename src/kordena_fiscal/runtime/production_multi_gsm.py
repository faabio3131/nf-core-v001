"""Production multi-tenant GSM Worker over the *existing* outbox and binding authority.

One process, one canonical PostgreSQL database, two platform workload identities.
Every dispatch is claimed in an EXACT tenant/unit/host/fiscal partition. No
tenant data comes from .env, job payloads, or an untrusted request. No cloud
resource is created here. Existing lease/idempotency/retry/audit machinery is reused.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from google.cloud import secretmanager_v1

from kordena_fiscal.application.background_runtime import BackgroundCycleResult
from kordena_fiscal.contingency.outbox import OutboxClaimSelection
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.secret_binding import SecretBinding
from kordena_fiscal.security.secrets import (
    SecretReference,
    SecretResolver,
    SecretScope,
)
from kordena_fiscal.vault.google_secret_manager import (
    DurableGsmReader,
    GoogleSdkSecretAccess,
    GoogleSignatureSecretBackend,
)

from .config import RuntimeConfigurationError, RuntimeEnvironment, RuntimeSettings
from .observability import (
    MetricsRegistry,
    StructuredLogger,
    WorkerHealth,
    WorkerObservability,
)
from .production_gsm import (
    ProductionWorkloadIdentity,
    production_config,
    production_credentials,
)
from .secret_manager import build_gsm_worker_webhook_dependencies
from .worker_composition import (
    DELIVER_WEBHOOK_OPERATION,
    ProductionWorkerComposition,
    build_canonical_worker_handlers,
    build_production_worker_runtime,
)

if TYPE_CHECKING:
    from kordena_fiscal.contingency.outbox import FiscalOutboxStatus

MULTI_MODE = "multi-tenant-production-sa-v1"


class ProductionGsmWorkloadClientCache:
    """One Google transport and credential identity per Worker process.

    Only the Google workload transport is cached. Durable binding metadata,
    per-tenant allowed_resources, exact outbox claims and egress authorization
    remain independent and are revalidated for every dispatch.
    """

    def __init__(
        self,
        source: Mapping[str, str],
        *,
        project: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._project = project
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stamp: tuple[object, ...] | None = None
        self._client: secretmanager_v1.SecretManagerServiceClient | None = None
        self._expiry: datetime | None = None

    @property
    def project(self) -> str:
        return self._project

    def _stamp_current(self) -> tuple[object, ...]:
        prefix = "NFCORE_WORKER_GSM_"
        try:
            credential_path = Path(self._source[prefix + "CREDENTIAL_FILE"])
            metadata = credential_path.lstat()
            if (
                not credential_path.is_absolute()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o077
                or metadata.st_uid != os.getuid()
                or not 128 <= metadata.st_size <= 65536
            ):
                raise ValueError
            identity_fields = (
                "NFCORE_ENVIRONMENT",
                "NFCORE_GSM_PROJECT_ID",
                "NFCORE_GSM_PROJECT_NUMBER",
                "NFCORE_GSM_ALLOWED_PROJECTS",
                "NFCORE_GSM_API_SERVICE_ACCOUNT",
                "NFCORE_GSM_WORKER_SERVICE_ACCOUNT",
                "GOOGLE_APPLICATION_CREDENTIALS",
                prefix + "CREDENTIAL_JSON",
                prefix + "KEY_ID",
                prefix + "KEY_CREATED_AT",
                prefix + "KEY_NOT_AFTER",
            )
            return (
                str(credential_path),
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_uid,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
                *(self._source.get(name, "") for name in identity_fields),
            )
        except (OSError, KeyError, TypeError, ValueError):
            raise RuntimeConfigurationError("production GSM workload identity unavailable") from None

    def get(self) -> tuple[secretmanager_v1.SecretManagerServiceClient, datetime]:
        """Fail closed on expiry, tampering or rotation; refresh only on identity change."""
        project, _ = platform_project(self._source)
        if project != self._project:
            raise RuntimeConfigurationError("production GSM workload identity changed")
        stamp = self._stamp_current()
        if self._client is not None and stamp == self._stamp and self._expiry is not None:
            if self._clock() >= self._expiry:
                raise RuntimeConfigurationError("production GSM workload identity expired")
            return self._client, self._expiry

        credentials, expiry = production_credentials(
            self._source,
            ProductionWorkloadIdentity(
                role="WORKER",
                project=self._project,
                service_account=self._source["NFCORE_GSM_WORKER_SERVICE_ACCOUNT"],
            ),
        )
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

        previous = self._client
        self._client = client
        self._expiry = expiry
        self._stamp = stamp
        if previous is not None:
            with suppress(Exception):
                previous.transport.close()
        return client, expiry

    def close(self) -> None:
        if self._client is not None:
            with suppress(Exception):
                self._client.transport.close()
            self._client = None
            self._expiry = None
            self._stamp = None



def platform_project(source: Mapping[str, str]) -> tuple[str, str]:
    """Operator-controlled project, independent of any individual customer."""
    project = source.get("NFCORE_GSM_PROJECT_ID", "")
    number = source.get("NFCORE_GSM_PROJECT_NUMBER", "")
    allowed = source.get("NFCORE_GSM_ALLOWED_PROJECTS", "").split(",")
    api = source.get("NFCORE_GSM_API_SERVICE_ACCOUNT", "")
    worker = source.get("NFCORE_GSM_WORKER_SERVICE_ACCOUNT", "")
    if (
        source.get("NFCORE_ENVIRONMENT") != "production"
        or not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project)
        or "staging" in project
        or not re.fullmatch(r"[1-9][0-9]{5,19}", number)
        or not allowed
        or any(not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", x) for x in allowed)
        or project not in allowed
        or len(set(allowed)) != len(allowed)
        or api == worker
        or not re.fullmatch(
            rf"[a-z][a-z0-9-]{{2,62}}@{re.escape(project)}\.iam\.gserviceaccount\.com",
            api,
        )
        or not re.fullmatch(
            rf"[a-z][a-z0-9-]{{2,62}}@{re.escape(project)}\.iam\.gserviceaccount\.com",
            worker,
        )
    ):
        raise RuntimeConfigurationError("multi-tenant production GSM project/identity denied")
    return project, number


def production_worker_bindings(
    database: PostgresFiscalDatabase,
    *,
    project: str,
    now: datetime,
) -> tuple[tuple[SecretBinding, str], ...]:
    """Fail-closed registry from canonical bindings + units + approved destinations.

    No new table, queue or backend. Ambiguous signing bindings or webhook
    destinations for a unit are NOT selected. Fiscal approval is still checked
    by the canonical WebhookDispatchPolicy immediately before outgoing I/O.
    """
    with database() as uow:
        signatures = uow.secret_bindings.list_active_signatures(
            workload_id="nfcore-worker", runtime_environment="production"
        )
        chosen: dict[tuple[str, str], tuple[SecretBinding, str] | None] = {}
        for binding in signatures:
            if (
                binding.tenant_id is None
                or binding.unit_id is None
                or binding.purpose != "webhook-signing"
                or binding.provider_id is None
                or binding.fiscal_environment is not None
                or binding.state != "active"
                or binding.kind != "signature"
                or not binding.resource.startswith(f"projects/{project}/secrets/")
                or binding.not_after is not None
                and binding.not_after <= now
            ):
                continue
            unit = uow.control_plane.get_unit(binding.tenant_id, binding.unit_id)
            if unit is None or FiscalEnvironment.HOMOLOGATION not in unit.enabled_environments:
                continue
            destinations = uow.commercial.list_webhook_destinations(
                tenant_id=binding.tenant_id,
                unit_id=binding.unit_id,
                environment=FiscalEnvironment.HOMOLOGATION,
            )
            active = [row for row in destinations if row.enabled]
            # Even if one destination is active, it must have explicit egress approval.
            if len(active) != 1:
                continue
            dest = active[0]
            scope = ExecutionScope(
                host_namespace="nfcore",
                tenant_id=binding.tenant_id,
                unit_id=binding.unit_id,
                environment=FiscalEnvironment.HOMOLOGATION,
                correlation_id="gsm-multi-discovery",
            )
            approval = uow.commercial.webhook_approval(scope, dest.destination_id)
            if (
                approval is None
                or not approval["enabled"]
                or approval["approval_status"] != "approved"
            ):
                continue
            key = (binding.tenant_id, binding.unit_id)
            if key in chosen:
                chosen[key] = None  # conflicting active references: deny the scope
            else:
                chosen[key] = (binding, dest.destination_id)
    if len(chosen) > 4096:
        raise RuntimeConfigurationError("GSM active scope capacity exceeded")
    return tuple(value for key, value in sorted(chosen.items()) if value is not None)


def _scoped_worker(
    database: PostgresFiscalDatabase,
    source: Mapping[str, str],
    *,
    binding: SecretBinding,
    destination_id: str,
    namespace: str,
    client_cache: ProductionGsmWorkloadClientCache,
) -> ProductionWorkerComposition:
    """Build one canonical scoped cycle; no new worker implementation or key cache."""
    if binding.tenant_id is None or binding.unit_id is None:
        raise RuntimeConfigurationError("GSM tenant scope missing")
    # These keys are constructed only as ephemeral in-memory contract inputs,
    # *not* process environment changes or tenant-specific server configuration.
    if type(binding.canonical_version) is not int:
        raise RuntimeConfigurationError("production signing version must be numeric")
    ephemeral = dict(source)
    prefix = "NFCORE_WORKER_GSM_"
    ephemeral.update(
        {
            prefix + "TENANT_ID": binding.tenant_id,
            prefix + "UNIT_ID": binding.unit_id,
            prefix + "SIGNING_REFERENCE": binding.reference_id,
            prefix + "SIGNING_VERSION": str(binding.canonical_version),
            prefix + "PROVIDER_ID": binding.provider_id or "",
            prefix + "RESOURCE": binding.resource,
            prefix + "CLOUD_VERSION": binding.cloud_version,
        }
    )
    cfg = production_config(ephemeral, "WORKER")
    if cfg.project != client_cache.project:
        raise RuntimeConfigurationError("production GSM signing project mismatch")
    client, expiry = client_cache.get()
    reader = DurableGsmReader(
        uow_factory=database,
        access=GoogleSdkSecretAccess(client, bootstrap_not_after=expiry),
        environment="production",
        workload_id="nfcore-worker",
        allowed_resources=frozenset({binding.resource}),
        project_numbers={cfg.project: cfg.project_number},
    )
    resolver = SecretResolver(
        GoogleSignatureSecretBackend(reader, provider_id=cfg.provider),
        environment="production",
    )
    webhook = build_gsm_worker_webhook_dependencies(
        resolver=resolver,
        reference=SecretReference(binding.reference_id, binding.canonical_version),
        scope=SecretScope(binding.tenant_id, binding.unit_id, "webhook-signing"),
        destination_id=destination_id,
    )
    selection = OutboxClaimSelection(
        scope=ExecutionScope(
            tenant_id=binding.tenant_id,
            unit_id=binding.unit_id,
            host_namespace=namespace,
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="gsm-multi-claim",
        ),
        operations=frozenset({DELIVER_WEBHOOK_OPERATION}),
    )
    return build_production_worker_runtime(
        uow_factory=database,
        handlers=build_canonical_worker_handlers(uow_factory=database, webhook=webhook),
        environment="production",
        batch_size=1,  # fair bounded round robin; no single tenant monopolizes cycles
        claim_selection=selection,
    )


class MultiTenantGsmWorkerComposition:
    """One process/lifecycle, dynamic canonical exact-scope worker cycles."""

    def __init__(
        self,
        database: PostgresFiscalDatabase,
        source: Mapping[str, str],
        namespace: str,
        loader: Callable[..., tuple[tuple[SecretBinding, str], ...]] = production_worker_bindings,
        scoped_factory: Callable[..., ProductionWorkerComposition] | None = None,
    ) -> None:
        self._db = database
        self._source = source
        self._namespace = namespace
        self._loader = loader
        self._project, _ = platform_project(source)
        self._client_cache = ProductionGsmWorkloadClientCache(source, project=self._project)
        self._scoped = scoped_factory or partial(_scoped_worker, client_cache=self._client_cache)
        self._observer = WorkerObservability(
            metrics=MetricsRegistry(),
            logger=StructuredLogger(service="nfcore-worker", environment="production"),
            queue_counts=self._counts,
        )

    def _counts(self) -> Mapping[FiscalOutboxStatus, int]:
        with self._db() as uow:
            return uow.outbox.counts_by_status()

    def health(self) -> WorkerHealth:
        return self._observer.health()

    def run_forever(self, stop: Event) -> None:
        self._observer.worker_started()
        try:
            while not stop.is_set():
                started = datetime.now(UTC)
                try:
                    assignments = self._loader(self._db, project=self._project, now=started)
                    claimed = succeeded = retry_wait = dead_letter = 0
                    failures = 0
                    for binding, destination_id in assignments:
                        if stop.is_set():
                            break
                        try:
                            scoped = self._scoped(
                                self._db,
                                self._source,
                                binding=binding,
                                destination_id=destination_id,
                                namespace=self._namespace,
                            )
                            outcome = scoped.runtime.run_cycle()
                            claimed += outcome.claimed
                            succeeded += outcome.succeeded
                            retry_wait += outcome.retry_wait
                            dead_letter += outcome.dead_letter
                        except Exception:
                            # No cross-tenant fallback, no error text with secret data,
                            # no global starvation of independent tenant scopes.
                            failures += 1
                    if failures:
                        self._observer.cycle_failed(
                            error_type="TenantScopeUnavailable", elapsed_seconds=0.0
                        )
                    else:
                        self._observer.cycle_completed(
                            BackgroundCycleResult(
                                claimed,
                                succeeded,
                                retry_wait,
                                dead_letter,
                                (datetime.now(UTC) - started).total_seconds(),
                            )
                        )
                except Exception:
                    self._observer.cycle_failed(
                        error_type="WorkerRegistryUnavailable", elapsed_seconds=0.0
                    )
                stop.wait(1.0)
        finally:
            self._observer.worker_stopped()
            self._client_cache.close()


def production_multi_worker_handler_factory(
    environ: Mapping[str, str] | None = None,
) -> Callable[[PostgresFiscalDatabase, RuntimeSettings], MultiTenantGsmWorkerComposition]:
    source = os.environ if environ is None else environ
    if source.get("NFCORE_WORKER_GSM_MODE") != MULTI_MODE:
        raise RuntimeConfigurationError("multi-tenant GSM Worker mode denied")
    platform_project(source)
    namespace = source.get("NFCORE_WORKER_GSM_HOST_NAMESPACE", "")
    if not namespace or namespace == "*" or any(ord(c) < 33 or ord(c) == 127 for c in namespace):
        raise RuntimeConfigurationError("multi-tenant GSM Worker namespace denied")

    def build(
        database: PostgresFiscalDatabase, settings: RuntimeSettings
    ) -> MultiTenantGsmWorkerComposition:
        if (
            settings.environment is not RuntimeEnvironment.PRODUCTION
            or settings.secret_backend != "external"
        ):
            raise RuntimeConfigurationError("multi-tenant GSM Worker requires production/external")
        project, _ = platform_project(source)
        # Read and validate the single Worker service account even before the
        # first tenant exists. No simulated key or fake tenant identity.
        production_credentials(
            source,
            ProductionWorkloadIdentity(
                role="WORKER",
                project=project,
                service_account=source["NFCORE_GSM_WORKER_SERVICE_ACCOUNT"],
            ),
        )
        return MultiTenantGsmWorkerComposition(database, source, namespace)

    return build
