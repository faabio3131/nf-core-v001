from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kordena_fiscal.security.human_administration import (
    HumanAdministrationConflictError,
    HumanAdministrationNotFoundError,
    HumanAdministrationService,
    InMemoryHumanAdministrationStore,
)
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAccount,
    HumanAuthorizationError,
    PortalRole,
    ScryptPasswordHasher,
)

NOW = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
KNOWN_UNITS = frozenset({"unit-a", "unit-b"})


def account(
    name: str,
    role: PortalRole,
    *,
    tenant: str = "tenant-a",
    units: frozenset[str] | None = None,
    platform_admin: bool = False,
    enabled: bool = True,
    version: int = 0,
) -> HumanAccount:
    return HumanAccount(
        account_id="account-" + name,
        email=name + "@example.com",
        password_hash="synthetic-password-hash",
        tenant_id=tenant,
        role=role,
        unit_ids=units,
        platform_admin=platform_admin,
        enabled=enabled,
        session_epoch=version,
    )


def authority(value: HumanAccount) -> AuthenticatedHuman:
    return AuthenticatedHuman(
        account=value,
        session_id="session-" + value.account_id,
        csrf_token_sha256="0" * 64,
        expires_at=NOW + timedelta(hours=1),
    )


def service(*accounts: HumanAccount) -> HumanAdministrationService:
    return HumanAdministrationService(
        store=InMemoryHumanAdministrationStore(tuple(accounts)),
        password_hasher=ScryptPasswordHasher(),
    )


def test_owner_can_create_declared_roles_without_granting_platform_authority() -> None:
    owner = account("owner", PortalRole.OWNER)
    users = service(owner)

    for index, role in enumerate(PortalRole):
        created = users.create_user(
            authority=authority(owner),
            email=f"user-{index}@example.com",
            target_role=role,
            target_unit_ids=["unit-a"],
            known_unit_ids=KNOWN_UNITS,
            idempotency_key=f"create-{index}",
            now=NOW,
        )
        assert created.created and not created.replay
        assert created.account.role is role
        assert created.account.platform_admin is False
        assert created.account.unit_ids == frozenset({"unit-a"})
        assert created.account.password_hash
        assert "user-" not in created.account.password_hash

    rows = users.list_users(authority=authority(owner))
    assert {row["role"] for row in rows} >= {role.value for role in PortalRole}
    assert all("password" not in row for row in rows)


def test_owner_cannot_create_accountant_without_explicit_units() -> None:
    owner = account("owner", PortalRole.OWNER)
    with pytest.raises(HumanAuthorizationError):
        service(owner).create_user(
            authority=authority(owner), email="accountant@example.com",
            target_role=PortalRole.ACCOUNTANT, target_unit_ids=None,
            known_unit_ids=KNOWN_UNITS, idempotency_key="accountant-all", now=NOW,
        )


def test_admin_cannot_grant_permissions_or_unit_scope_it_does_not_hold() -> None:
    admin = account("admin", PortalRole.ADMIN, units=frozenset({"unit-a"}))
    users = service(admin)

    for forbidden_role in (PortalRole.OWNER, PortalRole.ADMIN, PortalRole.ACCOUNTANT):
        with pytest.raises(HumanAuthorizationError):
            users.create_user(
                authority=authority(admin),
                email=forbidden_role.value + "@example.com",
                target_role=forbidden_role,
                target_unit_ids=["unit-a"],
                known_unit_ids=KNOWN_UNITS,
                idempotency_key="forbidden-" + forbidden_role.value,
                now=NOW,
            )

    with pytest.raises(HumanAuthorizationError):
        users.create_user(
            authority=authority(admin),
            email="all-units@example.com",
            target_role=PortalRole.OPERATOR,
            target_unit_ids=None,
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="all-units",
            now=NOW,
        )
    with pytest.raises(HumanAuthorizationError):
        users.create_user(
            authority=authority(admin),
            email="other-unit@example.com",
            target_role=PortalRole.OPERATOR,
            target_unit_ids=["unit-b"],
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="other-unit",
            now=NOW,
        )

    for allowed_role in (PortalRole.OPERATOR, PortalRole.AUDITOR, PortalRole.BILLING):
        allowed = users.create_user(
            authority=authority(admin),
            email=allowed_role.value + "-allowed@example.com",
            target_role=allowed_role,
            target_unit_ids=["unit-a"],
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="allowed-" + allowed_role.value,
            now=NOW,
        )
        assert allowed.account.role is allowed_role


@pytest.mark.parametrize("role", [
    PortalRole.OPERATOR, PortalRole.AUDITOR, PortalRole.BILLING, PortalRole.ACCOUNTANT,
])
def test_non_manager_roles_fail_closed(role: PortalRole) -> None:
    actor = account(role.value, role)
    users = service(actor)
    with pytest.raises(HumanAuthorizationError):
        users.list_users(authority=authority(actor))


def test_platform_admin_and_self_are_read_only_from_tenant_user_administration() -> None:
    owner = account("owner", PortalRole.OWNER)
    platform = account("platform", PortalRole.OWNER, platform_admin=True)
    users = service(owner, platform)

    rows = {row["account_id"]: row for row in users.list_users(authority=authority(owner))}
    assert rows[platform.account_id]["platform_admin"] is True
    assert rows[platform.account_id]["mutable"] is False
    assert rows[owner.account_id]["mutable"] is False

    with pytest.raises(HumanAuthorizationError):
        users.update_user(
            authority=authority(owner),
            target_account_id=platform.account_id,
            expected_version=0,
            target_role=PortalRole.OPERATOR,
            target_unit_ids=["unit-a"],
            enabled=True,
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="touch-platform",
            now=NOW,
        )
    with pytest.raises(HumanAuthorizationError):
        users.update_user(
            authority=authority(owner),
            target_account_id=owner.account_id,
            expected_version=0,
            target_role=PortalRole.OWNER,
            target_unit_ids=None,
            enabled=True,
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="touch-self",
            now=NOW,
        )


def test_update_is_versioned_replay_safe_and_reused_key_cannot_target_another_user() -> None:
    owner = account("owner", PortalRole.OWNER)
    target = account("target", PortalRole.OPERATOR, units=frozenset({"unit-a"}))
    users = service(owner, target)

    updated = users.update_user(
        authority=authority(owner),
        target_account_id=target.account_id,
        expected_version=0,
        target_role=PortalRole.AUDITOR,
        target_unit_ids=["unit-a"],
        enabled=True,
        known_unit_ids=KNOWN_UNITS,
        idempotency_key="update-one",
        now=NOW,
    )
    assert updated.account.session_epoch == 1
    assert updated.account.role is PortalRole.AUDITOR

    replay = users.update_user(
        authority=authority(owner),
        target_account_id=target.account_id,
        expected_version=0,
        target_role=PortalRole.AUDITOR,
        target_unit_ids=["unit-a"],
        enabled=True,
        known_unit_ids=KNOWN_UNITS,
        idempotency_key="update-one",
        now=NOW,
    )
    assert replay.replay
    assert replay.account.session_epoch == 1

    with pytest.raises(HumanAdministrationConflictError):
        users.create_user(
            authority=authority(owner),
            email="different@example.com",
            target_role=PortalRole.OPERATOR,
            target_unit_ids=["unit-a"],
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="update-one",
            now=NOW,
        )


def test_cross_tenant_target_is_not_disclosed_and_restricted_admin_lists_only_covered_users(
) -> None:
    admin = account("admin", PortalRole.ADMIN, units=frozenset({"unit-a"}))
    local = account("local", PortalRole.OPERATOR, units=frozenset({"unit-a"}))
    broad = account("broad", PortalRole.OPERATOR, units=None)
    owner = account("other-owner", PortalRole.OWNER, units=frozenset({"unit-a"}))
    foreign = account(
        "foreign",
        PortalRole.OPERATOR,
        tenant="tenant-b",
        units=frozenset({"unit-a"}),
    )
    users = service(admin, local, broad, owner, foreign)

    rows = users.list_users(authority=authority(admin))
    assert {row["account_id"] for row in rows} == {admin.account_id, local.account_id}

    with pytest.raises(HumanAdministrationNotFoundError):
        users.update_user(
            authority=authority(admin),
            target_account_id=foreign.account_id,
            expected_version=0,
            target_role=PortalRole.OPERATOR,
            target_unit_ids=["unit-a"],
            enabled=True,
            known_unit_ids=KNOWN_UNITS,
            idempotency_key="cross-tenant",
            now=NOW,
        )
