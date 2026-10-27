"""Canonical fiscal ingress adapters for the FM NFCORE runtime.

Bridge and Portal translate their trusted authority into one application execution path.
No provider, secret, production grant, or synthetic fiscal result is created here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.operations import InutilizationRequest
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.security.human_identity import AuthenticatedHuman
from kordena_fiscal.security.s2s import (
    AuthorizedFiscalRequest,
    FiscalCapability,
    S2SAuthorizer,
    WorkloadAuthenticationError,
    WorkloadAuthenticator,
    WorkloadAuthorizationError,
    WorkloadRateLimitError,
)
from kordena_fiscal.web.app import (
    AuthorizedBridgeContext,
    BridgeExecutionResult,
    BridgeHttpContext,
    HttpContractError,
)

FiscalOperationHandler = Callable[
    [ExecutionScope, Mapping[str, Any], str | None],
    Mapping[str, Any],
]

_CAPABILITY_BY_OPERATION: dict[str, FiscalCapability] = {
    "queryArchiveReference": FiscalCapability.ARCHIVE_READ,
    "cancelFiscalDocument": FiscalCapability.CANCEL,
    "queryCapabilities": FiscalCapability.CAPABILITIES_READ,
    "inutilizeFiscalRange": FiscalCapability.INUTILIZE,
    "issueFiscalDocument": FiscalCapability.ISSUE,
    "queryFiscalDocument": FiscalCapability.QUERY,
    "reconcileFiscalOperation": FiscalCapability.RECONCILE,
}

_BRIDGE_STATUS_BY_OPERATION: dict[str, int] = {
    "queryArchiveReference": 200,
    "cancelFiscalDocument": 202,
    "queryCapabilities": 200,
    "inutilizeFiscalRange": 202,
    "issueFiscalDocument": 202,
    "queryFiscalDocument": 200,
    "reconcileFiscalOperation": 200,
}


class FiscalRuntimeUnavailableError(RuntimeError):
    """Raised when a canonical operation has no real execution dependency configured."""


class CanonicalFiscalOperationPath:
    """Single runtime dispatcher shared by Bridge and Portal ingress adapters.

    The dispatcher owns no fiscal business rule. It delegates durable scope resolution to
    ``FiscalApplicationService`` and delegates individual operations only to explicitly
    injected handlers. Missing handlers remain fail-closed rather than fabricating a
    synthetic provider/runtime result.
    """

    def __init__(
        self,
        application: FiscalApplicationService,
        *,
        handlers: Mapping[str, FiscalOperationHandler] | None = None,
    ) -> None:
        self._application = application
        supplied = dict(handlers or {})
        unknown = set(supplied) - set(_CAPABILITY_BY_OPERATION)
        if unknown:
            raise FiscalValidationError(
                "unsupported canonical fiscal operation handler: " + ", ".join(sorted(unknown))
            )
        self._handlers = supplied

    @property
    def configured_operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def execution_scope(
        self,
        host_scope: HostScope,
        *,
        environment: FiscalEnvironment,
        correlation_id: str,
    ) -> ExecutionScope:
        return self._application.resolve_scope(
            host_scope,
            environment=environment,
            correlation_id=correlation_id,
        )

    def validate_prepared(
        self,
        *,
        operation_id: str,
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> None:
        """Read-only opt-in validation before a Portal intent is persisted."""
        handler = self._handlers.get(operation_id)
        if handler is None:
            raise FiscalRuntimeUnavailableError("canonical fiscal operation is not configured")
        preflight = getattr(handler, "preflight", None)
        if callable(preflight):
            preflight(scope, payload, idempotency_key)

    def execute(
        self,
        *,
        operation_id: str,
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        if operation_id not in _CAPABILITY_BY_OPERATION:
            raise FiscalValidationError("unsupported canonical fiscal operation")
        handler = self._handlers.get(operation_id)
        if handler is None:
            raise FiscalRuntimeUnavailableError(
                f"canonical fiscal operation is not configured: {operation_id}"
            )
        result = handler(scope, payload, idempotency_key)
        if not isinstance(result, Mapping):
            raise FiscalValidationError("fiscal operation handler must return a mapping")
        return result


class CanonicalBridgeSecurityBoundary:
    """Authenticate workload identity and bind untrusted host headers to fiscal scope."""

    def __init__(
        self,
        *,
        authenticator: WorkloadAuthenticator,
        authorizer: S2SAuthorizer,
    ) -> None:
        self._authenticator = authenticator
        self._authorizer = authorizer

    def authorize(
        self,
        *,
        operation_id: str,
        context: BridgeHttpContext,
    ) -> AuthorizedBridgeContext:
        capability = _CAPABILITY_BY_OPERATION.get(operation_id)
        if capability is None:
            raise HttpContractError(
                404,
                "UNKNOWN_FISCAL_OPERATION",
                "Fiscal operation is not supported by the canonical runtime",
                context.correlation_id,
            )
        try:
            host_scope = HostScope(
                namespace=HostNamespace(context.host_namespace),
                tenant_id=context.tenant_id,
                unit_id=context.unit_id,
            )
            environment = FiscalEnvironment(context.environment)
        except (FiscalValidationError, ValueError) as exc:
            raise HttpContractError(
                400,
                "INVALID_FISCAL_SCOPE",
                "Fiscal host scope is invalid",
                context.correlation_id,
            ) from exc

        now = datetime.now(UTC)
        try:
            caller = self._authenticator.authenticate(
                credential_id=context.credential_id,
                presented_secret=context.presented_secret,
                now=now,
            )
        except WorkloadAuthenticationError as exc:
            raise HttpContractError(
                401,
                "WORKLOAD_AUTHENTICATION_FAILED",
                "Workload credential is not usable",
                context.correlation_id,
            ) from exc

        try:
            authorized = self._authorizer.authorize(
                caller=caller,
                host_scope=host_scope,
                environment=environment,
                capability=capability,
                correlation_id=context.correlation_id,
                causation_id=context.causation_id,
                now=now,
            )
        except WorkloadRateLimitError as exc:
            raise HttpContractError(
                429,
                "WORKLOAD_RATE_LIMITED",
                "Workload rate limit exceeded",
                context.correlation_id,
            ) from exc
        except WorkloadAuthorizationError as exc:
            raise HttpContractError(
                403,
                "WORKLOAD_AUTHORIZATION_FAILED",
                "Workload is not authorized for requested fiscal scope",
                context.correlation_id,
            ) from exc
        except FiscalValidationError as exc:
            raise HttpContractError(
                403,
                "FISCAL_BINDING_REQUIRED",
                "Exact fiscal binding is not available for requested scope",
                context.correlation_id,
            ) from exc

        return AuthorizedBridgeContext(
            authority=authorized,
            correlation_id=authorized.correlation_id,
        )


class CanonicalBridgeRequestExecutor:
    """Translate an authorized Bridge request into the shared canonical path."""

    def __init__(self, path: CanonicalFiscalOperationPath) -> None:
        self._path = path

    def execute(
        self,
        *,
        operation_id: str,
        authorized: AuthorizedBridgeContext,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> BridgeExecutionResult:
        authority = authorized.authority
        if not isinstance(authority, AuthorizedFiscalRequest):
            raise HttpContractError(
                403,
                "INVALID_FISCAL_AUTHORITY",
                "Bridge authority is not a canonical authorized fiscal request",
                authorized.correlation_id,
            )
        try:
            body = self._path.execute(
                operation_id=operation_id,
                scope=authority.scope,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except FiscalRuntimeUnavailableError as exc:
            raise HttpContractError(
                503,
                "FISCAL_RUNTIME_NOT_READY",
                "Canonical fiscal execution dependency is not configured",
                authorized.correlation_id,
            ) from exc
        except FiscalValidationError as exc:
            raise HttpContractError(
                400,
                "INVALID_FISCAL_REQUEST",
                "Fiscal request is invalid",
                authorized.correlation_id,
            ) from exc
        return BridgeExecutionResult(
            status_code=_BRIDGE_STATUS_BY_OPERATION[operation_id],
            body=body,
        )


class CanonicalPortalOperationExecutor:
    """Translate authenticated human authority into the same canonical fiscal path."""

    def __init__(
        self,
        *,
        unit_of_work_factory: FiscalUnitOfWorkFactory,
        path: CanonicalFiscalOperationPath,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._path = path

    @property
    def configured_operations(self) -> tuple[str, ...]:
        return self._path.configured_operations

    def validate_prepared(
        self,
        *,
        operation_id: str,
        scope: ExecutionScope,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> None:
        """Scope and permission were checked by the canonical Portal intent authority."""
        try:
            self._path.validate_prepared(
                operation_id=operation_id,
                scope=scope,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except FiscalValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PREPARED_DOCUMENT",
                    "message": "Prepared document reference is invalid or unavailable",
                },
            ) from exc

    def execute(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        unit_id = payload.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FISCAL_UNIT_REQUIRED",
                    "message": "unit_id is required for fiscal operations",
                },
            )
        unit_id = unit_id.strip()
        if authority.account.unit_ids is not None and unit_id not in authority.account.unit_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PORTAL_FORBIDDEN",
                    "message": "Operation is not permitted for requested unit",
                },
            )

        raw_environment = payload.get("environment", FiscalEnvironment.HOMOLOGATION.value)
        if not isinstance(raw_environment, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_ENVIRONMENT", "message": "environment must be text"},
            )
        try:
            environment = FiscalEnvironment(raw_environment.strip().lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_ENVIRONMENT",
                    "message": "Fiscal environment is invalid",
                },
            ) from exc

        with self._unit_of_work_factory() as uow:
            organization = uow.control_plane.get_organization(authority.tenant_id)
            unit = uow.control_plane.get_unit(authority.tenant_id, unit_id)
        if organization is None or unit is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "FISCAL_UNIT_NOT_CONFIGURED",
                    "message": "Fiscal tenant/unit must be configured before execution",
                },
            )
        if environment not in unit.enabled_environments:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FISCAL_ENVIRONMENT_NOT_ENABLED",
                    "message": "Requested fiscal environment is not enabled for this unit",
                },
            )

        correlation_id = idempotency_key or uuid4().hex
        scope = ExecutionScope(
            tenant_id=authority.tenant_id,
            unit_id=unit_id,
            environment=environment,
            correlation_id=correlation_id,
            host_namespace="fm-nfcore",
        )
        try:
            if operation_id == "inutilizeFiscalRange":
                fields = {"model", "series", "first_number", "last_number", "justification"}
                if set(payload) - fields - {"unit_id", "environment"} or not fields <= set(payload):
                    raise FiscalValidationError("inutilization fields do not match the contract")
                if type(payload["model"]) is not int or not isinstance(
                    payload["justification"], str
                ):
                    raise FiscalValidationError("inutilization model/justification type is invalid")
                try:
                    model = ElectronicInvoiceModel(payload["model"])
                except ValueError as exc:
                    raise FiscalValidationError("inutilization model is invalid") from exc
                request = InutilizationRequest.build(
                    scope=scope,
                    model=model,
                    series=payload["series"],
                    first_number=payload["first_number"],
                    last_number=payload["last_number"],
                    justification=payload["justification"],
                )
                payload = {
                    "unit_id": scope.unit_id,
                    "environment": scope.environment.value,
                    "model": request.model.value,
                    "series": request.series,
                    "first_number": request.first_number,
                    "last_number": request.last_number,
                    "justification": request.justification,
                }
            return self._path.execute(
                operation_id=operation_id,
                scope=scope,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except FiscalRuntimeUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "FISCAL_RUNTIME_NOT_READY",
                    "message": "Canonical fiscal execution dependency is not configured",
                },
            ) from exc
        except FiscalValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_FISCAL_REQUEST",
                    "message": "Fiscal request is invalid",
                },
            ) from exc
