"""Production composition root for canonical NFCORE application services.

This module only wires already-certified boundaries. It does not create a second auth,
portal, billing, fiscal authority or secret system. Raw secret material remains outside
this composition root and fiscal production authority is injected independently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from kordena_fiscal.application.cakto_claim_automation import (
    CaktoClaimAutomationService,
    CaktoClaimDelivery,
)
from kordena_fiscal.application.cakto_reconciliation import (
    CaktoCanonicalCommercialBridgeService,
)
from kordena_fiscal.application.commercial_activation import (
    CommercialCustomerActivationService,
)
from kordena_fiscal.application.commercial_claim import CommercialClaimService
from kordena_fiscal.application.commercial_fulfillment import CommercialFulfillmentService
from kordena_fiscal.application.commercial_portal import CommercialPortalReadService
from kordena_fiscal.application.commercial_trial import GovernedTrialService
from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive.danfe_pdf import render_authorized_nfe_danfe
from kordena_fiscal.archive.danfse_pdf import render_authorized_national_danfse
from kordena_fiscal.compliance import CapabilityReadinessService
from kordena_fiscal.control_plane.cakto_checkout import (
    CaktoCheckoutAdministrationService,
)
from kordena_fiscal.control_plane.commercial_release import (
    CommercialReleaseAdministrationService,
)
from kordena_fiscal.control_plane.pricing_admin import CommercialPricingAdministrationService
from kordena_fiscal.domain import ExecutionScope
from kordena_fiscal.persistence.cakto import postgres_cakto_commercial_database
from kordena_fiscal.persistence.commercial_fulfillment import (
    postgres_canonical_commercial_database,
)
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.human_administration import HumanAdministrationService
from kordena_fiscal.security.human_identity import (
    HumanIdentityService,
    LoginAttemptLimiter,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_recovery import PasswordRecoveryService
from kordena_fiscal.security.s2s import (
    InMemorySecurityAuditSink,
    S2SAuthorizer,
    SecurityAuditSink,
    WorkloadAuthenticator,
    WorkloadCredentialRecord,
)
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor

from .commercial_provisioning import CommercialCustomerProvisioningService
from .fiscal_runtime import (
    CanonicalBridgeRequestExecutor,
    CanonicalBridgeSecurityBoundary,
    CanonicalFiscalOperationPath,
    CanonicalPortalOperationExecutor,
    FiscalOperationHandler,
)
from .internal_archive_handler import build_archive_reference_handler
from .observability import MetricsRegistry

FiscalOperationHandlerFactory = Callable[
    [FiscalApplicationService], Mapping[str, FiscalOperationHandler]
]


@dataclass(frozen=True, slots=True)
class RuntimeComposition:
    """Canonical durable services owned by one runtime database lifecycle."""

    human_identity: HumanIdentityService
    human_administration: HumanAdministrationService | None
    password_recovery: PasswordRecoveryService
    commercial_provisioning: CommercialCustomerProvisioningService
    commercial_fulfillment: CommercialFulfillmentService
    commercial_claim: CommercialClaimService
    commercial_portal_read: CommercialPortalReadService
    commercial_activation: CommercialCustomerActivationService
    commercial_trial: GovernedTrialService
    pricing_administration: CommercialPricingAdministrationService
    commercial_release_administration: CommercialReleaseAdministrationService
    cakto_checkout_administration: CaktoCheckoutAdministrationService | None
    cakto_claim_automation: CaktoClaimAutomationService
    cakto_canonical_bridge: CaktoCanonicalCommercialBridgeService
    fiscal_application: FiscalApplicationService
    fiscal_operation_path: CanonicalFiscalOperationPath
    bridge_security: CanonicalBridgeSecurityBoundary
    bridge_executor: CanonicalBridgeRequestExecutor
    portal_fiscal_operation_executor: CanonicalPortalOperationExecutor
    bridge_workload_identity_configured: bool
    portal_executor: DurableHumanPortalExecutor


def build_postgres_runtime_composition(
    database: PostgresFiscalDatabase,
    *,
    workload_credentials: tuple[WorkloadCredentialRecord, ...] = (),
    security_audit_sink: SecurityAuditSink | None = None,
    fiscal_operation_handlers: Mapping[str, FiscalOperationHandler] | None = None,
    fiscal_operation_handler_factory: FiscalOperationHandlerFactory | None = None,
    capability_readiness: CapabilityReadinessService | None = None,
    enable_cakto_checkout: bool = False,
    metrics: MetricsRegistry | None = None,
    password_reset_ttl: timedelta = timedelta(minutes=10),
    cakto_claim_delivery: CaktoClaimDelivery | None = None,
    resolve_sp4_numbering: Callable[
        [ExecutionScope, str, str], tuple[int, str]
    ] | None = None,
) -> RuntimeComposition:
    """Compose commercial, human and fiscal ingress over the same PostgreSQL lifecycle."""

    accounts = database.human_accounts()
    sessions = database.web_sessions()
    password_resets = database.password_resets()
    password_hasher = ScryptPasswordHasher()

    identity = HumanIdentityService(
        accounts=accounts,
        sessions=sessions,
        password_hasher=password_hasher,
        login_limiter=LoginAttemptLimiter(),
    )
    human_administration_factory = getattr(database, "human_administration", None)
    human_administration = (
        HumanAdministrationService(
            store=human_administration_factory(),
            password_hasher=password_hasher,
        )
        if callable(human_administration_factory)
        else None
    )
    recovery = PasswordRecoveryService(
        accounts=accounts,
        sessions=sessions,
        resets=password_resets,
        password_hasher=password_hasher,
        reset_ttl=password_reset_ttl,
    )
    provisioning = CommercialCustomerProvisioningService(
        unit_of_work_factory=database,
        accounts=accounts,
        password_hasher=password_hasher,
        password_recovery=recovery,
    )
    canonical_commercial_database = postgres_canonical_commercial_database(database)
    pricing_administration = CommercialPricingAdministrationService(database.pricing_catalog())
    commercial_portal_read = CommercialPortalReadService(
        unit_of_work_factory=canonical_commercial_database,
        pricing=pricing_administration,
    )
    commercial_activation = CommercialCustomerActivationService(
        unit_of_work_factory=canonical_commercial_database,
        provisioning=provisioning,
        password_recovery=recovery,
        pricing=pricing_administration,
    )
    commercial_fulfillment = CommercialFulfillmentService(
        canonical_commercial_database,
        contract_factory=commercial_activation.contract_for,
        metrics=metrics,
    )
    commercial_claim = CommercialClaimService(
        unit_of_work_factory=canonical_commercial_database,
        accounts=accounts,
    )
    commercial_trial = GovernedTrialService(
        unit_of_work_factory=canonical_commercial_database,
        activation=commercial_activation,
        pricing=pricing_administration,
        accounts=accounts,
        request_guard=canonical_commercial_database.guard_trial,
    )
    commercial_release_administration = CommercialReleaseAdministrationService(
        database.commercial_release_catalog()
    )
    cakto_claim_automation = CaktoClaimAutomationService(
        unit_of_work_factory=canonical_commercial_database,
        claims=commercial_claim,
        delivery=cakto_claim_delivery,
    )
    cakto_canonical_bridge = CaktoCanonicalCommercialBridgeService(
        unit_of_work_factory=canonical_commercial_database,
        fulfillment=commercial_fulfillment,
        pricing=pricing_administration,
        claim_automation=cakto_claim_automation,
    )
    cakto_checkout_administration: CaktoCheckoutAdministrationService | None = None
    if enable_cakto_checkout:
        cakto_commercial_database = postgres_cakto_commercial_database(database)
        cakto_commercial_database.require_current_schema()
        cakto_checkout_administration = CaktoCheckoutAdministrationService(
            cakto_commercial_database
        )
    if fiscal_operation_handlers is not None and fiscal_operation_handler_factory is not None:
        raise ValueError("two independent fiscal handler authorities are prohibited")
    fiscal_application = FiscalApplicationService(database, metrics=metrics)
    if fiscal_operation_handler_factory is None:
        canonical_handlers = dict(fiscal_operation_handlers or {})
    else:
        provided = fiscal_operation_handler_factory(fiscal_application)
        if not isinstance(provided, Mapping):
            raise TypeError("fiscal handler factory must return an operation mapping")
        canonical_handlers = dict(provided)
    canonical_handlers.setdefault(
        "queryArchiveReference", build_archive_reference_handler(database)
    )
    fiscal_operation_path = CanonicalFiscalOperationPath(
        fiscal_application,
        handlers=canonical_handlers,
    )
    audit_sink = security_audit_sink
    if audit_sink is None:
        audit_sink = InMemorySecurityAuditSink()
    workload_authenticator = WorkloadAuthenticator(workload_credentials)
    s2s_authorizer = S2SAuthorizer(
        bindings=fiscal_operation_path,
        audit_sink=audit_sink,
    )
    bridge_security = CanonicalBridgeSecurityBoundary(
        authenticator=workload_authenticator,
        authorizer=s2s_authorizer,
    )
    bridge_executor = CanonicalBridgeRequestExecutor(fiscal_operation_path)
    portal_fiscal_operation_executor = CanonicalPortalOperationExecutor(
        unit_of_work_factory=database,
        path=fiscal_operation_path,
    )
    portal = DurableHumanPortalExecutor(
        database,
        operation_executor=portal_fiscal_operation_executor,
        capability_readiness=capability_readiness,
        user_administration=human_administration,
        commercial_reader=commercial_portal_read,
        danfe_renderer=render_authorized_nfe_danfe,
        danfse_renderer=render_authorized_national_danfse,
        resolve_sp4_numbering=resolve_sp4_numbering,
    )
    return RuntimeComposition(
        human_identity=identity,
        human_administration=human_administration,
        password_recovery=recovery,
        commercial_provisioning=provisioning,
        commercial_fulfillment=commercial_fulfillment,
        commercial_claim=commercial_claim,
        commercial_portal_read=commercial_portal_read,
        commercial_activation=commercial_activation,
        commercial_trial=commercial_trial,
        pricing_administration=pricing_administration,
        commercial_release_administration=commercial_release_administration,
        cakto_checkout_administration=cakto_checkout_administration,
        cakto_claim_automation=cakto_claim_automation,
        cakto_canonical_bridge=cakto_canonical_bridge,
        fiscal_application=fiscal_application,
        fiscal_operation_path=fiscal_operation_path,
        bridge_security=bridge_security,
        bridge_executor=bridge_executor,
        portal_fiscal_operation_executor=portal_fiscal_operation_executor,
        bridge_workload_identity_configured=bool(workload_credentials),
        portal_executor=portal,
    )
