"""Explicit, on-host GSM authority for the Osasco fiscal provider key.

Reuses NFCore's production API service identity and durable Control Plane.
No key material is stored in the manifest, environment, UI or GitHub.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from google.cloud import secretmanager_v1

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.vault.contracts import SecretResolutionService
from kordena_fiscal.vault.external import (
    ExternalFiscalSecretVault,
    NullSecretAccessAuditSink,
)
from kordena_fiscal.vault.google_secret_manager import (
    DurableGsmReader,
    GoogleFiscalSecretClient,
    GoogleSdkSecretAccess,
)

from .config import RuntimeConfigurationError
from .production_gsm import ProductionWorkloadIdentity, production_credentials

_RESOURCE = re.compile(r"projects/([a-z][a-z0-9-]{4,62})/secrets/[A-Za-z0-9_-]{1,255}\Z")


def build_osasco_gsm_secret_factory(
    source: Mapping[str, str],
) -> Callable[[FiscalApplicationService], SecretResolutionService]:
    """Bind provider secrets to a pinned production workload and project allowlist."""
    if source.get("NFCORE_ENVIRONMENT") != "production":
        raise RuntimeConfigurationError("Osasco GSM bootstrap requires production runtime")
    try:
        project = source["NFCORE_GSM_PROJECT_ID"]
        account = source["NFCORE_GSM_API_SERVICE_ACCOUNT"]
        number = source["NFCORE_GSM_PROJECT_NUMBER"]
        resources = source["NFCORE_OSASCO_GSM_ALLOWED_RESOURCES"].split(",")
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project)
            or not re.fullmatch(r"[1-9][0-9]{5,19}", number)
            or not resources
            or len(resources) != len(set(resources))
            or any(
                (match := _RESOURCE.fullmatch(resource)) is None
                or match.group(1) != project
                for resource in resources
            )
        ):
            raise ValueError
        identity = ProductionWorkloadIdentity(
            role="API", project=project, service_account=account,
        )
        credentials, expiry = production_credentials(source, identity)
    except (KeyError, ValueError, TypeError):
        raise RuntimeConfigurationError("Osasco GSM provider identity is not approved") from None
    try:
        client = secretmanager_v1.SecretManagerServiceClient(
            credentials=credentials,
            client_options={
                "api_endpoint": "secretmanager.googleapis.com",
                "universe_domain": "googleapis.com",
            },
        )
    except Exception:
        raise RuntimeConfigurationError("Osasco GSM SDK identity unavailable") from None
    access = GoogleSdkSecretAccess(client, bootstrap_not_after=expiry)

    def resolve(application: FiscalApplicationService) -> SecretResolutionService:
        # Same persistence factory and workload identity used by the canonical app.
        uow_factory = application._uow_factory
        reader = DurableGsmReader(
            uow_factory=uow_factory, access=access,
            environment="production", workload_id="nfcore-api",
            allowed_resources=frozenset(resources),
            project_numbers={project: number},
        )
        vault = ExternalFiscalSecretVault(
            client=GoogleFiscalSecretClient(reader),
            audit=NullSecretAccessAuditSink(),
        )
        return SecretResolutionService(unit_of_work_factory=uow_factory, vault=vault)

    return resolve
