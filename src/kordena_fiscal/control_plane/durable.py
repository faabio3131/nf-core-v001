"""Durable V2-11 Control Plane application service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from kordena_fiscal.domain import FiscalProfile, FiscalValidationError
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWorkFactory,
    PersistenceConflictError,
)

from .models import (
    AdminPrincipal,
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
    ControlPlanePermission,
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
)
from .service import (
    ControlPlaneAuthorizationError,
    ControlPlaneConflictError,
    ControlPlaneNotFoundError,
)


class DurableControlPlaneClock(Protocol):
    def now(self) -> datetime:
        ...


class SystemDurableControlPlaneClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class DurableControlPlaneService:
    """Atomic administrative writes backed by the common fiscal unit of work."""

    def __init__(
        self,
        unit_of_work_factory: FiscalUnitOfWorkFactory,
        *,
        clock: DurableControlPlaneClock | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock or SystemDurableControlPlaneClock()

    def onboard_organization(
        self,
        *,
        actor: AdminPrincipal,
        tenant_id: str,
        legal_name: str,
        correlation_id: str,
    ) -> FiscalOrganization:
        self._require_permission(actor, ControlPlanePermission.ORGANIZATION_WRITE)
        if not actor.global_scope:
            raise ControlPlaneAuthorizationError(
                "organization onboarding requires a global-scope administrative actor"
            )
        organization = FiscalOrganization(tenant_id=tenant_id, legal_name=legal_name)
        with self._unit_of_work_factory() as uow:
            if uow.control_plane.get_organization(organization.tenant_id) is not None:
                raise ControlPlaneConflictError(
                    f"organization already exists: {organization.tenant_id}"
                )
            try:
                uow.control_plane.add_organization(organization)
                uow.control_plane.append_audit(
                    self._audit_event(
                        actor=actor,
                        action=ControlPlaneAuditAction.ORGANIZATION_ONBOARDED,
                        target_type="organization",
                        target_id=organization.tenant_id,
                        correlation_id=correlation_id,
                        tenant_id=organization.tenant_id,
                        unit_id=None,
                    )
                )
            except PersistenceConflictError as exc:
                raise ControlPlaneConflictError(str(exc)) from exc
            uow.commit()
        return organization

    def onboard_unit(
        self,
        *,
        actor: AdminPrincipal,
        registration: FiscalUnitRegistration,
        correlation_id: str,
    ) -> FiscalUnitRegistration:
        if not isinstance(registration, FiscalUnitRegistration):
            raise FiscalValidationError("registration must be FiscalUnitRegistration")
        self._require_tenant_permission(
            actor,
            ControlPlanePermission.UNIT_WRITE,
            registration.tenant_id,
        )
        with self._unit_of_work_factory() as uow:
            if uow.control_plane.get_organization(registration.tenant_id) is None:
                raise ControlPlaneNotFoundError(
                    f"organization is not onboarded: {registration.tenant_id}"
                )
            if (
                uow.control_plane.get_unit(registration.tenant_id, registration.unit_id)
                is not None
            ):
                raise ControlPlaneConflictError(
                    "unit already exists: "
                    f"{registration.tenant_id}/{registration.unit_id}"
                )
            try:
                uow.control_plane.add_unit(registration)
                uow.control_plane.append_audit(
                    self._audit_event(
                        actor=actor,
                        action=ControlPlaneAuditAction.UNIT_ONBOARDED,
                        target_type="unit",
                        target_id=registration.unit_id,
                        correlation_id=correlation_id,
                        tenant_id=registration.tenant_id,
                        unit_id=registration.unit_id,
                    )
                )
            except PersistenceConflictError as exc:
                raise ControlPlaneConflictError(str(exc)) from exc
            uow.commit()
        return registration

    def bind_secret_reference(
        self,
        *,
        actor: AdminPrincipal,
        reference: SecretReference,
        correlation_id: str,
    ) -> SecretReference:
        if not isinstance(reference, SecretReference):
            raise FiscalValidationError("reference must be SecretReference")
        self._require_tenant_permission(
            actor,
            ControlPlanePermission.SECRET_REFERENCE_WRITE,
            reference.tenant_id,
        )
        with self._unit_of_work_factory() as uow:
            unit = uow.control_plane.get_unit(reference.tenant_id, reference.unit_id)
            if unit is None:
                raise ControlPlaneNotFoundError(
                    f"unit is not onboarded: {reference.tenant_id}/{reference.unit_id}"
                )
            if reference.environment not in unit.enabled_environments:
                raise ControlPlaneAuthorizationError(
                    "secret reference environment is not enabled for the target unit"
                )
            if (
                uow.control_plane.get_secret_reference(
                    reference.tenant_id,
                    reference.unit_id,
                    reference.environment,
                    reference.kind,
                    provider_id=reference.provider_id,
                )
                is not None
            ):
                raise ControlPlaneConflictError(
                    "secret reference kind/provider is already bound for unit/environment"
                )
            try:
                uow.control_plane.add_secret_reference(reference)
                uow.control_plane.append_audit(
                    self._audit_event(
                        actor=actor,
                        action=ControlPlaneAuditAction.SECRET_REFERENCE_BOUND,
                        target_type="secret-reference",
                        target_id=reference.reference_id,
                        correlation_id=correlation_id,
                        tenant_id=reference.tenant_id,
                        unit_id=reference.unit_id,
                    )
                )
            except PersistenceConflictError as exc:
                raise ControlPlaneConflictError(str(exc)) from exc
            uow.commit()
        return reference

    def add_fiscal_profile(
        self,
        *,
        actor: AdminPrincipal,
        profile: FiscalProfile,
    ) -> FiscalProfile:
        if not isinstance(profile, FiscalProfile):
            raise FiscalValidationError("profile must be FiscalProfile")
        self._require_tenant_permission(
            actor,
            ControlPlanePermission.PROFILE_WRITE,
            profile.scope.tenant_id,
        )
        if profile.scope.host_namespace is None:
            raise FiscalValidationError("Control Plane fiscal profile requires host_namespace")
        with self._unit_of_work_factory() as uow:
            if uow.control_plane.get_organization(profile.scope.tenant_id) is None:
                raise ControlPlaneNotFoundError(
                    f"organization is not onboarded: {profile.scope.tenant_id}"
                )
            unit = uow.control_plane.get_unit(
                profile.scope.tenant_id,
                profile.scope.unit_id,
            )
            if unit is None:
                raise ControlPlaneNotFoundError(
                    "unit is not onboarded: "
                    f"{profile.scope.tenant_id}/{profile.scope.unit_id}"
                )
            if profile.scope.environment not in unit.enabled_environments:
                raise ControlPlaneAuthorizationError(
                    "fiscal profile environment is not enabled for the target unit"
                )
            try:
                uow.control_plane.add_profile(profile)
                uow.control_plane.append_audit(
                    self._audit_event(
                        actor=actor,
                        action=ControlPlaneAuditAction.FISCAL_PROFILE_ADDED,
                        target_type="fiscal-profile",
                        target_id=f"{profile.profile_id}:v{profile.version}",
                        correlation_id=profile.scope.correlation_id,
                        tenant_id=profile.scope.tenant_id,
                        unit_id=profile.scope.unit_id,
                    )
                )
            except PersistenceConflictError as exc:
                raise ControlPlaneConflictError(str(exc)) from exc
            uow.commit()
        return profile

    def supersede_fiscal_profile(
        self,
        *,
        actor: AdminPrincipal,
        previous: FiscalProfile,
        successor: FiscalProfile,
    ) -> FiscalProfile:
        """Atomically close the open profile version and add the next one, audited."""
        self._require_tenant_permission(
            actor, ControlPlanePermission.PROFILE_WRITE, successor.scope.tenant_id,
        )
        with self._unit_of_work_factory() as uow:
            try:
                uow.control_plane.supersede_profile(previous, successor)
                uow.control_plane.append_audit(
                    self._audit_event(
                        actor=actor,
                        action=ControlPlaneAuditAction.FISCAL_PROFILE_SUPERSEDED,
                        target_type="fiscal-profile",
                        target_id=f"{successor.profile_id}:v{successor.version}",
                        correlation_id=successor.scope.correlation_id,
                        tenant_id=successor.scope.tenant_id,
                        unit_id=successor.scope.unit_id,
                    )
                )
            except PersistenceConflictError as exc:
                raise ControlPlaneConflictError(str(exc)) from exc
            uow.commit()
        return successor

    def list_audit(
        self,
        *,
        actor: AdminPrincipal,
        tenant_id: str | None = None,
    ) -> tuple[ControlPlaneAuditEvent, ...]:
        self._require_permission(actor, ControlPlanePermission.AUDIT_READ)
        if tenant_id is not None and not actor.can_access_tenant(tenant_id):
            raise ControlPlaneAuthorizationError(
                f"actor cannot access tenant audit: {tenant_id}"
            )
        with self._unit_of_work_factory() as uow:
            if actor.global_scope:
                events = uow.control_plane.list_audit(tenant_id)
            elif tenant_id is not None:
                events = uow.control_plane.list_audit(tenant_id)
            else:
                allowed = actor.tenant_ids
                events = tuple(
                    event
                    for event in uow.control_plane.list_audit()
                    if event.tenant_id in allowed
                )
        return events

    @staticmethod
    def _require_permission(
        actor: AdminPrincipal,
        permission: ControlPlanePermission,
    ) -> None:
        if not isinstance(actor, AdminPrincipal):
            raise FiscalValidationError("actor must be AdminPrincipal")
        if not actor.has_permission(permission):
            raise ControlPlaneAuthorizationError(
                f"actor lacks required permission: {permission.value}"
            )

    def _require_tenant_permission(
        self,
        actor: AdminPrincipal,
        permission: ControlPlanePermission,
        tenant_id: str,
    ) -> None:
        self._require_permission(actor, permission)
        if not actor.can_access_tenant(tenant_id):
            raise ControlPlaneAuthorizationError(
                f"actor cannot access tenant: {tenant_id}"
            )

    def _audit_event(
        self,
        *,
        actor: AdminPrincipal,
        action: ControlPlaneAuditAction,
        target_type: str,
        target_id: str,
        correlation_id: str,
        tenant_id: str,
        unit_id: str | None,
    ) -> ControlPlaneAuditEvent:
        return ControlPlaneAuditEvent(
            event_id=f"audit-{uuid4().hex}",
            occurred_at=self._clock.now(),
            actor_id=actor.actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            unit_id=unit_id,
        )
