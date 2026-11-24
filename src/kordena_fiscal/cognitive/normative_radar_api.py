"""Session-scoped projection of public normative observations. No model or writes."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from kordena_fiscal.compliance.normative_radar import project_radar
from kordena_fiscal.compliance.normative_watch import NormativeWatchError
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalPermission

from .portal_evidence import SurfaceReader

NormativeReader = Callable[[AuthenticatedHuman, str, FiscalEnvironment], dict[str, Any]]


def build_normative_reader(
    reader: SurfaceReader, environ: Mapping[str, str],
) -> NormativeReader | None:
    if environ.get("NFCORE_NORMATIVE_RADAR_ENABLED") != "true":
        return None
    configured = environ.get("NFCORE_NORMATIVE_RADAR_STATE", "").strip()
    if not configured or not Path(configured).is_absolute():
        return None
    path = Path(configured)

    def scoped(
        authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment,
    ) -> dict[str, Any]:
        authority.assert_permission(PortalPermission.AUDIT_READ, unit_id=unit_id)
        rows = reader.surface(
            surface_id="units", authority=authority, unit_id=unit_id, environment=environment,
        )
        if not any(
            row.get("unit_id") == unit_id
            and row.get("tenant_id", authority.tenant_id) == authority.tenant_id
            and environment.value in (row.get("enabled_environments") or ())
            for row in rows
        ):
            raise HTTPException(403, detail={"code": "NORMATIVE_SCOPE_FORBIDDEN"})
        scope = ExecutionScope(
            tenant_id=authority.tenant_id, unit_id=unit_id, environment=environment,
            host_namespace="fm-nfcore", correlation_id="normative-radar",
        )
        try:
            return project_radar(path, scope)
        except (NormativeWatchError, OSError):
            raise HTTPException(503, detail={"code": "NORMATIVE_STATE_UNAVAILABLE"}) from None

    return scoped
