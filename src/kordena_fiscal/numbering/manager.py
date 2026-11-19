"""Atomic, partitioned fiscal sequence reservation contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum
from threading import Lock
from typing import Protocol

from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalDomainError,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.domain.primitives import _normalize_host_namespace


class InternalFiscalSequenceStream(IntEnum):
    """Private numbering namespace; never an official invoice model code.

    Value 90 is reserved only in the NFCore fm_fiscal_sequences persistence
    partition for municipal RPS. It MUST NOT be serialized as a fiscal
    document model, access-key model, or NFS-e XML value.
    """

    NFSE_RPS = 90


class SequenceExhaustedError(FiscalDomainError):
    """Raised when a configured fiscal sequence cannot allocate another number."""


class SequenceStateError(FiscalDomainError):
    """Raised when sequence state is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class FiscalSequenceKey:
    """Stable partition for one legal fiscal numbering stream."""

    tenant_id: str
    unit_id: str
    environment: FiscalEnvironment
    model: ElectronicInvoiceModel | InternalFiscalSequenceStream
    series: int
    host_namespace: str | None = None

    def __post_init__(self) -> None:
        tenant_id = self.tenant_id.strip()
        unit_id = self.unit_id.strip()
        if not tenant_id:
            raise FiscalValidationError("tenant_id must not be blank")
        if not unit_id:
            raise FiscalValidationError("unit_id must not be blank")
        if not isinstance(self.environment, FiscalEnvironment):
            raise FiscalValidationError("environment must be FiscalEnvironment")
        if not isinstance(self.model, (ElectronicInvoiceModel, InternalFiscalSequenceStream)):
            raise FiscalValidationError("model must be an approved fiscal sequence stream")
        if not isinstance(self.series, int) or isinstance(self.series, bool):
            raise FiscalValidationError("series must be an integer")
        if self.series < 0:
            raise FiscalValidationError("series must be non-negative")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "unit_id", unit_id)
        if self.host_namespace is not None:
            object.__setattr__(
                self,
                "host_namespace",
                _normalize_host_namespace(self.host_namespace),
            )

    @classmethod
    def from_scope(
        cls,
        scope: ExecutionScope,
        *,
        model: ElectronicInvoiceModel | InternalFiscalSequenceStream,
        series: int,
    ) -> FiscalSequenceKey:
        if not isinstance(scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        return cls(
            tenant_id=scope.tenant_id,
            unit_id=scope.unit_id,
            environment=scope.environment,
            model=model,
            series=series,
            host_namespace=scope.host_namespace,
        )

    @property
    def canonical_material(self) -> str:
        legacy = (
            self.tenant_id,
            self.unit_id,
            self.environment.value,
            str(self.model.value),
            str(self.series),
        )
        if self.host_namespace is None:
            return "|".join(legacy)
        return "|".join((self.host_namespace, *legacy))


@dataclass(frozen=True, slots=True)
class FiscalSequencePolicy:
    """Host-configured sequence bounds, independent of model-specific XSD rules."""

    first_number: int = 1
    max_number: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.first_number, int) or isinstance(self.first_number, bool):
            raise FiscalValidationError("first_number must be an integer")
        if self.first_number < 1:
            raise FiscalValidationError("first_number must be >= 1")
        if self.max_number is not None:
            if not isinstance(self.max_number, int) or isinstance(self.max_number, bool):
                raise FiscalValidationError("max_number must be an integer when provided")
            if self.max_number < self.first_number:
                raise FiscalValidationError("max_number must be >= first_number")


@dataclass(frozen=True, slots=True)
class FiscalNumberReservation:
    """One unique number reserved from a sequence partition."""

    key: FiscalSequenceKey
    number: int
    reservation_token: str

    def __post_init__(self) -> None:
        if self.number < 1:
            raise FiscalValidationError("reserved fiscal number must be >= 1")
        if len(self.reservation_token) != 64:
            raise FiscalValidationError("reservation_token must be a SHA-256 hex digest")
        try:
            int(self.reservation_token, 16)
        except ValueError as exc:
            raise FiscalValidationError("reservation_token must be hexadecimal") from exc


class FiscalSequenceStore(Protocol):
    """Atomic persistence contract required by production numbering adapters."""

    def reserve_next(
        self,
        key: FiscalSequenceKey,
        policy: FiscalSequencePolicy,
    ) -> FiscalNumberReservation: ...

    def last_reserved(self, key: FiscalSequenceKey) -> int | None: ...


class InMemoryFiscalSequenceStore:
    """Thread-safe reference store for tests; not a distributed production store."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_by_key: dict[FiscalSequenceKey, int] = {}
        self._policy_by_key: dict[FiscalSequenceKey, FiscalSequencePolicy] = {}

    def reserve_next(
        self,
        key: FiscalSequenceKey,
        policy: FiscalSequencePolicy,
    ) -> FiscalNumberReservation:
        if not isinstance(key, FiscalSequenceKey):
            raise FiscalValidationError("key must be FiscalSequenceKey")
        if not isinstance(policy, FiscalSequencePolicy):
            raise FiscalValidationError("policy must be FiscalSequencePolicy")

        with self._lock:
            stored_policy = self._policy_by_key.get(key)
            if stored_policy is not None and stored_policy != policy:
                raise SequenceStateError(
                    "sequence policy cannot change after the first reservation"
                )

            previous = self._last_by_key.get(key)
            candidate = policy.first_number if previous is None else previous + 1
            if policy.max_number is not None and candidate > policy.max_number:
                raise SequenceExhaustedError("fiscal sequence has reached its configured maximum")

            self._policy_by_key[key] = policy
            self._last_by_key[key] = candidate
            return FiscalNumberReservation(
                key=key,
                number=candidate,
                reservation_token=_reservation_token(key, candidate),
            )

    def last_reserved(self, key: FiscalSequenceKey) -> int | None:
        if not isinstance(key, FiscalSequenceKey):
            raise FiscalValidationError("key must be FiscalSequenceKey")
        with self._lock:
            return self._last_by_key.get(key)


class FiscalSequenceManager:
    """Application-facing API for atomic fiscal-number reservations."""

    def __init__(
        self,
        store: FiscalSequenceStore,
        *,
        policy: FiscalSequencePolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or FiscalSequencePolicy()

    def reserve(
        self,
        scope: ExecutionScope,
        *,
        model: ElectronicInvoiceModel,
        series: int,
    ) -> FiscalNumberReservation:
        key = FiscalSequenceKey.from_scope(scope, model=model, series=series)
        return self._store.reserve_next(key, self._policy)

    def last_reserved(
        self,
        scope: ExecutionScope,
        *,
        model: ElectronicInvoiceModel,
        series: int,
    ) -> int | None:
        key = FiscalSequenceKey.from_scope(scope, model=model, series=series)
        return self._store.last_reserved(key)


def _reservation_token(key: FiscalSequenceKey, number: int) -> str:
    material = f"{key.canonical_material}|{number}".encode()
    return hashlib.sha256(material).hexdigest()
