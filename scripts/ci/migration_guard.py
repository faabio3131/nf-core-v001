"""Govern schema migration execution for staging and production runtimes."""

from __future__ import annotations

import argparse
import hashlib
import os
import re

from kordena_fiscal.persistence.cakto import (
    CAKTO_SCHEMA_NAME,
    CAKTO_SCHEMA_STATEMENTS,
    CAKTO_SCHEMA_VERSION,
    postgres_cakto_commercial_database,
)
from kordena_fiscal.persistence.cognitive_quota_schema import (
    COGNITIVE_QUOTA_NAME,
    COGNITIVE_QUOTA_SCHEMA,
    COGNITIVE_QUOTA_VERSION,
)
from kordena_fiscal.persistence.command_commercial_schema import (
    COMMAND_COMMERCIAL_NAME,
    COMMAND_COMMERCIAL_SCHEMA,
    COMMAND_COMMERCIAL_VERSION,
)
from kordena_fiscal.persistence.commercial_period_schema import (
    COMMERCIAL_PERIOD_NAME,
    COMMERCIAL_PERIOD_SCHEMA,
    COMMERCIAL_PERIOD_VERSION,
)
from kordena_fiscal.persistence.customer_configuration_schema import (
    CUSTOMER_CONFIGURATION_NAME,
    CUSTOMER_CONFIGURATION_SCHEMA,
    CUSTOMER_CONFIGURATION_VERSION,
)
from kordena_fiscal.persistence.fiscal_scope_schema import (
    FISCAL_SCOPE_NAME,
    FISCAL_SCOPE_SCHEMA,
    FISCAL_SCOPE_VERSION,
)
from kordena_fiscal.persistence.postgres import (
    _COMMERCIAL_ACQUISITION_SCHEMA,
    _COMMERCIAL_CLAIM_SCHEMA,
    _COMMERCIAL_FULFILLMENT_SCHEMA,
    _COMMERCIAL_LIFECYCLE_SCHEMA,
    _COMMERCIAL_RELEASE_SCHEMA,
    _PRICING_SCHEMA,
    PostgresFiscalDatabase,
)
from kordena_fiscal.persistence.public_trial_rate_schema import (
    PUBLIC_TRIAL_RATE_NAME,
    PUBLIC_TRIAL_RATE_SCHEMA,
    PUBLIC_TRIAL_RATE_VERSION,
)
from kordena_fiscal.persistence.secret_binding_schema import (
    SECRET_BINDING_NAME,
    SECRET_BINDING_SCHEMA,
    SECRET_BINDING_VERSION,
)
from kordena_fiscal.persistence.sqlite import _MIGRATIONS

_DESTRUCTIVE = re.compile(
    r"\b(?:DROP\s+(?:TABLE|SCHEMA|DATABASE|COLUMN)|TRUNCATE|DELETE\s+FROM)\b",
    re.IGNORECASE,
)
# Migration 5 predates WP-WEB-09 and was already certified. Its destructive step is
# fingerprint-pinned so changing it, or adding any new destructive migration, fails closed.
_APPROVED_LEGACY_DESTRUCTIVE = {
    (
        5,
        "51652667759562a46b810dde224253444c5dc93916a601dc36205d3f4a8441d5",
    ),
}


def _statement_fingerprint(statement: str) -> str:
    normalized = " ".join(statement.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _reject_unapproved_destructive(
    *,
    version: int,
    name: str,
    statements: tuple[str, ...],
) -> None:
    for statement in statements:
        if not _DESTRUCTIVE.search(statement):
            continue
        fingerprint = _statement_fingerprint(statement)
        if (version, fingerprint) not in _APPROVED_LEGACY_DESTRUCTIVE:
            raise RuntimeError(f"destructive migration blocked: version={version} name={name}")


def validate_policy() -> tuple[int, ...]:
    versions = tuple(migration.version for migration in _MIGRATIONS) + (
        PostgresFiscalDatabase.HUMAN_MIGRATION_VERSION,
        PostgresFiscalDatabase.PRICING_MIGRATION_VERSION,
        PostgresFiscalDatabase.COMMERCIAL_RELEASE_MIGRATION_VERSION,
        PostgresFiscalDatabase.COMMERCIAL_FULFILLMENT_MIGRATION_VERSION,
        PostgresFiscalDatabase.COMMERCIAL_CLAIM_MIGRATION_VERSION,
        PostgresFiscalDatabase.COMMERCIAL_ACQUISITION_MIGRATION_VERSION,
        PostgresFiscalDatabase.COMMERCIAL_LIFECYCLE_MIGRATION_VERSION,
        FISCAL_SCOPE_VERSION,
        CUSTOMER_CONFIGURATION_VERSION,
        COMMAND_COMMERCIAL_VERSION,
        COMMERCIAL_PERIOD_VERSION,
        SECRET_BINDING_VERSION,
        PUBLIC_TRIAL_RATE_VERSION,
        COGNITIVE_QUOTA_VERSION,
    )
    if versions != tuple(range(1, max(versions) + 1)):
        raise RuntimeError(f"migration versions must be contiguous from 1: {versions!r}")

    for migration in _MIGRATIONS:
        _reject_unapproved_destructive(
            version=migration.version,
            name=migration.name,
            statements=migration.statements,
        )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.PRICING_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.PRICING_MIGRATION_NAME,
        statements=_PRICING_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.COMMERCIAL_RELEASE_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.COMMERCIAL_RELEASE_MIGRATION_NAME,
        statements=_COMMERCIAL_RELEASE_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.COMMERCIAL_FULFILLMENT_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.COMMERCIAL_FULFILLMENT_MIGRATION_NAME,
        statements=_COMMERCIAL_FULFILLMENT_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.COMMERCIAL_CLAIM_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.COMMERCIAL_CLAIM_MIGRATION_NAME,
        statements=_COMMERCIAL_CLAIM_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.COMMERCIAL_ACQUISITION_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.COMMERCIAL_ACQUISITION_MIGRATION_NAME,
        statements=_COMMERCIAL_ACQUISITION_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=PostgresFiscalDatabase.COMMERCIAL_LIFECYCLE_MIGRATION_VERSION,
        name=PostgresFiscalDatabase.COMMERCIAL_LIFECYCLE_MIGRATION_NAME,
        statements=_COMMERCIAL_LIFECYCLE_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=FISCAL_SCOPE_VERSION,
        name=FISCAL_SCOPE_NAME,
        statements=FISCAL_SCOPE_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=CAKTO_SCHEMA_VERSION,
        name=CAKTO_SCHEMA_NAME,
        statements=CAKTO_SCHEMA_STATEMENTS,
    )
    _reject_unapproved_destructive(
        version=CUSTOMER_CONFIGURATION_VERSION,
        name=CUSTOMER_CONFIGURATION_NAME,
        statements=CUSTOMER_CONFIGURATION_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=COMMAND_COMMERCIAL_VERSION, name=COMMAND_COMMERCIAL_NAME,
        statements=COMMAND_COMMERCIAL_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=COMMERCIAL_PERIOD_VERSION, name=COMMERCIAL_PERIOD_NAME,
        statements=COMMERCIAL_PERIOD_SCHEMA,
    )
    _reject_unapproved_destructive(version=SECRET_BINDING_VERSION,
        name=SECRET_BINDING_NAME, statements=SECRET_BINDING_SCHEMA)
    _reject_unapproved_destructive(
        version=PUBLIC_TRIAL_RATE_VERSION,
        name=PUBLIC_TRIAL_RATE_NAME,
        statements=PUBLIC_TRIAL_RATE_SCHEMA,
    )
    _reject_unapproved_destructive(
        version=COGNITIVE_QUOTA_VERSION,
        name=COGNITIVE_QUOTA_NAME,
        statements=COGNITIVE_QUOTA_SCHEMA,
    )
    print(
        "migration policy: PASS "
        f"versions={','.join(str(item) for item in versions)} "
        f"cakto_schema={CAKTO_SCHEMA_VERSION}"
    )
    return versions


def _require_apply_approval(environment: str) -> None:
    if os.getenv("NFCORE_SCHEMA_MIGRATION_APPROVED", "").casefold() != "true":
        raise RuntimeError(
            "schema migration blocked: NFCORE_SCHEMA_MIGRATION_APPROVED=true required"
        )
    production_approval = os.getenv("NFCORE_PRODUCTION_APPROVAL")
    if environment == "production" and production_approval != "PRODUCTION_APPROVED":
        raise RuntimeError(
            "production migration blocked: NFCORE_PRODUCTION_APPROVAL=PRODUCTION_APPROVED required"
        )



def plan_staging() -> None:
    """Read-only plan using the canonical migration authorities.

    An unknown, out-of-order or newer installed version is NOT safe to upgrade.
    Missing Cakto tracking table is the expected uninitialized Cakto state.
    """
    expected = validate_policy()
    if os.getenv("NFCORE_ENVIRONMENT") != "staging":
        raise RuntimeError("schema preflight is restricted to staging")
    if os.getenv("RAILWAY_SERVICE_ID", "").strip():
        raise RuntimeError("schema preflight must execute outside service startup")
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("schema preflight requires DATABASE_URL")
    database = PostgresFiscalDatabase(dsn)
    try:
        before = database.applied_migrations()
        if before != expected[:len(before)]:
            raise RuntimeError("schema preflight blocked: unexpected fiscal migration sequence")
        with database.connection() as connection:
            available = connection.execute(
                "SELECT to_regclass('public.fm_cakto_schema_migrations')"
            ).fetchone()
            if available is None:
                raise RuntimeError("schema preflight blocked: PostgreSQL catalog unavailable")
            if available[0] is None:
                cakto = ()
            else:
                rows = connection.execute(
                    "SELECT version FROM fm_cakto_schema_migrations ORDER BY version"
                ).fetchall()
                cakto = tuple(int(row[0]) for row in rows)
        expected_cakto = tuple(range(1, CAKTO_SCHEMA_VERSION + 1))
        if cakto != expected_cakto[:len(cakto)]:
            raise RuntimeError("schema preflight blocked: unexpected Cakto migration sequence")
    finally:
        database.close()
    print(
        "schema preflight: PASS READ_ONLY "
        f"fiscal_installed={before} fiscal_pending={expected[len(before):]} "
        f"cakto_installed={cakto} cakto_pending={expected_cakto[len(cakto):]}"
    )



def assert_current_production() -> None:
    """Read-only gate: permit a code-only deploy only with exact current schema.

    This command never runs migrations. Pending or drifted schemas require
    separately approved migration workflow before any deploy.
    """
    expected = validate_policy()
    if os.getenv("NFCORE_ENVIRONMENT") != "production":
        raise RuntimeError("production schema assertion requires production environment")
    if os.getenv("RAILWAY_SERVICE_ID", "").strip():
        raise RuntimeError("production schema assertion must run outside service startup")
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("production schema assertion requires DATABASE_URL")
    database = PostgresFiscalDatabase(dsn)
    try:
        before = database.applied_migrations()
        if before != expected:
            raise RuntimeError("production schema has pending/drifted fiscal migrations")
        with database.connection() as connection:
            row = connection.execute(
                "SELECT to_regclass('public.fm_cakto_schema_migrations')"
            ).fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("production schema has missing Cakto tracking table")
            rows = connection.execute(
                "SELECT version FROM fm_cakto_schema_migrations ORDER BY version"
            ).fetchall()
            cakto = tuple(int(item[0]) for item in rows)
        if cakto != tuple(range(1, CAKTO_SCHEMA_VERSION + 1)):
            raise RuntimeError("production schema has pending/drifted Cakto migrations")
    finally:
        database.close()
    print("production schema: PASS READ_ONLY CURRENT; no migration needed")


def apply() -> None:
    validate_policy()
    environment = os.getenv("NFCORE_ENVIRONMENT", "").strip().casefold()
    if environment not in {"staging", "production"}:
        raise RuntimeError("schema migration apply is restricted to staging/production profiles")
    # Railway service preDeployCommand must not be a second migration authority.
    # Only the external governed orchestrator, after a proven backup, may apply.
    if os.getenv("RAILWAY_SERVICE_ID", "").strip():
        raise RuntimeError(
            "schema migration blocked: Railway service preDeploy is not an authorized executor"
        )
    _require_apply_approval(environment)
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("schema migration blocked: DATABASE_URL is required")

    database = PostgresFiscalDatabase(dsn)
    try:
        before = database.applied_migrations()
        applied = database.initialize()
        after = database.require_current_schema()
        cakto = postgres_cakto_commercial_database(database)
        cakto_changed = cakto.initialize()
        cakto_versions = cakto.require_current_schema()
    finally:
        database.close()
    print(
        "schema migration: PASS "
        f"environment={environment} before={before} applied={applied} after={after} "
        f"cakto_changed={cakto_changed} cakto_versions={cakto_versions}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-policy", action="store_true")
    action.add_argument("--plan-staging", action="store_true")
    action.add_argument("--assert-current-production", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.check_policy:
        validate_policy()
    elif args.plan_staging:
        plan_staging()
    elif args.assert_current_production:
        assert_current_production()
    else:
        apply()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
