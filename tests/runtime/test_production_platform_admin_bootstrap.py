"""One-time production administration: strict gates and safe reexecution."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from kordena_fiscal.runtime import production_first_admin as bootstrap
from kordena_fiscal.runtime.commercial_provisioning import CommercialCustomerProvisioningService
from kordena_fiscal.security.human_identity import PortalRole

MAIL = "primary-admin@nfcore.example"


def approved() -> dict[str, str]:
    return {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_PRODUCTION_APPROVAL": "PRODUCTION_APPROVED",
        "NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP": "APPROVED_ONCE",
        "NFCORE_FIRST_PLATFORM_ADMIN_EMAIL": MAIL,
        "DATABASE_URL": "postgresql://placeholder-only/nfcore",
        "NFCORE_ACTIVATION_EMAIL_PROVIDER": "brevo",
    }


class FakeDelivery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def deliver(self, *, email: str, reset: object) -> None:
        self.calls.append((email, reset))


class FakeDb:
    def __init__(self) -> None:
        self.admin = False
        self.closed = False
        self.owner: object | None = None
        self.promotions = 0
        self.guards = 0

    def require_current_schema(self) -> tuple[int, ...]:
        return tuple(range(1, 19))

    @contextmanager
    def first_platform_admin_bootstrap_guard(self, *, account_id: str, email: str):
        self.guards += 1
        if self.admin:
            raise RuntimeError("first platform admin bootstrap denied")
        yield

    def human_accounts(self):
        return SimpleNamespace(by_id=lambda _id: self.owner)

    def promote_first_platform_admin(self, **kwargs: object) -> None:
        assert not self.admin
        assert kwargs["account_id"] == CommercialCustomerProvisioningService._account_id(
            "fm-platform", MAIL
        )
        self.admin = True
        self.promotions += 1

    def close(self) -> None:
        self.closed = True


class FakeProvision:
    def __init__(self, db: FakeDb) -> None:
        self.db = db
        self.calls = 0

    def provision(self, **kwargs: object):
        self.calls += 1
        assert kwargs["owner_email"] == MAIL
        assert kwargs["tenant_id"] == "fm-platform"
        account_id = CommercialCustomerProvisioningService._account_id("fm-platform", MAIL)
        self.db.owner = SimpleNamespace(
            account_id=account_id,
            tenant_id="fm-platform",
            role=PortalRole.OWNER,
            enabled=True,
            platform_admin=False,
        )
        return SimpleNamespace(
            account_id=account_id, activation_reset=SimpleNamespace(reset_token="<ephemeral>")
        )


def _patch(monkeypatch: pytest.MonkeyPatch, db: FakeDb, delivery: FakeDelivery):
    provisioning = FakeProvision(db)
    composition = SimpleNamespace(
        commercial_provisioning=provisioning,
        password_recovery=SimpleNamespace(request_reset=lambda **_: None),
    )
    monkeypatch.setattr(bootstrap, "build_postgres_runtime_composition", lambda _db: composition)
    monkeypatch.setattr(bootstrap, "build_activation_delivery_from_mapping", lambda _: delivery)
    return provisioning


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("NFCORE_ENVIRONMENT", "staging"),
        ("NFCORE_ENVIRONMENT", ""),
        ("NFCORE_PRODUCTION_APPROVAL", "pending"),
        ("NFCORE_PRODUCTION_APPROVAL", ""),
        ("NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP", "true"),
        ("NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP", ""),
        ("NFCORE_FIRST_PLATFORM_ADMIN_EMAIL", "attacker@nfcore.example"),
        ("DATABASE_URL", "sqlite:///tmp/not-allowed"),
    ],
)
def test_bootstrap_rejects_wrong_gate_before_database_open(
    monkeypatch: pytest.MonkeyPatch, field: str, invalid: str
) -> None:
    source = approved()
    source[field] = invalid

    def forbidden(_dsn: str):
        pytest.fail("database must not open")

    with pytest.raises(bootstrap.FirstPlatformAdminBootstrapDenied):
        bootstrap.run(
            email=MAIL,
            tenant_id="fm-platform",
            legal_name="FM Tecnologia",
            environ=source,
            database_factory=forbidden,
        )


def test_bootstrap_rejects_missing_delivery_before_database_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = approved()
    monkeypatch.setattr(bootstrap, "build_activation_delivery_from_mapping", lambda _: None)
    with pytest.raises(bootstrap.FirstPlatformAdminBootstrapDenied):
        bootstrap.run(
            email=MAIL,
            tenant_id="fm-platform",
            legal_name="FM Tecnologia",
            environ=source,
            database_factory=lambda _: pytest.fail("database opened"),
        )


def test_bootstrap_uses_provisioning_recovery_grant_and_single_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, delivery = FakeDb(), FakeDelivery()
    provisioning = _patch(monkeypatch, db, delivery)
    actual = bootstrap.run(
        email=MAIL,
        tenant_id="fm-platform",
        legal_name="FM Tecnologia",
        environ=approved(),
        database_factory=lambda _: db,
    )
    assert actual.startswith("commercial-owner-")
    assert db.admin and db.promotions == 1 and db.closed
    assert provisioning.calls == 1
    assert len(delivery.calls) == 1 and delivery.calls[0][0] == MAIL


def test_reexecution_refused_before_provisioning_or_new_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, delivery = FakeDb(), FakeDelivery()
    provisioning = _patch(monkeypatch, db, delivery)
    for run_number in (1, 2):
        if run_number == 2:
            with pytest.raises(RuntimeError, match="bootstrap denied"):
                bootstrap.run(
                    email=MAIL,
                    tenant_id="fm-platform",
                    legal_name="FM Tecnologia",
                    environ=approved(),
                    database_factory=lambda _: db,
                )
        else:
            bootstrap.run(
                email=MAIL,
                tenant_id="fm-platform",
                legal_name="FM Tecnologia",
                environ=approved(),
                database_factory=lambda _: db,
            )
    assert provisioning.calls == 1
    assert db.promotions == 1 and len(delivery.calls) == 1


def test_denies_invalid_owner_or_missing_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, delivery = FakeDb(), FakeDelivery()
    provisioning = _patch(monkeypatch, db, delivery)
    original = provisioning.provision

    def malformed(**kwargs: object):
        record = original(**kwargs)
        db.owner.platform_admin = True
        return record

    provisioning.provision = malformed  # type: ignore[method-assign]
    with pytest.raises(bootstrap.FirstPlatformAdminBootstrapDenied):
        bootstrap.run(
            email=MAIL,
            tenant_id="fm-platform",
            legal_name="FM Tecnologia",
            environ=approved(),
            database_factory=lambda _: db,
        )
    assert db.promotions == 0 and not delivery.calls


def test_no_password_input_is_exposed_by_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bootstrap_production_platform_admin",
            "--email",
            MAIL,
            "--tenant-id",
            "fm-platform",
            "--legal-name",
            "FM Tecnologia",
            "--password",
            "never-allowed",
        ],
    )
    with pytest.raises(SystemExit) as rejected:
        bootstrap.main()
    assert rejected.value.code == 2
