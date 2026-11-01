"""Session-authorized advisory route for the Portal.

Authority is rebuilt from the session cookie exactly like the rest of the portal: the browser
never supplies tenant, role or permissions, CSRF is required, and an ``Idempotency-Key`` is
mandatory. The route is read-only and advisory: it cannot trigger any fiscal operation.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanIdentityService,
    PortalPermission,
)
from kordena_fiscal.web.portal_api import (
    _authenticated,
    _authorized,
    _csrf,
    _reject_browser_authority,
)

from .contracts import AdviceRequest, AdviceResult, AdviceStatus, Capability, Evidence
from .service import CognitiveAdviceService

HOST_NAMESPACE = "fm-nfcore"

CAPABILITY_PERMISSIONS: dict[Capability, PortalPermission] = {
    Capability.EXPLAIN_REJECTION: PortalPermission.DOCUMENT_QUERY,
    Capability.EXPLAIN_RECONCILIATION: PortalPermission.DOCUMENT_QUERY,
    Capability.ANSWER_ACCOUNTANT_QUESTION: PortalPermission.DOCUMENT_QUERY,
    Capability.SUGGEST_CLASSIFICATION: PortalPermission.CONFIGURATION_WRITE,
}


class EvidenceProvider(Protocol):
    def collect(
        self,
        *,
        authority: AuthenticatedHuman,
        capability: Capability,
        unit_id: str,
        environment: FiscalEnvironment,
        subject_id: str | None,
    ) -> tuple[Evidence, ...]: ...


def _bad(code: str, message: str, http: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message})


def project_result(result: AdviceResult, *, ai_enabled: bool) -> dict[str, Any]:
    p = result.provenance
    return {
        "status": result.status.value,
        "advisoryOnly": True,
        "requiresHumanApproval": True,
        "aiEnabled": ai_enabled,
        "disclaimer": result.disclaimer,
        "sections": [
            {"kind": s.kind.value, "text": s.text, "evidenceIds": list(s.evidence_ids)}
            for s in result.sections
        ],
        "provenance": {
            "schemaVersion": p.schema_version,
            "capability": p.capability.value,
            "correlationId": p.correlation_id,
            "contextHash": p.context_hash,
            "baselineVersion": p.baseline_version,
            "model": p.model,
            "modelVersion": p.model_version,
            "degradedReason": p.degraded_reason,
            "guardFindings": len(p.guard_findings),
            "latencyMs": p.latency_ms,
        },
    }


def create_cognitive_router(
    identity: HumanIdentityService,
    advisor: CognitiveAdviceService | None,
    evidence: EvidenceProvider | None,
    *,
    ai_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/v1/portal/cognitive", tags=["cognitive-advisory"])

    @router.post("/advise")
    async def advise(
        request: Request, body: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        try:
            capability = Capability(str(body.get("capability", "")))
        except ValueError as exc:
            raise _bad("UNKNOWN_CAPABILITY", "Unknown cognitive capability") from exc
        unit_id = body.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise _bad("UNIT_REQUIRED", "unit_id is required")
        _authorized(auth, CAPABILITY_PERMISSIONS[capability], unit_id=unit_id)
        _csrf(request, identity, auth)
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key:
            raise _bad("MISSING_IDEMPOTENCY_KEY", "Idempotency-Key is required")
        try:
            environment = FiscalEnvironment(str(body.get("environment", "homologation")))
        except ValueError as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        subject_id = body.get("subject_id")
        question = body.get("question", "")
        if subject_id is not None and not isinstance(subject_id, str):
            raise _bad("INVALID_SUBJECT", "subject_id must be text")
        if not isinstance(question, str) or len(question) > 1000:
            raise _bad("INVALID_QUESTION", "question must be text up to 1000 characters")
        if advisor is None or evidence is None:
            raise _bad(
                "COGNITIVE_NOT_CONFIGURED",
                "Cognitive advisory is not configured",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        facts = await run_in_threadpool(
            evidence.collect,
            authority=auth,
            capability=capability,
            unit_id=unit_id.strip(),
            environment=environment,
            subject_id=subject_id,
        )
        granted = frozenset(
            cap for cap, permission in CAPABILITY_PERMISSIONS.items()
            if permission in auth.permissions
        )
        scope = ExecutionScope(
            host_namespace=HOST_NAMESPACE,
            tenant_id=auth.tenant_id,
            unit_id=unit_id.strip(),
            environment=environment,
            correlation_id=request.headers.get("X-Correlation-Id") or f"cog-{uuid.uuid4().hex}",
        )
        advice = AdviceRequest(
            scope=scope,
            # Scoped by tenant so two tenants can never collide on usage idempotency.
            request_id=hashlib.sha256(f"{auth.tenant_id}\x00{key}".encode()).hexdigest(),
            actor_id="portal-" + hashlib.sha256(auth.account.account_id.encode()).hexdigest()[:24],
            granted_capabilities=granted,
            capability=capability,
            evidence=facts,
            question=question,
        )
        result = await run_in_threadpool(advisor.advise, advice)
        if result.status is AdviceStatus.DENIED:
            raise _bad(
                "COGNITIVE_FORBIDDEN", "Operation is not permitted", status.HTTP_403_FORBIDDEN
            )
        return project_result(result, ai_enabled=ai_enabled)

    return router
