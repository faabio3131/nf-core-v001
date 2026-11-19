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

from kordena_fiscal.application.bling_operations import BlingOperationsService
from kordena_fiscal.application.command_commercial import CommandCommercialReceiver
from kordena_fiscal.application.commercial_acquisition import CommercialAcquisitionService
from kordena_fiscal.cognitive.composition import build_cognitive_router
from kordena_fiscal.cognitive.durable_usage import DurableTokenQuotaStore
from kordena_fiscal.compliance.nfse_preaudit import (
    extrema_abrasf_service_preaudit,
    nfse_preaudit,
)
from kordena_fiscal.gateway.production_activation import ProductionExecutionAuthority
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
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
from kordena_fiscal.product.command_commercial_snapshot_api import (
    CommandCommercialSnapshotReader,
    create_command_commercial_snapshot_router,
)
from kordena_fiscal.product.command_operational_usage_snapshot_api import (
    CommandOperationalUsageSnapshotReader,
    create_command_operational_usage_snapshot_router,
)
from kordena_fiscal.product.commercial_readiness import CommercialDeliveryPathReadiness
from kordena_fiscal.security.s2s import (
    FixedWindowRateLimiter,
    SecurityAuditSink,
    WebhookSecurity,
    WorkloadCredentialRecord,
)
from kordena_fiscal.security.secrets import SecretResolver
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web.app import create_app
from kordena_fiscal.web.command_commercial import create_command_commercial_router
from kordena_fiscal.web.commercial_acquisition import (
    create_commercial_acquisition_router,
)
from kordena_fiscal.web.commercial_claim import create_commercial_claim_router
from kordena_fiscal.web.commercial_trial import create_commercial_trial_router
from kordena_fiscal.web.human_recovery import PasswordResetDelivery
from kordena_fiscal.web.production_gsm_binding_admin import create_production_gsm_binding_router
from kordena_fiscal.web.production_gsm_tenant_admin import create_production_gsm_tenant_router
from kordena_fiscal.web.public_commercial_acquisition import (
    PublicCommercialAcquisitionAbuseGate,
    create_public_commercial_acquisition_router,
)
from kordena_fiscal.web.public_trial import PublicTrialAbuseGate, create_public_trial_router
from kordena_fiscal.web.staging_gsm_binding_admin import create_staging_gsm_binding_router
from kordena_fiscal.web.staging_webhook_approval import create_staging_webhook_egress_router
from kordena_fiscal.web.staging_webhook_probe import create_staging_webhook_probe_router

from .activation_email import build_activation_delivery_from_environ
from .ai_secrets import build_production_openai_key_readers
from .alert_rules import InternalAlertMonitor, OperationalSignals
from .api_staging_gsm_probe import staging_probe_verifier
from .bling_ingress import build_bling_ingress
from .bling_multitenant_ingress import build_multitenant_bling_ingress
from .bling_oauth_factory import build_bling_oauth_service
from .bling_oauth_routes import build_bling_oauth_router
from .bling_operations import build_bling_operations_router
from .bling_preparation import BlingSalePreparer
from .bling_review import build_bling_review_router
from .bling_status import build_bling_status_router
from .bling_worker import build_bling_orders
from .bridge_credentials import load_bridge_credentials
from .cakto import build_cakto_webhook_router, compose_postgres_cakto_commercial_runtime
from .cakto_claim_email import build_cakto_claim_delivery_from_environ
from .canonical_fiscal_composition import (
    build_runtime_fiscal_handler_factory,
    fiscal_external_dependency_snapshot,
)
from .composition import (
    FiscalOperationHandlerFactory,
    RuntimeComposition,
    build_postgres_runtime_composition,
)
from .config import RuntimeConfigurationError, RuntimeSettings
from .development_commercial_ingress import (
    development_command_resolver,
    development_commercial_ingress,
)
from .development_fiscal_ingress import development_fiscal_ingress
from .extrema_webiss_environment import build_extrema_webiss_exchange
from .fiscal_runtime import FiscalOperationHandler
from .observability import (
    MetricsRegistry,
    RequestTimer,
    SafeTracer,
    StructuredLogger,
    TraceContext,
)
from .otel_trace_sink import build_trace_sink
from .production_cakto_ingress import production_cakto_webhook_secret
from .production_cakto_webhook_env import production_cakto_webhook_secret_from_env
from .production_command_ingress import production_command_resolver
from .production_commercial_acquisition_env import (
    production_commercial_acquisition_security_from_env,
)
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
        fiscal_operation_handler_factory: FiscalOperationHandlerFactory | None = None,
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
                    if os.environ.get("NFCORE_BLING_INSTALLATIONS_ENABLED") == "true":
                        database.require_current_schema(require_bling=True)
                    else:
                        database.require_current_schema()
                else:
                    database.initialize(
                        enable_bling=os.environ.get("NFCORE_BLING_INSTALLATIONS_ENABLED") == "true"
                    )
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
                        fiscal_operation_handler_factory=fiscal_operation_handler_factory,
                        metrics=metrics,
                        enable_cakto_checkout=(
                            settings.commercial_checkout_provider == "cakto"
                        ),
                        password_reset_ttl=timedelta(
                            minutes=settings.password_reset_ttl_minutes
                        ),
                        cakto_claim_delivery=build_cakto_claim_delivery_from_environ(),
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
    public_commercial_acquisition_allowed_origins: tuple[str, ...] = (),
    public_commercial_acquisition_rate_limiter: PublicCommercialAcquisitionAbuseGate | None = None,
    password_reset_delivery: PasswordResetDelivery | None = None,
    production_authority: ProductionExecutionAuthority | None = None,
    workload_credentials: tuple[WorkloadCredentialRecord, ...] = (),
    security_audit_sink: SecurityAuditSink | None = None,
    fiscal_operation_handlers: Mapping[str, FiscalOperationHandler] | None = None,
    fiscal_operation_handler_factory: FiscalOperationHandlerFactory | None = None,
    certificate_vault: EncryptedA1Vault | None = None,
    fiscal_dependency_probe: Callable[[], Mapping[str, bool]] | None = None,
) -> FastAPI:
    resolved = settings or RuntimeSettings.from_environ()
    runtime_metrics = metrics or MetricsRegistry()
    runtime = RuntimeApi(
        resolved,
        workload_credentials=workload_credentials,
        security_audit_sink=security_audit_sink,
        fiscal_operation_handlers=fiscal_operation_handlers,
        fiscal_operation_handler_factory=fiscal_operation_handler_factory,
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
    if resolved.environment.value == "production":
        # Separate, explicitly approved Command signing scope. A configured
        # production channel may never downgrade to development HMAC material.
        if runtime.database is None:
            if os.getenv("NFCORE_PRODUCTION_COMMAND_MODE"):
                raise RuntimeConfigurationError(
                    "production Command requires canonical PostgreSQL"
                )
        else:
            # Optional API identity probe, validating the existing GSM authority.
            production_api_verifier(runtime.database)
            approved_command = production_command_resolver(runtime.database)
            if approved_command is not None:
                if command_secret_resolver is not None:
                    raise RuntimeConfigurationError(
                        "duplicate production Command secret authority"
                    )
                command_secret_resolver = approved_command
            # Separate, explicitly approved Cakto webhook signing scope. A
            # configured production secret may never downgrade to a caller-
            # supplied receiver or guessed/default material.
            approved_cakto_webhook_secret = production_cakto_webhook_secret(
                runtime.database
            )
            if approved_cakto_webhook_secret is None:
                # Lightweight fallback, mirroring EncryptedA1Vault.from_environ():
                # a deployment-owned secret supplied out of band via env var for
                # deployments that have not bootstrapped GSM yet. Fail-closed,
                # never guessed/derived; GSM takes precedence when configured.
                approved_cakto_webhook_secret = production_cakto_webhook_secret_from_env()
            if approved_cakto_webhook_secret is not None:
                if cakto_receiver is not None:
                    raise RuntimeConfigurationError(
                        "duplicate production Cakto webhook authority"
                    )
                cakto_receiver = compose_postgres_cakto_commercial_runtime(
                    fiscal_database=runtime.database,
                    webhook_secret=approved_cakto_webhook_secret,
                    metrics=runtime_metrics,
                    canonical_bridge=(
                        composition.cakto_canonical_bridge
                        if composition is not None
                        else None
                    ),
                ).receiver
            # Separate, explicitly approved commercial-acquisition signing
            # scope. The first-party offer must not advertise a purchase
            # without this signed route; a configured production secret may
            # never downgrade to development/staging HMAC material.
            approved_commercial_acquisition_security = (
                production_commercial_acquisition_security_from_env()
            )
            if approved_commercial_acquisition_security is not None:
                if commercial_acquisition_security is not None:
                    raise RuntimeConfigurationError(
                        "duplicate production commercial acquisition authority"
                    )
                commercial_acquisition_security = approved_commercial_acquisition_security
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
    elif selected_checkout is not None and selected_checkout.provider_id == "cakto":
        # The Cakto webhook receiver only exists when a real, governed webhook
        # secret was resolved (production_cakto_webhook_secret / explicit dev
        # config), and it is always composed with the same canonical bridge
        # (composition.cakto_canonical_bridge) that drives fulfillment and
        # activation for Command. Cakto is therefore an equally authoritative
        # direct-sale channel, not a degraded one — required for an individual
        # (pessoa física) seller who has no Command counterpart to process
        # through.
        selected_checkout_processing = cakto_receiver is not None
    else:
        # No recognized processing/fulfillment/activation pipeline is bound to
        # this provider; a legacy inbox receiver or a caller's boolean does
        # not compose canonical processing/fulfillment/activation.
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
            ):
                return False
            if selected_checkout.provider_id == "command":
                if command_product_id != "nfcore" or command_receiver is None:
                    return False
                return command_receiver.ready(now=now)
            if selected_checkout.provider_id == "cakto":
                # Cakto has no rotating S2S binding to revalidate live, unlike
                # Command. Its one static, governed webhook secret is resolved
                # once at process startup (compose_postgres_cakto_commercial_runtime);
                # a non-None cakto_receiver is proof that resolution already
                # succeeded and the receiver is wired to the same canonical
                # bridge that drives fulfillment/activation for Command. There
                # is nothing further to revalidate per-request.
                return cakto_receiver is not None
            # No recognized channel has an operational-readiness probe.
            return False
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
    app.state.nfcore_public_trial_configured = False
    app.state.nfcore_public_commercial_acquisition_configured = False
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
            # These are dependency-configuration indicators, not a declaration
            # that any tenant's real fiscal documents are officially homologated.
            **(
                fiscal_dependency_probe()
                if fiscal_dependency_probe is not None
                else fiscal_external_dependency_snapshot(certificate_vault=certificate_vault)
            ),
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
            # Separate the anonymous HTTPS trial route from signed S2S trial.
            "public_trial_configured": app.state.nfcore_public_trial_configured,
            # Separate the anonymous HTTPS acquisition route from signed S2S.
            "public_commercial_acquisition_configured": (
                app.state.nfcore_public_commercial_acquisition_configured
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

    # The new multi-installation mode is opt-in and never coexists with
    # the legacy single-company webhook/worker authority.
    if os.environ.get("NFCORE_BLING_INSTALLATIONS_ENABLED") == "true":
        if any(
            os.environ.get("NFCORE_BLING_" + field, "").strip()
            for field in ("COMPANY_ID", "TENANT_ID", "UNIT_ID", "ENVIRONMENT")
        ):
            raise RuntimeConfigurationError(
                "Bling global single-company authority conflicts with multi-installation mode"
            )
        if composition is None or runtime.database is None:
            raise RuntimeConfigurationError("Bling requires canonical runtime composition")
        installations, oauth = build_bling_oauth_service(runtime.database, os.environ)
        app.include_router(build_multitenant_bling_ingress(
            composition.fiscal_application, installations, oauth,
        ))
        app.include_router(build_bling_oauth_router(
            composition.human_identity, installations, oauth,
        ))
        app.include_router(build_bling_operations_router(
            composition.human_identity, installations,
            BlingOperationsService(runtime.database, installations, oauth),
            preparer=BlingSalePreparer(os.environ),
        ))
    else:
        bling_router = build_bling_ingress(
            composition.fiscal_application if composition is not None else None,
            os.environ,
        )
        if bling_router is not None:
            app.include_router(bling_router)
            if composition is not None and runtime.database is not None:
                bling_database = runtime.database
                app.include_router(build_bling_review_router(
                    composition.human_identity,
                    lambda: build_bling_orders(bling_database, os.environ),
                    preparer=BlingSalePreparer(os.environ),
                ))
                app.include_router(build_bling_status_router(
                    runtime.database, os.environ["NFCORE_BLING_COMPANY_ID"].strip(),
                    composition.bridge_security,
                ))

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

    # Self-service claim: lets a paying customer, who already received a
    # one-time claim link by email after an upstream checkout provider (e.g.
    # Cakto) confirmed payment, activate their own canonical purchase. Gated on
    # the same composition/delivery used by every other activation path so no
    # second provisioning or account-creation authority is introduced here.
    if (
        composition is not None
        and composition.commercial_claim is not None
        and composition.commercial_activation is not None
        and password_reset_delivery is not None
    ):
        app.include_router(
            create_commercial_claim_router(
                composition.commercial_claim,
                activation=composition.commercial_activation,
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
        app.state.nfcore_public_trial_configured = True

    # Public first-party acquisition intake: the browser-facing counterpart to
    # the signed /v1/commercial/acquisitions route. Same opt-in posture as
    # public trial intake above -- explicit origins, externally shared
    # anti-abuse gate, never automatically enabled. It calls the same
    # in-process CommercialAcquisitionService the signed route uses, so the
    # HMAC signature requirement (which protects an authenticated network
    # boundary) does not apply: this process is already the trusted caller.
    configured_acquisition_origins = os.getenv(
        "NFCORE_PUBLIC_COMMERCIAL_ACQUISITION_ALLOWED_ORIGINS", ""
    ).strip()
    if configured_acquisition_origins and public_commercial_acquisition_allowed_origins:
        raise RuntimeConfigurationError(
            "duplicate public commercial acquisition origin configuration"
        )
    if configured_acquisition_origins:
        public_commercial_acquisition_allowed_origins = tuple(
            value.strip() for value in configured_acquisition_origins.split(",")
        )
    if (
        public_commercial_acquisition_allowed_origins
        and public_commercial_acquisition_rate_limiter is None
        and runtime.database is not None
    ):
        public_commercial_acquisition_rate_limiter = PostgresPublicTrialAbuseGate(
            runtime.database.connection,
            scope_prefix="public-acquisition",
        )
    if (
        public_commercial_acquisition_allowed_origins
        or public_commercial_acquisition_rate_limiter is not None
    ):
        if (
            commercial_acquisition is None
            or public_commercial_acquisition_rate_limiter is None
            or not public_commercial_acquisition_allowed_origins
        ):
            raise RuntimeConfigurationError(
                "public commercial acquisition prerequisites are incomplete"
            )
        if resolved.is_production_like and not set(
            public_commercial_acquisition_allowed_origins
        ).issubset(resolved.allowed_origins):
            raise RuntimeConfigurationError(
                "public commercial acquisition origins must be allowed by canonical"
                " edge CORS policy"
            )
        if resolved.is_production_like and isinstance(
            public_commercial_acquisition_rate_limiter, FixedWindowRateLimiter
        ):
            raise RuntimeConfigurationError(
                "public commercial acquisition requires an externally shared anti-abuse gate"
            )
        app.include_router(
            create_public_commercial_acquisition_router(
                commercial_acquisition,
                allowed_origins=public_commercial_acquisition_allowed_origins,
                rate_limiter=public_commercial_acquisition_rate_limiter,
            )
        )
        app.state.nfcore_public_commercial_acquisition_configured = True

    def public_trial_operational_readiness() -> bool:
        """Read-only, fail-closed availability of the independent browser trial."""
        if (
            not app.state.nfcore_public_trial_configured
            or runtime.database is None
            or composition is None
            or composition.commercial_trial is None
            or password_reset_delivery is None
            or not commercial_delivery_readiness.ready
        ):
            return False
        try:
            if not runtime.ready()[0]:
                return False
            with runtime.database.connection() as connection:
                row = connection.execute(
                    "SELECT to_regclass('fm_public_trial_rate_windows')"
                ).fetchone()
            return row is not None and row[0] is not None
        except Exception:
            return False

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

    # Single reader instance shared by the commercial snapshot router and the
    # operational-usage router below: the latter only projects fields out of
    # rows the former already fetches, never a second query/connection.
    _command_commercial_reader = (
        CommandCommercialSnapshotReader(runtime.database.connection)
        if runtime.database is not None else None
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
            certificate_vault=certificate_vault,
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
            commercial_public_trial_configured=(
                app.state.nfcore_public_trial_configured
            ),
            # Explicitly operator-attested FM Site S2S route. Never infer
            # channel readiness from a secret existing on the API.
            commercial_trial_site_channel_configured=(
                os.getenv("NFCORE_SITE_TRIAL_CHANNEL_READY", "") == "true"
            ),
            commercial_operational_readiness=commercial_operational_readiness,
            commercial_trial_operational_readiness=(
                public_trial_operational_readiness
            ),
            cakto_checkout_administration=cakto_checkout_administration,
            runtime_metrics=runtime_metrics,
            cognitive_router=build_cognitive_router(
                human_identity,
                portal_executor,
                os.environ,
                audit_uow_factory=runtime.database,
                runtime_environment=resolved.environment.value,
                quota_store=(
                    DurableTokenQuotaStore(runtime.database.connection)
                    if runtime.database is not None else None
                ),
                model_key_readers=(
                    build_production_openai_key_readers(os.environ)
                    if (
                        resolved.environment.value == "production"
                        and os.environ.get("NFCORE_COGNITIVE_ENABLED") == "true"
                        and os.environ.get("NFCORE_COGNITIVE_DURABLE_AI_ENABLED") == "true"
                        and runtime.database is not None
                    )
                    else None
                ),
            ),
            command_commercial_router=create_command_commercial_snapshot_router(
                _command_commercial_reader,
                os.environ,
            ),
            command_operational_usage_router=create_command_operational_usage_snapshot_router(
                CommandOperationalUsageSnapshotReader(_command_commercial_reader)
                if _command_commercial_reader is not None else None,
                os.environ,
            ),
        ),
    )
    return app


_entrypoint_settings = RuntimeSettings.from_environ()
_entrypoint_certificate_vault = EncryptedA1Vault.from_environ()
_development_ingress = development_commercial_ingress(_entrypoint_settings, os.environ)
app = create_runtime_app(
    _entrypoint_settings,
    workload_credentials=load_bridge_credentials(os.environ),
    password_reset_delivery=build_activation_delivery_from_environ(),
    certificate_vault=_entrypoint_certificate_vault,
    fiscal_dependency_probe=lambda: fiscal_external_dependency_snapshot(
        certificate_vault=_entrypoint_certificate_vault,
        trusted_signed_dps_builder=build_signed_dps,
        nfse_preaudit=nfse_preaudit,
    ),
    command_secret_resolver=development_command_resolver(
        _entrypoint_settings, os.environ
    ),
    fiscal_operation_handlers=(
        development_fiscal_ingress(_entrypoint_settings, os.environ)
        if _entrypoint_settings.environment.value in {"development", "test"}
        else None
    ),
    fiscal_operation_handler_factory=(
        build_runtime_fiscal_handler_factory(
            certificate_vault=_entrypoint_certificate_vault,
            trusted_signed_dps_builder=build_signed_dps,
            nfse_preaudit=nfse_preaudit,
            webiss_extrema_exchange=build_extrema_webiss_exchange(os.environ),
            webiss_service_preaudit=(
                extrema_abrasf_service_preaudit
                if os.environ.get("NFCORE_EXTREMA_WEBISS_HOMOLOGATION_URL")
                else None
            ),
        )
        if _entrypoint_settings.environment.value in {"staging", "production"}
        else None
    ),
    commercial_acquisition_security=_development_ingress.get(
        "commercial_acquisition_security"
    ),
    commercial_trial_security=_development_ingress.get("commercial_trial_security"),
)
