"""Provider-neutral fiscal query, cancellation and inutilization operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalDomainError,
    FiscalValidationError,
)
from kordena_fiscal.gateway import GatewayProviderMetadata
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    FiscalStateMachine,
    FiscalStateSnapshot,
)
from kordena_fiscal.xml import NfeAccessKey


class FiscalOperationsContractError(FiscalDomainError):
    """Raised when an operations adapter violates the public contract."""


class FiscalQueryStatus(StrEnum):
    AUTHORIZED = "authorized"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"
    PENDING = "pending"


class FiscalEventStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"


def _required(value: str, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _justification(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 15:
        raise FiscalValidationError("justification must contain at least 15 characters")
    if len(normalized) > 255:
        raise FiscalValidationError("justification exceeds max length 255")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


def _operation_id(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FiscalQueryRequest:
    scope: ExecutionScope
    access_key: NfeAccessKey

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")


@dataclass(frozen=True, slots=True)
class FiscalQueryResult:
    status: FiscalQueryStatus
    scope: ExecutionScope
    access_key: NfeAccessKey
    provider: GatewayProviderMetadata
    provider_request_id: str | None = None
    protocol_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, FiscalQueryStatus):
            raise FiscalValidationError("status must be FiscalQueryStatus")
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")
        if not isinstance(self.provider, GatewayProviderMetadata):
            raise FiscalValidationError("provider must be GatewayProviderMetadata")
        for field_name in ("provider_request_id", "protocol_reference"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _required(value, field_name, 512))
        if self.status is FiscalQueryStatus.AUTHORIZED and self.protocol_reference is None:
            raise FiscalValidationError("authorized query requires protocol_reference")


@dataclass(frozen=True, slots=True)
class CancellationRequest:
    scope: ExecutionScope
    access_key: NfeAccessKey
    authorization_protocol: str
    justification: str
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")
        object.__setattr__(
            self,
            "authorization_protocol",
            _required(self.authorization_protocol, "authorization_protocol", 512),
        )
        object.__setattr__(self, "justification", _justification(self.justification))
        object.__setattr__(self, "request_id", _sha256(self.request_id, "request_id"))

    @classmethod
    def build(
        cls,
        *,
        scope: ExecutionScope,
        access_key: NfeAccessKey,
        authorization_protocol: str,
        justification: str,
    ) -> CancellationRequest:
        normalized_protocol = authorization_protocol.strip()
        normalized_justification = justification.strip()
        request_id = _operation_id(
            (
                "cancel",
                scope.tenant_id,
                scope.unit_id,
                scope.environment.value,
                access_key.value,
                normalized_protocol,
                normalized_justification,
            )
        )
        return cls(
            scope=scope,
            access_key=access_key,
            authorization_protocol=normalized_protocol,
            justification=normalized_justification,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class CancellationResult:
    status: FiscalEventStatus
    scope: ExecutionScope
    access_key: NfeAccessKey
    request_id: str
    provider: GatewayProviderMetadata
    provider_request_id: str | None = None
    event_protocol_reference: str | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None

    def __post_init__(self) -> None:
        _validate_event_result(
            self,
            status=self.status,
            scope=self.scope,
            request_id=self.request_id,
            provider=self.provider,
            event_protocol_reference=self.event_protocol_reference,
            rejection_code=self.rejection_code,
            rejection_message=self.rejection_message,
        )
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")
        if self.provider_request_id is not None:
            object.__setattr__(
                self,
                "provider_request_id",
                _required(self.provider_request_id, "provider_request_id", 512),
            )


@dataclass(frozen=True, slots=True)
class InutilizationRequest:
    scope: ExecutionScope
    model: ElectronicInvoiceModel
    series: int
    first_number: int
    last_number: int
    justification: str
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.model, ElectronicInvoiceModel):
            raise FiscalValidationError("model must be ElectronicInvoiceModel")
        if not isinstance(self.series, int) or isinstance(self.series, bool):
            raise FiscalValidationError("series must be an integer")
        if self.series < 0 or self.series > 999:
            raise FiscalValidationError("series must be between 0 and 999")
        for field_name in ("first_number", "last_number"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise FiscalValidationError(f"{field_name} must be a positive integer")
        if self.last_number < self.first_number:
            raise FiscalValidationError("last_number must be >= first_number")
        object.__setattr__(self, "justification", _justification(self.justification))
        object.__setattr__(self, "request_id", _sha256(self.request_id, "request_id"))

    @classmethod
    def build(
        cls,
        *,
        scope: ExecutionScope,
        model: ElectronicInvoiceModel,
        series: int,
        first_number: int,
        last_number: int,
        justification: str,
    ) -> InutilizationRequest:
        normalized_justification = justification.strip()
        request_id = _operation_id(
            (
                "inutilize",
                scope.tenant_id,
                scope.unit_id,
                scope.environment.value,
                str(model.value),
                str(series),
                str(first_number),
                str(last_number),
                normalized_justification,
            )
        )
        return cls(
            scope=scope,
            model=model,
            series=series,
            first_number=first_number,
            last_number=last_number,
            justification=normalized_justification,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class InutilizationResult:
    status: FiscalEventStatus
    scope: ExecutionScope
    model: ElectronicInvoiceModel
    series: int
    first_number: int
    last_number: int
    request_id: str
    provider: GatewayProviderMetadata
    provider_request_id: str | None = None
    event_protocol_reference: str | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None

    def __post_init__(self) -> None:
        _validate_event_result(
            self,
            status=self.status,
            scope=self.scope,
            request_id=self.request_id,
            provider=self.provider,
            event_protocol_reference=self.event_protocol_reference,
            rejection_code=self.rejection_code,
            rejection_message=self.rejection_message,
        )
        if not isinstance(self.model, ElectronicInvoiceModel):
            raise FiscalValidationError("model must be ElectronicInvoiceModel")
        if self.series < 0 or self.series > 999:
            raise FiscalValidationError("series must be between 0 and 999")
        if self.first_number < 1 or self.last_number < self.first_number:
            raise FiscalValidationError("inutilization result contains invalid number range")
        if self.provider_request_id is not None:
            object.__setattr__(
                self,
                "provider_request_id",
                _required(self.provider_request_id, "provider_request_id", 512),
            )


class FiscalOperationsGateway(Protocol):
    def query(self, request: FiscalQueryRequest) -> FiscalQueryResult: ...

    def cancel(self, request: CancellationRequest) -> CancellationResult: ...

    def inutilize(self, request: InutilizationRequest) -> InutilizationResult: ...


class FiscalOperationsClient:
    """Fail-closed boundary for query and event adapters."""

    def __init__(self, gateway: FiscalOperationsGateway) -> None:
        self._gateway = gateway

    def query(self, request: FiscalQueryRequest) -> FiscalQueryResult:
        if not isinstance(request, FiscalQueryRequest):
            raise FiscalValidationError("request must be FiscalQueryRequest")
        result = self._gateway.query(request)
        if not isinstance(result, FiscalQueryResult):
            raise FiscalOperationsContractError("gateway must return FiscalQueryResult")
        if result.scope != request.scope or result.access_key != request.access_key:
            raise FiscalOperationsContractError("query result does not match request identity")
        return result

    def cancel(self, request: CancellationRequest) -> CancellationResult:
        if not isinstance(request, CancellationRequest):
            raise FiscalValidationError("request must be CancellationRequest")
        result = self._gateway.cancel(request)
        if not isinstance(result, CancellationResult):
            raise FiscalOperationsContractError("gateway must return CancellationResult")
        if result.scope != request.scope:
            raise FiscalOperationsContractError("cancellation returned a different scope")
        if result.access_key != request.access_key:
            raise FiscalOperationsContractError("cancellation returned a different access key")
        if result.request_id != request.request_id:
            raise FiscalOperationsContractError("cancellation returned a different request_id")
        return result

    def inutilize(self, request: InutilizationRequest) -> InutilizationResult:
        if not isinstance(request, InutilizationRequest):
            raise FiscalValidationError("request must be InutilizationRequest")
        result = self._gateway.inutilize(request)
        if not isinstance(result, InutilizationResult):
            raise FiscalOperationsContractError("gateway must return InutilizationResult")
        identity = (
            result.scope,
            result.model,
            result.series,
            result.first_number,
            result.last_number,
            result.request_id,
        )
        expected = (
            request.scope,
            request.model,
            request.series,
            request.first_number,
            request.last_number,
            request.request_id,
        )
        if identity != expected:
            raise FiscalOperationsContractError("inutilization result does not match request")
        return result


@dataclass(frozen=True, slots=True)
class CancellationOutcome:
    result: CancellationResult
    lifecycle: FiscalStateSnapshot


class FiscalCancellationService:
    """Synchronize cancellation events with the fiscal document state machine."""

    def __init__(
        self,
        client: FiscalOperationsClient,
        state_machine: FiscalStateMachine | None = None,
    ) -> None:
        self._client = client
        self._state_machine = state_machine or FiscalStateMachine()

    def cancel(
        self,
        *,
        lifecycle: FiscalStateSnapshot,
        request: CancellationRequest,
        occurred_at: datetime,
        correlation_id: str,
    ) -> CancellationOutcome:
        requested = self.prepare(
            lifecycle=lifecycle, occurred_at=occurred_at, correlation_id=correlation_id
        )
        result = self._client.cancel(request)
        return self.complete(
            requested=requested, result=result, occurred_at=occurred_at,
            correlation_id=correlation_id,
        )

    def prepare(
        self, *, lifecycle: FiscalStateSnapshot, occurred_at: datetime, correlation_id: str
    ) -> FiscalStateSnapshot:
        if not isinstance(lifecycle, FiscalStateSnapshot):
            raise FiscalValidationError("lifecycle must be FiscalStateSnapshot")
        if lifecycle.state is not FiscalDocumentState.AUTHORIZED:
            raise FiscalValidationError("only an AUTHORIZED document can be cancelled")
        _aware(occurred_at, "occurred_at")
        correlation_id = _required(correlation_id, "correlation_id", 256)
        return self._state_machine.transition(
            lifecycle,
            FiscalDocumentState.CANCEL_REQUESTED,
            occurred_at=occurred_at,
            reason="fiscal cancellation requested",
            correlation_id=correlation_id,
        )
    def complete(
        self, *, requested: FiscalStateSnapshot, result: CancellationResult,
        occurred_at: datetime, correlation_id: str,
    ) -> CancellationOutcome:
        if requested.state is not FiscalDocumentState.CANCEL_REQUESTED:
            raise FiscalValidationError("cancellation must have a requested lifecycle")
        if not isinstance(result, CancellationResult):
            raise FiscalValidationError("validated cancellation result is required")
        _aware(occurred_at, "occurred_at")
        correlation_id = _required(correlation_id, "correlation_id", 256)
        if result.status is FiscalEventStatus.ACCEPTED:
            final = self._state_machine.transition(
                requested,
                FiscalDocumentState.CANCELLED,
                occurred_at=occurred_at,
                reason="fiscal cancellation accepted",
                correlation_id=correlation_id,
            )
        elif result.status is FiscalEventStatus.REJECTED:
            final = self._state_machine.transition(
                requested,
                FiscalDocumentState.AUTHORIZED,
                occurred_at=occurred_at,
                reason="fiscal cancellation rejected",
                correlation_id=correlation_id,
            )
        else:
            final = requested
        return CancellationOutcome(result=result, lifecycle=final)


def _validate_event_result(
    target: object,
    *,
    status: FiscalEventStatus,
    scope: ExecutionScope,
    request_id: str,
    provider: GatewayProviderMetadata,
    event_protocol_reference: str | None,
    rejection_code: str | None,
    rejection_message: str | None,
) -> None:
    if not isinstance(status, FiscalEventStatus):
        raise FiscalValidationError("status must be FiscalEventStatus")
    if not isinstance(scope, ExecutionScope):
        raise FiscalValidationError("scope must be ExecutionScope")
    if not isinstance(provider, GatewayProviderMetadata):
        raise FiscalValidationError("provider must be GatewayProviderMetadata")
    object.__setattr__(target, "request_id", _sha256(request_id, "request_id"))
    protocol = (
        _required(event_protocol_reference, "event_protocol_reference", 512)
        if event_protocol_reference is not None
        else None
    )
    code = _required(rejection_code, "rejection_code", 512) if rejection_code else None
    message = (
        _required(rejection_message, "rejection_message", 512)
        if rejection_message
        else None
    )
    object.__setattr__(target, "event_protocol_reference", protocol)
    object.__setattr__(target, "rejection_code", code)
    object.__setattr__(target, "rejection_message", message)
    if status is FiscalEventStatus.ACCEPTED:
        if protocol is None or code is not None or message is not None:
            raise FiscalValidationError("accepted event requires protocol only")
    elif status is FiscalEventStatus.REJECTED:
        if protocol is not None or code is None or message is None:
            raise FiscalValidationError("rejected event requires rejection metadata only")
    elif protocol is not None or code is not None or message is not None:
        raise FiscalValidationError("pending event cannot contain final metadata")


def _sha256(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise FiscalValidationError(f"{field_name} must be SHA-256 hex")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise FiscalValidationError(f"{field_name} must be hexadecimal") from exc
    return normalized
