"""Human identity, session and RBAC primitives for the FM NFCORE web portal.

This module is deliberately transport- and persistence-neutral. Passwords and raw
session/CSRF tokens are never stored. Durable repositories are supplied by later
infrastructure adapters.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable

from kordena_fiscal.domain.errors import FiscalDomainError


class HumanIdentityError(FiscalDomainError):
    """Base error for human identity decisions."""


class HumanAuthenticationError(HumanIdentityError):
    """Raised when credentials or a web session cannot be authenticated."""


class PasswordPolicyError(ValueError):
    """Raised when a human password violates the explicit password policy."""


PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024


class HumanRateLimitError(HumanAuthenticationError):
    """Raised when login attempts exceed the configured defensive policy."""


class HumanAuthorizationError(HumanIdentityError):
    """Raised when an authenticated user lacks authority."""


class CsrfValidationError(HumanIdentityError):
    """Raised when a state-changing browser request lacks valid CSRF proof."""


class PortalPermission(StrEnum):
    PORTAL_READ = "portal.read"
    DOCUMENT_QUERY = "document.query"
    DOCUMENT_ISSUE = "document.issue"
    DOCUMENT_CANCEL = "document.cancel"
    DOCUMENT_INUTILIZE = "document.inutilize"
    RECONCILIATION_EXECUTE = "reconciliation.execute"
    CONFIGURATION_WRITE = "configuration.write"
    CERTIFICATE_MANAGE = "certificate.manage"
    INTEGRATION_MANAGE = "integration.manage"
    BILLING_READ = "billing.read"
    BILLING_MANAGE = "billing.manage"
    AUDIT_READ = "audit.read"
    USER_MANAGE = "user.manage"


class PortalRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    ACCOUNTANT = "accountant"
    BILLING = "billing"


_ROLE_PERMISSIONS: dict[PortalRole, frozenset[PortalPermission]] = {
    PortalRole.OWNER: frozenset(PortalPermission),
    PortalRole.ADMIN: frozenset(
        {
            PortalPermission.PORTAL_READ,
            PortalPermission.DOCUMENT_QUERY,
            PortalPermission.DOCUMENT_ISSUE,
            PortalPermission.DOCUMENT_CANCEL,
            PortalPermission.DOCUMENT_INUTILIZE,
            PortalPermission.RECONCILIATION_EXECUTE,
            PortalPermission.CONFIGURATION_WRITE,
            PortalPermission.CERTIFICATE_MANAGE,
            PortalPermission.INTEGRATION_MANAGE,
            PortalPermission.BILLING_READ,
            PortalPermission.AUDIT_READ,
            PortalPermission.USER_MANAGE,
        }
    ),
    PortalRole.OPERATOR: frozenset(
        {
            PortalPermission.PORTAL_READ,
            PortalPermission.DOCUMENT_QUERY,
            PortalPermission.DOCUMENT_ISSUE,
            PortalPermission.DOCUMENT_CANCEL,
            PortalPermission.DOCUMENT_INUTILIZE,
            PortalPermission.RECONCILIATION_EXECUTE,
        }
    ),
    PortalRole.AUDITOR: frozenset(
        {
            PortalPermission.PORTAL_READ,
            PortalPermission.DOCUMENT_QUERY,
            PortalPermission.BILLING_READ,
            PortalPermission.AUDIT_READ,
        }
    ),
    PortalRole.ACCOUNTANT: frozenset(
        {PortalPermission.PORTAL_READ, PortalPermission.DOCUMENT_QUERY, PortalPermission.AUDIT_READ}
    ),
    PortalRole.BILLING: frozenset(
        {
            PortalPermission.PORTAL_READ,
            PortalPermission.BILLING_READ,
            PortalPermission.BILLING_MANAGE,
        }
    ),
}


def _required(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ScryptPasswordHasher:
    """Versioned scrypt password hashing with a unique random salt per password."""

    algorithm = "scrypt"

    def __init__(self, *, n: int = 2**14, r: int = 8, p: int = 1, dklen: int = 32) -> None:
        if n < 2**14 or n & (n - 1):
            raise ValueError("scrypt n must be a power of two >= 16384")
        if r < 8 or p < 1 or dklen < 32:
            raise ValueError("scrypt work factors are below the accepted baseline")
        self._n = n
        self._r = r
        self._p = p
        self._dklen = dklen

    def hash(self, password: str) -> str:
        normalized = self._validate_password(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            normalized.encode("utf-8"),
            salt=salt,
            n=self._n,
            r=self._r,
            p=self._p,
            dklen=self._dklen,
        )
        return "$".join(
            (
                self.algorithm,
                str(self._n),
                str(self._r),
                str(self._p),
                base64.urlsafe_b64encode(salt).decode("ascii"),
                base64.urlsafe_b64encode(digest).decode("ascii"),
            )
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            normalized = self._validate_password(password)
            algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
            if algorithm != self.algorithm:
                return False
            n = int(n_text)
            r = int(r_text)
            p = int(p_text)
            if n < 2**14 or r < 8 or p < 1:
                return False
            salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
            candidate = hashlib.scrypt(
                normalized.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                dklen=len(expected),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(candidate, expected)

    @staticmethod
    def _validate_password(password: str) -> str:
        if not isinstance(password, str):
            raise PasswordPolicyError("password must be a string")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise PasswordPolicyError(
                f"password must contain at least {PASSWORD_MIN_LENGTH} characters"
            )
        if len(password) > PASSWORD_MAX_LENGTH:
            raise PasswordPolicyError(
                f"password exceeds max length {PASSWORD_MAX_LENGTH}"
            )
        return password


@dataclass(frozen=True, slots=True)
class HumanAccount:
    account_id: str
    email: str
    password_hash: str
    tenant_id: str
    role: PortalRole
    unit_ids: frozenset[str] | None = None
    platform_admin: bool = False
    enabled: bool = True
    session_epoch: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _required(self.account_id, "account_id", 128))
        email = _required(self.email, "email", 320).casefold()
        if "@" not in email:
            raise ValueError("email must contain @")
        object.__setattr__(self, "email", email)
        object.__setattr__(
            self,
            "password_hash",
            _required(self.password_hash, "password_hash", 4096),
        )
        object.__setattr__(self, "tenant_id", _required(self.tenant_id, "tenant_id", 128))
        if not isinstance(self.role, PortalRole):
            raise ValueError("role must be PortalRole")
        if self.unit_ids is not None:
            normalized_units = frozenset(
                _required(value, "unit_id", 128) for value in self.unit_ids
            )
            if not normalized_units:
                raise ValueError("unit_ids must be None or contain at least one unit")
            object.__setattr__(self, "unit_ids", normalized_units)
        if not isinstance(self.platform_admin, bool):
            raise ValueError("platform_admin must be bool")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be bool")
        valid_epoch = (
            isinstance(self.session_epoch, int)
            and not isinstance(self.session_epoch, bool)
            and self.session_epoch >= 0
        )
        if not valid_epoch:
            raise ValueError("session_epoch must be a non-negative integer")

    @property
    def permissions(self) -> frozenset[PortalPermission]:
        return _ROLE_PERMISSIONS[self.role]

    @property
    def is_platform_admin(self) -> bool:
        """Platform administration is explicit and never inferred from tenant role."""

        return self.platform_admin


@runtime_checkable
class HumanAccountRepository(Protocol):
    def by_email(self, email: str) -> HumanAccount | None: ...

    def by_id(self, account_id: str) -> HumanAccount | None: ...

    def save(self, account: HumanAccount) -> None: ...


class InMemoryHumanAccountRepository:
    """Thread-safe reference repository; PostgreSQL arrives in WP-WEB-03."""

    def __init__(self, accounts: tuple[HumanAccount, ...] = ()) -> None:
        self._lock = Lock()
        self._by_id: dict[str, HumanAccount] = {}
        self._email_to_id: dict[str, str] = {}
        for account in accounts:
            self.save(account)

    def by_email(self, email: str) -> HumanAccount | None:
        normalized = email.strip().casefold()
        with self._lock:
            account_id = self._email_to_id.get(normalized)
            return self._by_id.get(account_id) if account_id is not None else None

    def by_id(self, account_id: str) -> HumanAccount | None:
        with self._lock:
            return self._by_id.get(account_id.strip())

    def save(self, account: HumanAccount) -> None:
        if not isinstance(account, HumanAccount):
            raise ValueError("account must be HumanAccount")
        with self._lock:
            existing_id = self._email_to_id.get(account.email)
            if existing_id is not None and existing_id != account.account_id:
                raise ValueError("email is already assigned to another account")
            old = self._by_id.get(account.account_id)
            if old is not None and old.email != account.email:
                self._email_to_id.pop(old.email, None)
            self._by_id[account.account_id] = account
            self._email_to_id[account.email] = account.account_id


@dataclass(frozen=True, slots=True)
class WebSessionRecord:
    session_id: str
    account_id: str
    session_token_sha256: str
    csrf_token_sha256: str
    session_epoch: int
    created_at: datetime
    expires_at: datetime
    revoked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _required(self.session_id, "session_id", 128))
        object.__setattr__(self, "account_id", _required(self.account_id, "account_id", 128))
        for field_name in ("session_token_sha256", "csrf_token_sha256"):
            value = _required(getattr(self, field_name), field_name, 64).lower()
            if len(value) != 64:
                raise ValueError(f"{field_name} must be SHA-256 hex")
            try:
                int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{field_name} must be hexadecimal") from exc
            object.__setattr__(self, field_name, value)
        _aware(self.created_at, "created_at")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.session_epoch < 0:
            raise ValueError("session_epoch must be non-negative")


@runtime_checkable
class WebSessionRepository(Protocol):
    def by_token_digest(self, session_token_sha256: str) -> WebSessionRecord | None: ...

    def save(self, session: WebSessionRecord) -> None: ...

    def revoke(self, session_id: str) -> None: ...

    def revoke_account(self, account_id: str) -> None: ...


class InMemoryWebSessionRepository:
    """Thread-safe hashed-token session store used until WP-WEB-03 persistence."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_id: dict[str, WebSessionRecord] = {}
        self._token_to_id: dict[str, str] = {}

    def by_token_digest(self, session_token_sha256: str) -> WebSessionRecord | None:
        with self._lock:
            session_id = self._token_to_id.get(session_token_sha256)
            return self._by_id.get(session_id) if session_id is not None else None

    def save(self, session: WebSessionRecord) -> None:
        if not isinstance(session, WebSessionRecord):
            raise ValueError("session must be WebSessionRecord")
        with self._lock:
            old = self._by_id.get(session.session_id)
            if old is not None and old.session_token_sha256 != session.session_token_sha256:
                self._token_to_id.pop(old.session_token_sha256, None)
            self._by_id[session.session_id] = session
            self._token_to_id[session.session_token_sha256] = session.session_id

    def revoke(self, session_id: str) -> None:
        with self._lock:
            session = self._by_id.get(session_id)
            if session is not None and not session.revoked:
                self._by_id[session_id] = replace(session, revoked=True)

    def revoke_account(self, account_id: str) -> None:
        with self._lock:
            for session_id, session in tuple(self._by_id.items()):
                if session.account_id == account_id and not session.revoked:
                    self._by_id[session_id] = replace(session, revoked=True)


class LoginAttemptLimiter:
    """Reference fixed-window limiter for human login attempts."""

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        if max_failures < 1 or window_seconds < 1:
            raise ValueError("login rate-limit values must be positive")
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._lock = Lock()
        self._failures: dict[tuple[str, int], int] = {}

    def _key(self, email: str, now: datetime) -> tuple[str, int]:
        _aware(now, "now")
        normalized = _required(email, "email", 320).casefold()
        return normalized, int(now.timestamp()) // self._window_seconds

    def assert_allowed(self, email: str, now: datetime) -> None:
        key = self._key(email, now)
        with self._lock:
            if self._failures.get(key, 0) >= self._max_failures:
                raise HumanRateLimitError("too many login attempts")

    def record_failure(self, email: str, now: datetime) -> None:
        key = self._key(email, now)
        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1

    def reset(self, email: str, now: datetime) -> None:
        key = self._key(email, now)
        with self._lock:
            self._failures.pop(key, None)


@dataclass(frozen=True, slots=True)
class IssuedWebSession:
    session_token: str
    csrf_token: str
    expires_at: datetime
    account: HumanAccount

    def __repr__(self) -> str:
        return (
            "IssuedWebSession(session_token=<redacted>, csrf_token=<redacted>, "
            f"expires_at={self.expires_at!r}, account={self.account.account_id!r})"
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedHuman:
    account: HumanAccount
    session_id: str
    csrf_token_sha256: str
    expires_at: datetime

    @property
    def tenant_id(self) -> str:
        return self.account.tenant_id

    @property
    def permissions(self) -> frozenset[PortalPermission]:
        return self.account.permissions

    def assert_permission(
        self,
        permission: PortalPermission,
        *,
        unit_id: str | None = None,
    ) -> None:
        if permission not in self.permissions:
            raise HumanAuthorizationError("user does not have the required permission")
        if unit_id is not None:
            normalized = _required(unit_id, "unit_id", 128)
            if self.account.unit_ids is not None and normalized not in self.account.unit_ids:
                raise HumanAuthorizationError("user is not authorized for the requested unit")


class HumanIdentityService:
    """Authenticate humans and issue opaque revocable sessions without storing raw tokens."""

    def __init__(
        self,
        *,
        accounts: HumanAccountRepository,
        sessions: WebSessionRepository,
        password_hasher: ScryptPasswordHasher,
        session_ttl: timedelta = timedelta(hours=8),
        login_limiter: LoginAttemptLimiter | None = None,
    ) -> None:
        if not isinstance(accounts, HumanAccountRepository):
            raise ValueError("accounts must implement HumanAccountRepository")
        if not isinstance(sessions, WebSessionRepository):
            raise ValueError("sessions must implement WebSessionRepository")
        if session_ttl <= timedelta(minutes=5) or session_ttl > timedelta(days=30):
            raise ValueError("session_ttl must be > 5 minutes and <= 30 days")
        self._accounts = accounts
        self._sessions = sessions
        self._password_hasher = password_hasher
        self._session_ttl = session_ttl
        self._login_limiter = login_limiter or LoginAttemptLimiter()
        self._dummy_hash = password_hasher.hash("nfcore-dummy-password-never-authenticates")

    def login(self, *, email: str, password: str, now: datetime) -> IssuedWebSession:
        return self.issue_session(
            self.authenticate_password(email=email, password=password, now=now), now=now,
        )

    def account_by_id(self, account_id: str) -> HumanAccount | None:
        return self._accounts.by_id(_required(account_id, "account_id", 128))

    def authenticate_password(self, *, email: str, password: str, now: datetime) -> HumanAccount:
        """First factor only; callers decide whether a second factor is due."""
        _aware(now, "now")
        normalized_email = _required(email, "email", 320).casefold()
        self._login_limiter.assert_allowed(normalized_email, now)
        account = self._accounts.by_email(normalized_email)
        encoded = account.password_hash if account is not None else self._dummy_hash
        password_valid = self._password_hasher.verify(password, encoded)
        if account is None or not account.enabled or not password_valid:
            self._login_limiter.record_failure(normalized_email, now)
            raise HumanAuthenticationError("invalid email or password")

        self._login_limiter.reset(normalized_email, now)
        return account

    def issue_session(self, account: HumanAccount, *, now: datetime) -> IssuedWebSession:
        _aware(now, "now")
        current = self._accounts.by_id(account.account_id)
        if current is None or not current.enabled:
            raise HumanAuthenticationError("invalid email or password")
        account = current
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + self._session_ttl
        record = WebSessionRecord(
            session_id=secrets.token_urlsafe(24),
            account_id=account.account_id,
            session_token_sha256=_token_digest(session_token),
            csrf_token_sha256=_token_digest(csrf_token),
            session_epoch=account.session_epoch,
            created_at=now,
            expires_at=expires_at,
        )
        self._sessions.save(record)
        return IssuedWebSession(
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
            account=account,
        )

    def authenticate_session(self, *, session_token: str, now: datetime) -> AuthenticatedHuman:
        _aware(now, "now")
        normalized = _required(session_token, "session_token", 4096)
        session = self._sessions.by_token_digest(_token_digest(normalized))
        if session is None or session.revoked or now >= session.expires_at:
            raise HumanAuthenticationError("web session is not usable")
        account = self._accounts.by_id(session.account_id)
        if account is None or not account.enabled or account.session_epoch != session.session_epoch:
            raise HumanAuthenticationError("web session is not usable")
        return AuthenticatedHuman(
            account=account,
            session_id=session.session_id,
            csrf_token_sha256=session.csrf_token_sha256,
            expires_at=session.expires_at,
        )

    def assert_csrf(self, authenticated: AuthenticatedHuman, presented_token: str) -> None:
        normalized = _required(presented_token, "csrf_token", 4096)
        candidate = _token_digest(normalized)
        if not hmac.compare_digest(candidate, authenticated.csrf_token_sha256):
            raise CsrfValidationError("invalid CSRF token")

    def logout(self, authenticated: AuthenticatedHuman) -> None:
        self._sessions.revoke(authenticated.session_id)

    def revoke_all_sessions(self, account_id: str) -> None:
        account = self._accounts.by_id(_required(account_id, "account_id", 128))
        if account is None:
            return
        self._accounts.save(replace(account, session_epoch=account.session_epoch + 1))
        self._sessions.revoke_account(account.account_id)
