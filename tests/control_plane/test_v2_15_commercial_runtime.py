from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CommercialConfigurationService,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    ProviderRuntimePolicyConfig,
)
from kordena_fiscal.control_plane.commercial_admin import (
    CommercialRuntimeConfigurationService,
)
from kordena_fiscal.control_plane.commercial_models import (
    HomologationEvidenceRecord,
    NumberingConfiguration,
)
from kordena_fiscal.control_plane.service import ControlPlaneNotFoundError
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalUnitId,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.gateway import (
    ProviderOperation,
    ProviderRequest,
    ProviderResponse,
    ProviderResponseStatus,
    ProviderTimeoutPolicy,
    ProviderUnavailableError,
    SyntheticProviderTransport,
)
from kordena_fiscal.homologation import TechnicalGateState
from kordena_fiscal.numbering import InMemoryFiscalSequenceStore
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.commercial import (
    DurableConfiguredSequenceManager,
    DurableFiscalBindingResolver,
    DurableHomologationEvidenceResolver,
    DurableNumberingConfigurationResolver,
    DurablePolicyResilientProviderGateway,
    DurableProviderRuntimePolicyResolver,
    DurableWorkloadAuthenticator,
    PolicyBoundFiscalProviderTransport,
)
from kordena_fiscal.security import (
    CallerIdentity,
    FiscalCapability,
    HostScopeGrant,
    InMemorySecurityAuditSink,
    S2SAuthorizer,
    WorkloadAuthenticationError,
    WorkloadCredentialRecord,
)
from kordena_fiscal.vault import EphemeralProviderCredentialsMaterial

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
SECRET = "v2-15-durable-workload-secret-0123456789abcdef"


def _database(tmp_path) -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-commercial-runtime.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-15-global-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.COMMERCIAL_CONFIG_WRITE,
            }
        ),
        global_scope=True,
    )


def _onboard(database: SqliteFiscalDatabase) -> None:
    service = DurableControlPlaneService(database)
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id="tenant-a",
        legal_name="V2-15 Synthetic Tenant",
        correlation_id="corr-v2-15-org",
    )
    service.onboard_unit(
        actor=_global_admin(),
        registration=FiscalUnitRegistration(
            tenant_id="tenant-a",
            unit_id="unit-a",
            display_name="V2-15 Synthetic Unit",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ),
        correlation_id="corr-v2-15-unit",
    )


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.synthetic",
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-v2-15-runtime",
    )


def _policy() -> ProviderRuntimePolicyConfig:
    return ProviderRuntimePolicyConfig(
        policy_id="policy-provider-a-hml",
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="provider-a",
        connect_timeout_seconds=7,
        read_timeout_seconds=11,
        max_attempts=2,
        base_delay_seconds=0.5,
        max_delay_seconds=1.0,
        jitter_ratio=0,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=15,
        circuit_success_threshold=1,
    )


def _query_request() -> ProviderRequest:
    return ProviderRequest(
        scope=_scope(),
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=BrazilianJurisdiction("SP"),
        operation=ProviderOperation.QUERY,
        payload=b"<synthetic-query />",
        correlation_id="corr-v2-15-query",
        workload_id="workload-v2-15",
    )


def test_numbering_configuration_survives_restart_and_drives_series_and_bounds(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    service = CommercialRuntimeConfigurationService(database)
    service.set_numbering_configuration(
        actor=_global_admin(),
        config=NumberingConfiguration(
            tenant_id="tenant-a",
            unit_id="unit-a",
            environment=FiscalEnvironment.HOMOLOGATION,
            model=ElectronicInvoiceModel.NFCE,
            series=7,
            first_number=100,
            max_number=101,
        ),
    )

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    resolver = DurableNumberingConfigurationResolver(restarted)
    manager = DurableConfiguredSequenceManager(
        store=InMemoryFiscalSequenceStore(),
        resolver=resolver,
    )

    first = manager.reserve(_scope(), model=ElectronicInvoiceModel.NFCE)
    second = manager.reserve(_scope(), model=ElectronicInvoiceModel.NFCE)

    assert first.key.series == 7
    assert first.number == 100
    assert second.number == 101


def test_workload_identity_grants_and_hashed_credential_are_durable_and_revocable(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    host_scope = HostScope(
        namespace=HostNamespace("fm.synthetic"),
        tenant_id="external-tenant-a",
        unit_id="external-unit-a",
    )
    with database.unit_of_work() as uow:
        uow.bindings.add(
            FiscalAccountBinding(
                binding_id="binding-v2-15-a",
                host_scope=host_scope,
                fiscal_account_id=FiscalAccountId("tenant-a"),
                fiscal_unit_id=FiscalUnitId("unit-a"),
            )
        )
        uow.commit()

    caller = CallerIdentity(
        caller_id="synthetic-backend",
        host_namespace=HostNamespace("fm.synthetic"),
        capabilities=frozenset({FiscalCapability.QUERY}),
        scope_grants=(
            HostScopeGrant(
                tenant_id="external-tenant-a",
                unit_id="external-unit-a",
            ),
        ),
    )
    credential = WorkloadCredentialRecord.from_secret(
        credential_id="credential-v2-15-a",
        caller=caller,
        secret=SECRET,
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    runtime_service = CommercialRuntimeConfigurationService(database)
    runtime_service.set_workload_credential(actor=_global_admin(), record=credential)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    authenticated = DurableWorkloadAuthenticator(restarted).authenticate(
        credential_id=credential.credential_id,
        presented_secret=SECRET,
        now=NOW,
    )
    authorized = S2SAuthorizer(
        bindings=DurableFiscalBindingResolver(restarted),
        audit_sink=InMemorySecurityAuditSink(),
    ).authorize(
        caller=authenticated,
        host_scope=host_scope,
        environment=FiscalEnvironment.HOMOLOGATION,
        capability=FiscalCapability.QUERY,
        correlation_id="corr-v2-15-s2s",
        now=NOW,
    )
    assert authorized.scope.tenant_id == "tenant-a"
    assert authorized.scope.unit_id == "unit-a"

    CommercialRuntimeConfigurationService(restarted).set_workload_credential(
        actor=_global_admin(),
        record=replace(credential, revoked=True),
    )
    with pytest.raises(WorkloadAuthenticationError, match="revoked"):
        DurableWorkloadAuthenticator(restarted).authenticate(
            credential_id=credential.credential_id,
            presented_secret=SECRET,
            now=NOW,
        )

    with sqlite3.connect(restarted.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(fm_commercial_workload_credentials)"
            ).fetchall()
        }
        persisted_hash = connection.execute(
            "SELECT secret_sha256 FROM fm_commercial_workload_credentials "
            "WHERE credential_id = ?",
            (credential.credential_id,),
        ).fetchone()[0]
    assert "secret" not in columns
    assert "secret_sha256" in columns
    assert persisted_hash == credential.secret_sha256
    assert SECRET not in str(persisted_hash)


def test_runtime_policy_drives_transport_timeout_retry_and_circuit_configuration(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard(database)
    CommercialConfigurationService(database).set_runtime_policy(
        actor=_global_admin(),
        policy=_policy(),
    )
    resolver = DurableProviderRuntimePolicyResolver(database)
    transport = SyntheticProviderTransport()
    bound = PolicyBoundFiscalProviderTransport(
        transport=transport,
        policy_resolver=resolver,
    )
    request = _query_request()
    bound.exchange(
        provider_id="provider-a",
        request=request,
        credentials=EphemeralProviderCredentialsMaterial(
            reference_id="ref:synthetic-provider-a",
            credential_bytes=b"synthetic-runtime-credential",
        ),
        csc=None,
        timeout=ProviderTimeoutPolicy(connect_seconds=1, read_seconds=1),
    )
    assert transport.observations[0].connect_timeout_seconds == 7
    assert transport.observations[0].read_timeout_seconds == 11

    sleeper = _Sleeper()
    executor = _FlakyExecutor()
    response = DurablePolicyResilientProviderGateway(
        executor=executor,
        policy_resolver=resolver,
        sleeper=sleeper,
        jitter=_ZeroJitter(),
    ).execute(request, provider_id="provider-a")
    assert response.status is ProviderResponseStatus.FOUND
    assert executor.calls == 2
    assert sleeper.delays == [0.5]


class _Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


class _ZeroJitter:
    def value(self) -> float:
        return 0.0


class _FlakyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        if self.calls == 1:
            raise ProviderUnavailableError("synthetic transient outage")
        assert provider_id is not None
        return ProviderResponse(
            provider_id=provider_id,
            operation=request.operation,
            status=ProviderResponseStatus.FOUND,
            correlation_id=request.correlation_id,
        )


def test_homologation_evidence_is_durable_exact_and_does_not_imply_official_status(
    tmp_path,
) -> None:
    database = _database(tmp_path)
    _onboard(database)
    record = HomologationEvidenceRecord(
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="provider-a",
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=BrazilianJurisdiction("SP"),
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
    )
    CommercialRuntimeConfigurationService(database).set_homologation_evidence(
        actor=_global_admin(),
        record=record,
    )

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    resolver = DurableHomologationEvidenceResolver(restarted)
    persisted = resolver.resolve_record(
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="provider-a",
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=BrazilianJurisdiction("SP"),
        operation="authorize",
    )
    rule = resolver.technical_rule(
        tenant_id="tenant-a",
        unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="provider-a",
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=BrazilianJurisdiction("SP"),
        operation="authorize",
    )
    assert persisted.external_official is False
    assert persisted.external_evidence_id is None
    assert rule.technical_state is TechnicalGateState.TECHNICALLY_CERTIFIED

    with pytest.raises(ControlPlaneNotFoundError):
        resolver.resolve_record(
            tenant_id="tenant-a",
            unit_id="unit-a",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id="provider-b",
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=BrazilianJurisdiction("SP"),
            operation="authorize",
        )
