"""Production binding bootstrap over the existing authenticated platform authority.

Only metadata from immutable operator configuration is accepted, never request
payload identity fields or secret bytes. First bootstrap in a newly migrated,
schema-only PostgreSQL is recorded in the canonical Control Plane audit.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from kordena_fiscal.runtime.production_gsm import provisionable_production_bindings
from kordena_fiscal.runtime.secret_manager import SecretBindingAdministration
from kordena_fiscal.security.human_identity import HumanIdentityService
from kordena_fiscal.security.secrets import SecretResolutionError
from kordena_fiscal.web.portal_api import _csrf
from kordena_fiscal.web.pricing_admin import _platform_actor


def create_production_gsm_binding_router(
    identity: HumanIdentityService,
    administration: SecretBindingAdministration,
    *,
    environ: Mapping[str, str] | None = None,
) -> APIRouter:
    """Only platform admins may create two exact, separate production bindings."""
    source = os.environ if environ is None else environ
    router = APIRouter(tags=["production-gsm-bootstrap"])

    @router.post("/internal/production/gsm-bindings", include_in_schema=False)
    async def register_production_bindings(request: Request) -> dict[str, str]:
        authority, _principal = _platform_actor(request, identity)
        _csrf(request, identity, authority)
        if await request.body():
            raise HTTPException(status_code=400, detail="BODY_NOT_ALLOWED")
        try:
            bindings = provisionable_production_bindings(source)
            for binding in bindings:
                # Never update/rebind silently. Exact replay is idempotent.
                existing = administration.current_binding(binding.reference_id)
                if existing is not None and existing != binding:
                    raise SecretResolutionError("production GSM binding conflict")
                administration.put(
                    actor=authority,
                    binding=binding,
                    expected_revision=0,
                    correlation_id=uuid4().hex,
                )
        except (SecretResolutionError, RuntimeError):
            raise HTTPException(status_code=409, detail="PRODUCTION_GSM_BINDING_DENIED") from None
        return {"status": "bound", "scope": "production"}

    return router
