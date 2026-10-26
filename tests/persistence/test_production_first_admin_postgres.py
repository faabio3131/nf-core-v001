"""Real ephemeral PostgreSQL certification of first-admin creation and audit."""

from __future__ import annotations

import os

import psycopg
import pytest

from kordena_fiscal.control_plane.models import ControlPlaneAuditAction
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime import production_first_admin as bootstrap
from kordena_fiscal.runtime.commercial_provisioning import CommercialCustomerProvisioningService

MAIL = "platform-bootstrap@nfcore.example"
TENANT = "fm-platform"
DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"


def test_first_admin_bootstrap_real_postgres_is_audited_and_one_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = os.environ.get(DSN_ENV, "").strip()
    if not dsn:
        pytest.skip(f"{DSN_ENV} not configured for integration certification")
    with psycopg.connect(dsn, autocommit=True) as raw:
        raw.execute("DROP SCHEMA public CASCADE")
        raw.execute("CREATE SCHEMA public")
    db = PostgresFiscalDatabase(dsn)
    try:
        assert db.initialize() == tuple(range(1, 19))
    finally:
        db.close()

    class Delivery:
        def __init__(self) -> None:
            self.called = 0

        def deliver(self, *, email: str, reset: object) -> None:
            assert email == MAIL
            assert reset is not None
            self.called += 1

    delivery = Delivery()
    monkeypatch.setattr(bootstrap, "build_activation_delivery_from_mapping", lambda _env: delivery)
    environ = {
        "DATABASE_URL": dsn,
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_PRODUCTION_APPROVAL": "PRODUCTION_APPROVED",
        "NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP": "APPROVED_ONCE",
        "NFCORE_FIRST_PLATFORM_ADMIN_EMAIL": MAIL,
    }
    result = bootstrap.run(
        email=MAIL,
        tenant_id=TENANT,
        legal_name="FM Platform Control",
        environ=environ,
    )
    assert result == CommercialCustomerProvisioningService._account_id(TENANT, MAIL)
    assert delivery.called == 1
    verified = PostgresFiscalDatabase(dsn)
    try:
        owner = verified.human_accounts().by_id(result)
        assert owner is not None
        assert owner.platform_admin
        assert owner.tenant_id == TENANT
        with verified() as uow:
            events = uow.control_plane.list_audit(TENANT)
            organization = uow.control_plane.get_organization(TENANT)
        assert organization is not None
        assert any(
            e.action is ControlPlaneAuditAction.HUMAN_ACCOUNT_UPDATED
            and e.actor_id == "production-bootstrap"
            and e.target_id == result
            for e in events
        )
        with pytest.raises(Exception, match="bootstrap denied"):
            bootstrap.run(
                email=MAIL,
                tenant_id=TENANT,
                legal_name="FM Platform Control",
                environ=environ,
            )
        assert delivery.called == 1
    finally:
        verified.close()
