"""Fail-closed ASGI/HTTP adapter for the public FM NFCORE Bridge API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, runtime_checkable
from uuid import uuid4

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.control_plane.cakto_checkout import (
    CaktoCheckoutAdministrationService,
)
from kordena_fiscal.control_plane.commercial_release import (
    CommercialReleaseAdministrationService,
)
from kordena_fiscal.control_plane.pricing_admin import CommercialPricingAdministrationService
from kordena_fiscal.product.checkout import CommercialCheckoutProjector
from kordena_fiscal.product.commercial_readiness import CommercialDeliveryPathReadiness
from kordena_fiscal.runtime.observability import (
    MetricsRegistry,
    RequestTimer,
    SafeTracer,
    StructuredLogger,
    StructuredLogTraceSink,
    TraceContext,
)
from kordena_fiscal.security.human_identity import HumanIdentityService
from kordena_fiscal.security.human_recovery import PasswordRecoveryService
from kordena_fiscal.web.cakto_checkout import create_cakto_checkout_router
from kordena_fiscal.web.commercial_release import create_commercial_release_router
from kordena_fiscal.web.human_auth import create_human_auth_router
from kordena_fiscal.web.human_recovery import (
    PasswordResetDelivery,
    create_password_recovery_router,
)
from kordena_fiscal.web.portal_api import HumanPortalExecutor, create_portal_router
from kordena_fiscal.web.pricing_admin import create_pricing_router


@dataclass(frozen=True, slots=True)
class BridgeHttpContext:
    """Untrusted HTTP claims collected before workload authorization."""

    host_namespace: str
    tenant_id: str
    unit_id: str
    environment: str
    correlation_id: str
    causation_id: str | None
    credential_id: str
    presented_secret: str
    idempotency_key: str | None

    def __repr__(self) -> str:
        return (
            "BridgeHttpContext("
            f"host_namespace={self.host_namespace!r}, tenant_id={self.tenant_id!r}, "
            f"unit_id={self.unit_id!r}, environment={self.environment!r}, "
            f"correlation_id={self.correlation_id!r}, causation_id={self.causation_id!r}, "
            f"credential_id={self.credential_id!r}, presented_secret=<redacted>, "
            f"idempotency_key={self.idempotency_key!r})"
        )


@dataclass(frozen=True, slots=True)
class AuthorizedBridgeContext:
    """Opaque result of the security boundary used by the HTTP adapter."""

    authority: object
    correlation_id: str


@dataclass(frozen=True, slots=True)
class BridgeExecutionResult:
    status_code: int
    body: Mapping[str, Any]


@runtime_checkable
class BridgeSecurityBoundary(Protocol):
    def authorize(
        self,
        *,
        operation_id: str,
        context: BridgeHttpContext,
    ) -> AuthorizedBridgeContext:
        """Authenticate and authorize one request or raise a security-domain error."""


@runtime_checkable
class BridgeRequestExecutor(Protocol):
    def execute(
        self,
        *,
        operation_id: str,
        authorized: AuthorizedBridgeContext,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> BridgeExecutionResult:
        """Execute one already-authorized Bridge operation."""


class HttpContractError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        correlation_id: str = "unknown",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.correlation_id = correlation_id


_OPERATION_PATHS: tuple[tuple[str, str, int, bool], ...] = (
    ("/v1/archive/references/query", "queryArchiveReference", 200, False),
    ("/v1/cancellations", "cancelFiscalDocument", 202, True),
    ("/v1/capabilities/query", "queryCapabilities", 200, False),
    ("/v1/inutilizations", "inutilizeFiscalRange", 202, True),
    ("/v1/issuances", "issueFiscalDocument", 202, True),
    ("/v1/queries", "queryFiscalDocument", 200, False),
    ("/v1/reconciliations", "reconcileFiscalOperation", 200, True),
)


def _required_header(request: Request, name: str, correlation_id: str) -> str:
    value = request.headers.get(name, "").strip()
    if not value:
        raise HttpContractError(
            400,
            "MISSING_HEADER",
            f"Required header {name} is missing",
            correlation_id,
        )
    if len(value) > 256:
        raise HttpContractError(
            400,
            "INVALID_HEADER",
            f"Header {name} is too long",
            correlation_id,
        )
    return value


def _credentials(request: Request, correlation_id: str) -> tuple[str, str]:
    credential_id = request.headers.get("X-FM-Workload-Credential-Id", "").strip()
    authorization = request.headers.get("Authorization", "").strip()
    if not credential_id or not authorization:
        raise HttpContractError(
            401,
            "AUTHENTICATION_REQUIRED",
            "Workload authentication is required",
            correlation_id,
        )
    scheme, separator, secret = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not secret.strip():
        raise HttpContractError(
            401,
            "INVALID_AUTHORIZATION",
            "Authorization must use Bearer credentials",
            correlation_id,
        )
    if len(credential_id) > 128 or len(secret) > 4096:
        raise HttpContractError(
            401,
            "INVALID_AUTHORIZATION",
            "Workload credential is invalid",
            correlation_id,
        )
    return credential_id, secret.strip()


def _context(request: Request, *, idempotency_required: bool) -> BridgeHttpContext:
    correlation_id = request.headers.get("X-Correlation-Id", "").strip() or "unknown"
    if correlation_id == "unknown" or len(correlation_id) > 256:
        raise HttpContractError(
            400,
            "INVALID_CORRELATION_ID",
            "X-Correlation-Id is required",
            correlation_id,
        )

    credential_id, presented_secret = _credentials(request, correlation_id)
    environment = _required_header(request, "X-FM-Environment", correlation_id)
    if environment not in {"homologation", "production"}:
        raise HttpContractError(
            400,
            "INVALID_ENVIRONMENT",
            "X-FM-Environment is invalid",
            correlation_id,
        )

    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_required and (idempotency_key is None or not idempotency_key.strip()):
        raise HttpContractError(
            400,
            "MISSING_IDEMPOTENCY_KEY",
            "Idempotency-Key is required",
            correlation_id,
        )
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if len(idempotency_key) > 256:
            raise HttpContractError(
                400,
                "INVALID_IDEMPOTENCY_KEY",
                "Idempotency-Key is too long",
                correlation_id,
            )

    causation_id = request.headers.get("X-Causation-Id")
    if causation_id is not None:
        causation_id = causation_id.strip() or None
        if causation_id is not None and len(causation_id) > 256:
            raise HttpContractError(
                400,
                "INVALID_CAUSATION_ID",
                "X-Causation-Id is too long",
                correlation_id,
            )

    return BridgeHttpContext(
        host_namespace=_required_header(request, "X-FM-Host-Namespace", correlation_id),
        tenant_id=_required_header(request, "X-FM-Tenant-Id", correlation_id),
        unit_id=_required_header(request, "X-FM-Unit-Id", correlation_id),
        environment=environment,
        correlation_id=correlation_id,
        causation_id=causation_id,
        credential_id=credential_id,
        presented_secret=presented_secret,
        idempotency_key=idempotency_key,
    )


def _error_payload(error: HttpContractError) -> dict[str, str]:
    return {
        "code": error.code,
        "message": error.message,
        "correlation_id": error.correlation_id,
    }


def _metric_http_method(method: str) -> str:
    """Bound metric cardinality; never expose arbitrary method or request fields."""
    allowed = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    return method if method in allowed else "OTHER"


def create_app(
    *,
    security: BridgeSecurityBoundary | None = None,
    executor: BridgeRequestExecutor | None = None,
    human_identity: HumanIdentityService | None = None,
    human_login_completed: Callable[[str, datetime], None] | None = None,
    password_recovery: PasswordRecoveryService | None = None,
    password_reset_delivery: PasswordResetDelivery | None = None,
    password_reset_completed: Callable[[str, datetime], None] | None = None,
    portal_executor: HumanPortalExecutor | None = None,
    pricing_administration: CommercialPricingAdministrationService | None = None,
    commercial_release_administration: CommercialReleaseAdministrationService | None = None,
    commercial_checkout: CommercialCheckoutProjector | None = None,
    commercial_checkout_processing_configured: bool = False,
    commercial_trial_ingress_configured: bool = False,
    commercial_trial_site_channel_configured: bool = False,
    commercial_public_trial_configured: bool = False,
    commercial_delivery_readiness: CommercialDeliveryPathReadiness | None = None,
    commercial_operational_readiness: Callable[[], bool] | None = None,
    commercial_trial_operational_readiness: Callable[[], bool] | None = None,
    cakto_checkout_administration: CaktoCheckoutAdministrationService | None = None,
    runtime_metrics: MetricsRegistry | None = None,
) -> FastAPI:
    """Create the web adapter without granting fiscal authority by default."""

    app = FastAPI(
        title="FM NFCORE Bridge API",
        version="1.0.0",
        description="Web-first HTTP adapter for FM NFCORE fiscal infrastructure.",
    )

    http_metrics = runtime_metrics if runtime_metrics is not None else MetricsRegistry()
    app.state.runtime_metrics = http_metrics
    http_tracer = SafeTracer(
        StructuredLogTraceSink(
            StructuredLogger(service="nfcore-api", environment="unspecified")
        )
    )

    @app.middleware("http")
    async def trace_http_request(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        timer = RequestTimer()
        started = datetime.now(UTC)
        context = TraceContext(trace_id=uuid4().hex, correlation_id=uuid4().hex)
        try:
            response = await call_next(request)
        except Exception:
            duration = timer.elapsed()
            try:
                http_metrics.increment(
                    "nfcore_http_requests_total",
                    method=_metric_http_method(request.method), status_class="5xx",
                )
                http_metrics.observe_seconds(
                    "nfcore_http_request", duration,
                    method=_metric_http_method(request.method), status_class="5xx",
                )
            except Exception:
                pass  # Metrics cannot become an HTTP/fiscal execution authority.
            http_tracer.record(
                operation="http.request", context=context, started_at=started,
                elapsed_seconds=duration, outcome="error",
            )
            raise
        duration = timer.elapsed()
        status_class = (
            f"{response.status_code // 100}xx"
            if 100 <= response.status_code <= 599 else "other"
        )
        try:
            http_metrics.increment(
                "nfcore_http_requests_total",
                method=_metric_http_method(request.method), status_class=status_class,
            )
            http_metrics.observe_seconds(
                "nfcore_http_request", duration,
                method=_metric_http_method(request.method), status_class=status_class,
            )
        except Exception:
            pass  # No telemetry failure may change the canonical HTTP response.
        http_tracer.record(
            operation="http.request", context=context, started_at=started,
            elapsed_seconds=duration,
            outcome="error" if response.status_code >= 500 else "ok",
        )
        return response

    if human_identity is not None:
        app.include_router(
            create_human_auth_router(
                human_identity,
                on_login=human_login_completed,
            )
        )
        platform_surfaces = tuple(
            surface
            for surface, configured in (
                ("pricing-admin", pricing_administration is not None),
                (
                    "commercial-release",
                    commercial_release_administration is not None,
                ),
                (
                    "checkout-admin",
                    cakto_checkout_administration is not None,
                ),
            )
            if configured
        )
        app.include_router(
            create_portal_router(
                human_identity,
                portal_executor,
                platform_surfaces=platform_surfaces,
            )
        )
        if pricing_administration is not None:
            app.include_router(
                create_pricing_router(human_identity, pricing_administration)
            )
        if cakto_checkout_administration is not None:
            app.include_router(
                create_cakto_checkout_router(
                    human_identity,
                    cakto_checkout_administration,
                )
            )
        if (
            pricing_administration is not None
            and commercial_release_administration is not None
        ):
            app.include_router(
                create_commercial_release_router(
                    human_identity,
                    pricing_administration,
                    commercial_release_administration,
                    commercial_checkout,
                    checkout_processing_configured=(
                        commercial_checkout_processing_configured
                    ),
                    delivery_readiness=commercial_delivery_readiness,
                    trial_ingress_configured=commercial_trial_ingress_configured,
                    trial_site_channel_configured=(
                        commercial_trial_site_channel_configured
                    ),
                    public_trial_configured=commercial_public_trial_configured,
                    operational_readiness=commercial_operational_readiness,
                    trial_operational_readiness=commercial_trial_operational_readiness,
                    runtime_metrics=http_metrics,
                )
            )
    if password_recovery is not None:
        app.include_router(
            create_password_recovery_router(
                password_recovery,
                delivery=password_reset_delivery,
                on_completed=password_reset_completed,
            )
        )

    @app.exception_handler(HttpContractError)
    async def contract_error_handler(
        _request: Request,
        exc: HttpContractError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc),
            headers={"X-Correlation-Id": exc.correlation_id},
        )

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "live", "product": "FM NFCORE"}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> JSONResponse:
        if security is None or executor is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "reason": "bridge_dependencies_not_configured",
                },
            )
        return JSONResponse(status_code=200, content={"status": "ready"})

    def endpoint_factory(
        operation_id: str,
        success_status: int,
        idempotency_required: bool,
    ) -> Callable[[Request, dict[str, Any]], Awaitable[JSONResponse]]:
        async def endpoint(
            request: Request,
            payload: Annotated[dict[str, Any], Body()],
        ) -> JSONResponse:
            context = _context(request, idempotency_required=idempotency_required)
            if security is None or executor is None:
                raise HttpContractError(
                    503,
                    "RUNTIME_NOT_READY",
                    "Bridge security and execution adapters are not configured",
                    context.correlation_id,
                )
            authorized = security.authorize(operation_id=operation_id, context=context)
            result = executor.execute(
                operation_id=operation_id,
                authorized=authorized,
                payload=payload,
                idempotency_key=context.idempotency_key,
            )
            status_code = result.status_code or success_status
            return JSONResponse(
                status_code=status_code,
                content=dict(result.body),
                headers={"X-Correlation-Id": authorized.correlation_id},
            )

        endpoint.__name__ = operation_id
        return endpoint

    for path, operation_id, success_status, idempotency_required in _OPERATION_PATHS:
        app.add_api_route(
            path,
            endpoint_factory(operation_id, success_status, idempotency_required),
            methods=["POST"],
            operation_id=operation_id,
            status_code=success_status,
            tags=["bridge"],
        )

    return app


app = create_app()
