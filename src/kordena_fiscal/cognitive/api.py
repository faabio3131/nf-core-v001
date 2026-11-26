"""Session-authorized advisory route for the Portal.

Authority is rebuilt from the session cookie exactly like the rest of the portal: the browser
never supplies tenant, role or permissions, CSRF is required, and an ``Idempotency-Key`` is
mandatory. The route is read-only and advisory: it cannot trigger any fiscal operation.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Body, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from kordena_fiscal.application.accounting_dossier import (
    AccountingDossierService,
    DossierAuthorityError,
    DossierStepUpRequired,
)
from kordena_fiscal.application.accounting_review import ReviewDecision, ReviewTarget
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanIdentityError,
    HumanIdentityService,
    PortalPermission,
)
from kordena_fiscal.tax.federal_benefits import PROGRAMS
from kordena_fiscal.tax.state_benefits import state_index
from kordena_fiscal.web.human_auth import CSRF_HEADER, SESSION_COOKIE
from kordena_fiscal.web.portal_api import (
    _authenticated,
    _authorized,
    _csrf,
    _reject_browser_authority,
)

from .accounting_review_api import AccountingReviewRunner
from .contracts import AdviceRequest, AdviceResult, AdviceStatus, Capability, Evidence, stable_hash
from .economy_contract import CAPABILITIES, EconomyAdvice, project_economy
from .federal_benefits_api import FederalBenefitRunner, FederalBenefitSearchRunner
from .historical_audit_api import HistoricalAuditRunner
from .opportunity_radar_api import OpportunityRunner
from .service import CognitiveAdviceService
from .simples_diagnostic_api import DiagnosticRunner
from .state_benefits_api import StateBenefitRunner, StateSearchRunner

HOST_NAMESPACE = "fm-nfcore"

CAPABILITY_PERMISSIONS: dict[Capability, PortalPermission] = {
    Capability.EXPLAIN_REJECTION: PortalPermission.DOCUMENT_QUERY,
    Capability.EXPLAIN_RECONCILIATION: PortalPermission.DOCUMENT_QUERY,
    Capability.ANSWER_ACCOUNTANT_QUESTION: PortalPermission.DOCUMENT_QUERY,
    Capability.SUGGEST_CLASSIFICATION: PortalPermission.CONFIGURATION_WRITE,
    Capability.OPPORTUNITY_RADAR: PortalPermission.AUDIT_READ,
    Capability.CREDIT_RECOVERY: PortalPermission.AUDIT_READ,
    Capability.TAX_SIMULATION: PortalPermission.AUDIT_READ,
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


def _scoped_advice_request_id(
    *, tenant_id: str, unit_id: str, account_id: str,
    environment: FiscalEnvironment, capability: Capability,
    subject_id: str | None, key: str,
) -> str:
    """Prevent cross-account/unit/capability replay collisions in usage accounting."""
    return stable_hash({
        "version": "cognitive-idempotency/v2",
        "tenant": tenant_id,
        "unit": unit_id,
        "account": account_id,
        "environment": environment.value,
        "capability": capability.value,
        "subject": subject_id,
        "key": key,
    })


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
    normative_radar: Callable[[AuthenticatedHuman, str, FiscalEnvironment], dict[str, Any]]
    | None = None,
    diagnostic_runner: DiagnosticRunner | None = None,
    segregation_runner: DiagnosticRunner | None = None,
    assessment_runner: DiagnosticRunner | None = None,
    federal_benefit_runner: FederalBenefitRunner | None = None,
    federal_benefit_search_runner: FederalBenefitSearchRunner | None = None,
    state_benefit_runner: StateBenefitRunner | None = None,
    state_search_runner: StateSearchRunner | None = None,
    opportunity_runner: OpportunityRunner | None = None,
    simulation_runner: OpportunityRunner | None = None,
    annual_comparison_runner: OpportunityRunner | None = None,
    accounting_review_runner: AccountingReviewRunner | None = None,
    historical_audit_runner: HistoricalAuditRunner | None = None,
    dossier_service: AccountingDossierService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/portal/cognitive", tags=["cognitive-advisory"])

    @router.get("/economy/normative-alerts")
    async def normative_alerts(
        request: Request, unit_id: str,
        environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        if normative_radar is None:
            raise _bad("NORMATIVE_RADAR_NOT_CONFIGURED", "Normative radar unavailable", 503)
        return await run_in_threadpool(normative_radar, auth, unit_id, environment)

    @router.post("/economy/simples-diagnostic")
    async def simples_diagnostic(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {"unit_id", "environment", "snapshot_id", "snapshot_version",
                  "rule_id", "rule_version"}
        if set(body) != fields:
            raise _bad("INVALID_SIMPLES_INPUT", "Only scoped record references are accepted")
        for key in ("unit_id", "snapshot_id", "rule_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_SIMPLES_REFERENCE", "Invalid record reference")
        for key in ("snapshot_version", "rule_version"):
            if type(body[key]) is not int or not 1 <= body[key] <= 2147483647:
                raise _bad("INVALID_SIMPLES_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if diagnostic_runner is None:
            raise _bad("SIMPLES_NOT_CONFIGURED", "Simples diagnosis unavailable", 503)
        return await run_in_threadpool(
            diagnostic_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
            body["rule_id"].strip(), body["rule_version"],
        )

    @router.post("/economy/simples-segregation")
    async def simples_segregation(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {"unit_id", "environment", "snapshot_id", "snapshot_version",
                  "rule_id", "rule_version"}
        if set(body) != fields:
            raise _bad("INVALID_SIMPLES_INPUT", "Only scoped record references are accepted")
        for key in ("unit_id", "snapshot_id", "rule_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_SIMPLES_REFERENCE", "Invalid record reference")
        for key in ("snapshot_version", "rule_version"):
            if type(body[key]) is not int or not 1 <= body[key] <= 2147483647:
                raise _bad("INVALID_SIMPLES_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if segregation_runner is None:
            raise _bad("SIMPLES_NOT_CONFIGURED", "Simples segregation unavailable", 503)
        return await run_in_threadpool(
            segregation_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
            body["rule_id"].strip(), body["rule_version"],
        )

    @router.post("/economy/simples-assessment")
    async def simples_assessment(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {"unit_id", "environment", "snapshot_id", "snapshot_version",
                  "rule_id", "rule_version"}
        if set(body) != fields:
            raise _bad("INVALID_SIMPLES_INPUT", "Only scoped record references are accepted")
        for key in ("unit_id", "snapshot_id", "rule_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_SIMPLES_REFERENCE", "Invalid record reference")
        for key in ("snapshot_version", "rule_version"):
            if type(body[key]) is not int or not 1 <= body[key] <= 2147483647:
                raise _bad("INVALID_SIMPLES_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if assessment_runner is None:
            raise _bad("SIMPLES_NOT_CONFIGURED", "Simples assessment unavailable", 503)
        return await run_in_threadpool(
            assessment_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
            body["rule_id"].strip(), body["rule_version"],
        )

    @router.get("/economy/federal-programs")
    async def federal_programs(request: Request, unit_id: str) -> dict[str, Any]:
        """Published registry is a SOURCE INDEX, not a granted fiscal incentive."""
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        return {
            "schema_version": "nfcore.federal-program-index/v1",
            "advisory_only": True, "eligibility_certified": False,
            "issuance_authorized": False, "complete_national_coverage": False,
            "programs": [
                {
                    "program_code": item.code, "tax_code": item.tax_code,
                    "operation": item.operation, "legal_act": item.legal_act,
                    "official_source": item.official_url,
                    "requires_reviewed_policy": True,
                }
                for item in sorted(PROGRAMS.values(), key=lambda x: x.code)
            ],
        }

    @router.post("/economy/federal-benefit")
    async def federal_benefit(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        required = {"unit_id", "environment", "snapshot_id", "snapshot_version",
                    "benefit_id", "benefit_version"}
        if set(body) != required:
            raise _bad("INVALID_FEDERAL_BENEFIT_INPUT", "Only scoped references allowed")
        for key in ("unit_id", "snapshot_id", "benefit_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_FEDERAL_BENEFIT_REFERENCE", "Invalid record reference")
        for key in ("snapshot_version", "benefit_version"):
            if type(body[key]) is not int or not 1 <= body[key] <= 2147483647:
                raise _bad("INVALID_FEDERAL_BENEFIT_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if federal_benefit_runner is None:
            raise _bad("FEDERAL_BENEFIT_NOT_CONFIGURED",
                       "Federal benefit catalog unavailable", 503)
        return await run_in_threadpool(
            federal_benefit_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
            body["benefit_id"].strip(), body["benefit_version"],
        )

    @router.post("/economy/federal-benefit-search")
    async def federal_benefit_search(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {"unit_id", "environment", "snapshot_id", "snapshot_version"}
        if set(body) != fields:
            raise _bad("INVALID_FEDERAL_BENEFIT_SEARCH",
                       "Only scoped reviewed snapshot references are accepted")
        for key in ("unit_id", "snapshot_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_FEDERAL_BENEFIT_REFERENCE", "Invalid record reference")
        if type(body["snapshot_version"]) is not int or not 1 <= body[
            "snapshot_version"
        ] <= 2147483647:
            raise _bad("INVALID_FEDERAL_BENEFIT_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if federal_benefit_search_runner is None:
            raise _bad("FEDERAL_BENEFIT_NOT_CONFIGURED",
                       "Federal benefit search unavailable", 503)
        return await run_in_threadpool(
            federal_benefit_search_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
        )

    @router.get("/economy/state-jurisdictions")
    async def state_jurisdictions(request: Request, unit_id: str) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        return state_index()

    @router.post("/economy/state-benefit")
    async def state_benefit(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {
            "unit_id", "environment", "snapshot_id", "snapshot_version",
            "benefit_id", "benefit_version",
        }
        if set(body) != fields:
            raise _bad("INVALID_STATE_BENEFIT_INPUT", "Only scoped IDs are accepted")
        for key in ("unit_id", "snapshot_id", "benefit_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_STATE_BENEFIT_REFERENCE", "Invalid scoped reference")
        for key in ("snapshot_version", "benefit_version"):
            if type(body[key]) is not int or not 1 <= body[key] <= 2147483647:
                raise _bad("INVALID_STATE_BENEFIT_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if state_benefit_runner is None:
            raise _bad("STATE_BENEFIT_NOT_CONFIGURED",
                       "State catalog unavailable", 503)
        return await run_in_threadpool(
            state_benefit_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
            body["benefit_id"].strip(), body["benefit_version"],
        )

    @router.post("/economy/state-benefit-search")
    async def state_benefit_search(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        fields = {"unit_id", "environment", "snapshot_id", "snapshot_version"}
        if set(body) != fields:
            raise _bad("INVALID_STATE_BENEFIT_SEARCH", "Only scoped IDs are accepted")
        for key in ("unit_id", "snapshot_id"):
            if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 128:
                raise _bad("INVALID_STATE_BENEFIT_REFERENCE", "Invalid scoped reference")
        if type(body["snapshot_version"]) is not int or not 1 <= body[
            "snapshot_version"
        ] <= 2147483647:
            raise _bad("INVALID_STATE_BENEFIT_VERSION", "Invalid record version")
        unit_id = body["unit_id"].strip()
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit_id)
        _csrf(request, identity, auth)
        try:
            environment = FiscalEnvironment(body["environment"])
        except (TypeError, ValueError) as exc:
            raise _bad("INVALID_ENVIRONMENT", "Unknown environment") from exc
        if state_search_runner is None:
            raise _bad("STATE_BENEFIT_NOT_CONFIGURED",
                       "State search unavailable", 503)
        return await run_in_threadpool(
            state_search_runner, auth, unit_id, environment,
            body["snapshot_id"].strip(), body["snapshot_version"],
        )

    def authorized_month(request: Request, body: dict[str, Any]) -> tuple[
        AuthenticatedHuman, str, FiscalEnvironment, date,
    ]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _reject_browser_authority(body)
        if set(body) != {"unit_id", "environment", "competence"}:
            raise _bad("INVALID_RADAR_REQUEST", "Expected unit, environment and month")
        unit = body["unit_id"]
        if not isinstance(unit, str) or not 1 <= len(unit.strip()) <= 128:
            raise _bad("INVALID_RADAR_UNIT", "Invalid unit")
        _authorized(auth, PortalPermission.AUDIT_READ, unit_id=unit)
        _csrf(request, identity, auth)
        try:
            month = date.fromisoformat(body["competence"])
            environment = FiscalEnvironment(body["environment"])
            if month.day != 1 or month.isoformat() != body["competence"] or month.year >= 9999:
                raise ValueError
        except (ValueError, TypeError):
            raise _bad("INVALID_RADAR_PERIOD", "Invalid environment or competence") from None
        return auth, unit, environment, month

    @router.post("/economy/opportunity-radar")
    async def opportunity_scan(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth, unit, environment, month = authorized_month(request, body)
        if opportunity_runner is None:
            raise _bad("RADAR_UNAVAILABLE", "Radar unavailable", 503)
        return await run_in_threadpool(opportunity_runner, auth, unit, environment, month)

    @router.post("/economy/quarterly-simulation")
    async def quarterly_simulation(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth, unit, environment, month = authorized_month(request, body)
        if simulation_runner is None:
            raise _bad("SIMULATION_UNAVAILABLE", "Simulation unavailable", 503)
        return await run_in_threadpool(simulation_runner, auth, unit, environment, month)

    @router.post("/economy/annual-regime-comparison")
    async def annual_regime_comparison(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth, unit, environment, month = authorized_month(request, body)
        if annual_comparison_runner is None:
            raise _bad("ANNUAL_COMPARISON_UNAVAILABLE", "Comparison unavailable", 503)
        return await run_in_threadpool(annual_comparison_runner, auth, unit, environment, month)

    @router.post("/economy/historical-audit")
    async def historical_audit(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        _reject_browser_authority(body)
        required = {"unit_id", "environment", "competence"}
        if not required <= set(body) or set(body) - required - {"detail"}:
            raise _bad("INVALID_HISTORICAL_AUDIT_REQUEST", "Invalid historical audit request")
        auth, unit, environment, month = authorized_month(
            request, {key: body[key] for key in required},
        )
        detail = body.get("detail")
        if "detail" in body:
            try:
                if not isinstance(detail, dict) or set(detail) != {
                    "month", "page", "snapshot_digest", "window_digest",
                }:
                    raise ValueError
                selected = date.fromisoformat(detail["month"])
                if (selected.day != 1 or selected.isoformat() != detail["month"]
                        or type(detail["page"]) is not int or not 0 <= detail["page"] <= 310
                        or any(not isinstance(detail[k], str) or len(detail[k]) != 64
                               or any(c not in "0123456789abcdef" for c in detail[k])
                               for k in ("snapshot_digest", "window_digest"))):
                    raise ValueError
            except (ValueError, TypeError):
                raise _bad(
                    "INVALID_HISTORICAL_AUDIT_REQUEST", "Invalid historical audit page",
                ) from None
        if historical_audit_runner is None:
            raise _bad("HISTORICAL_AUDIT_UNAVAILABLE", "Historical audit unavailable", 503)
        return await run_in_threadpool(
            historical_audit_runner, auth, unit, environment, month, detail,
        )

    def dossier_context(
        request: Request, body: dict[str, Any],
    ) -> tuple[AccountingDossierService, str, str, str, date]:
        _, unit, environment, month = authorized_month(request, body)
        if environment is not FiscalEnvironment.HOMOLOGATION:
            raise _bad("DOSSIER_SCOPE_FORBIDDEN", "Sandbox only", 403)
        if dossier_service is None:
            raise _bad("DOSSIER_UNAVAILABLE", "Dossier unavailable", 503)
        return (
            dossier_service, request.cookies.get(SESSION_COOKIE, ""),
            request.headers.get(CSRF_HEADER, ""), unit, month,
        )

    def dossier_error(exc: Exception) -> HTTPException:
        if isinstance(exc, DossierStepUpRequired):
            return _bad("STEP_UP_REQUIRED", "Recent MFA required", 403)
        if isinstance(exc, (DossierAuthorityError, HumanIdentityError)):
            return _bad("DOSSIER_SCOPE_FORBIDDEN", "Accountant authority required", 403)
        return _bad("DOSSIER_EVIDENCE_INVALID", "Refresh verified evidence", 409)

    @router.post("/economy/accounting-dossier/candidates")
    async def dossier_candidates(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        service, token, csrf, unit, month = dossier_context(request, body)
        try:
            return await run_in_threadpool(service.candidates, token, csrf, unit, month)
        except (FiscalValidationError, HumanIdentityError, ValueError, KeyError, TypeError) as exc:
            raise dossier_error(exc) from None

    @router.post("/economy/accounting-dossier/export", response_class=Response)
    async def dossier_export(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> Response:
        _reject_browser_authority(body)
        selection = {"finding_id", "source_version", "source_digest"}
        context = {"unit_id", "environment", "competence"}
        if set(body) != context | selection:
            raise _bad("INVALID_DOSSIER_REQUEST", "Expected source-bound finding")
        service, token, csrf, unit, month = dossier_context(
            request, {key: body[key] for key in context},
        )
        try:
            raw = await run_in_threadpool(
                service.export, token, csrf, unit, month, body["finding_id"],
                body["source_version"], body["source_digest"],
            )
        except (FiscalValidationError, HumanIdentityError, ValueError, KeyError, TypeError) as exc:
            raise dossier_error(exc) from None
        return Response(
            content=raw, media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="nfcore-dossie.zip"',
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/economy/accounting-review")
    async def accounting_review(
        request: Request, body: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        _reject_browser_authority(body)
        required = {"unit_id", "environment", "competence", "target"}
        if not required <= set(body) or set(body) - required - {"command", "before_version"}:
            raise _bad("INVALID_ACCOUNTING_REVIEW_REQUEST", "Invalid accounting review request")
        auth, unit, environment, month = authorized_month(
            request, {key: body[key] for key in ("unit_id", "environment", "competence")},
        )
        try:
            target = ReviewTarget.model_validate(body["target"])
            command = ReviewDecision.model_validate(body["command"]) if "command" in body else None
            before = body.get("before_version")
            if before is not None and (type(before) is not int or not 2 <= before <= 2147483647):
                raise ValueError("invalid history cursor")
            if command is not None and before is not None:
                raise ValueError("cursor cannot accompany decision")
        except ValueError:
            raise _bad("INVALID_ACCOUNTING_REVIEW_REQUEST", "Invalid review data") from None
        if accounting_review_runner is None:
            raise _bad("ACCOUNTING_REVIEW_UNAVAILABLE", "Accounting review unavailable", 503)
        return await run_in_threadpool(
            accounting_review_runner, auth, unit, environment, month, target, command, before,
        )

    @router.get("/economy/schema")
    async def economy_schema(request: Request) -> dict[str, Any]:
        auth = _authenticated(request, identity, now=datetime.now(UTC))
        _authorized(auth, PortalPermission.AUDIT_READ)
        return EconomyAdvice.model_json_schema()

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
        if subject_id is not None:
            if (
                not isinstance(subject_id, str)
                or not subject_id.strip()
                or len(subject_id) > 128
            ):
                raise _bad("INVALID_SUBJECT", "subject_id must be 1-128 nonblank characters")
            subject_id = subject_id.strip()
        if not isinstance(question, str) or len(question) > 1000:
            raise _bad("INVALID_QUESTION", "question must be text up to 1000 characters")
        if advisor is None or evidence is None:
            raise _bad(
                "COGNITIVE_NOT_CONFIGURED",
                "Cognitive advisory is not configured",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if capability in CAPABILITIES:
            if subject_id is None:
                raise _bad("SUBJECT_REQUIRED", "Economy advice requires an evaluation id")
            if set(body) - {"capability", "unit_id", "environment", "subject_id", "question"}:
                raise _bad("INVALID_ECONOMY_INPUT", "Fiscal evidence is server controlled")
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
            # The browser key is not the scope authority; bind all server-derived
            # identity and request dimensions before checking usage idempotency.
            request_id=_scoped_advice_request_id(
                tenant_id=auth.tenant_id,
                unit_id=unit_id.strip(),
                account_id=auth.account.account_id,
                environment=environment,
                capability=capability,
                subject_id=subject_id,
                key=key,
            ),
            actor_id="portal-" + hashlib.sha256(auth.account.account_id.encode()).hexdigest()[:24],
            granted_capabilities=granted,
            capability=capability,
            evidence=facts,
            question=question,
            subject_id=subject_id,
        )
        result = await run_in_threadpool(advisor.advise, advice)
        if result.status is AdviceStatus.DENIED:
            raise _bad(
                "COGNITIVE_FORBIDDEN", "Operation is not permitted", status.HTTP_403_FORBIDDEN
            )
        response = project_result(result, ai_enabled=ai_enabled)
        if capability in CAPABILITIES:
            response["economy"] = project_economy(advice, result).model_dump(mode="json")
        return response

    return router
