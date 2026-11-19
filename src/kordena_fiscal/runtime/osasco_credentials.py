"""Resolve Osasco's 36-character WCF key through the existing scoped fiscal vault.

The key is *never* held in provider metadata, a browser request or a source file.
Control Plane binds credentials to tenant/unit/environment/provider, and this
boundary additionally checks the currently effective Osasco CNPJ/municipal IM.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from kordena_fiscal.control_plane import SecretReferenceKind
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.osasco_rtc_homologation import OSASCO_RTC_PROVIDER_ID
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.vault.contracts import (
    EphemeralProviderCredentialsMaterial,
    SecretResolutionContext,
    SecretResolutionService,
    SecretUsagePurpose,
)

_OSASCO_KEY = re.compile(r"[A-Za-z0-9-]{36}\Z")


def build_osasco_scoped_key_resolver(
    *,
    unit_of_work_factory: FiscalUnitOfWorkFactory,
    secrets: SecretResolutionService,
    workload_id: str,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[ExecutionScope, str], str]:
    """Use the canonical Control Plane secret reference and one scoped Vault.

    The Osasco transport calls this *after* resolving its durable provider
    binding; missing municipal IM or a different taxpayer CNPJ prevents Vault I/O.
    Key bytes are returned only at the last responsible moment for SOAP assembly.
    """
    if not isinstance(secrets, SecretResolutionService):
        raise ValueError("Canonical fiscal secret resolution service is required")
    if not isinstance(workload_id, str) or not workload_id.strip():
        raise ValueError("Reviewed Osasco workload identity required")
    now = clock or (lambda: datetime.now(UTC))

    def resolve(scope: ExecutionScope, issuer_cnpj: str) -> str:
        if (
            not isinstance(scope, ExecutionScope)
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not scope.host_namespace
            or not isinstance(issuer_cnpj, str)
        ):
            raise FiscalValidationError("Osasco requires scoped fiscal credentials")
        identifier = Cnpj(issuer_cnpj)
        with unit_of_work_factory() as uow:
            profile = uow.control_plane.resolve_profile(
                host_namespace=scope.host_namespace,
                tenant_id=scope.tenant_id, unit_id=scope.unit_id,
                environment=scope.environment, instant=now(),
            )
        if (
            profile is None
            or profile.cnpj != identifier
            or profile.municipal_registration is None
            or profile.address.jurisdiction.state_code != "SP"
            or profile.address.jurisdiction.municipality_ibge_code != "3534401"
        ):
            raise FiscalValidationError(
                "Osasco WCF taxpayer and municipal registration do not match fiscal profile"
            )
        material = secrets.resolve(SecretResolutionContext(
            scope=scope, purpose=SecretUsagePurpose.PROVIDER_AUTHENTICATION,
            kind=SecretReferenceKind.CREDENTIALS, workload_id=workload_id,
            provider_id=OSASCO_RTC_PROVIDER_ID,
        ))
        if not isinstance(material, EphemeralProviderCredentialsMaterial):
            raise FiscalValidationError("Osasco provider key type mismatch")
        try:
            key = material.credential_bytes.decode("ascii")
        except UnicodeError:
            raise FiscalValidationError("Osasco provider key encoding invalid") from None
        if not _OSASCO_KEY.fullmatch(key):
            raise FiscalValidationError("Osasco provider key shape invalid")
        return key

    return resolve
