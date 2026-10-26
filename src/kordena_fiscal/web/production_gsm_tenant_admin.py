"""Platform-admin-only production GSM metadata onboarding for many tenants.

No IAM/cloud writes, no free-form secrets, no public route, no per-tenant .env.
Existing human session/CSRF and SecretBindingAdministration remain authoritative.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime.production_multi_gsm import platform_project
from kordena_fiscal.runtime.secret_manager import SecretBindingAdministration
from kordena_fiscal.security.human_identity import HumanIdentityService
from kordena_fiscal.security.secret_binding import SecretBinding
from kordena_fiscal.security.secrets import SecretResolutionError
from kordena_fiscal.web.portal_api import _csrf
from kordena_fiscal.web.pricing_admin import _platform_actor


def create_production_gsm_tenant_router(
    identity: HumanIdentityService,
    administration: SecretBindingAdministration,
    database: PostgresFiscalDatabase,
    *,
    environ: Mapping[str, str] | None = None,
) -> APIRouter:
    """Only signed-in platform_admin can bind/revoke scoped metadata."""
    source = os.environ if environ is None else environ
    router = APIRouter(tags=["production-gsm-tenants"])

    @router.post("/internal/production/gsm-tenant-bindings", include_in_schema=False)
    async def write_binding(request: Request) -> dict[str, object]:
        actor, _principal = _platform_actor(request, identity)
        _csrf(request, identity, actor)
        if (
            source.get("NFCORE_ENVIRONMENT") != "production"
            or source.get("NFCORE_PRODUCTION_GSM_TENANT_ADMIN") != "platform-admin-v1"
        ):
            raise HTTPException(status_code=403, detail="GSM_TENANT_ADMIN_DISABLED")
        try:
            project, _ = platform_project(source)
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {
                "binding",
                "expected_revision",
            }:
                raise ValueError
            metadata = data["binding"]
            expected_revision = data["expected_revision"]
            if (
                not isinstance(metadata, dict)
                or type(expected_revision) is not int
                or expected_revision < 0
                or set(metadata) != set(SecretBinding.__dataclass_fields__)
            ):
                raise ValueError
            binding = SecretBinding.from_metadata(metadata)
            if (
                binding.runtime_environment != "production"
                or binding.kind != "signature"
                or binding.workload_id != "nfcore-worker"
                or binding.purpose != "webhook-signing"
                or binding.fiscal_environment is not None
                or binding.provider_id is None
                or not binding.tenant_id
                or not binding.unit_id
                or not binding.resource.startswith(f"projects/{project}/secrets/")
                or binding.revision != expected_revision + 1
                or binding.state not in {"active", "revoked"}
            ):
                raise ValueError
            with database() as uow:
                unit = uow.control_plane.get_unit(binding.tenant_id, binding.unit_id)
                if unit is None or FiscalEnvironment.HOMOLOGATION not in unit.enabled_environments:
                    raise ValueError
                # Reject a second active key for the same tenant/unit, not merely
                # selecting one by chance. This is additional to the Worker's
                # fail-closed ambiguity handling for concurrent updates.
                if binding.state == "active":
                    existing = uow.secret_bindings.list_active_signatures(
                        workload_id="nfcore-worker",
                        runtime_environment="production",
                    )
                    if any(
                        x.reference_id != binding.reference_id
                        and x.tenant_id == binding.tenant_id
                        and x.unit_id == binding.unit_id
                        for x in existing
                    ):
                        raise ValueError
            previous = administration.current_binding(binding.reference_id)
            if binding.state == "revoked" and previous is None:
                raise ValueError
            administration.put(
                actor=actor,
                binding=binding,
                expected_revision=expected_revision,
                correlation_id=uuid4().hex,
            )
        except (ValueError, TypeError, KeyError, SecretResolutionError, RuntimeError):
            raise HTTPException(status_code=409, detail="GSM_TENANT_BINDING_DENIED") from None
        return {
            "status": "bound" if binding.state == "active" else "revoked",
            "reference_id": binding.reference_id,
            "revision": binding.revision,
        }

    return router
