from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CommercialConfigurationService,
    ConfiguredFiscalOperation,
    ControlPlaneAuditAction,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    ProviderBinding,
    ProviderRuntimePolicyConfig,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.control_plane.commercial_admin import (
    CommercialRuntimeConfigurationService,
)
from kordena_fiscal.control_plane.commercial_models import HomologationEvidenceRecord
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    HostNamespace,
)
from kordena_fiscal.gateway import ProviderDescriptor, ProviderOperation
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.controlled_pilots import (
    ControlledPilotGovernanceService,
    ControlledPilotScope,
    PilotDecisionStatus,
)
from kordena_fiscal.runtime.homologation_readiness import (
    DurableHomologationEnvironmentReadinessService,
)
from kordena_fiscal.security import (
    AuthenticatedCaller,
    AuthorizedFiscalRequest,
    CallerIdentity,
    FiscalCapability,
    HostScopeGrant,
)

NOW = datetime(2026, 9, 13, 20, 30, tzinfo=UTC)
SP = BrazilianJurisdiction("SP")
PROVIDER = "provider-pilot-b5"


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-b5-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.COMMERCIAL_CONFIG_WRITE,
            }
        ),
        global_scope=True,
    )


def _scope(*, tenant_id: str = "tenant-b5") -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.synthetic-b5",
        tenant_id=tenant_id,
        unit_id="unit-b5",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-b5-scope",
    )


def _pilot() -> ControlledPilotScope:
    return ControlledPilotScope(
        pilot_id="pilot-b5",
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=SP,
        provider_id=PROVIDER,
        allowed_operations=frozenset({ProviderOperation.AUTHORIZE}),
    )


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=PROVIDER,
        document_kinds=frozenset({FiscalDocumentKind.NFE}),
        jurisdictions=(SP,),
        environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        operations=frozenset({ProviderOperation.AUTHORIZE}),
    )


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-b5-pilot.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    control = DurableControlPlaneService(database)
    control.onboard_organization(
        actor=_admin(),
        tenant_id="tenant-b5",
        legal_name="Synthetic B5 Pilot Tenant",
        correlation_id="corr-b5-org",
    )
    control.onboard_unit(
        actor=_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-b5",
            unit_id="unit-b5",
            display_name="Synthetic B5 Pilot Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-b5-unit",
    )
    for kind, provider_id, suffix in (
        (SecretReferenceKind.CERTIFICATE, None, "certificate"),
        (SecretReferenceKind.CREDENTIALS, PROVIDER, "credentials"),
    ):
        control.bind_secret_reference(
            actor=_admin(),
            reference=SecretReference(
                reference_id=f"ref:synthetic/b5/{suffix}",
                kind=kind,
                tenant_id="tenant-b5",
                unit_id="unit-b5",
                environment=FiscalEnvironment.HOMOLOGATION,
                provider_id=provider_id,
            ),
            correlation_id=f"corr-b5-{suffix}",
        )

    commercial = CommercialConfigurationService(database)
    commercial.set_runtime_policy(
        actor=_admin(),
        policy=ProviderRuntimePolicyConfig(
            policy_id="policy-b5",
            tenant_id="tenant-b5",
            unit_id="unit-b5",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER,
            connect_timeout_seconds=5,
            read_timeout_seconds=15,
            max_attempts=2,
            base_delay_seconds=0.1,
            max_delay_seconds=0.5,
            jitter_ratio=0,
            circuit_failure_threshold=2,
            circuit_recovery_seconds=10,
        ),
    )
    commercial.set_provider_binding(
        actor=_admin(),
        binding=ProviderBinding(
            binding_id="binding-pilot-b5",
            tenant_id="tenant-b5",
            unit_id="unit-b5",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id=PROVIDER,
        ),
    )
    CommercialRuntimeConfigurationService(database).set_homologation_evidence(
        actor=_admin(),
        record=HomologationEvidenceRecord(
            tenant_id="tenant-b5",
            unit_id="unit-b5",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id=PROVIDER,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation="authorize",
            provider_adapter_available=True,
            credentials_reference_configured=True,
            signer_capability=True,
            csc_reference_configured=False,
            transport_configured=True,
            resilience_certified=True,
            contract_tests_certified=True,
            jurisdiction_mapping=True,
            operation_supported=True,
            requires_signer=True,
            external_official=False,
            recorded_at=NOW,
        ),
    )
    return database


def _service(database: SqliteFiscalDatabase) -> ControlledPilotGovernanceService:
    readiness = DurableHomologationEnvironmentReadinessService(
        database,
        provider_catalog=(_descriptor(),),
    )
    return ControlledPilotGovernanceService(database, readiness=readiness)


def _authorized(
    *,
    capability: FiscalCapability = FiscalCapability.ISSUE,
    scope: ExecutionScope | None = None,
) -> AuthorizedFiscalRequest:
    caller = AuthenticatedCaller(
        identity=CallerIdentity(
            caller_id="synthetic-b5-backend",
            host_namespace=HostNamespace("fm.synthetic-b5"),
            capabilities=frozenset(
                {
                    FiscalCapability.ISSUE,
                    FiscalCapability.QUERY,
                    FiscalCapability.CANCEL,
                }
            ),
            scope_grants=(HostScopeGrant(tenant_id="tenant-b5", unit_id="unit-b5"),),
        ),
        credential_id="synthetic-b5-authenticated",
    )
    return AuthorizedFiscalRequest(
        caller=caller,
        capability=capability,
        scope=scope or _scope(),
        correlation_id="corr-b5-authorized",
    )


def test_b5_internal_pilot_go_and_external_pilot_blocked_without_official_evidence(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    service = _service(database)
    pilot = _pilot()
    service.activate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-activate",
        now=NOW,
    )

    internal = service.decide(
        pilot=pilot,
        authorized_request=_authorized(),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-go-internal",
        now=NOW + timedelta(seconds=1),
    )
    external = service.decide(
        pilot=pilot,
        authorized_request=_authorized(),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-external",
        now=NOW + timedelta(seconds=2),
        require_external=True,
    )

    assert internal.status is PilotDecisionStatus.GO_INTERNAL
    assert internal.internal_ready is True
    assert internal.official_evidence_present is False
    assert external.status is PilotDecisionStatus.BLOCKED_EXTERNAL
    assert external.reasons == ("external_official_evidence_missing",)


def test_b5_kill_switch_is_durable_and_fails_closed_after_restart(tmp_path) -> None:
    database = _database(tmp_path)
    pilot = _pilot()
    service = _service(database)
    service.activate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-activate-kill",
        now=NOW,
    )
    service.deactivate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-deactivate",
        now=NOW + timedelta(seconds=1),
    )

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    decision = _service(restarted).decide(
        pilot=pilot,
        authorized_request=_authorized(),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-after-restart",
        now=NOW + timedelta(seconds=2),
    )

    assert decision.status is PilotDecisionStatus.NO_GO
    assert decision.reasons == ("pilot_kill_switch_disabled",)


def test_b5_operation_allowlist_and_s2s_scope_fail_closed(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    pilot = _pilot()
    service.activate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-activate-negative",
        now=NOW,
    )

    not_allowlisted = service.decide(
        pilot=pilot,
        authorized_request=_authorized(capability=FiscalCapability.QUERY),
        operation=ProviderOperation.QUERY,
        correlation_id="corr-b5-not-allowlisted",
        now=NOW + timedelta(seconds=1),
    )
    wrong_scope = service.decide(
        pilot=pilot,
        authorized_request=_authorized(scope=_scope(tenant_id="tenant-other")),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-cross-tenant",
        now=NOW + timedelta(seconds=2),
    )

    assert not_allowlisted.status is PilotDecisionStatus.NO_GO
    assert not_allowlisted.reasons == ("operation_not_allowlisted",)
    assert wrong_scope.status is PilotDecisionStatus.NO_GO
    assert wrong_scope.reasons == ("s2s_scope_mismatch",)


def test_b5_provider_operation_kill_switch_is_configuration_driven(tmp_path) -> None:
    database = _database(tmp_path)
    pilot = _pilot()
    service = _service(database)
    service.activate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-activate-provider",
        now=NOW,
    )
    CommercialConfigurationService(database).set_provider_binding(
        actor=_admin(),
        binding=ProviderBinding(
            binding_id="binding-pilot-b5-disabled",
            tenant_id="tenant-b5",
            unit_id="unit-b5",
            environment=FiscalEnvironment.HOMOLOGATION,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=SP,
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id=PROVIDER,
            enabled=False,
        ),
    )

    decision = service.decide(
        pilot=pilot,
        authorized_request=_authorized(),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-provider-disabled",
        now=NOW + timedelta(seconds=1),
    )

    assert decision.status is PilotDecisionStatus.NO_GO
    assert "provider_binding" in decision.reasons


def test_b5_pilot_governance_is_audited_without_secret_payloads(tmp_path) -> None:
    database = _database(tmp_path)
    service = _service(database)
    pilot = _pilot()
    service.activate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-audit-activate",
        now=NOW,
    )
    service.decide(
        pilot=pilot,
        authorized_request=_authorized(),
        operation=ProviderOperation.AUTHORIZE,
        correlation_id="corr-b5-audit-decision",
        now=NOW + timedelta(seconds=1),
    )
    service.record_scope_change(
        actor=_admin(),
        previous=pilot,
        current=pilot,
        correlation_id="corr-b5-audit-scope",
        now=NOW + timedelta(seconds=2),
    )
    service.deactivate(
        actor=_admin(),
        pilot=pilot,
        correlation_id="corr-b5-audit-deactivate",
        now=NOW + timedelta(seconds=3),
    )

    with database() as uow:
        records = uow.control_plane.list_audit("tenant-b5")

    pilot_actions = tuple(
        record.action
        for record in records
        if record.target_type == "controlled_pilot"
    )
    assert ControlPlaneAuditAction.PILOT_ACTIVATED in pilot_actions
    assert ControlPlaneAuditAction.PILOT_DECISION_RECORDED in pilot_actions
    assert ControlPlaneAuditAction.PILOT_SCOPE_CHANGED in pilot_actions
    assert ControlPlaneAuditAction.PILOT_DEACTIVATED in pilot_actions
    serialized = "\n".join(repr(record) for record in records)
    assert "synthetic-workload-secret" not in serialized
    assert "private_key" not in serialized
