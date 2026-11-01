"""Host-neutral administrative contracts for the FM Fiscal Control Plane."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError

_TOKEN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_REFERENCE = re.compile(r"^ref:[a-z0-9][a-z0-9._:/-]{2,252}[a-z0-9]$")


def _required_text(value: str, field_name: str, *, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _token(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name, max_length=128).lower()
    if not _TOKEN.fullmatch(normalized):
        raise FiscalValidationError(
            f"{field_name} must use lowercase letters, digits, '.', '_' or '-'"
        )
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


class ControlPlanePermission(StrEnum):
    """Administrative permissions; authorization fails closed by default."""

    ORGANIZATION_WRITE = "organization.write"
    UNIT_WRITE = "unit.write"
    PROFILE_WRITE = "profile.write"
    CAPABILITY_READ = "capability.read"
    CAPABILITY_WRITE = "capability.write"
    SECRET_REFERENCE_WRITE = "secret_reference.write"
    COMMERCIAL_CONFIG_WRITE = "commercial_config.write"
    AUDIT_READ = "audit.read"
    OPERATIONS_READ = "operations.read"


class SecretReferenceKind(StrEnum):
    """Kinds of opaque references governed by V2-11 without secret material."""

    CERTIFICATE = "certificate"
    CSC = "csc"
    CREDENTIALS = "credentials"


class ControlPlaneAuditAction(StrEnum):
    FISCAL_INTENT_PREPARED = "fiscal_intent.prepared"
    FISCAL_INTENT_RECOVERED = "fiscal_intent.recovered"
    FISCAL_INTENT_RESUMED = "fiscal_intent.resumed"
    FISCAL_INTENT_BLOCKED = "fiscal_intent.blocked"
    CUSTOMER_CONFIGURATION_CHANGED = "customer_configuration.changed"
    WEBHOOK_EGRESS_DECIDED = "webhook_egress.decided"
    HUMAN_ACCOUNT_CREATED = "human_account.created"
    HUMAN_ACCOUNT_UPDATED = "human_account.updated"
    ORGANIZATION_ONBOARDED = "organization.onboarded"
    UNIT_ONBOARDED = "unit.onboarded"
    SECRET_REFERENCE_BOUND = "secret_reference.bound"
    FISCAL_PROFILE_ADDED = "fiscal_profile.added"
    PILOT_ACTIVATED = "pilot.activated"
    PILOT_DEACTIVATED = "pilot.deactivated"
    PILOT_SCOPE_CHANGED = "pilot.scope_changed"
    PILOT_DECISION_RECORDED = "pilot.decision_recorded"
    COGNITIVE_ADVICE_RECORDED = "cognitive_advice.recorded"


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    """Authenticated administrative actor with explicit permissions and scope."""

    actor_id: str
    permissions: frozenset[ControlPlanePermission]
    tenant_ids: frozenset[str] = frozenset()
    global_scope: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _token(self.actor_id, "actor_id"))
        if not isinstance(self.permissions, frozenset):
            raise FiscalValidationError("permissions must be a frozenset")
        if not all(isinstance(item, ControlPlanePermission) for item in self.permissions):
            raise FiscalValidationError("permissions contain invalid values")
        if not isinstance(self.tenant_ids, frozenset):
            raise FiscalValidationError("tenant_ids must be a frozenset")
        normalized_tenants = frozenset(_token(item, "tenant_id") for item in self.tenant_ids)
        object.__setattr__(self, "tenant_ids", normalized_tenants)
        if self.global_scope and normalized_tenants:
            raise FiscalValidationError("global_scope principal must not declare tenant_ids")

    def has_permission(self, permission: ControlPlanePermission) -> bool:
        return permission in self.permissions

    def can_access_tenant(self, tenant_id: str) -> bool:
        normalized = _token(tenant_id, "tenant_id")
        return self.global_scope or normalized in self.tenant_ids


@dataclass(frozen=True, slots=True)
class FiscalOrganization:
    """Control Plane organization identity; tax profile data is modeled separately."""

    tenant_id: str
    legal_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "legal_name",
            _required_text(self.legal_name, "legal_name", max_length=256),
        )


@dataclass(frozen=True, slots=True)
class FiscalUnitRegistration:
    """One administrative unit and the environments explicitly enabled for it."""

    tenant_id: str
    unit_id: str
    display_name: str
    enabled_environments: frozenset[FiscalEnvironment] = field(
        default_factory=lambda: frozenset({FiscalEnvironment.HOMOLOGATION})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "unit_id", _token(self.unit_id, "unit_id"))
        object.__setattr__(
            self,
            "display_name",
            _required_text(self.display_name, "display_name", max_length=256),
        )
        if not isinstance(self.enabled_environments, frozenset):
            raise FiscalValidationError("enabled_environments must be a frozenset")
        if not self.enabled_environments:
            raise FiscalValidationError("enabled_environments must not be empty")
        if not all(
            isinstance(environment, FiscalEnvironment) for environment in self.enabled_environments
        ):
            raise FiscalValidationError("enabled_environments contain invalid values")


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Opaque pointer only; secret/certificate/CSC material is never stored here.

    Provider credentials and NFC-e CSC are provider-scoped so one unit can use
    multiple providers in the same environment without overwriting references.
    Certificate references remain unit/environment scoped because document signing
    is a Core capability rather than a provider credential.
    """

    reference_id: str
    kind: SecretReferenceKind
    tenant_id: str
    unit_id: str
    environment: FiscalEnvironment
    provider_id: str | None = None

    def __post_init__(self) -> None:
        normalized = _required_text(self.reference_id, "reference_id", max_length=256).lower()
        if not _REFERENCE.fullmatch(normalized):
            raise FiscalValidationError(
                "reference_id must be an opaque ref:... identifier without secret material"
            )
        object.__setattr__(self, "reference_id", normalized)
        if not isinstance(self.kind, SecretReferenceKind):
            raise FiscalValidationError("kind must be SecretReferenceKind")
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "unit_id", _token(self.unit_id, "unit_id"))
        if not isinstance(self.environment, FiscalEnvironment):
            raise FiscalValidationError("environment must be FiscalEnvironment")

        provider_id = self.provider_id
        provider_scoped = self.kind in {
            SecretReferenceKind.CSC,
            SecretReferenceKind.CREDENTIALS,
        }
        if provider_scoped and provider_id is None:
            raise FiscalValidationError(
                "provider_id is required for CSC and provider credentials references"
            )
        if not provider_scoped and provider_id is not None:
            raise FiscalValidationError(
                "provider_id is not allowed for unit-scoped certificate references"
            )
        if provider_id is not None:
            object.__setattr__(self, "provider_id", _token(provider_id, "provider_id"))

    @property
    def provider_scope(self) -> str:
        return self.provider_id or ""


@dataclass(frozen=True, slots=True)
class ControlPlaneAuditEvent:
    """Append-only administrative audit fact with no free-form secret payload."""

    event_id: str
    occurred_at: datetime
    actor_id: str
    action: ControlPlaneAuditAction
    target_type: str
    target_id: str
    correlation_id: str
    tenant_id: str
    unit_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _token(self.event_id, "event_id"))
        _aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "actor_id", _token(self.actor_id, "actor_id"))
        if not isinstance(self.action, ControlPlaneAuditAction):
            raise FiscalValidationError("action must be ControlPlaneAuditAction")
        object.__setattr__(self, "target_type", _token(self.target_type, "target_type"))
        object.__setattr__(
            self,
            "target_id",
            _required_text(self.target_id, "target_id", max_length=256),
        )
        object.__setattr__(
            self,
            "correlation_id",
            _required_text(self.correlation_id, "correlation_id", max_length=256),
        )
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        if self.unit_id is not None:
            object.__setattr__(self, "unit_id", _token(self.unit_id, "unit_id"))
