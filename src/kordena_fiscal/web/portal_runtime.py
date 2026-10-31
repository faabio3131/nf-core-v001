"""Durable server-side portal projections for the commercial NFCORE runtime.

The browser never chooses tenant authority. Every read is scoped from the authenticated
human session and backed by the canonical fiscal/control-plane unit of work. Fiscal
mutations remain delegated to an explicitly configured operation executor and fail
closed when that execution boundary is not yet present.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException, status

from kordena_fiscal.application.commercial_portal import (
    CommercialPortalReader,
    CommercialPortalReadError,
)
from kordena_fiscal.compliance import CapabilityReadinessService, JurisdictionCapabilityError
from kordena_fiscal.compliance.capability_api import CapabilityReadinessError
from kordena_fiscal.contingency import FiscalOutboxStatus
from kordena_fiscal.control_plane.capability import (
    CapabilityControlContext,
    GovernedCapabilityReadinessService,
)
from kordena_fiscal.control_plane.commercial import CommercialConfigurationService
from kordena_fiscal.control_plane.durable import DurableControlPlaneService
from kordena_fiscal.control_plane.models import (
    AdminPrincipal,
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
    ControlPlanePermission,
    FiscalOrganization,
    FiscalUnitRegistration,
)
from kordena_fiscal.control_plane.service import (
    ControlPlaneAuthorizationError,
    ControlPlaneConflictError,
    ControlPlaneNotFoundError,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory, PersistenceConflictError
from kordena_fiscal.security.human_administration import (
    HumanAdministrationConflictError,
    HumanAdministrationNotFoundError,
    HumanAdministrationResult,
    HumanAdministrationService,
)
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAuthorizationError,
    PortalPermission,
)


class PortalOperationExecutor(Protocol):
    """Already-authorized fiscal operation boundary used by the human portal."""

    def execute(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]: ...


def _runtime_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "PORTAL_RUNTIME_NOT_READY", "message": message},
    )


def _portal_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


class DurableHumanPortalExecutor:
    """Read canonical durable state and execute safe self-service configuration."""

    _DURABLE_SURFACES = frozenset(
        {
            "overview",
            "documents",
            "issuances",
            "inutilizations",
            "errors",
            "reconciliation",
            "capabilities",
            "tax-reform",
            "onboarding",
            "companies",
            "units",
            "environments",
            "audit",
            "settings",
            "certificates",
            "providers",
            "webhooks",
            "integrations",
            "support",
        }
    )

    def __init__(
        self,
        unit_of_work_factory: FiscalUnitOfWorkFactory,
        *,
        operation_executor: PortalOperationExecutor | None = None,
        capability_readiness: CapabilityReadinessService | None = None,
        user_administration: HumanAdministrationService | None = None,
        commercial_reader: CommercialPortalReader | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._operation_executor = operation_executor
        self._user_administration = user_administration
        self._commercial_reader = commercial_reader
        self._capabilities = (
            GovernedCapabilityReadinessService(
                unit_of_work_factory=unit_of_work_factory,
                readiness=capability_readiness,
            )
            if capability_readiness is not None
            else None
        )

    def snapshot(self, *, authority: AuthenticatedHuman) -> Mapping[str, Any]:
        organization, units, _events = self._tenant_state(authority)
        configured_operations = tuple(
            getattr(self._operation_executor, "configured_operations", ())
        )
        environments = sorted(
            {environment.value for unit in units for environment in unit.enabled_environments}
        )
        if organization is None:
            onboarding_stage = "commercial_provisioning_required"
        elif not units:
            onboarding_stage = "unit_setup_required"
        else:
            onboarding_stage = "basic_setup_complete"
        return {
            "organization_onboarded": organization is not None,
            "legal_name": None if organization is None else organization.legal_name,
            "unit_count": len(units),
            "authorized_units": [
                {
                    "unit_id": unit.unit_id,
                    "display_name": unit.display_name,
                    "environments": sorted(env.value for env in unit.enabled_environments),
                }
                for unit in units
            ],
            "capability_readiness_configured": self._capabilities is not None,
            "legacy_unscoped_lifecycle_visibility": "excluded_unconfirmed",
            "unit_scope": "all" if authority.account.unit_ids is None else "restricted",
            "enabled_environments": environments,
            "fiscal_operation_executor_configured": self._operation_executor is not None,
            "fiscal_operations_configured": bool(configured_operations),
            "configured_fiscal_operations": list(configured_operations),
            "onboarding_stage": onboarding_stage,
            "basic_onboarding_complete": organization is not None and bool(units),
            "available_surfaces": sorted(
                self._DURABLE_SURFACES
                | ({"users"} if self._user_administration is not None else set())
                | ({"billing", "plans", "usage"} if self._commercial_reader is not None else set())
                | ({"webhook-egress"} if authority.account.platform_admin else set())
            ),
            "customer_configuration_mode": "governed_configuration",
            "customer_configuration_operations": [
                "configureCertificates",
                "configureProviders",
                "configureWebhooks",
                "configureIntegrations",
                "configureSettings",
            ],
        }

    def surface(
        self,
        *,
        surface_id: str,
        authority: AuthenticatedHuman,
        unit_id: str | None = None,
        environment: FiscalEnvironment | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Mapping[str, Any]]:
        if surface_id == "users":
            if self._user_administration is None:
                raise _runtime_unavailable("Human administration is not configured")
            return self._user_administration.list_users(authority=authority)
        if surface_id in {"billing", "plans", "usage"}:
            if self._commercial_reader is None:
                raise _runtime_unavailable("Canonical commercial reader is not configured")
            try:
                return self._commercial_reader.surface(
                    surface_id=surface_id,
                    tenant_id=authority.tenant_id,
                )
            except CommercialPortalReadError as exc:
                raise _runtime_unavailable("Canonical commercial state is not readable") from exc
        if surface_id not in self._DURABLE_SURFACES:
            raise _runtime_unavailable(
                f"Durable projection is not configured for portal surface {surface_id}"
            )

        organization, units, events = self._tenant_state(authority)
        if unit_id is not None:
            units = tuple(unit for unit in units if unit.unit_id == unit_id)
            if not units:
                raise _portal_error(409, "UNIT_NOT_CONFIGURED", "Selected unit is not configured")
        if surface_id in {
            "documents",
            "issuances",
            "inutilizations",
            "errors",
            "reconciliation",
            "capabilities",
            "tax-reform",
            "certificates",
            "providers",
            "webhooks",
            "integrations",
            "settings",
        }:
            if not units:
                return ()
            if len(units) != 1:
                raise _portal_error(409, "UNIT_SELECTION_REQUIRED", "Select an authorized unit")
            selected_environment = environment or FiscalEnvironment.HOMOLOGATION
            if selected_environment not in units[0].enabled_environments:
                raise _portal_error(
                    409, "ENVIRONMENT_NOT_ENABLED", "Selected environment is not enabled"
                )
            scope = ExecutionScope(
                host_namespace="fm-nfcore",
                tenant_id=authority.tenant_id,
                unit_id=units[0].unit_id,
                environment=selected_environment,
                correlation_id="portal-projection",
            )
            if surface_id in {"certificates", "providers", "webhooks", "integrations", "settings"}:
                return self._configuration_surface(surface_id, authority, scope, limit, offset)
            return self._fiscal_surface(surface_id, authority, scope, limit, offset)

        if surface_id == "support":
            # Existing authorized unit/configuration state, not an SLA or health probe.
            return tuple(
                {
                    "unit_id": unit.unit_id,
                    "environment": selected.value,
                    "record_type": "support_configuration",
                    "status": "operational_evidence_required",
                    "fiscal_executor": (
                        "configured_internal"
                        if getattr(self._operation_executor, "configured_operations", ())
                        else "unavailable"
                    ),
                    "capability_authority": (
                        "configured_internal" if self._capabilities is not None else "unavailable"
                    ),
                    "support_delivery": "not_configured",
                    "production": "not_authorized_by_portal",
                }
                for unit in units
                for selected in sorted(unit.enabled_environments, key=lambda item: item.value)
                if environment is None or selected == environment
            )[offset : offset + limit]

        if surface_id == "companies":
            if organization is None:
                return ()
            return (
                {
                    "tenant_id": organization.tenant_id,
                    "legal_name": organization.legal_name,
                    "status": "onboarded",
                },
            )
        if surface_id == "units":
            return tuple(
                {
                    "unit_id": unit.unit_id,
                    "display_name": unit.display_name,
                    "enabled_environments": sorted(
                        environment.value for environment in unit.enabled_environments
                    ),
                }
                for unit in units
            )
        if surface_id == "environments":
            return tuple(
                {
                    "unit_id": unit.unit_id,
                    "environment": environment.value,
                    "enabled": True,
                }
                for unit in units
                for environment in sorted(
                    unit.enabled_environments,
                    key=lambda item: item.value,
                )
            )
        if surface_id == "audit":
            return tuple(
                {
                    "event_id": event.event_id,
                    "occurred_at": event.occurred_at.isoformat(),
                    "action": event.action.value,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "correlation_id": event.correlation_id,
                    "unit_id": event.unit_id,
                }
                for event in events
                if (
                    (authority.account.unit_ids is None and unit_id is None)
                    or event.unit_id in {unit.unit_id for unit in units}
                )
            )

        row = dict(self.snapshot(authority=authority))
        row["tenant_id"] = authority.tenant_id
        row["surface"] = surface_id
        return (row,)

    def _configuration_surface(
        self,
        surface_id: str,
        authority: AuthenticatedHuman,
        scope: ExecutionScope,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, Any]]:
        permission = (
            PortalPermission.CERTIFICATE_MANAGE
            if surface_id == "certificates"
            else PortalPermission.CONFIGURATION_WRITE
            if surface_id == "settings"
            else PortalPermission.INTEGRATION_MANAGE
        )
        authority.assert_permission(permission, unit_id=scope.unit_id)
        base: dict[str, Any] = {
            "unit_id": scope.unit_id,
            "environment": scope.environment.value,
            "status": "configuration_recorded",
            "configuration_mode": "governed_configuration",
            "operational_verification": "not_confirmed",
        }
        with self._unit_of_work_factory() as uow:
            if surface_id == "certificates":
                return tuple(
                    {
                        **base,
                        "reference_id": reference.reference_id,
                        "reference_kind": reference.kind.value,
                        "provider_id": reference.provider_id,
                        "material_resolution": "not_attempted",
                        "version": uow.commercial.configuration_version(
                            scope,
                            "certificates",
                            reference.kind.value + ":" + (reference.provider_id or ""),
                        ),
                    }
                    for reference in uow.control_plane.list_secret_references(
                        scope, limit=limit, offset=offset
                    )
                )
            rows: list[Mapping[str, Any]] = [
                {**base, **metadata, "record_type": surface_id}
                for metadata in uow.commercial.list_portal_configuration(
                    surface_id, scope, limit=limit, offset=offset
                )
            ]
            if surface_id == "webhooks":
                rows.extend(
                    {
                        **base,
                        "record_type": "webhook_delivery",
                        "entry_id": entry.entry_id,
                        "status": entry.status.value,
                        "attempt_count": entry.attempt_count,
                        "created_at": entry.created_at.isoformat(),
                        "available_at": entry.available_at.isoformat(),
                        "failure_recorded": entry.last_error is not None,
                    }
                    for entry in uow.outbox.list_for_scope(scope, limit=limit, offset=offset)
                    if entry.operation == "webhook_event"
                )
            if surface_id == "integrations":
                rows.extend(
                    {
                        **base,
                        "record_type": "fiscal_binding",
                        "binding_id": binding.binding_id,
                        "integration_host": binding.host_scope.namespace.value,
                        "binding_environment": "not_environment_partitioned",
                    }
                    for binding in uow.bindings.list_for_fiscal_unit(
                        scope, limit=limit, offset=offset
                    )
                )
            return tuple(rows)

    def _fiscal_surface(
        self,
        surface_id: str,
        authority: AuthenticatedHuman,
        scope: ExecutionScope,
        limit: int,
        offset: int,
    ) -> Sequence[Mapping[str, Any]]:
        base = {"unit_id": scope.unit_id, "environment": scope.environment.value}
        if surface_id == "capabilities":
            return self._capability_rows(authority, scope)[offset : offset + limit]
        if surface_id == "tax-reform":
            # The only issuer authority is the existing versioned Control Plane
            # profile. The federal IRPJ regime is NOT inferred from NF-e CRT.
            with self._unit_of_work_factory() as uow:
                issuer = uow.control_plane.resolve_profile(
                    host_namespace=scope.host_namespace or "fm-nfcore",
                    tenant_id=scope.tenant_id,
                    unit_id=scope.unit_id,
                    environment=scope.environment,
                    instant=datetime.now(UTC),
                )
            if issuer is None:
                return ({**base, "record_type": "rtc_issuer",
                         "status": "fiscal_profile_not_configured",
                         "federal_regime_status": "declaration_not_configured",
                         "calculation_status": "not_certified"},)[offset : offset + limit]
            return ({
                **base,
                "record_type": "rtc_issuer",
                "status": "profile_effective",
                "profile_id": issuer.profile_id,
                "profile_version": issuer.version,
                "legal_name": issuer.legal_name,
                "crt": int(issuer.tax_regime),
                "primary_cnae": issuer.primary_cnae.value,
                "state_code": issuer.address.jurisdiction.state_code,
                "municipality_ibge_code": issuer.address.jurisdiction.municipality_ibge_code,
                "effective_from": issuer.effective_from.isoformat(),
                "effective_to": (issuer.effective_to.isoformat()
                                 if issuer.effective_to is not None else None),
                "federal_regime_status": "declaration_not_configured",
                "calculation_status": "not_certified",
            },)[offset : offset + limit]
        rows: list[Mapping[str, Any]] = []
        with self._unit_of_work_factory() as uow:
            if surface_id in {"inutilizations", "errors", "reconciliation"}:
                from kordena_fiscal.operations.event_archive import event_result_projection

                for entry in uow.archive.list_for_scope(scope, limit=limit, offset=offset):
                    outcome = event_result_projection(entry)
                    if outcome is None:
                        continue
                    if (
                        surface_id == "inutilizations"
                        and outcome["operation"] != "inutilizeFiscalRange"
                    ):
                        continue
                    if surface_id == "errors" and outcome["status"] != "rejected":
                        continue
                    if surface_id == "reconciliation" and outcome["status"] != "pending":
                        continue
                    rows.append({
                        **base, **outcome, "record_type": "fiscal_event",
                        "entry_id": entry.entry_id, "archived_at": entry.archived_at.isoformat(),
                    })
            if surface_id == "inutilizations":
                rows.extend(
                    {
                        **base,
                        "record_type": "outbox",
                        "entry_id": entry.entry_id,
                        "operation": entry.operation,
                        "status": entry.status.value,
                        "attempt_count": entry.attempt_count,
                        "created_at": entry.created_at.isoformat(),
                        "available_at": entry.available_at.isoformat(),
                        "fiscal_confirmation": "not_inferred_from_outbox",
                    }
                    for entry in uow.outbox.list_for_scope(
                        scope,
                        limit=limit,
                        offset=offset,
                        operations=frozenset({"inutilize", "inutilizefiscalrange"}),
                    )
                )
                return tuple(rows)
            if surface_id in {"documents", "issuances", "errors"}:
                for snapshot in uow.lifecycle.list_for_scope(
                    scope,
                    limit=limit,
                    offset=offset,
                    states=(
                        frozenset({FiscalDocumentState.ERROR, FiscalDocumentState.REJECTED})
                        if surface_id == "errors"
                        else None
                    ),
                ):
                    if surface_id == "errors" and snapshot.state not in {
                        FiscalDocumentState.ERROR,
                        FiscalDocumentState.REJECTED,
                    }:
                        continue
                    attempt = (
                        uow.idempotency.latest_for_document(snapshot.document_id)
                        if surface_id == "issuances"
                        else None
                    )
                    rows.append(
                        {
                            **base,
                            **(
                                {
                                    "attempt_status": attempt.status.value,
                                    "attempt_generation": attempt.generation,
                                }
                                if attempt
                                else {}
                            ),
                            "record_type": "lifecycle",
                            "document_id": snapshot.document_id,
                            "state": snapshot.state.value,
                            "version": snapshot.version,
                            "updated_at": snapshot.updated_at.isoformat(),
                        }
                    )
            if surface_id == "documents":
                for entry in uow.archive.list_for_scope(scope, limit=limit, offset=offset):
                    rows.append(
                        {
                            **base,
                            "record_type": "archive",
                            "entry_id": entry.entry_id,
                            "document_reference": entry.document_reference,
                            "kind": entry.kind.value,
                            "archived_at": entry.archived_at.isoformat(),
                            "content_sha256": entry.content_sha256,
                            "media_type": entry.media_type,
                        }
                    )
            if surface_id in {"issuances", "errors"}:
                for queued in uow.outbox.list_for_scope(
                    scope,
                    limit=limit,
                    offset=offset,
                    statuses=(
                        frozenset({FiscalOutboxStatus.RETRY_WAIT, FiscalOutboxStatus.DEAD_LETTER})
                        if surface_id == "errors"
                        else None
                    ),
                ):
                    if surface_id == "errors" and queued.status not in {
                        FiscalOutboxStatus.RETRY_WAIT,
                        FiscalOutboxStatus.DEAD_LETTER,
                    }:
                        continue
                    rows.append(
                        {
                            **base,
                            "record_type": "outbox",
                            "entry_id": queued.entry_id,
                            "operation": queued.operation,
                            "status": queued.status.value,
                            "attempt_count": queued.attempt_count,
                            "created_at": queued.created_at.isoformat(),
                            "available_at": queued.available_at.isoformat(),
                            "correlation_id": queued.scope.correlation_id,
                        }
                    )
            if surface_id == "reconciliation":
                for result in uow.reconciliations.list_for_scope(scope, limit=limit, offset=offset):
                    rows.append(
                        {
                            **base,
                            "record_type": "reconciliation",
                            "source_type": result.source.source_type,
                            "source_id": result.source.source_id,
                            "status": result.status.value,
                            "document_id": result.selected_document_id,
                            "issue_codes": [issue.code.value for issue in result.issues],
                            "correlation_id": result.scope.correlation_id,
                        }
                    )
        return tuple(rows)

    def _capability_rows(
        self,
        authority: AuthenticatedHuman,
        scope: ExecutionScope,
    ) -> tuple[Mapping[str, Any], ...]:
        rows: list[Mapping[str, Any]] = []
        actor = AdminPrincipal(
            actor_id="portal-" + hashlib.sha256(authority.account.account_id.encode()).hexdigest(),
            permissions=frozenset({ControlPlanePermission.CAPABILITY_READ}),
            tenant_ids=frozenset({authority.tenant_id}),
        )
        for kind in FiscalDocumentKind:
            row: dict[str, Any] = {
                "unit_id": scope.unit_id,
                "environment": scope.environment.value,
                "document_kind": kind.value,
            }
            if self._capabilities is None:
                row.update(status="blocked", code="CAPABILITY_AUTHORITY_NOT_CONFIGURED")
            else:
                try:
                    snapshot = self._capabilities.query(
                        actor=actor,
                        context=CapabilityControlContext(
                            host_namespace="fm-nfcore",
                            tenant_id=scope.tenant_id,
                            unit_id=scope.unit_id,
                            environment=scope.environment,
                            document_kind=kind,
                            instant=datetime.now(UTC),
                        ),
                    )
                    row.update(
                        status="declared",
                        readiness=snapshot.readiness.name,
                        capability_version=snapshot.capability_version,
                        actions=[action.value for action in snapshot.actions],
                        effective_from=snapshot.effective_from.isoformat(),
                        effective_to=(
                            snapshot.effective_to.isoformat() if snapshot.effective_to else None
                        ),
                    )
                except (
                    CapabilityReadinessError,
                    JurisdictionCapabilityError,
                    ControlPlaneNotFoundError,
                    FiscalValidationError,
                ):
                    row.update(status="blocked", code="CAPABILITY_OR_PROFILE_NOT_CONFIGURED")
                except ControlPlaneAuthorizationError as exc:
                    raise _portal_error(
                        403, "PORTAL_FORBIDDEN", "Capability scope is not authorized"
                    ) from exc
            rows.append(row)
        return tuple(rows)

    def fiscal_intents(
        self, *, authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment
    ) -> Sequence[Mapping[str, Any]]:
        from .fiscal_intent_recovery import FiscalIntentRecovery

        return FiscalIntentRecovery(self._unit_of_work_factory).list(
            authority, {"unit_id": unit_id, "environment": environment.value}
        )

    def prepare_fiscal_intent(
        self,
        *,
        authority: AuthenticatedHuman,
        operation_id: str,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        from .fiscal_intent_recovery import FiscalIntentRecovery

        if self._operation_executor is None or operation_id not in getattr(
            self._operation_executor, "configured_operations", ()
        ):
            raise _portal_error(
                503, "FISCAL_RUNTIME_NOT_READY", "Fiscal operation is not configured"
            )
        recovery = FiscalIntentRecovery(self._unit_of_work_factory)
        # Validate authority before resolving a reference, and do not create an
        # uncertain execution receipt for a deterministically invalid document.
        recovery.permission(authority, operation_id)
        if not idempotency_key or not idempotency_key.strip():
            raise _portal_error(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency key is required")
        scope = recovery.scope(authority, payload)
        preflight = getattr(self._operation_executor, "validate_prepared", None)
        if callable(preflight):
            preflight(
                operation_id=operation_id,
                scope=scope,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        try:
            return recovery.prepare(
                authority, operation_id, payload, idempotency_key
            )
        except PersistenceConflictError as exc:
            raise _portal_error(
                409, "FISCAL_INTENT_CONTENT_CONFLICT", "Preserve the original request"
            ) from exc

    def resume_fiscal_intent(
        self,
        *,
        authority: AuthenticatedHuman,
        intent_id: str,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
        legacy_result: bool = False,
    ) -> Mapping[str, Any]:
        from .fiscal_intent_recovery import FiscalIntentRecovery

        recovery = FiscalIntentRecovery(self._unit_of_work_factory)
        scope, row, dispatch = recovery.claim(authority, intent_id, payload, idempotency_key)
        if not dispatch:
            return recovery.project(row)
        if self._operation_executor is None:
            raise _portal_error(
                503, "FISCAL_RUNTIME_NOT_READY", "Fiscal operation is not configured"
            )
        result = self._operation_executor.execute(
            operation_id=str(row["operation"]),
            authority=authority,
            payload=payload,
            idempotency_key=str(row["original_key"]),
        )
        updated = recovery.finish(
            authority, scope, row, result.get("entry_id", result.get("document_id"))
        )
        if not legacy_result:
            return recovery.project(updated, replay=False)
        return {
            k: v
            for k, v in result.items()
            if k not in {"idempotency_key", "original_key", "fingerprint"}
        }

    def execute(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        configurations = {
            "configureCertificates": "certificates",
            "configureProviders": "providers",
            "configureWebhooks": "webhooks",
            "configureIntegrations": "integrations",
            "configureSettings": "settings",
        }
        if operation_id in configurations:
            return self.configure(
                authority=authority,
                tenant_id=authority.tenant_id,
                surface_id=configurations[operation_id],
                payload=payload,
                idempotency_key=idempotency_key,
            )
        if operation_id == "registerFiscalProfile":
            return self._register_fiscal_profile(
                authority=authority, payload=payload, idempotency_key=idempotency_key
            )
        if operation_id in {"createUser", "updateUser"}:
            return self._user_command(
                operation_id=operation_id,
                authority=authority,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        if operation_id == "onboardUnit":
            return self._onboard_unit(
                authority=authority,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        from .fiscal_intent_recovery import PERMISSIONS

        if operation_id in PERMISSIONS:
            receipt = self.prepare_fiscal_intent(
                authority=authority,
                operation_id=operation_id,
                payload=payload,
                idempotency_key=idempotency_key,
            )
            return self.resume_fiscal_intent(
                authority=authority,
                intent_id=str(receipt["intent_id"]),
                payload=payload,
                idempotency_key=idempotency_key,
                legacy_result=True,
            )
        if self._operation_executor is None:
            raise _runtime_unavailable("Fiscal portal operation executor is not configured")
        return self._operation_executor.execute(
            operation_id=operation_id,
            authority=authority,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def _register_fiscal_profile(
        self,
        *,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        """Register an initial issuer snapshot using the existing Control Plane.

        Tenant, host, profile identity, version, actor and effective timestamp
        are server owned. A retried key never creates a second issuer profile.
        """
        from kordena_fiscal.domain import (
            BrazilianJurisdiction,
            CnaeCode,
            Cnpj,
            FiscalAddress,
            FiscalProfile,
            StateRegistration,
            TaxRegimeCode,
        )

        required = {
            "unit_id", "environment", "cnpj", "legal_name", "crt", "primary_cnae",
            "state_registration", "state_registration_exempt", "street", "number",
            "district", "municipality_name", "state_code", "municipality_ibge_code",
            "postal_code",
        }
        try:
            if set(payload) != required:
                raise ValueError("invalid issuer profile command fields")
            key = (idempotency_key or "").strip()
            if not key or len(key) > 256:
                raise ValueError("idempotency key required")
            text_keys = required - {"crt", "state_registration_exempt"}
            if any(not isinstance(payload[item], str) for item in text_keys):
                raise ValueError("issuer profile string fields required")
            if type(payload["crt"]) is not int:
                raise ValueError("CRT must be integer")
            if type(payload["state_registration_exempt"]) is not bool:
                raise ValueError("state registration exemption must be boolean")
            if payload["state_registration_exempt"] and payload["state_registration"].strip():
                raise ValueError("exempt issuer cannot declare state registration number")
            unit_id = payload["unit_id"].strip()
            environment = FiscalEnvironment(payload["environment"])
            authority.assert_permission(PortalPermission.CONFIGURATION_WRITE, unit_id=unit_id)
            fingerprint = hashlib.sha256(
                (authority.tenant_id + ":" + unit_id + ":" + environment.value + ":" + key)
                .encode("utf-8")
            ).hexdigest()
            profile = FiscalProfile(
                profile_id="portal-" + fingerprint[:32],
                version=1,
                scope=ExecutionScope(
                    host_namespace="fm-nfcore",
                    tenant_id=authority.tenant_id,
                    unit_id=unit_id,
                    environment=environment,
                    correlation_id="profile-" + fingerprint[:20],
                ),
                cnpj=Cnpj(payload["cnpj"]),
                legal_name=payload["legal_name"],
                tax_regime=TaxRegimeCode(payload["crt"]),
                state_registration=StateRegistration(
                    state_code=payload["state_code"],
                    number=(None if payload["state_registration_exempt"]
                            else payload["state_registration"]),
                    exempt=payload["state_registration_exempt"],
                ),
                primary_cnae=CnaeCode(payload["primary_cnae"]),
                address=FiscalAddress(
                    street=payload["street"],
                    number=payload["number"],
                    district=payload["district"],
                    municipality_name=payload["municipality_name"],
                    jurisdiction=BrazilianJurisdiction(
                        state_code=payload["state_code"],
                        municipality_ibge_code=payload["municipality_ibge_code"],
                    ),
                    postal_code=payload["postal_code"],
                ),
                effective_from=datetime.now(UTC),
            )
            actor = AdminPrincipal(
                actor_id=authority.account.account_id,
                permissions=frozenset({ControlPlanePermission.PROFILE_WRITE}),
                tenant_ids=frozenset({authority.tenant_id}),
            )
            try:
                DurableControlPlaneService(self._unit_of_work_factory).add_fiscal_profile(
                    actor=actor, profile=profile
                )
            except ControlPlaneConflictError as exc:
                # Retry may only replay the exact same server-scoped issuer facts.
                with self._unit_of_work_factory() as uow:
                    existing = uow.control_plane.get_profile(profile.profile_id, 1)
                if existing is None or (
                    existing.cnpj != profile.cnpj
                    or existing.legal_name != profile.legal_name
                    or existing.tax_regime != profile.tax_regime
                    or existing.state_registration != profile.state_registration
                    or existing.primary_cnae != profile.primary_cnae
                    or existing.address != profile.address
                    or existing.scope.tenant_id != authority.tenant_id
                    or existing.scope.unit_id != unit_id
                    or existing.scope.environment != environment
                ):
                    raise _portal_error(
                        409, "FISCAL_PROFILE_CONFLICT", "Reload issuer configuration"
                    ) from exc
                return {
                    "status": "profile_registered", "profile_id": existing.profile_id,
                    "version": existing.version, "replay": True,
                }
            return {
                "status": "profile_registered", "profile_id": profile.profile_id,
                "version": profile.version, "replay": False,
            }
        except HumanAuthorizationError as exc:
            raise _portal_error(403, "FISCAL_PROFILE_FORBIDDEN", "Profile scope denied") from exc
        except ControlPlaneNotFoundError as exc:
            raise _portal_error(
                404, "FISCAL_PROFILE_UNIT_NOT_FOUND", "Unit not configured"
            ) from exc
        except ControlPlaneAuthorizationError as exc:
            raise _portal_error(403, "FISCAL_PROFILE_FORBIDDEN", "Profile scope denied") from exc
        except (FiscalValidationError, ValueError, TypeError, AttributeError) as exc:
            raise _portal_error(400, "INVALID_FISCAL_PROFILE", "Invalid issuer profile") from exc

    @staticmethod
    def _user_result(result: HumanAdministrationResult) -> Mapping[str, Any]:
        account = result.account
        return {
            "account_id": account.account_id,
            "email": account.email,
            "role": account.role.value,
            "unit_ids": None if account.unit_ids is None else sorted(account.unit_ids),
            "enabled": account.enabled,
            "platform_admin": account.platform_admin,
            "version": account.session_epoch,
            "created": result.created,
            "replay": result.replay,
            "activation": "password_recovery",
        }

    def _known_tenant_units(self, tenant_id: str) -> frozenset[str]:
        with self._unit_of_work_factory() as uow:
            events = uow.control_plane.list_audit(tenant_id)
        return frozenset(
            event.target_id
            for event in events
            if event.action is ControlPlaneAuditAction.UNIT_ONBOARDED
        )

    def _user_command(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        if self._user_administration is None:
            raise _runtime_unavailable("Human administration is not configured")
        try:
            if operation_id == "createUser":
                if set(payload) != {"email", "target_role", "target_unit_ids"}:
                    raise ValueError("invalid createUser fields")
                result = self._user_administration.create_user(
                    authority=authority,
                    email=payload["email"],
                    target_role=payload["target_role"],
                    target_unit_ids=payload["target_unit_ids"],
                    known_unit_ids=self._known_tenant_units(authority.tenant_id),
                    idempotency_key=idempotency_key or "",
                )
            elif operation_id == "updateUser":
                if set(payload) != {
                    "target_account_id",
                    "expected_version",
                    "target_role",
                    "target_unit_ids",
                    "enabled",
                }:
                    raise ValueError("invalid updateUser fields")
                result = self._user_administration.update_user(
                    authority=authority,
                    target_account_id=payload["target_account_id"],
                    expected_version=payload["expected_version"],
                    target_role=payload["target_role"],
                    target_unit_ids=payload["target_unit_ids"],
                    enabled=payload["enabled"],
                    known_unit_ids=self._known_tenant_units(authority.tenant_id),
                    idempotency_key=idempotency_key or "",
                )
            else:
                raise ValueError("unknown human administration operation")
            return self._user_result(result)
        except HumanAuthorizationError as exc:
            raise _portal_error(403, "USER_ADMIN_FORBIDDEN", "User administration denied") from exc
        except HumanAdministrationNotFoundError as exc:
            raise _portal_error(404, "USER_NOT_FOUND", "User account not found") from exc
        except HumanAdministrationConflictError as exc:
            raise _portal_error(409, "USER_ADMIN_CONFLICT", "Reload current user state") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise _portal_error(400, "INVALID_USER_ADMINISTRATION", "Invalid user command") from exc

    def configure(
        self,
        *,
        authority: AuthenticatedHuman,
        tenant_id: str,
        surface_id: str,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
        decision: str | None = None,
    ) -> Mapping[str, Any]:
        from uuid import uuid4

        try:
            if set(payload) - {"unit_id", "environment", "values", "expected_version"}:
                raise FiscalValidationError("unknown command field")
            if "expected_version" not in payload or not isinstance(payload.get("values"), Mapping):
                raise FiscalValidationError("configuration values are required")
            scope = ExecutionScope(
                host_namespace="fm-nfcore",
                tenant_id=tenant_id,
                unit_id=payload.get("unit_id", ""),
                environment=FiscalEnvironment(payload.get("environment", "")),
                correlation_id=uuid4().hex,
            )
            return CommercialConfigurationService(self._unit_of_work_factory).configure_customer(
                authority=authority,
                scope=scope,
                surface_id=surface_id,
                values=payload["values"],
                expected_version=payload["expected_version"],
                idempotency_key=idempotency_key or "",
                decision=decision,
            )
        except (ControlPlaneAuthorizationError, HumanAuthorizationError) as exc:
            raise _portal_error(403, "CONFIGURATION_FORBIDDEN", "Configuration denied") from exc
        except (ControlPlaneConflictError, PersistenceConflictError) as exc:
            raise _portal_error(409, "CONFIGURATION_CONFLICT", "Reload current version") from exc
        except ControlPlaneNotFoundError as exc:
            raise _portal_error(404, "CONFIGURATION_NOT_FOUND", "Configuration not found") from exc
        except (FiscalValidationError, ValueError, TypeError, AttributeError) as exc:
            raise _portal_error(400, "INVALID_CONFIGURATION", "Invalid configuration") from exc

    def egress_request(
        self,
        *,
        authority: AuthenticatedHuman,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        destination_id: str,
    ) -> Mapping[str, Any]:
        if not authority.account.platform_admin:
            raise _portal_error(403, "EGRESS_FORBIDDEN", "Platform authority required")
        scope = ExecutionScope(
            tenant_id=tenant_id,
            unit_id=unit_id,
            environment=environment,
            correlation_id="egress-review",
        )
        with self._unit_of_work_factory() as uow:
            record = uow.commercial.webhook_approval(scope, destination_id)
            if record is None:
                raise _portal_error(404, "EGRESS_NOT_FOUND", "Request not found")
            from kordena_fiscal.control_plane.webhook_policy import (
                WebhookPolicyDenied,
                normalize_webhook_url,
            )

            try:
                url, _hostname, _path = normalize_webhook_url(str(record["url"]))
            except WebhookPolicyDenied as exc:
                raise _portal_error(
                    409,
                    "EGRESS_REQUEST_REPLACEMENT_REQUIRED",
                    "A new valid destination request is required",
                ) from exc
            return {
                "destination_id": destination_id,
                "url": url,
                "enabled": bool(record["enabled"]),
                "approval_status": record["approval_status"],
                "approved_until": record["approved_until"],
                "version": uow.commercial.configuration_version(scope, "webhooks", destination_id),
                "operational_verification": "not_confirmed",
            }

    def _onboard_unit(
        self,
        *,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        unit_id = payload.get("unit_id")
        display_name = payload.get("display_name")
        if not isinstance(unit_id, str) or not isinstance(display_name, str):
            raise _portal_error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_UNIT_ONBOARDING",
                "unit_id and display_name are required",
            )
        if not idempotency_key:
            raise _portal_error(
                status.HTTP_400_BAD_REQUEST,
                "MISSING_IDEMPOTENCY_KEY",
                "Idempotency-Key is required",
            )

        registration = FiscalUnitRegistration(
            tenant_id=authority.tenant_id,
            unit_id=unit_id,
            display_name=display_name,
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        )
        with self._unit_of_work_factory() as uow:
            organization = uow.control_plane.get_organization(authority.tenant_id)
            existing = uow.control_plane.get_unit(authority.tenant_id, registration.unit_id)
        if organization is None:
            raise _portal_error(
                status.HTTP_409_CONFLICT,
                "COMMERCIAL_PROVISIONING_REQUIRED",
                "Commercial tenant organization must be provisioned before unit setup",
            )
        if existing is not None:
            if existing == registration:
                return {
                    "status": "already_onboarded",
                    "unit_id": existing.unit_id,
                    "environment": FiscalEnvironment.HOMOLOGATION.value,
                }
            raise _portal_error(
                status.HTTP_409_CONFLICT,
                "UNIT_ALREADY_EXISTS",
                "Unit already exists with different configuration",
            )

        actor_digest = hashlib.sha256(authority.account.account_id.encode("utf-8")).hexdigest()
        actor = AdminPrincipal(
            actor_id=f"human-{actor_digest[:24]}",
            permissions=frozenset({ControlPlanePermission.UNIT_WRITE}),
            tenant_ids=frozenset({authority.tenant_id}),
        )
        service = DurableControlPlaneService(self._unit_of_work_factory)
        try:
            created = service.onboard_unit(
                actor=actor,
                registration=registration,
                correlation_id=idempotency_key,
            )
        except ControlPlaneNotFoundError as exc:
            raise _portal_error(
                status.HTTP_409_CONFLICT,
                "COMMERCIAL_PROVISIONING_REQUIRED",
                "Commercial tenant organization must be provisioned before unit setup",
            ) from exc
        except ControlPlaneConflictError as exc:
            raise _portal_error(
                status.HTTP_409_CONFLICT,
                "UNIT_ONBOARDING_CONFLICT",
                "Unit onboarding conflicts with existing state",
            ) from exc
        except FiscalValidationError as exc:
            raise _portal_error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_UNIT_ONBOARDING",
                "Unit onboarding payload is invalid",
            ) from exc
        return {
            "status": "onboarded",
            "unit_id": created.unit_id,
            "environment": FiscalEnvironment.HOMOLOGATION.value,
        }

    def _tenant_state(
        self,
        authority: AuthenticatedHuman,
    ) -> tuple[
        FiscalOrganization | None,
        tuple[FiscalUnitRegistration, ...],
        tuple[ControlPlaneAuditEvent, ...],
    ]:
        tenant_id = authority.tenant_id
        with self._unit_of_work_factory() as uow:
            organization = uow.control_plane.get_organization(tenant_id)
            events = uow.control_plane.list_audit(tenant_id)
            discovered_unit_ids = {
                event.target_id
                for event in events
                if event.action is ControlPlaneAuditAction.UNIT_ONBOARDED
            }
            if authority.account.unit_ids is not None:
                discovered_unit_ids &= set(authority.account.unit_ids)
            units = tuple(
                unit
                for unit_id in sorted(discovered_unit_ids)
                if (unit := uow.control_plane.get_unit(tenant_id, unit_id)) is not None
            )
        return organization, units, events
