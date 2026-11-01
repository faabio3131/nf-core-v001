"""Container-facing API assembly with infrastructure readiness and observability."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.application.command_commercial import CommandCommercialReceiver
from kordena_fiscal.application.commercial_acquisition import CommercialAcquisitionService
from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.gateway.production_activation import ProductionExecutionAuthority
from kordena_fiscal.persistence.command_commercial import CommandCommercialStore
from kordena_fiscal.persistence.commercial_fulfillment import (
    postgres_canonical_commercial_database,
)
from kordena_fiscal.persistence.commercial_period_schema import COMMERCIAL_PERIOD_VERSION
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.product.cakto import CaktoWebhookReceiver
from kordena_fiscal.product.checkout import (
    CommercialCheckoutProjector,
    CommercialCheckoutStarter,
)
from kordena_fiscal.product.commercial_readiness import CommercialDeliveryPathReadiness
from kordena_fiscal.security.s2s import (
    FixedWindowRateLimiter,
    SecurityAuditSink,
    WebhookSecurity,
    WorkloadCredentialRecord,
)
from kordena_fiscal.security.secrets import SecretResolver
from kordena_fiscal.web.app import create_app
from kordena_fiscal.web.command_commercial import create_command_commercial_router
from kordena_fiscal.web.commercial_acquisition import (
    create_commercial_acquisition_router,
)
from kordena_fiscal.web.commercial_trial import create_commercial_trial_router
from kordena_fiscal.web.human_recovery import PasswordResetDelivery
from kordena_fiscal.web.production_gsm_binding_admin import create_production_gsm_binding_router
from kordena_fiscal.web.production_gsm_tenant_admin import create_production_gsm_tenant_router
from kordena_fiscal.web.public_trial import PublicTrialAbuseGate, create_public_trial_router
from kordena_fiscal.web.staging_gsm_binding_admin import create_staging_gsm_binding_router
from kordena_fiscal.web.staging_webhook_approval import create_staging_webhook_egress_router
from kordena_fiscal.web.staging_webhook_probe import create_staging_webhook_probe_router

from .activation_email import build_activation_delivery_from_environ
from .alert_rules import InternalAlertMonitor, OperationalSignals
from .api_staging_gsm_probe import staging_probe_verifier
from .cakto import build_cakto_webhook_router
from .composition import RuntimeComposition, build_postgres_runtime_composition
from .config import RuntimeConfigurationError, RuntimeSettings
from .development_commercial_ingress import (
    development_command_resolver,
    development_commercial_ingress,
)
from .development_fiscal_ingress import development_fiscal_ingress
from .fiscal_runtime import FiscalOperationHandler
from .observability import (
    MetricsRegistry,
    RequestTimer,
    SafeTracer,
    StructuredLogger,
    TraceContext,
)
from .otel_trace_sink import build_trace_sink
from .production_gsm import production_api_verifier
from .public_trial_abuse import PostgresPublicTrialAbuseGate
from .secret_manager import SecretBindingAdministration
from .security import configure_edge_security
from .staging_commercial_ingress import staging_commercial_ingress

_TRACE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class RuntimeApi:
    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        workload_credentials: tuple[WorkloadCredentialRecord, ...] = (),
        security_audit_sink: SecurityAuditSink | None = None,
        fiscal_operation_handlers: Mapping[str, FiscalOperationHandler] | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.database: PostgresFiscalDatabase | None = None
        self.composition: RuntimeComposition | None = None
        self._database_boot_error = False
        self._composition_boot_error = False
        if settings.persistence_backend == "postgres":
            assert settings.database_url is not None
            database = None
            try:
                database = PostgresFiscalDatabase(settings.database_url)
                if settings.is_production_like:
                    database.require_current_schema()
                else:
                    database.initialize()
            except Exception:
                if database is not None:
                    database.close()
                self._database_boot_error = True
            else:
                self.database = database
                try:
                    self.composition = build_postgres_runtime_composition(
                        database,
                        workload_credentials=workload_credentials,
                        security_audit_sink=security_audit_sink,
                        fiscal_operation_handlers=fiscal_operation_handlers,
                        metrics=metrics,
                        enable_cakto_checkout=(
                            settings.commercial_checkout_provider == "cakto"
                        ),
                        password_reset_ttl=timedelta(
                            minutes=settings.password_reset_ttl_minutes
                        ),
                    )
                except Exception:
                    self._composition_boot_error = True

    def ready(self) -> tuple[bool, str]:
        if self.settings.persistence_backend == "postgres":
            if self._database_boot_error or self.database is None:
                return False, "database_unavailable"
            if self._composition_boot_error or self.composition is None:
                return False, "composition_unavailable"
            try:
                with self.database.connection() as connection:
                    connection.execute("SELECT 1").fetchone()
                if not self.database.applied_migrations():
                    return False, "schema_not_initialized"
            except Exception:
                return False, "database_unavailable"
        return True, "ready"

    def close(self) -> None:
        if self.database is not None:
            self.database.close()


def _record_commercial_activation_attempt(
    operation: Callable[[], object], metrics: MetricsRegistry
) -> None:
    """Observe activation attempts, never promote telemetry to commercial authority."""
    try:
        operation()
    except Exception:
        try:
            metrics.increment("nfcore_commercial_activation_attempts_total", outcome="failed")
        except Exception:
            pass
        raise
    try:
        metrics.increment("nfcore_commercial_activation_attempts_total", outcome="succeeded")
    except Exception:
        pass


def create_runtime_app(
    settings: RuntimeSettings | None = None,
    *,
    metrics: MetricsRegistry | None = None,
    logger: StructuredLogger | None = None,
    tracer: SafeTracer | None = None,
    cakto_receiver: CaktoWebhookReceiver | None = None,
    command_secret_resolver: SecretResolver | None = None,
    command_product_id: str = "nfcore",
    command_rate_limiter: FixedWindowRateLimiter | None = None,
    commercial_checkout_projector: CommercialCheckoutProjector | None = None,
    commercial_checkout_starter: CommercialCheckoutStarter | None = None,
    commercial_checkout_processing_configured: bool = False,
    commercial_acquisition_security: WebhookSecurity | None = None,
    commercial_acquisition_rate_limiter: FixedWindowRateLimiter | None = None,
    commercial_readiness_rate_limiter: FixedWindowRateLimiter | None = None,
    commercial_trial_security: WebhookSecurity | None = None,
    staging_probe_security: WebhookSecurity | None = None,
    commercial_trial_rate_limiter: FixedWindowRateLimiter | None = None,
    public_trial_allowed_origins: tuple[str, ...] = (),
    public_trial_rate_limiter: PublicTrialAbuseGate | None = None,
    password_reset_delivery: PasswordResetDelivery | None = None,
    production_authority: ProductionExecutionAuthority | None = None,
    workload_credentials: tuple[WorkloadCredentialRecord, ...] = (),
    security_audit_sink: SecurityAuditSink | None = None,
    fiscal_operation_handlers: Mapping[str, FiscalOperationHandler] | None = None,
) -> FastAPI:
    resolved = settings or RuntimeSettings.from_environ()
    runtime_metrics = metrics or MetricsRegistry()
    runtime = RuntimeApi(
        resolved,
        workload_credentials=workload_credentials,
        security_audit_sink=security_audit_sink,
        fiscal_operation_handlers=fiscal_operation_handlers,
        metrics=runtime_metrics,
    )
    runtime_logger = logger or StructuredLogger(
        service="nfcore-api",
        environment=resolved.environment.value,
    )
    runtime_tracer = tracer if tracer is not None else SafeTracer(
        build_trace_sink(runtime_logger, service="nfcore-api")
    )
    composition = runtime.composition
    if (
        staging_probe_security is None
        and resolved.environment.value == "staging"
        and runtime.database is not None
    ):
        staging_probe_security = staging_probe_verifier(runtime.database)
    if resolved.environment.value == "production" and runtime.database is not None:
        # Optional; if explicitly enabled, startup must verify the production
        # service account, durable binding and real GSM read before readiness.
        production_api_verifier(runtime.database)
    if resolved.environment.value == "staging" and runtime.database is not None:
        # Separate channel-specific GSM bindings, validated against the same
        # canonical external vault and existing nfcore-api identity.
        governed_ingress = staging_commercial_ingress(runtime.database)
        if governed_ingress:
            if commercial_trial_security is not None or commercial_acquisition_security is not None:
                raise RuntimeConfigurationError("duplicate commercial ingress authority")
            commercial_trial_security = governed_ingress.get("commercial_trial_security")
            commercial_acquisition_security = governed_ingress.get(
                "commercial_acquisition_security"
            )
    selected_checkout = commercial_checkout_projector
    selected_checkout_starter = commercial_checkout_starter
    selected_checkout_processing = commercial_checkout_processing_configured
    if (
        selected_checkout is None
        and resolved.commercial_checkout_provider == "cakto"
        and composition is not None
        and composition.cakto_checkout_administration is not None
    ):
        selected_checkout = composition.cakto_checkout_administration
        selected_checkout_starter = composition.cakto_checkout_administration
        selected_checkout_processing = cakto_receiver is not None
    if (
        selected_checkout is not None
        and resolved.commercial_checkout_provider is not None
        and selected_checkout.provider_id != resolved.commercial_checkout_provider
    ):
        selected_checkout = None
        selected_checkout_starter = None
        selected_checkout_processing = False

    command_receiver: CommandCommercialReceiver | None = None
    if composition is not None and runtime.database is not None and command_secret_resolver:
        command_receiver = CommandCommercialReceiver(
            store=CommandCommercialStore(runtime.database.connection),
            secrets=command_secret_resolver, product_id=command_product_id,
            environment=resolved.environment.value,
            unit_of_work_factory=postgres_canonical_commercial_database(runtime.database),
            fulfillment=composition.commercial_fulfillment,
            activation=composition.commercial_activation, delivery=password_reset_delivery,
            pricing=composition.pricing_administration,
            release=composition.commercial_release_administration,
        )
    if selected_checkout is not None and selected_checkout.provider_id == "command":
        selected_checkout_processing = command_receiver is not None
    else:
        # The launch channel is Command. A legacy inbox receiver or a caller's
        # boolean does not compose canonical processing/fulfillment/activation.
        selected_checkout_processing = False

    commercial_delivery_readiness = CommercialDeliveryPathReadiness(
        canonical_commercial_persistence=(
            composition is not None and runtime.database is not None
        ),
        fulfillment=(composition is not None and composition.commercial_fulfillment is not None),
        provisioning=(composition is not None and composition.commercial_provisioning is not None),
        activation_delivery=(
            composition is not None and composition.commercial_activation is not None
            and password_reset_delivery is not None
        ),
    )

    readiness_limiter = commercial_readiness_rate_limiter or FixedWindowRateLimiter(
        max_requests=120, window_seconds=60,
    )

    def commercial_operational_readiness() -> bool:
        # One fixed process bucket: no attacker-controlled keys or positive cache.
        # Each assessment resolves at most eight platform-owned candidates.
        now = datetime.now(UTC)
        if not readiness_limiter.allow("commercial-readiness", now):
            return False
        try:
            if not runtime.ready()[0] or runtime.database is None or composition is None:
                return False
            if not set(range(1, COMMERCIAL_PERIOD_VERSION + 1)).issubset(
                runtime.database.applied_migrations()
            ):
                return False
            if (
                composition.commercial_fulfillment is None
                or composition.commercial_provisioning is None
                or composition.commercial_activation is None
                or password_reset_delivery is None
                or selected_checkout is None
                or selected_checkout.provider_id != "command"
                or command_product_id != "nfcore"
                or command_receiver is None
            ):
                return False
            return command_receiver.ready(now=now)
        except Exception:
            return False

    commercial_acquisition: CommercialAcquisitionService | None = None
    if (
        composition is not None
        and runtime.database is not None
        and selected_checkout is not None
        and selected_checkout_starter is not None
        and commercial_acquisition_security is not None
        and selected_checkout.provider_id == selected_checkout_starter.provider_id
    ):
        commercial_acquisition = CommercialAcquisitionService(
            unit_of_work_factory=postgres_canonical_commercial_database(
                runtime.database
            ),
            pricing=composition.pricing_administration,
            release=composition.commercial_release_administration,
            checkout=selected_checkout,
            checkout_starter=selected_checkout_starter,
            checkout_processing_configured=selected_checkout_processing,
            delivery_readiness=commercial_delivery_readiness,
            operational_readiness=commercial_operational_readiness,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(title="FM NFCORE Runtime", version="1.0.0", lifespan=lifespan)
    app.state.nfcore_runtime = runtime
    app.state.nfcore_runtime_composition = composition
    app.state.nfcore_password_recovery = (
        None if composition is None else composition.password_recovery
    )
    app.state.nfcore_password_reset_delivery = password_reset_delivery
    app.state.nfcore_commercial_activation = (
        None if composition is None else composition.commercial_activation
    )
    app.state.nfcore_command_commercial = command_receiver
    app.state.nfcore_commercial_acquisition = commercial_acquisition
    app.state.nfcore_commercial_trial = (
        composition.commercial_trial
        if composition is not None
        and commercial_trial_security is not None
        and password_reset_delivery is not None
        else None
    )
    app.state.nfcore_metrics = runtime_metrics
    alert_monitor = InternalAlertMonitor(runtime_metrics)
    app.state.nfcore_alert_monitor = alert_monitor
    app.state.nfcore_logger = runtime_logger
    app.state.nfcore_tracer = runtime_tracer
    app.state.nfcore_production_authority = production_authority
    configure_edge_security(app, resolved)

    @app.middleware("http")
    async def observe_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        timer = RequestTimer()
        started_at = datetime.now(UTC)
        correlation_id = request.headers.get("X-Correlation-Id", "").strip() or uuid4().hex
        causation_id = request.headers.get("X-Causation-Id", "").strip() or None
        # Untrusted HTTP headers may contain secrets; only bounded safe references
        # become trace metadata. Existing request/header contracts are unchanged.
        trace_correlation = (
            correlation_id if _TRACE_REFERENCE.fullmatch(correlation_id) else uuid4().hex
        )
        trace_causation = (
            causation_id
            if causation_id is not None and _TRACE_REFERENCE.fullmatch(causation_id)
            else None
        )
        context = TraceContext(
            trace_id=uuid4().hex,
            correlation_id=trace_correlation,
            causation_id=trace_causation,
        )
        request.state.nfcore_trace_context = context
        try:
            response = await call_next(request)
            status_code = response.status_code
            outcome = "success" if status_code < 500 else "server_error"
        except Exception as exc:
            elapsed = timer.elapsed()
            runtime_metrics.increment(
                "nfcore_http_requests_total",
                method=request.method,
                status_class="5xx",
            )
            runtime_metrics.observe_seconds(
                "nfcore_http_request",
                elapsed,
                method=request.method,
                status_class="5xx",
            )
            runtime_logger.emit(
                "ERROR",
                "http_request_failed",
                request_id=correlation_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                method=request.method,
                path=request.url.path,
                duration_seconds=elapsed,
                error_type=type(exc).__name__,
            )
            runtime_tracer.record(
                operation="http.request",
                context=context,
                started_at=started_at,
                elapsed_seconds=elapsed,
                outcome="error",
                attributes={"method": request.method, "status_class": "5xx"},
            )
            raise
        elapsed = timer.elapsed()
        status_class = f"{status_code // 100}xx"
        runtime_metrics.increment(
            "nfcore_http_requests_total",
            method=request.method,
            status_class=status_class,
        )
        runtime_metrics.observe_seconds(
            "nfcore_http_request",
            elapsed,
            method=request.method,
            status_class=status_class,
        )
        runtime_logger.emit(
            "INFO",
            "http_request_completed",
            request_id=correlation_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            result=outcome,
            duration_seconds=elapsed,
        )
        runtime_tracer.record(
            operation="http.request",
            context=context,
            started_at=started_at,
            elapsed_seconds=elapsed,
            outcome=outcome,
            attributes={"method": request.method, "status_class": status_class},
        )
        response.headers["X-Correlation-Id"] = correlation_id
        return response

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "live", "product": "FM NFCORE"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        db_timer = RequestTimer()
        db_started = datetime.now(UTC)
        healthy, reason = runtime.ready()
        # Health checks drive real internal evaluation without external I/O or paging.
        app.state.nfcore_alert_candidates = alert_monitor.poll(
            signals=OperationalSignals(
                database_ready=None if reason == "composition_unavailable" else healthy
            )
        )
        if resolved.persistence_backend == "postgres":
            runtime_tracer.record(
                operation="db.readiness",
                context=request.state.nfcore_trace_context,
                started_at=db_started,
                elapsed_seconds=db_timer.elapsed(),
                outcome="ok" if healthy else "error",
                attributes={"backend": "postgres"},
            )
        runtime_metrics.increment(
            "nfcore_dependency_checks_total",
            service="postgres" if resolved.persistence_backend == "postgres" else "sqlite",
            outcome="ready" if healthy else "not_ready",
        )
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "not_ready", "reason": reason},
        )

    @app.get("/internal/metrics", tags=["operability"])
    async def metric_snapshot() -> dict[str, object]:
        # Preserve the existing metrics contract while exposing bounded candidates.
        candidates = alert_monitor.poll()
        return {
            "metrics": runtime_metrics.as_dicts(),
            "alert_candidates": [asdict(candidate) for candidate in candidates],
        }

    @app.get("/runtime/profile", tags=["health"])
    async def profile() -> dict[str, object]:
        active_grants = 0 if production_authority is None else production_authority.active_count
        return {
            "environment": resolved.environment.value,
            "persistence_backend": resolved.persistence_backend,
            "secret_backend_profile": resolved.secret_backend,
            "https_required": resolved.require_https,
            "public_hostname_configured": resolved.public_hostname is not None,
            "trusted_proxy_networks_configured": len(resolved.trusted_proxy_cidrs),
            "human_identity_configured": composition is not None,
            "portal_executor_configured": composition is not None,
            "bridge_security_configured": composition is not None,
            "bridge_executor_configured": composition is not None,
            "bridge_workload_identity_configured": (
                composition is not None
                and composition.bridge_workload_identity_configured
            ),
            "portal_fiscal_operation_executor_configured": composition is not None,
            "fiscal_operation_handlers_configured": (
                []
                if composition is None
                else list(composition.fiscal_operation_path.configured_operations)
            ),
            # P1 certification must distinguish internal ingress composition from
            # external fiscal execution dependencies. These remain false until
            # their concrete adapters are composed in the owning phases.
            "fiscal_provider_transport_real_configured": False,
            "fiscal_external_secret_client_configured": False,
            "fiscal_signer_configured": False,
            "fiscal_runtime_external_execution_ready": False,
            "password_recovery_configured": composition is not None,
            "password_reset_delivery_configured": password_reset_delivery is not None,
            "commercial_activation_configured": (
                composition is not None
                and composition.commercial_activation is not None
            ),
            "pricing_admin_configured": pricing_administration is not None,
            "pricing_catalog_published": (
                pricing_administration is not None
                and pricing_administration.current is not None
            ),
            "commercial_release_admin_configured": (
                commercial_release_administration is not None
            ),
            "commercial_release_status": (
                "unavailable"
                if commercial_release_administration is None
                or commercial_release_administration.current is None
                else commercial_release_administration.current.status.value
            ),
            "commercial_checkout_provider_configured": (
                resolved.commercial_checkout_provider
            ),
            "commercial_checkout_provider_active": (
                None if selected_checkout is None else selected_checkout.provider_id
            ),
            "commercial_checkout_status": (
                "unconfigured"
                if selected_checkout is None
                else selected_checkout.project(
                    None
                    if pricing_administration is None
                    else pricing_administration.current
                ).status.value
            ),
            "commercial_checkout_processing_configured": (
                selected_checkout_processing
            ),
            "canonical_commercial_persistence_configured": (
                commercial_delivery_readiness.canonical_commercial_persistence
            ),
            "commercial_fulfillment_configured": (
                commercial_delivery_readiness.fulfillment
            ),
            "commercial_provisioning_configured": (
                commercial_delivery_readiness.provisioning
            ),
            "commercial_activation_delivery_configured": (
                commercial_delivery_readiness.activation_delivery
            ),
            "commercial_delivery_path_ready": commercial_delivery_readiness.ready,
            "commercial_first_party_acquisition_configured": (
                commercial_acquisition is not None
            ),
            "commercial_trial_configured": (
                app.state.nfcore_commercial_trial is not None
            ),
            "cakto_checkout_admin_configured": (
                cakto_checkout_administration is not None
            ),
            "cakto_checkout_status": (
                "unconfigured"
                if cakto_checkout_administration is None
                else cakto_checkout_administration.project(
                    None
                    if pricing_administration is None
                    else pricing_administration.current
                ).status.value
            ),
            "fiscal_production_activated": active_grants > 0,
            "fiscal_production_active_grants": active_grants,
            "command_webhook_configured": command_receiver is not None,
            "cakto_webhook_configured": cakto_receiver is not None,
        }

    if (
        resolved.environment.value == "staging"
        and composition is not None
        and runtime.database is not None
    ):
        app.include_router(create_staging_gsm_binding_router(
            composition.human_identity,
            SecretBindingAdministration(runtime.database),
        ))
        app.include_router(create_staging_webhook_egress_router(
            composition.human_identity,
            runtime.database,
        ))

    if (
        resolved.environment.value == "production"
        and composition is not None
        and runtime.database is not None
    ):
        app.include_router(create_production_gsm_binding_router(
            composition.human_identity,
            SecretBindingAdministration(runtime.database),
        ))
        app.include_router(create_production_gsm_tenant_router(
            composition.human_identity,
            SecretBindingAdministration(runtime.database),
            runtime.database,
        ))

    if staging_probe_security is not None:
        if resolved.environment.value != "staging":
            raise ValueError("staging webhook probe prohibited outside staging")
        app.include_router(create_staging_webhook_probe_router(staging_probe_security))

    if command_receiver is not None:
        app.include_router(create_command_commercial_router(
            command_receiver, rate_limiter=command_rate_limiter or FixedWindowRateLimiter(
                max_requests=120, window_seconds=60,
            ),
        ))

    if cakto_receiver is not None:
        app.include_router(build_cakto_webhook_router(cakto_receiver))

    if commercial_acquisition is not None and commercial_acquisition_security is not None:
        app.include_router(
            create_commercial_acquisition_router(
                commercial_acquisition,
                security=commercial_acquisition_security,
                rate_limiter=(
                    commercial_acquisition_rate_limiter
                    or FixedWindowRateLimiter(
                        max_requests=30,
                        window_seconds=60,
                    )
                ),
            )
        )

    if (
        composition is not None
        and commercial_trial_security is not None
        and password_reset_delivery is not None
    ):
        app.include_router(
            create_commercial_trial_router(
                composition.commercial_trial,
                security=commercial_trial_security,
                rate_limiter=(
                    commercial_trial_rate_limiter
                    or FixedWindowRateLimiter(
                        max_requests=10,
                        window_seconds=3600,
                    )
                ),
                delivery=password_reset_delivery,
            )
        )

    # Public intake is strictly opt-in and requires externally governed rate
    # limiting, explicit origins, durable commercial state and activation delivery.
    # It is not a fallback for the signed server-to-server commercial route.
    configured_origins = os.getenv("NFCORE_PUBLIC_TRIAL_ALLOWED_ORIGINS", "").strip()
    if configured_origins and public_trial_allowed_origins:
        raise RuntimeConfigurationError("duplicate public trial origin configuration")
    if configured_origins:
        public_trial_allowed_origins = tuple(
            value.strip() for value in configured_origins.split(",")
        )
    if public_trial_allowed_origins and public_trial_rate_limiter is None:
        if runtime.database is not None:
            public_trial_rate_limiter = PostgresPublicTrialAbuseGate(
                runtime.database.connection
            )
    if public_trial_allowed_origins or public_trial_rate_limiter is not None:
        if (
            composition is None
            or password_reset_delivery is None
            or public_trial_rate_limiter is None
            or not public_trial_allowed_origins
        ):
            raise RuntimeConfigurationError("public trial prerequisites are incomplete")
        if resolved.is_production_like and not set(public_trial_allowed_origins).issubset(
            resolved.allowed_origins
        ):
            raise RuntimeConfigurationError(
                "public trial origins must be allowed by canonical edge CORS policy"
            )
        if resolved.is_production_like and isinstance(
            public_trial_rate_limiter, FixedWindowRateLimiter
        ):
            raise RuntimeConfigurationError(
                "public trial requires an externally shared anti-abuse gate"
            )
        def trial_release_authorized() -> bool:
            # The same governed decision used by /v1/commercial/offer controls
            # public trial intake, not a published price or browser assertion.
            decision = composition.commercial_release_administration.current
            return decision is not None and decision.commercially_approved

        app.include_router(
            create_public_trial_router(
                composition.commercial_trial,
                pricing=composition.pricing_administration,
                allowed_origins=public_trial_allowed_origins,
                rate_limiter=public_trial_rate_limiter,
                delivery=password_reset_delivery,
                commercially_authorized=trial_release_authorized,
            )
        )

    human_identity = None if composition is None else composition.human_identity
    password_recovery = None if composition is None else composition.password_recovery
    bridge_security = None if composition is None else composition.bridge_security
    bridge_executor = None if composition is None else composition.bridge_executor
    portal_executor = None if composition is None else composition.portal_executor
    pricing_administration = (
        None if composition is None else composition.pricing_administration
    )
    commercial_release_administration = (
        None
        if composition is None
        else composition.commercial_release_administration
    )
    cakto_checkout_administration = (
        None
        if composition is None
        else composition.cakto_checkout_administration
    )
    def mark_commercial_active(account_id: str, now: datetime) -> None:
        if composition is None:
            return
        _record_commercial_activation_attempt(
            lambda: composition.commercial_activation.mark_active(
                account_id=account_id, now=now
            ),
            runtime_metrics,
        )

    commercial_activation_completed = (
        None if composition is None else mark_commercial_active
    )

    # Fiscal production stays false unless a governed authority is explicitly injected.
    app.mount(
        "/",
        create_app(
            security=bridge_security,
            executor=bridge_executor,
            human_identity=human_identity,
            human_login_completed=commercial_activation_completed,
            password_recovery=password_recovery,
            password_reset_delivery=password_reset_delivery,
            password_reset_completed=commercial_activation_completed,
            portal_executor=portal_executor,
            pricing_administration=pricing_administration,
            commercial_release_administration=commercial_release_administration,
            commercial_checkout=selected_checkout,
            commercial_checkout_processing_configured=(
                # The first-party offer must not advertise a purchase without
                # the signed acquisition route and its matching checkout starter.
                selected_checkout_processing and commercial_acquisition is not None
            ),
            commercial_delivery_readiness=commercial_delivery_readiness,
            commercial_trial_ingress_configured=(
                app.state.nfcore_commercial_trial is not None
            ),
            # Explicitly operator-attested FM Site S2S route. Never infer
            # channel readiness from a secret existing on the API.
            commercial_trial_site_channel_configured=(
                os.getenv("NFCORE_SITE_TRIAL_CHANNEL_READY", "") == "true"
            ),
            commercial_operational_readiness=commercial_operational_readiness,
            cakto_checkout_administration=cakto_checkout_administration,
            runtime_metrics=runtime_metrics,
            cognitive_router=build_cognitive_router(
                human_identity,
                portal_executor,
                os.environ,
                audit_uow_factory=runtime.database,
            ),
        ),
    )
    return app


_entrypoint_settings = RuntimeSettings.from_environ()
_development_ingress = development_commercial_ingress(_entrypoint_settings, os.environ)
app = create_runtime_app(
    _entrypoint_settings,
    password_reset_delivery=build_activation_delivery_from_environ(),
    command_secret_resolver=development_command_resolver(
        _entrypoint_settings, os.environ
    ),
    fiscal_operation_handlers=development_fiscal_ingress(
        _entrypoint_settings, os.environ
    ),
    commercial_acquisition_security=_development_ingress.get(
        "commercial_acquisition_security"
    ),
    commercial_trial_security=_development_ingress.get("commercial_trial_security"),
)
