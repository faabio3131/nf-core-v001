"""Service-to-service authentication, authorization and webhook security.

The module is provider-neutral. It defines security semantics without binding FM Fiscal
to one cloud IAM, API gateway, token format, secret manager or webhook transport.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable

from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.domain.errors import FiscalDomainError


class S2SSecurityError(FiscalDomainError):
    """Base error for fail-closed service-to-service security decisions."""


class WorkloadAuthenticationError(S2SSecurityError):
    """Raised when a workload credential cannot be authenticated."""


class WorkloadAuthorizationError(S2SSecurityError):
    """Raised when an authenticated workload is not authorized."""


class WorkloadRateLimitError(S2SSecurityError):
    """Raised when a caller exceeds the configured in-memory rate policy."""


class WebhookSignatureError(S2SSecurityError):
    """Raised when a webhook signature is invalid, stale or otherwise unusable."""


class FiscalCapability(StrEnum):
    ISSUE = "fiscal.issue"
    QUERY = "fiscal.query"
    CANCEL = "fiscal.cancel"
    INUTILIZE = "fiscal.inutilize"
    CAPABILITIES_READ = "fiscal.capabilities.read"
    RECONCILE = "fiscal.reconcile"
    ARCHIVE_READ = "fiscal.archive.read"
    CERTIFICATE_DELEGATE = "fiscal.certificate.delegate"
    CERTIFICATE_STATUS_READ = "fiscal.certificate.status.read"
    CERTIFICATE_WITHDRAW = "fiscal.certificate.withdraw"


class SecurityAuditOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


def _required(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


def _sha256_hex(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise FiscalValidationError(f"{field_name} must be SHA-256 hex")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise FiscalValidationError(f"{field_name} must be hexadecimal") from exc
    return normalized


@dataclass(frozen=True, slots=True)
class HostScopeGrant:
    """Caller scope grant inside its fixed host namespace.

    ``tenant_id=None`` means every tenant of the caller host. When a tenant is set
    and ``unit_id=None``, every unit of that tenant is allowed. Setting a unit
    requires an explicit tenant, which avoids ambiguous cross-tenant grants.
    """

    tenant_id: str | None = None
    unit_id: str | None = None

    def __post_init__(self) -> None:
        if self.tenant_id is None and self.unit_id is not None:
            raise FiscalValidationError("unit_id grant requires tenant_id")
        if self.tenant_id is not None:
            object.__setattr__(self, "tenant_id", _required(self.tenant_id, "tenant_id", 128))
        if self.unit_id is not None:
            object.__setattr__(self, "unit_id", _required(self.unit_id, "unit_id", 128))

    def allows(self, host_scope: HostScope) -> bool:
        if not isinstance(host_scope, HostScope):
            raise FiscalValidationError("host_scope must be HostScope")
        if self.tenant_id is None:
            return True
        if self.tenant_id != host_scope.tenant_id:
            return False
        return self.unit_id is None or self.unit_id == host_scope.unit_id


@dataclass(frozen=True, slots=True)
class CallerIdentity:
    """Authenticated application identity with explicit authority boundaries."""

    caller_id: str
    host_namespace: HostNamespace
    capabilities: frozenset[FiscalCapability]
    scope_grants: tuple[HostScopeGrant, ...]
    environments: frozenset[FiscalEnvironment] = frozenset(FiscalEnvironment)

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_id", _required(self.caller_id, "caller_id", 128))
        if not isinstance(self.host_namespace, HostNamespace):
            raise FiscalValidationError("host_namespace must be HostNamespace")
        if not self.capabilities or not all(
            isinstance(capability, FiscalCapability) for capability in self.capabilities
        ):
            raise FiscalValidationError("capabilities must contain FiscalCapability values")
        if not self.environments or not all(
            isinstance(environment, FiscalEnvironment) for environment in self.environments
        ):
            raise FiscalValidationError("environments must contain FiscalEnvironment values")
        if not self.scope_grants or not all(
            isinstance(grant, HostScopeGrant) for grant in self.scope_grants
        ):
            raise FiscalValidationError("scope_grants must contain HostScopeGrant values")


@dataclass(frozen=True, slots=True)
class WorkloadCredentialRecord:
    """Hashed high-entropy workload credential with an explicit validity window."""

    credential_id: str
    caller: CallerIdentity
    secret_sha256: str
    valid_from: datetime
    expires_at: datetime
    revoked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "credential_id",
            _required(self.credential_id, "credential_id", 128),
        )
        if not isinstance(self.caller, CallerIdentity):
            raise FiscalValidationError("caller must be CallerIdentity")
        object.__setattr__(
            self,
            "secret_sha256",
            _sha256_hex(self.secret_sha256, "secret_sha256"),
        )
        _aware(self.valid_from, "valid_from")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.valid_from:
            raise FiscalValidationError("expires_at must be after valid_from")
        if not isinstance(self.revoked, bool):
            raise FiscalValidationError("revoked must be bool")

    @classmethod
    def from_secret(
        cls,
        *,
        credential_id: str,
        caller: CallerIdentity,
        secret: str,
        valid_from: datetime,
        expires_at: datetime,
        revoked: bool = False,
    ) -> WorkloadCredentialRecord:
        normalized_secret = _required(secret, "secret", 4096)
        if len(normalized_secret) < 32:
            raise FiscalValidationError("workload secret must contain at least 32 characters")
        digest = hashlib.sha256(normalized_secret.encode("utf-8")).hexdigest()
        return cls(
            credential_id=credential_id,
            caller=caller,
            secret_sha256=digest,
            valid_from=valid_from,
            expires_at=expires_at,
            revoked=revoked,
        )

    def assert_usable(self, now: datetime) -> None:
        _aware(now, "now")
        if self.revoked:
            raise WorkloadAuthenticationError("workload credential is revoked")
        if now < self.valid_from:
            raise WorkloadAuthenticationError("workload credential is not active yet")
        if now >= self.expires_at:
            raise WorkloadAuthenticationError("workload credential is expired")


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    identity: CallerIdentity
    credential_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CallerIdentity):
            raise FiscalValidationError("identity must be CallerIdentity")
        object.__setattr__(
            self,
            "credential_id",
            _required(self.credential_id, "credential_id", 128),
        )


class WorkloadAuthenticator:
    """Authenticate opaque high-entropy credentials without retaining raw tokens."""

    def __init__(self, records: tuple[WorkloadCredentialRecord, ...]) -> None:
        by_id: dict[str, WorkloadCredentialRecord] = {}
        for record in records:
            if not isinstance(record, WorkloadCredentialRecord):
                raise FiscalValidationError("records must contain WorkloadCredentialRecord")
            if record.credential_id in by_id:
                raise FiscalValidationError(f"duplicate credential_id: {record.credential_id}")
            by_id[record.credential_id] = record
        self._by_id = by_id

    def authenticate(
        self,
        *,
        credential_id: str,
        presented_secret: str,
        now: datetime,
    ) -> AuthenticatedCaller:
        normalized_id = _required(credential_id, "credential_id", 128)
        _aware(now, "now")
        try:
            record = self._by_id[normalized_id]
        except KeyError as exc:
            raise WorkloadAuthenticationError("unknown workload credential") from exc
        record.assert_usable(now)
        secret = _required(presented_secret, "presented_secret", 4096)
        candidate = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(candidate, record.secret_sha256):
            raise WorkloadAuthenticationError("invalid workload credential")
        return AuthenticatedCaller(identity=record.caller, credential_id=record.credential_id)


@dataclass(frozen=True, slots=True)
class SecurityAuditRecord:
    occurred_at: datetime
    caller_id: str
    credential_id: str
    host_namespace: str
    tenant_id: str
    unit_id: str
    capability: FiscalCapability
    outcome: SecurityAuditOutcome
    reason_code: str
    correlation_id: str

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        for field_name in (
            "caller_id",
            "credential_id",
            "host_namespace",
            "tenant_id",
            "unit_id",
            "reason_code",
            "correlation_id",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if not isinstance(self.capability, FiscalCapability):
            raise FiscalValidationError("capability must be FiscalCapability")
        if not isinstance(self.outcome, SecurityAuditOutcome):
            raise FiscalValidationError("outcome must be SecurityAuditOutcome")


@runtime_checkable
class FiscalExecutionScopeResolver(Protocol):
    def execution_scope(
        self,
        host_scope: HostScope,
        *,
        environment: FiscalEnvironment,
        correlation_id: str,
    ) -> ExecutionScope: ...


class SecurityAuditSink(Protocol):
    def record(self, record: SecurityAuditRecord) -> None: ...


class InMemorySecurityAuditSink:
    """Thread-safe reference sink; durable audit storage belongs to V2-07/V2-13."""

    def __init__(self) -> None:
        self._records: list[SecurityAuditRecord] = []
        self._lock = Lock()

    def record(self, record: SecurityAuditRecord) -> None:
        if not isinstance(record, SecurityAuditRecord):
            raise FiscalValidationError("record must be SecurityAuditRecord")
        with self._lock:
            self._records.append(record)

    @property
    def records(self) -> tuple[SecurityAuditRecord, ...]:
        with self._lock:
            return tuple(self._records)


class FixedWindowRateLimiter:
    """Small in-memory reference limiter keyed by authenticated caller id."""

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if not isinstance(max_requests, int) or isinstance(max_requests, bool) or max_requests < 1:
            raise FiscalValidationError("max_requests must be a positive integer")
        if (
            not isinstance(window_seconds, int)
            or isinstance(window_seconds, bool)
            or window_seconds < 1
        ):
            raise FiscalValidationError("window_seconds must be a positive integer")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = Lock()

    def allow(self, caller_id: str, now: datetime) -> bool:
        normalized = _required(caller_id, "caller_id", 128)
        _aware(now, "now")
        bucket = int(now.timestamp()) // self._window_seconds
        key = (normalized, bucket)
        with self._lock:
            current = self._counts.get(key, 0)
            if current >= self._max_requests:
                return False
            self._counts[key] = current + 1
            stale = [
                stored_key
                for stored_key in self._counts
                if stored_key[0] == normalized and stored_key[1] < bucket - 1
            ]
            for stored_key in stale:
                del self._counts[stored_key]
        return True


@dataclass(frozen=True, slots=True)
class AuthorizedFiscalRequest:
    caller: AuthenticatedCaller
    capability: FiscalCapability
    scope: ExecutionScope
    correlation_id: str
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.caller, AuthenticatedCaller):
            raise FiscalValidationError("caller must be AuthenticatedCaller")
        if not isinstance(self.capability, FiscalCapability):
            raise FiscalValidationError("capability must be FiscalCapability")
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        object.__setattr__(
            self,
            "correlation_id",
            _required(self.correlation_id, "correlation_id", 256),
        )
        if self.causation_id is not None:
            object.__setattr__(
                self,
                "causation_id",
                _required(self.causation_id, "causation_id", 256),
            )


class S2SAuthorizer:
    """Bind authenticated caller identity to host scope and fiscal execution scope."""

    def __init__(
        self,
        *,
        bindings: FiscalExecutionScopeResolver,
        audit_sink: SecurityAuditSink,
        rate_limiter: FixedWindowRateLimiter | None = None,
    ) -> None:
        if not isinstance(bindings, FiscalExecutionScopeResolver):
            raise FiscalValidationError(
                "bindings must implement FiscalExecutionScopeResolver"
            )
        self._bindings = bindings
        self._audit_sink = audit_sink
        self._rate_limiter = rate_limiter

    def authorize(
        self,
        *,
        caller: AuthenticatedCaller,
        host_scope: HostScope,
        environment: FiscalEnvironment,
        capability: FiscalCapability,
        correlation_id: str,
        now: datetime,
        causation_id: str | None = None,
    ) -> AuthorizedFiscalRequest:
        if not isinstance(caller, AuthenticatedCaller):
            raise FiscalValidationError("caller must be AuthenticatedCaller")
        if not isinstance(host_scope, HostScope):
            raise FiscalValidationError("host_scope must be HostScope")
        if not isinstance(environment, FiscalEnvironment):
            raise FiscalValidationError("environment must be FiscalEnvironment")
        if not isinstance(capability, FiscalCapability):
            raise FiscalValidationError("capability must be FiscalCapability")
        correlation = _required(correlation_id, "correlation_id", 256)
        _aware(now, "now")

        identity = caller.identity
        if identity.host_namespace != host_scope.namespace:
            self._deny(caller, host_scope, capability, correlation, now, "host_namespace_mismatch")
            raise WorkloadAuthorizationError("caller cannot act for another host namespace")
        if environment not in identity.environments:
            self._deny(caller, host_scope, capability, correlation, now, "environment_denied")
            raise WorkloadAuthorizationError("caller is not authorized for this environment")
        if capability not in identity.capabilities:
            self._deny(caller, host_scope, capability, correlation, now, "capability_denied")
            raise WorkloadAuthorizationError("caller does not have the required capability")
        if not any(grant.allows(host_scope) for grant in identity.scope_grants):
            self._deny(caller, host_scope, capability, correlation, now, "scope_denied")
            raise WorkloadAuthorizationError("caller is not authorized for host tenant/unit")
        if self._rate_limiter is not None and not self._rate_limiter.allow(
            identity.caller_id, now
        ):
            self._deny(caller, host_scope, capability, correlation, now, "rate_limited")
            raise WorkloadRateLimitError("caller exceeded the configured rate limit")

        try:
            scope = self._bindings.execution_scope(
                host_scope,
                environment=environment,
                correlation_id=correlation,
            )
        except FiscalValidationError:
            self._deny(caller, host_scope, capability, correlation, now, "binding_not_found")
            raise

        self._record(
            caller,
            host_scope,
            capability,
            correlation,
            now,
            SecurityAuditOutcome.ALLOWED,
            "authorized",
        )
        return AuthorizedFiscalRequest(
            caller=caller,
            capability=capability,
            scope=scope,
            correlation_id=correlation,
            causation_id=causation_id,
        )

    def _deny(
        self,
        caller: AuthenticatedCaller,
        host_scope: HostScope,
        capability: FiscalCapability,
        correlation_id: str,
        now: datetime,
        reason_code: str,
    ) -> None:
        self._record(
            caller,
            host_scope,
            capability,
            correlation_id,
            now,
            SecurityAuditOutcome.DENIED,
            reason_code,
        )

    def _record(
        self,
        caller: AuthenticatedCaller,
        host_scope: HostScope,
        capability: FiscalCapability,
        correlation_id: str,
        now: datetime,
        outcome: SecurityAuditOutcome,
        reason_code: str,
    ) -> None:
        self._audit_sink.record(
            SecurityAuditRecord(
                occurred_at=now,
                caller_id=caller.identity.caller_id,
                credential_id=caller.credential_id,
                host_namespace=host_scope.namespace.value,
                tenant_id=host_scope.tenant_id,
                unit_id=host_scope.unit_id,
                capability=capability,
                outcome=outcome,
                reason_code=reason_code,
                correlation_id=correlation_id,
            )
        )


@dataclass(frozen=True, slots=True)
class WebhookSignature:
    key_id: str
    timestamp: int
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id", 128))
        if not isinstance(self.timestamp, int) or isinstance(self.timestamp, bool):
            raise FiscalValidationError("timestamp must be an integer Unix timestamp")
        if self.timestamp < 0:
            raise FiscalValidationError("timestamp must be non-negative")
        object.__setattr__(self, "digest", _sha256_hex(self.digest, "digest"))

    @property
    def header_value(self) -> str:
        return f"t={self.timestamp},kid={self.key_id},v1={self.digest}"

    @classmethod
    def parse(cls, value: str) -> WebhookSignature:
        normalized = _required(value, "webhook_signature", 1024)
        parts: dict[str, str] = {}
        for segment in normalized.split(","):
            key, separator, item = segment.strip().partition("=")
            if not separator or key in parts:
                raise WebhookSignatureError("malformed webhook signature header")
            parts[key] = item
        if set(parts) != {"t", "kid", "v1"}:
            raise WebhookSignatureError("webhook signature header has unexpected fields")
        try:
            timestamp = int(parts["t"])
        except ValueError as exc:
            raise WebhookSignatureError("webhook signature timestamp is invalid") from exc
        return cls(key_id=parts["kid"], timestamp=timestamp, digest=parts["v1"])


class WebhookSecretResolver(Protocol):
    def resolve(self, key_id: str) -> bytes | None: ...


class InMemoryWebhookKeyRing:
    """Reference key ring supporting signing-key rotation without external I/O."""

    def __init__(self, *, active_key_id: str, keys: dict[str, bytes]) -> None:
        active = _required(active_key_id, "active_key_id", 128)
        if active not in keys:
            raise FiscalValidationError("active_key_id must exist in keys")
        normalized: dict[str, bytes] = {}
        for key_id, secret in keys.items():
            key = _required(key_id, "key_id", 128)
            if not isinstance(secret, bytes) or len(secret) < 32:
                raise FiscalValidationError("webhook secret must contain at least 32 bytes")
            normalized[key] = secret
        self._active_key_id = active
        self._keys = normalized

    def resolve(self, key_id: str) -> bytes | None:
        return self._keys.get(key_id)

    @property
    def active_key_id(self) -> str:
        return self._active_key_id


class WebhookSecurity:
    """HMAC-SHA256 signing and replay-bounded verification for fiscal webhooks."""

    def __init__(
        self,
        *,
        key_resolver: WebhookSecretResolver,
        signing_key_id: str,
        max_age_seconds: int = 300,
        max_future_skew_seconds: int = 30,
    ) -> None:
        self._key_resolver = key_resolver
        self._signing_key_id = _required(signing_key_id, "signing_key_id", 128)
        for value, field_name in (
            (max_age_seconds, "max_age_seconds"),
            (max_future_skew_seconds, "max_future_skew_seconds"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise FiscalValidationError(f"{field_name} must be a non-negative integer")
        self._max_age_seconds = max_age_seconds
        self._max_future_skew_seconds = max_future_skew_seconds

    def assert_dispatch_scope(self, scope: ExecutionScope) -> None:
        """Optional scope guard for explicit external signing dependencies."""
        del scope

    @staticmethod
    def _material(timestamp: int, body: bytes) -> bytes:
        if not isinstance(body, bytes):
            raise FiscalValidationError("body must be bytes")
        return str(timestamp).encode("ascii") + b"." + body

    def sign(self, body: bytes, *, now: datetime) -> WebhookSignature:
        _aware(now, "now")
        secret = self._key_resolver.resolve(self._signing_key_id)
        if secret is None or len(secret) < 32:
            raise WebhookSignatureError("active webhook signing key is unavailable")
        timestamp = int(now.astimezone(UTC).timestamp())
        digest = hmac.new(
            secret,
            self._material(timestamp, body),
            hashlib.sha256,
        ).hexdigest()
        return WebhookSignature(
            key_id=self._signing_key_id,
            timestamp=timestamp,
            digest=digest,
        )

    def verify(
        self,
        body: bytes,
        signature: WebhookSignature,
        *,
        now: datetime,
    ) -> None:
        if not isinstance(signature, WebhookSignature):
            raise FiscalValidationError("signature must be WebhookSignature")
        _aware(now, "now")
        now_timestamp = int(now.astimezone(UTC).timestamp())
        age = now_timestamp - signature.timestamp
        if age > self._max_age_seconds:
            raise WebhookSignatureError("webhook signature is stale")
        if age < -self._max_future_skew_seconds:
            raise WebhookSignatureError("webhook signature timestamp is too far in the future")
        secret = self._key_resolver.resolve(signature.key_id)
        if secret is None or len(secret) < 32:
            raise WebhookSignatureError("webhook verification key is unavailable")
        expected = hmac.new(
            secret,
            self._material(signature.timestamp, body),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.digest):
            raise WebhookSignatureError("webhook signature mismatch")
