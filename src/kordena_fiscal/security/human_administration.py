"""Governed tenant user administration over the canonical human identity authority.

This module deliberately reuses HumanAccount/PortalRole/PortalPermission. It does not
create a second authentication system, a browser-defined tenant authority, or a path
for tenant administrators to grant platform_admin.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol, runtime_checkable

from kordena_fiscal.domain.errors import FiscalDomainError

from .human_identity import (
    AuthenticatedHuman,
    HumanAccount,
    HumanAuthorizationError,
    PortalPermission,
    PortalRole,
    ScryptPasswordHasher,
)


class HumanAdministrationError(FiscalDomainError):
    """Base error for governed human-account administration."""


class HumanAdministrationConflictError(HumanAdministrationError):
    """Raised when durable account state or command ordering conflicts."""


class HumanAdministrationNotFoundError(HumanAdministrationError):
    """Raised without revealing cross-tenant account existence."""


@dataclass(frozen=True, slots=True)
class HumanAdministrationResult:
    account: HumanAccount
    created: bool
    replay: bool


@runtime_checkable
class HumanAdministrationStore(Protocol):
    def by_email(self, email: str) -> HumanAccount | None: ...

    def by_id(self, account_id: str) -> HumanAccount | None: ...

    def list_for_tenant(self, tenant_id: str) -> tuple[HumanAccount, ...]: ...

    def command_target(
        self, tenant_id: str, correlation_id: str
    ) -> tuple[str, str] | None: ...

    def create(
        self,
        account: HumanAccount,
        *,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> HumanAccount: ...

    def update(
        self,
        account: HumanAccount,
        *,
        expected_session_epoch: int,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> HumanAccount: ...


class InMemoryHumanAdministrationStore:
    """Reference store for policy tests; PostgreSQL is the durable runtime adapter."""

    def __init__(self, accounts: tuple[HumanAccount, ...] = ()) -> None:
        self._lock = Lock()
        self._by_id = {account.account_id: account for account in accounts}
        self._email_to_id = {account.email: account.account_id for account in accounts}
        self._commands: dict[tuple[str, str], tuple[str, str]] = {}

    def by_email(self, email: str) -> HumanAccount | None:
        with self._lock:
            account_id = self._email_to_id.get(email.strip().casefold())
            return None if account_id is None else self._by_id.get(account_id)

    def by_id(self, account_id: str) -> HumanAccount | None:
        with self._lock:
            return self._by_id.get(account_id.strip())

    def list_for_tenant(self, tenant_id: str) -> tuple[HumanAccount, ...]:
        normalized = tenant_id.strip()
        with self._lock:
            return tuple(
                sorted(
                    (
                        account
                        for account in self._by_id.values()
                        if account.tenant_id == normalized
                    ),
                    key=lambda account: (account.email, account.account_id),
                )
            )

    def save(self, account: HumanAccount) -> None:
        """Also satisfy HumanAccountRepository for shared in-memory integration tests."""

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

    def _claim_command(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        action: str,
        target_id: str,
    ) -> None:
        key = (tenant_id, correlation_id)
        prior = self._commands.get(key)
        if prior is not None:
            raise HumanAdministrationConflictError("idempotency key was already used")
        self._commands[key] = (action, target_id)

    def command_target(
        self, tenant_id: str, correlation_id: str
    ) -> tuple[str, str] | None:
        with self._lock:
            return self._commands.get((tenant_id.strip(), correlation_id.strip()))

    def create(
        self,
        account: HumanAccount,
        *,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> HumanAccount:
        del actor_id, occurred_at
        with self._lock:
            if account.account_id in self._by_id or account.email in self._email_to_id:
                raise HumanAdministrationConflictError("human account already exists")
            self._claim_command(
                tenant_id=account.tenant_id,
                correlation_id=correlation_id,
                action="human_account.created",
                target_id=account.account_id,
            )
            self._by_id[account.account_id] = account
            self._email_to_id[account.email] = account.account_id
            return account

    def update(
        self,
        account: HumanAccount,
        *,
        expected_session_epoch: int,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> HumanAccount:
        del actor_id, occurred_at
        with self._lock:
            current = self._by_id.get(account.account_id)
            if current is None or current.tenant_id != account.tenant_id:
                raise HumanAdministrationNotFoundError("human account was not found")
            if current.session_epoch != expected_session_epoch:
                raise HumanAdministrationConflictError("human account version changed")
            if current.role is PortalRole.OWNER and current.enabled and (
                account.role is not PortalRole.OWNER or not account.enabled
            ):
                other_owner = any(
                    candidate.account_id != current.account_id
                    and candidate.tenant_id == current.tenant_id
                    and candidate.role is PortalRole.OWNER
                    and candidate.enabled
                    for candidate in self._by_id.values()
                )
                if not other_owner:
                    raise HumanAdministrationConflictError(
                        "tenant must retain at least one enabled owner"
                    )
            self._claim_command(
                tenant_id=account.tenant_id,
                correlation_id=correlation_id,
                action="human_account.updated",
                target_id=account.account_id,
            )
            self._by_id[account.account_id] = account
            return account


class HumanAdministrationService:
    """Manage tenant humans without widening the authenticated actor's authority."""

    def __init__(
        self,
        *,
        store: HumanAdministrationStore,
        password_hasher: ScryptPasswordHasher,
    ) -> None:
        if not isinstance(store, HumanAdministrationStore):
            raise ValueError("store must implement HumanAdministrationStore")
        self._store = store
        self._password_hasher = password_hasher

    @staticmethod
    def _actor_id(authority: AuthenticatedHuman) -> str:
        digest = hashlib.sha256(authority.account.account_id.encode("utf-8")).hexdigest()
        return f"human-{digest[:24]}"

    @staticmethod
    def _correlation(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("Idempotency-Key is required and must be at most 256 characters")
        return normalized

    @staticmethod
    def _email(value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized or len(normalized) > 320 or "@" not in normalized:
            raise ValueError("email is invalid")
        return normalized

    @staticmethod
    def _role(value: str | PortalRole) -> PortalRole:
        try:
            return value if isinstance(value, PortalRole) else PortalRole(value.strip().lower())
        except (ValueError, AttributeError) as exc:
            raise ValueError("target_role is invalid") from exc

    @staticmethod
    def _unit_ids(value: object) -> frozenset[str] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("target_unit_ids must be a list or null")
        normalized = frozenset(str(item).strip() for item in value)
        if not normalized or any(not item or len(item) > 128 for item in normalized):
            raise ValueError("target_unit_ids must contain non-empty unit identifiers")
        return normalized

    @staticmethod
    def _assert_manage_permission(authority: AuthenticatedHuman) -> None:
        authority.assert_permission(PortalPermission.USER_MANAGE)

    @staticmethod
    def _role_within_actor(authority: AuthenticatedHuman, role: PortalRole) -> bool:
        """Apply the owner-approved T04 role-delegation policy explicitly.

        OWNER may administer all tenant roles. ADMIN may administer only
        OPERATOR, AUDITOR and BILLING. No tenant role can grant platform_admin.
        """

        if authority.account.role is PortalRole.OWNER:
            return True
        if authority.account.role is PortalRole.ADMIN:
            return role in {
                PortalRole.OPERATOR,
                PortalRole.AUDITOR,
                PortalRole.BILLING,
            }
        return False

    @staticmethod
    def _scope_within_actor(
        authority: AuthenticatedHuman,
        target_units: frozenset[str] | None,
    ) -> bool:
        actor_units = authority.account.unit_ids
        if actor_units is None:
            return True
        return target_units is not None and target_units <= actor_units

    def _assert_assignable(
        self,
        authority: AuthenticatedHuman,
        *,
        role: PortalRole,
        unit_ids: frozenset[str] | None,
        known_unit_ids: frozenset[str],
    ) -> None:
        if not self._role_within_actor(authority, role):
            raise HumanAuthorizationError("role would grant authority the actor does not hold")
        if role is PortalRole.ACCOUNTANT and unit_ids is None:
            raise HumanAuthorizationError("accountant requires explicitly assigned units")
        if not self._scope_within_actor(authority, unit_ids):
            raise HumanAuthorizationError("unit scope would exceed the actor scope")
        if unit_ids is not None and not unit_ids <= known_unit_ids:
            raise HumanAuthorizationError("unit scope contains an unavailable unit")

    def _visible(self, authority: AuthenticatedHuman, account: HumanAccount) -> bool:
        if account.tenant_id != authority.tenant_id:
            return False
        if account.account_id == authority.account.account_id:
            return True
        return self._scope_within_actor(authority, account.unit_ids) and self._role_within_actor(
            authority, account.role
        )

    def _mutable(self, authority: AuthenticatedHuman, account: HumanAccount) -> bool:
        return (
            account.account_id != authority.account.account_id
            and not account.platform_admin
            and self._visible(authority, account)
        )

    def list_users(self, *, authority: AuthenticatedHuman) -> tuple[dict[str, object], ...]:
        self._assert_manage_permission(authority)
        rows: list[dict[str, object]] = []
        for account in self._store.list_for_tenant(authority.tenant_id):
            if not self._visible(authority, account):
                continue
            rows.append(
                {
                    "account_id": account.account_id,
                    "email": account.email,
                    "role": account.role.value,
                    "unit_ids": (
                        None if account.unit_ids is None else sorted(account.unit_ids)
                    ),
                    "enabled": account.enabled,
                    "platform_admin": account.platform_admin,
                    "version": account.session_epoch,
                    "mutable": self._mutable(authority, account),
                    "activation": "password_recovery",
                }
            )
        return tuple(rows)

    def create_user(
        self,
        *,
        authority: AuthenticatedHuman,
        email: str,
        target_role: str | PortalRole,
        target_unit_ids: object,
        known_unit_ids: frozenset[str],
        idempotency_key: str,
        now: datetime | None = None,
    ) -> HumanAdministrationResult:
        self._assert_manage_permission(authority)
        normalized_email = self._email(email)
        role = self._role(target_role)
        units = self._unit_ids(target_unit_ids)
        self._assert_assignable(
            authority,
            role=role,
            unit_ids=units,
            known_unit_ids=known_unit_ids,
        )
        correlation_id = self._correlation(idempotency_key)
        account_id = "tenant-user-" + hashlib.sha256(
            f"{authority.tenant_id}|{normalized_email}".encode()
        ).hexdigest()[:32]

        existing = self._store.by_email(normalized_email)
        if existing is not None:
            exact = (
                existing.account_id == account_id
                and existing.tenant_id == authority.tenant_id
                and existing.role is role
                and existing.unit_ids == units
                and existing.enabled
                and not existing.platform_admin
            )
            if exact and self._store.command_target(
                authority.tenant_id, correlation_id
            ) == ("human_account.created", account_id):
                return HumanAdministrationResult(existing, created=False, replay=True)
            raise HumanAdministrationConflictError("email is unavailable")

        initial_password = secrets.token_urlsafe(48)
        account = HumanAccount(
            account_id=account_id,
            email=normalized_email,
            password_hash=self._password_hasher.hash(initial_password),
            tenant_id=authority.tenant_id,
            role=role,
            unit_ids=units,
            platform_admin=False,
            enabled=True,
            session_epoch=0,
        )
        created = self._store.create(
            account,
            actor_id=self._actor_id(authority),
            correlation_id=correlation_id,
            occurred_at=now or datetime.now(UTC),
        )
        return HumanAdministrationResult(created, created=True, replay=False)

    def update_user(
        self,
        *,
        authority: AuthenticatedHuman,
        target_account_id: str,
        expected_version: int,
        target_role: str | PortalRole,
        target_unit_ids: object,
        enabled: bool,
        known_unit_ids: frozenset[str],
        idempotency_key: str,
        now: datetime | None = None,
    ) -> HumanAdministrationResult:
        self._assert_manage_permission(authority)
        account_id = target_account_id.strip()
        if not account_id or len(account_id) > 128:
            raise ValueError("target_account_id is invalid")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be bool")
        correlation_id = self._correlation(idempotency_key)
        target = self._store.by_id(account_id)
        if target is None or target.tenant_id != authority.tenant_id:
            raise HumanAdministrationNotFoundError("human account was not found")
        if target.platform_admin:
            raise HumanAuthorizationError("platform authority cannot be changed by tenant admin")
        if target.account_id == authority.account.account_id:
            raise HumanAuthorizationError("self-administration is not allowed")

        if not self._visible(authority, target):
            raise HumanAuthorizationError("target account exceeds the actor authority")
        role = self._role(target_role)
        units = self._unit_ids(target_unit_ids)
        self._assert_assignable(
            authority,
            role=role,
            unit_ids=units,
            known_unit_ids=known_unit_ids,
        )

        desired_matches = (
            target.role is role and target.unit_ids == units and target.enabled is enabled
        )
        if desired_matches:
            if expected_version == target.session_epoch:
                return HumanAdministrationResult(target, created=False, replay=False)
            if (
                target.session_epoch > 0
                and expected_version == target.session_epoch - 1
                and self._store.command_target(authority.tenant_id, correlation_id)
                == ("human_account.updated", target.account_id)
            ):
                return HumanAdministrationResult(target, created=False, replay=True)
            raise HumanAdministrationConflictError("human account version changed")
        if expected_version != target.session_epoch:
            raise HumanAdministrationConflictError("human account version changed")

        updated = replace(
            target,
            role=role,
            unit_ids=units,
            enabled=enabled,
            session_epoch=target.session_epoch + 1,
        )
        persisted = self._store.update(
            updated,
            expected_session_epoch=target.session_epoch,
            actor_id=self._actor_id(authority),
            correlation_id=correlation_id,
            occurred_at=now or datetime.now(UTC),
        )
        return HumanAdministrationResult(persisted, created=False, replay=False)
