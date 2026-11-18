"""Persistence ports for the independently operable FM Fiscal application layer.

The domain stays persistence-agnostic. Existing atomic store contracts for
idempotency, numbering, outbox, archive and inbox are reused here; repository
ports and the unit-of-work boundary keep application coordination transactional.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, Self

from kordena_fiscal.archive import FiscalArchiveStore
from kordena_fiscal.contingency import FiscalOutboxStore
from kordena_fiscal.control_plane.models import (
    ControlPlaneAuditEvent,
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalEnvironment,
    FiscalProductProfile,
    FiscalProfile,
    HostScope,
    SourceReference,
)
from kordena_fiscal.events import FiscalDeliveryAuditStore, FiscalInboxStore
from kordena_fiscal.lifecycle import FiscalDocumentState, FiscalStateSnapshot, IdempotencyStore
from kordena_fiscal.numbering import DpsNumberingStore, FiscalSequenceStore
from kordena_fiscal.reconciliation import FiscalReconciliationResult

if TYPE_CHECKING:
    from kordena_fiscal.control_plane.commercial import (
        ConfiguredFiscalOperation,
        ProviderBinding,
        ProviderRuntimePolicyConfig,
        UnitModuleBinding,
        WebhookDestinationConfig,
    )
    from kordena_fiscal.control_plane.commercial_models import (
        HomologationEvidenceRecord,
        NumberingConfiguration,
    )
    from kordena_fiscal.security import WorkloadCredentialRecord
    from kordena_fiscal.security.secret_binding import SecretBinding


class FiscalPersistenceError(FiscalDomainError):
    """Base error for durable persistence contract violations."""


class PersistenceConflictError(FiscalPersistenceError):
    """Raised on duplicate identity or optimistic-concurrency conflict."""


class PersistenceStateError(FiscalPersistenceError):
    """Raised when durable state is missing, corrupt or violates a repository contract."""


class FiscalBindingRepository(Protocol):
    """Durable exact resolver for host scope -> fiscal account binding."""

    def list_for_fiscal_unit(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[FiscalAccountBinding, ...]: ...

    def add(self, binding: FiscalAccountBinding) -> FiscalAccountBinding: ...

    def resolve(self, host_scope: HostScope) -> FiscalAccountBinding: ...

    def get_by_id(self, binding_id: str) -> FiscalAccountBinding | None: ...


class FiscalLifecycleRepository(Protocol):
    """Optimistically-versioned persistence for complete lifecycle snapshots."""

    def add(
        self, snapshot: FiscalStateSnapshot, *, scope: ExecutionScope | None = None
    ) -> FiscalStateSnapshot: ...

    def assert_scope(self, document_id: str, scope: ExecutionScope) -> None: ...

    def list_for_scope(
        self,
        scope: ExecutionScope,
        *,
        limit: int = 100,
        offset: int = 0,
        states: frozenset[FiscalDocumentState] | None = None,
    ) -> tuple[FiscalStateSnapshot, ...]: ...

    def get(self, document_id: str) -> FiscalStateSnapshot | None: ...

    def save(
        self,
        snapshot: FiscalStateSnapshot,
        *,
        expected_version: int,
    ) -> FiscalStateSnapshot: ...


class FiscalReconciliationRepository(Protocol):
    """Durable latest reconciliation state for one operation identity."""

    def save(self, result: FiscalReconciliationResult) -> FiscalReconciliationResult: ...

    def list_for_scope(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[FiscalReconciliationResult, ...]: ...

    def get(
        self,
        scope: ExecutionScope,
        source: SourceReference,
    ) -> FiscalReconciliationResult | None: ...


class FiscalOutboxOrderingStore(Protocol):
    """Optional explicit ordering metadata; no key means no ordering dependency."""

    def register(self, entry_id: str, ordering_key: str) -> str: ...

    def get(self, entry_id: str) -> str | None: ...


class ControlPlaneStore(Protocol):
    """Durable administrative state used by the independent FM Fiscal Control Plane."""

    def add_organization(self, organization: FiscalOrganization) -> FiscalOrganization: ...

    def get_organization(self, tenant_id: str) -> FiscalOrganization | None: ...

    def add_unit(self, registration: FiscalUnitRegistration) -> FiscalUnitRegistration: ...

    def get_unit(self, tenant_id: str, unit_id: str) -> FiscalUnitRegistration | None: ...

    def list_secret_references(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[SecretReference, ...]: ...

    def add_secret_reference(self, reference: SecretReference) -> SecretReference: ...

    def put_secret_reference(self, reference: SecretReference) -> SecretReference: ...

    def get_secret_reference(
        self,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        kind: SecretReferenceKind,
        *,
        provider_id: str | None = None,
    ) -> SecretReference | None: ...

    def add_profile(self, profile: FiscalProfile) -> FiscalProfile: ...

    def get_profile(self, profile_id: str, version: int) -> FiscalProfile | None: ...

    def resolve_profile(
        self,
        *,
        host_namespace: str,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        instant: datetime,
    ) -> FiscalProfile | None: ...

    def append_audit(self, event: ControlPlaneAuditEvent) -> ControlPlaneAuditEvent: ...

    def list_audit(self, tenant_id: str | None = None) -> tuple[ControlPlaneAuditEvent, ...]: ...


class CommercialConfigurationStore(Protocol):
    """Durable zero-code customer configuration repository."""

    def configuration_version(
        self, scope: ExecutionScope, target_type: str, target_key: str
    ) -> int: ...

    def advance_configuration_version(
        self,
        scope: ExecutionScope,
        target_type: str,
        target_key: str,
        expected: int,
    ) -> int: ...

    def reserve_configuration_command(
        self,
        scope: ExecutionScope,
        command_key: str,
        fingerprint: str,
    ) -> Mapping[str, object] | None: ...

    def complete_configuration_command(
        self,
        scope: ExecutionScope,
        command_key: str,
        result: Mapping[str, object],
    ) -> None: ...

    def configuration_receipt(
        self, scope: ExecutionScope, command_key: str
    ) -> Mapping[str, object] | None: ...

    def list_configuration_receipts(
        self, scope: ExecutionScope, prefix: str
    ) -> tuple[Mapping[str, object], ...]: ...

    def replace_configuration_receipt(
        self,
        scope: ExecutionScope,
        command_key: str,
        expected: Mapping[str, object],
        updated: Mapping[str, object],
    ) -> bool: ...

    def webhook_approval(
        self, scope: ExecutionScope, destination_id: str
    ) -> Mapping[str, object] | None: ...

    def record_webhook_approval(
        self,
        scope: ExecutionScope,
        destination_id: str,
        *,
        status: str,
        version: int | None,
        expires_at: str | None,
        url_sha256: str | None,
        requested_by: str | None = None,
        approved_by: str | None = None,
    ) -> None: ...

    def list_portal_configuration(
        self, surface_id: str, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[Mapping[str, object], ...]: ...

    def put_provider_binding(self, binding: ProviderBinding) -> ProviderBinding: ...

    def resolve_provider_binding(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        document_kind: FiscalDocumentKind,
        jurisdiction: BrazilianJurisdiction,
        operation: ConfiguredFiscalOperation,
    ) -> ProviderBinding | None: ...

    def add_product_profile(self, profile: FiscalProductProfile) -> FiscalProductProfile: ...

    def resolve_product_profile(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        product_id: str,
        instant: datetime,
    ) -> FiscalProductProfile | None: ...

    def put_module_binding(self, binding: UnitModuleBinding) -> UnitModuleBinding: ...

    def list_module_bindings(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
    ) -> tuple[UnitModuleBinding, ...]: ...

    def put_webhook_destination(
        self,
        destination: WebhookDestinationConfig,
    ) -> WebhookDestinationConfig: ...

    def list_webhook_destinations(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
    ) -> tuple[WebhookDestinationConfig, ...]: ...

    def put_runtime_policy(
        self,
        policy: ProviderRuntimePolicyConfig,
    ) -> ProviderRuntimePolicyConfig: ...

    def get_runtime_policy(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        provider_id: str,
    ) -> ProviderRuntimePolicyConfig | None: ...

    def put_numbering_configuration(
        self,
        config: NumberingConfiguration,
    ) -> NumberingConfiguration: ...

    def get_numbering_configuration(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        model: object,
    ) -> NumberingConfiguration | None: ...

    def put_workload_credential(
        self,
        record: WorkloadCredentialRecord,
    ) -> WorkloadCredentialRecord: ...

    def get_workload_credential(
        self,
        credential_id: str,
    ) -> WorkloadCredentialRecord | None: ...

    def put_homologation_evidence(
        self,
        record: HomologationEvidenceRecord,
    ) -> HomologationEvidenceRecord: ...

    def get_homologation_evidence(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        provider_id: str,
        document_kind: FiscalDocumentKind,
        jurisdiction: BrazilianJurisdiction,
        operation: str,
    ) -> HomologationEvidenceRecord | None: ...


class SecretBindingStore(Protocol):
    def get(self, reference_id: str) -> SecretBinding | None: ...

    def put(self, binding: SecretBinding, *, expected_revision: int) -> None: ...

    def list_active_certificates(
        self, *, tenant_id: str, unit_id: str, fiscal_environment: str
    ) -> tuple[SecretBinding, ...]: ...


class FiscalUnitOfWork(Protocol):
    """One atomic local transaction spanning all durable fiscal repositories."""

    @property
    def idempotency(self) -> IdempotencyStore: ...

    @property
    def sequences(self) -> FiscalSequenceStore: ...

    @property
    def dps_sequences(self) -> DpsNumberingStore: ...

    @property
    def inbox(self) -> FiscalInboxStore: ...

    @property
    def outbox(self) -> FiscalOutboxStore: ...

    @property
    def outbox_ordering(self) -> FiscalOutboxOrderingStore: ...

    @property
    def delivery_audit(self) -> FiscalDeliveryAuditStore: ...

    @property
    def archive(self) -> FiscalArchiveStore: ...

    @property
    def bindings(self) -> FiscalBindingRepository: ...

    @property
    def lifecycle(self) -> FiscalLifecycleRepository: ...

    @property
    def reconciliations(self) -> FiscalReconciliationRepository: ...

    @property
    def control_plane(self) -> ControlPlaneStore: ...

    @property
    def commercial(self) -> CommercialConfigurationStore: ...

    @property
    def secret_bindings(self) -> SecretBindingStore: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class FiscalUnitOfWorkFactory(Protocol):
    def __call__(self) -> FiscalUnitOfWork: ...
