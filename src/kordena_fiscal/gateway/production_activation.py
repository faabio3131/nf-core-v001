"""Fail-closed fiscal production activation and gateway injection boundary.

Commercial billing is intentionally absent from this module. A production grant can only
be built from exact official homologation evidence plus an explicit human approval, and
must then be injected into the governed provider gateway. No environment variable, Cakto
event or technical readiness level can self-activate fiscal production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from kordena_fiscal.control_plane.commercial_models import HomologationEvidenceRecord
from kordena_fiscal.control_plane.models import AdminPrincipal, ControlPlanePermission
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalEnvironment,
    FiscalValidationError,
)

from .provider import ProviderOperation, ProviderRequest, ProviderResponse


class FiscalProductionActivationError(FiscalDomainError):
    """Base error for governed production activation failures."""


class FiscalProductionActivationRequiredError(FiscalProductionActivationError):
    """No exact active production grant was explicitly injected."""


class FiscalProductionApprovalError(FiscalProductionActivationError):
    """Human approval or official homologation evidence is insufficient."""


class ProductionActivationState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


def _required(value: str, field_name: str, *, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _token(value: str, field_name: str) -> str:
    normalized = _required(value, field_name, max_length=128).lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(character not in allowed for character in normalized):
        raise FiscalValidationError(f"{field_name} has invalid token format")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ProductionActivationKey:
    """Exact production cell; no tenant/provider/jurisdiction fallback is permitted."""

    tenant_id: str
    unit_id: str
    provider_id: str
    document_kind: FiscalDocumentKind
    jurisdiction: BrazilianJurisdiction
    operation: ProviderOperation

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "unit_id", _token(self.unit_id, "unit_id"))
        object.__setattr__(self, "provider_id", _token(self.provider_id, "provider_id"))
        if not isinstance(self.document_kind, FiscalDocumentKind):
            raise FiscalValidationError("document_kind must be FiscalDocumentKind")
        if not isinstance(self.jurisdiction, BrazilianJurisdiction):
            raise FiscalValidationError("jurisdiction must be BrazilianJurisdiction")
        if not isinstance(self.operation, ProviderOperation):
            raise FiscalValidationError("operation must be ProviderOperation")
        if (
            self.document_kind is FiscalDocumentKind.NFSE
            and self.jurisdiction.municipality_ibge_code is None
        ):
            raise FiscalValidationError(
                "NFSe production activation requires municipality_ibge_code"
            )

    @classmethod
    def from_request(
        cls,
        request: ProviderRequest,
        *,
        provider_id: str,
    ) -> ProductionActivationKey:
        return cls(
            tenant_id=request.scope.tenant_id,
            unit_id=request.scope.unit_id,
            provider_id=provider_id,
            document_kind=request.document_kind,
            jurisdiction=request.jurisdiction,
            operation=request.operation,
        )


@dataclass(frozen=True, slots=True)
class HumanProductionApproval:
    """Immutable explicit human decision for one exact production cell."""

    key: ProductionActivationKey
    approved_by: str
    approval_reference: str
    approved_at: datetime
    correlation_id: str
    decision: str = "PRODUCTION_APPROVED"

    def __post_init__(self) -> None:
        if not isinstance(self.key, ProductionActivationKey):
            raise FiscalValidationError("key must be ProductionActivationKey")
        object.__setattr__(self, "approved_by", _token(self.approved_by, "approved_by"))
        object.__setattr__(
            self,
            "approval_reference",
            _required(self.approval_reference, "approval_reference"),
        )
        _aware(self.approved_at, "approved_at")
        object.__setattr__(
            self,
            "correlation_id",
            _required(self.correlation_id, "correlation_id"),
        )
        if self.decision != "PRODUCTION_APPROVED":
            raise FiscalProductionApprovalError(
                "fiscal production requires explicit PRODUCTION_APPROVED human decision"
            )


@dataclass(frozen=True, slots=True)
class OfficialHomologationProof:
    """Sanitized official evidence projected onto the exact future production cell."""

    key: ProductionActivationKey
    external_evidence_id: str
    recorded_at: datetime

    @classmethod
    def from_record(
        cls,
        record: HomologationEvidenceRecord,
    ) -> OfficialHomologationProof:
        if not isinstance(record, HomologationEvidenceRecord):
            raise FiscalValidationError("record must be HomologationEvidenceRecord")
        if record.environment is not FiscalEnvironment.HOMOLOGATION:
            raise FiscalProductionApprovalError(
                "production activation requires official HOMOLOGATION evidence"
            )
        if not record.external_official or record.external_evidence_id is None:
            raise FiscalProductionApprovalError(
                "production activation requires external official homologation evidence"
            )
        if record.recorded_at is None:
            raise FiscalProductionApprovalError(
                "official homologation evidence requires a recorded timestamp"
            )
        required = {
            "provider_adapter_available": record.provider_adapter_available,
            "credentials_reference_configured": record.credentials_reference_configured,
            "transport_configured": record.transport_configured,
            "resilience_certified": record.resilience_certified,
            "contract_tests_certified": record.contract_tests_certified,
            "jurisdiction_mapping": record.jurisdiction_mapping,
            "operation_supported": record.operation_supported,
        }
        if record.requires_signer:
            required["signer_capability"] = record.signer_capability
        if record.requires_csc:
            required["csc_reference_configured"] = record.csc_reference_configured
        missing = tuple(name for name, present in required.items() if not present)
        if missing:
            raise FiscalProductionApprovalError(
                "official homologation evidence is incomplete: " + ", ".join(missing)
            )
        try:
            operation = ProviderOperation(record.operation)
        except ValueError as exc:
            raise FiscalProductionApprovalError(
                "official homologation evidence operation is unsupported"
            ) from exc
        return cls(
            key=ProductionActivationKey(
                tenant_id=record.tenant_id,
                unit_id=record.unit_id,
                provider_id=record.provider_id,
                document_kind=record.document_kind,
                jurisdiction=record.jurisdiction,
                operation=operation,
            ),
            external_evidence_id=record.external_evidence_id,
            recorded_at=record.recorded_at,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.key, ProductionActivationKey):
            raise FiscalValidationError("key must be ProductionActivationKey")
        object.__setattr__(
            self,
            "external_evidence_id",
            _required(self.external_evidence_id, "external_evidence_id"),
        )
        _aware(self.recorded_at, "recorded_at")


@dataclass(frozen=True, slots=True)
class ProductionActivationRecord:
    """Immutable auditable activation/revocation record with no secret material."""

    key: ProductionActivationKey
    state: ProductionActivationState
    approval_reference: str
    external_evidence_id: str
    changed_by: str
    changed_at: datetime
    correlation_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, ProductionActivationKey):
            raise FiscalValidationError("key must be ProductionActivationKey")
        if not isinstance(self.state, ProductionActivationState):
            raise FiscalValidationError("state must be ProductionActivationState")
        object.__setattr__(
            self,
            "approval_reference",
            _required(self.approval_reference, "approval_reference"),
        )
        object.__setattr__(
            self,
            "external_evidence_id",
            _required(self.external_evidence_id, "external_evidence_id"),
        )
        object.__setattr__(self, "changed_by", _token(self.changed_by, "changed_by"))
        _aware(self.changed_at, "changed_at")
        object.__setattr__(
            self,
            "correlation_id",
            _required(self.correlation_id, "correlation_id"),
        )


class ProductionActivationClock(Protocol):
    def now(self) -> datetime: ...


class SystemProductionActivationClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FiscalProductionActivationService:
    """Create/revoke production records only from human + official external evidence."""

    def __init__(self, *, clock: ProductionActivationClock | None = None) -> None:
        self._clock = clock or SystemProductionActivationClock()

    def activate(
        self,
        *,
        actor: AdminPrincipal,
        approval: HumanProductionApproval,
        proof: OfficialHomologationProof,
        correlation_id: str,
    ) -> ProductionActivationRecord:
        self._require_actor(actor, approval.key.tenant_id)
        if approval.key != proof.key:
            raise FiscalProductionApprovalError(
                "human approval and official evidence must target the exact same cell"
            )
        return ProductionActivationRecord(
            key=approval.key,
            state=ProductionActivationState.ACTIVE,
            approval_reference=approval.approval_reference,
            external_evidence_id=proof.external_evidence_id,
            changed_by=actor.actor_id,
            changed_at=self._clock.now(),
            correlation_id=correlation_id,
        )

    def revoke(
        self,
        *,
        actor: AdminPrincipal,
        current: ProductionActivationRecord,
        correlation_id: str,
    ) -> ProductionActivationRecord:
        self._require_actor(actor, current.key.tenant_id)
        return ProductionActivationRecord(
            key=current.key,
            state=ProductionActivationState.REVOKED,
            approval_reference=current.approval_reference,
            external_evidence_id=current.external_evidence_id,
            changed_by=actor.actor_id,
            changed_at=self._clock.now(),
            correlation_id=correlation_id,
        )

    @staticmethod
    def _require_actor(actor: AdminPrincipal, tenant_id: str) -> None:
        if not isinstance(actor, AdminPrincipal):
            raise FiscalValidationError("actor must be AdminPrincipal")
        if not actor.has_permission(ControlPlanePermission.CAPABILITY_WRITE):
            raise FiscalProductionApprovalError(
                "actor lacks capability.write for fiscal production activation"
            )
        if not actor.can_access_tenant(tenant_id):
            raise FiscalProductionApprovalError(
                "actor cannot activate fiscal production for target tenant"
            )


class ProductionExecutionAuthority:
    """Immutable injected authority; latest exact record wins and revocation is fail-closed."""

    def __init__(self, records: tuple[ProductionActivationRecord, ...]) -> None:
        if not isinstance(records, tuple) or not all(
            isinstance(item, ProductionActivationRecord) for item in records
        ):
            raise FiscalValidationError(
                "records must be a tuple of ProductionActivationRecord values"
            )
        latest: dict[ProductionActivationKey, ProductionActivationRecord] = {}
        for record in records:
            current = latest.get(record.key)
            if current is not None and record.changed_at == current.changed_at:
                raise FiscalValidationError(
                    "production activation records for one key must have unique timestamps"
                )
            if current is None or record.changed_at > current.changed_at:
                latest[record.key] = record
        self._latest = latest

    @property
    def active_count(self) -> int:
        return sum(
            1
            for record in self._latest.values()
            if record.state is ProductionActivationState.ACTIVE
        )

    @property
    def production_activated(self) -> bool:
        return self.active_count > 0

    def require_key(self, key: ProductionActivationKey) -> ProductionActivationRecord:
        """Exact-cell lookup for transports that do not build a ProviderRequest."""
        record = self._latest.get(key)
        if record is None or record.state is not ProductionActivationState.ACTIVE:
            raise FiscalProductionActivationRequiredError(
                "no exact active fiscal production grant was explicitly injected"
            )
        return record

    def require(
        self,
        request: ProviderRequest,
        *,
        provider_id: str,
    ) -> ProductionActivationRecord:
        if request.scope.environment is not FiscalEnvironment.PRODUCTION:
            raise FiscalProductionActivationRequiredError(
                "production authority can only authorize PRODUCTION requests"
            )
        key = ProductionActivationKey.from_request(request, provider_id=provider_id)
        record = self._latest.get(key)
        if record is None or record.state is not ProductionActivationState.ACTIVE:
            raise FiscalProductionActivationRequiredError(
                "no exact active fiscal production grant was explicitly injected"
            )
        return record


class ProviderGatewayExecutor(Protocol):
    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse: ...


class GovernedProviderGatewayService:
    """Production-safe facade requiring explicit injected authority and provider identity."""

    def __init__(
        self,
        delegate: ProviderGatewayExecutor,
        *,
        production_authority: ProductionExecutionAuthority | None = None,
    ) -> None:
        self._delegate = delegate
        self._production_authority = production_authority

    @property
    def fiscal_production_activated(self) -> bool:
        authority = self._production_authority
        return authority is not None and authority.production_activated

    def execute(
        self,
        request: ProviderRequest,
        *,
        provider_id: str | None = None,
    ) -> ProviderResponse:
        if not isinstance(request, ProviderRequest):
            raise FiscalValidationError("request must be ProviderRequest")
        selected_provider = provider_id
        if request.scope.environment is FiscalEnvironment.PRODUCTION:
            if selected_provider is None or not selected_provider.strip():
                raise FiscalProductionActivationRequiredError(
                    "production execution requires explicit provider_id"
                )
            authority = self._production_authority
            if authority is None:
                raise FiscalProductionActivationRequiredError(
                    "production execution requires explicitly injected authority"
                )
            authority.require(request, provider_id=selected_provider)
        return self._delegate.execute(request, provider_id=selected_provider)
