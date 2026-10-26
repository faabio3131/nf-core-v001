"""One-time, operator-approved initial platform admin bootstrap in production.

Uses the canonical commercial tenant/owner provisioning and password recovery.
No incoming password, direct application SQL, new identity authority or web signup.
Production data is not touched by importing/testing this module.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.runtime.activation_email import build_activation_delivery_from_mapping
from kordena_fiscal.runtime.commercial_provisioning import (
    CommercialCustomerProvisioningService,
)
from kordena_fiscal.runtime.composition import build_postgres_runtime_composition
from kordena_fiscal.security.human_identity import PortalRole


class FirstPlatformAdminBootstrapDenied(RuntimeError):
    """No authority to bootstrap the first production platform administrator."""


def require_approval(source: Mapping[str, str]) -> str:
    """Three exact, independent human/environment authorization gates."""
    if (
        source.get("NFCORE_ENVIRONMENT") != "production"
        or source.get("NFCORE_PRODUCTION_APPROVAL") != "PRODUCTION_APPROVED"
        or source.get("NFCORE_FIRST_PLATFORM_ADMIN_BOOTSTRAP") != "APPROVED_ONCE"
    ):
        raise FirstPlatformAdminBootstrapDenied("production first admin bootstrap denied")
    dsn = source.get("DATABASE_URL", "").strip()
    if not dsn or not dsn.startswith(("postgresql://", "postgres://")):
        raise FirstPlatformAdminBootstrapDenied("approved PostgreSQL target required")
    return dsn


def run(
    *,
    email: str,
    tenant_id: str,
    legal_name: str,
    environ: Mapping[str, str] | None = None,
    database_factory: Callable[[str], PostgresFiscalDatabase] = PostgresFiscalDatabase,
) -> str:
    """Bootstrap exactly once; admin elevation and audit commit atomically.

    The pre-existing commercial provisioner commits organization/owner/recovery as
    certified. A failure before privilege elevation may leave a non-admin owner;
    an identical approved invocation can safely resume, but an existing platform
    administrator blocks ALL reexecution. Delivery failure after commit must
    be recovered via the existing password-reset flow, never by new elevation.
    """
    source = os.environ if environ is None else environ
    dsn = require_approval(source)
    owner_email = email.strip().casefold()
    platform_tenant = tenant_id.strip().lower()
    org_name = legal_name.strip()
    if owner_email.count("@") != 1 or not platform_tenant or not org_name or len(owner_email) > 254:
        raise FirstPlatformAdminBootstrapDenied("bootstrap identity parameters invalid")
    if source.get("NFCORE_FIRST_PLATFORM_ADMIN_EMAIL", "").strip().casefold() != owner_email:
        raise FirstPlatformAdminBootstrapDenied("bootstrap email does not match approval")
    # A missing/broken Brevo configuration is a blocker before any persisted write.
    delivery = build_activation_delivery_from_mapping(source)
    if delivery is None:
        raise FirstPlatformAdminBootstrapDenied("activation email delivery required")

    database = database_factory(dsn)
    try:
        database.require_current_schema()
        composition = build_postgres_runtime_composition(database)
        account_id = CommercialCustomerProvisioningService._account_id(platform_tenant, owner_email)
        with database.first_platform_admin_bootstrap_guard(
            account_id=account_id, email=owner_email
        ):
            now = datetime.now(UTC)
            result = composition.commercial_provisioning.provision(
                tenant_id=platform_tenant,
                legal_name=org_name,
                owner_email=owner_email,
                correlation_id="production-first-platform-admin",
                now=now,
            )
            account = database.human_accounts().by_id(result.account_id)
            if (
                account is None
                or account.account_id != account_id
                or account.tenant_id != platform_tenant
                or account.role is not PortalRole.OWNER
                or not account.enabled
                or account.platform_admin
            ):
                raise FirstPlatformAdminBootstrapDenied("bootstrap owner unavailable")
            reset = result.activation_reset
            if reset is None:
                reset = composition.password_recovery.request_reset(email=owner_email, now=now)
            if reset is None:
                raise FirstPlatformAdminBootstrapDenied("bootstrap activation unavailable")
            # This canonical persistence operation commits elevation + audit together.
            database.promote_first_platform_admin(
                account_id=account_id,
                email=owner_email,
                tenant_id=platform_tenant,
                now=now,
            )
            # External side effect after commit; no secret/token in log or stdout.
            delivery.deliver(email=owner_email, reset=reset)
            return account_id
    finally:
        database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time approved production admin bootstrap")
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--legal-name", required=True)
    args = parser.parse_args()
    account_id = run(
        email=args.email,
        tenant_id=args.tenant_id,
        legal_name=args.legal_name,
    )
    print(f"production first platform administrator provisioned: account_id={account_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
