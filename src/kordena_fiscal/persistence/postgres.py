"""PostgreSQL production persistence for FM NFCORE.

The fiscal domain remains host-neutral. This module supplies a PostgreSQL-backed
unit-of-work and durable human identity stores while reusing the already-certified
repository semantics of the SQLite reference adapters through a deliberately small
DB-API compatibility boundary.

Only SQL placeholder syntax and driver exceptions are adapted here; fiscal rules,
idempotency semantics, archive behavior, control-plane rules and commercial
configuration remain in the certified repository implementations.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from types import TracebackType
from typing import Any, TypeVar, cast
from uuid import uuid4

from psycopg import Connection, Cursor, IntegrityError
from psycopg.errors import UndefinedTable
from psycopg_pool import ConnectionPool

from kordena_fiscal.contingency import FiscalOutboxEnqueueResult, FiscalOutboxEntry
from kordena_fiscal.control_plane.models import ControlPlaneAuditAction, ControlPlaneAuditEvent
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.events import FiscalInboxEntry, FiscalInboxReceiveResult
from kordena_fiscal.lifecycle import IdempotencyKey, IdempotencyReservation
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    FiscalSequencePolicy,
)
from kordena_fiscal.security.human_administration import (
    HumanAdministrationConflictError,
    HumanAdministrationNotFoundError,
)
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    PortalRole,
    WebSessionRecord,
)
from kordena_fiscal.security.human_recovery import PasswordResetRecord

from .cognitive_quota_schema import (
    COGNITIVE_QUOTA_NAME,
    COGNITIVE_QUOTA_SCHEMA,
    COGNITIVE_QUOTA_VERSION,
)
from .command_commercial_schema import (
    COMMAND_COMMERCIAL_NAME,
    COMMAND_COMMERCIAL_SCHEMA,
    COMMAND_COMMERCIAL_VERSION,
)
from .commercial_period_schema import (
    COMMERCIAL_PERIOD_NAME,
    COMMERCIAL_PERIOD_SCHEMA,
    COMMERCIAL_PERIOD_VERSION,
)
from .commercial_release import PostgresCommercialReleaseRepository
from .customer_configuration_schema import (
    CUSTOMER_CONFIGURATION_NAME,
    CUSTOMER_CONFIGURATION_SCHEMA,
    CUSTOMER_CONFIGURATION_VERSION,
)
from .fiscal_scope_schema import FISCAL_SCOPE_NAME, FISCAL_SCOPE_SCHEMA, FISCAL_SCOPE_VERSION
from .ports import PersistenceStateError
from .pricing_catalog import PostgresPricingCatalogRepository
from .public_trial_rate_schema import (
    PUBLIC_TRIAL_RATE_NAME,
    PUBLIC_TRIAL_RATE_SCHEMA,
    PUBLIC_TRIAL_RATE_VERSION,
)
from .secret_binding_schema import (
    SECRET_BINDING_NAME,
    SECRET_BINDING_SCHEMA,
    SECRET_BINDING_VERSION,
)
from .sqlite import _MIGRATIONS
from .sqlite_commercial import SqliteCommercialConfigurationStore
from .sqlite_control_plane import SqliteControlPlaneStore
from .sqlite_core import (
    SqliteBindingRepository,
    SqliteFiscalSequenceStore,
    SqliteLifecycleRepository,
)
from .sqlite_delivery import SqliteFiscalDeliveryAuditStore, SqliteFiscalOutboxOrderingStore
from .sqlite_idempotency import SqliteIdempotencyStore
from .sqlite_inbox import SqliteFiscalInboxStore
from .sqlite_outbox_archive import SqliteFiscalArchiveStore, SqliteFiscalOutboxStore
from .sqlite_reconciliation import SqliteReconciliationRepository
from .sqlite_secret_binding import SqliteSecretBindingStore

_T = TypeVar("_T")


class _CursorCompat:
    """Small cursor facade exposing the subset used by certified repositories."""

    def __init__(self, cursor: Cursor[Any]) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> tuple[object, ...] | None:
        row = self._cursor.fetchone()
        return None if row is None else cast(tuple[object, ...], row)

    def fetchall(self) -> list[tuple[object, ...]]:
        return [cast(tuple[object, ...], row) for row in self._cursor.fetchall()]


class _PostgresCompatConnection:
    """Translate qmark parameters and integrity errors for reference adapters."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    @staticmethod
    def _sql(statement: str) -> str:
        # Certified repository SQL never embeds literal question marks.
        return statement.replace("?", "%s")

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] = (),
    ) -> _CursorCompat:
        try:
            cursor = self._connection.execute(self._sql(statement), tuple(parameters))
        except IntegrityError as exc:
            # Reference adapters already map sqlite3.IntegrityError to domain conflicts.
            raise sqlite3.IntegrityError(str(exc)) from exc
        return _CursorCompat(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


def _advisory_lock(connection: sqlite3.Connection, material: str) -> None:
    compat = cast(_PostgresCompatConnection, connection)
    compat.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
        (material,),
    )


class PostgresIdempotencyStore(SqliteIdempotencyStore):
    """Idempotency store serialized per key across concurrent PostgreSQL workers."""

    def reserve(
        self,
        key: IdempotencyKey,
        request_fingerprint: str,
        document_id: str,
    ) -> IdempotencyReservation:
        if isinstance(key, IdempotencyKey):
            _advisory_lock(self._connection, f"idempotency:{key.value}")
        return super().reserve(key, request_fingerprint, document_id)


class PostgresFiscalSequenceStore(SqliteFiscalSequenceStore):
    """Sequence store with a transaction-scoped advisory lock per fiscal sequence."""

    def reserve_next(
        self,
        key: FiscalSequenceKey,
        policy: FiscalSequencePolicy,
    ) -> FiscalNumberReservation:
        if isinstance(key, FiscalSequenceKey):
            _advisory_lock(self._connection, f"sequence:{key.canonical_material}")
        return super().reserve_next(key, policy)


class PostgresFiscalInboxStore(SqliteFiscalInboxStore):
    """Inbox store that turns concurrent duplicate receives into deterministic replay."""

    def receive(self, entry: FiscalInboxEntry) -> FiscalInboxReceiveResult:
        if isinstance(entry, FiscalInboxEntry):
            _advisory_lock(self._connection, f"inbox:{entry.entry_id}")
        return super().receive(entry)


class PostgresFiscalOutboxStore(SqliteFiscalOutboxStore):
    """Outbox enqueue serialized per deterministic entry identity."""

    def enqueue(self, entry: FiscalOutboxEntry) -> FiscalOutboxEnqueueResult:
        if isinstance(entry, FiscalOutboxEntry):
            _advisory_lock(self._connection, f"outbox:{entry.entry_id}")
        return super().enqueue(entry)


class PostgresFiscalUnitOfWork:
    """One PostgreSQL transaction spanning the complete fiscal persistence surface."""

    def __init__(self, database: PostgresFiscalDatabase) -> None:
        self._database = database
        self._pool_context: Any | None = None
        self._raw_connection: Connection[Any] | None = None
        self._committed = False
        self._idempotency: PostgresIdempotencyStore | None = None
        self._sequences: PostgresFiscalSequenceStore | None = None
        self._inbox: PostgresFiscalInboxStore | None = None
        self._outbox: PostgresFiscalOutboxStore | None = None
        self._outbox_ordering: SqliteFiscalOutboxOrderingStore | None = None
        self._delivery_audit: SqliteFiscalDeliveryAuditStore | None = None
        self._archive: SqliteFiscalArchiveStore | None = None
        self._bindings: SqliteBindingRepository | None = None
        self._lifecycle: SqliteLifecycleRepository | None = None
        self._reconciliations: SqliteReconciliationRepository | None = None
        self._control_plane: SqliteControlPlaneStore | None = None
        self._commercial: SqliteCommercialConfigurationStore | None = None
        self._secret_bindings: SqliteSecretBindingStore | None = None

    def __enter__(self) -> PostgresFiscalUnitOfWork:
        if self._raw_connection is not None:
            raise PersistenceStateError("unit of work cannot be entered twice")
        pool_context = self._database._pool.connection()
        raw = pool_context.__enter__()
        compat = _PostgresCompatConnection(raw)
        sqlite_compat = cast(sqlite3.Connection, compat)
        self._pool_context = pool_context
        self._raw_connection = raw
        self._committed = False
        self._idempotency = PostgresIdempotencyStore(sqlite_compat)
        self._sequences = PostgresFiscalSequenceStore(sqlite_compat)
        self._inbox = PostgresFiscalInboxStore(sqlite_compat)
        self._outbox = PostgresFiscalOutboxStore(sqlite_compat)
        self._outbox_ordering = SqliteFiscalOutboxOrderingStore(sqlite_compat)
        self._delivery_audit = SqliteFiscalDeliveryAuditStore(sqlite_compat)
        self._archive = SqliteFiscalArchiveStore(sqlite_compat)
        self._bindings = SqliteBindingRepository(sqlite_compat)
        self._lifecycle = SqliteLifecycleRepository(sqlite_compat)
        self._reconciliations = SqliteReconciliationRepository(sqlite_compat)
        self._control_plane = SqliteControlPlaneStore(sqlite_compat)
        self._commercial = SqliteCommercialConfigurationStore(sqlite_compat)
        self._secret_bindings = SqliteSecretBindingStore(sqlite_compat)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        raw = self._raw_connection
        pool_context = self._pool_context
        if raw is None or pool_context is None:
            return
        try:
            if exc_type is not None or not self._committed:
                raw.rollback()
        finally:
            self._raw_connection = None
            self._pool_context = None
            pool_context.__exit__(exc_type, exc, traceback)

    @staticmethod
    def _require(value: _T | None, name: str) -> _T:
        if value is None:
            raise PersistenceStateError(f"unit of work {name} repository is not active")
        return value

    @property
    def idempotency(self) -> PostgresIdempotencyStore:
        return self._require(self._idempotency, "idempotency")

    @property
    def sequences(self) -> PostgresFiscalSequenceStore:
        return self._require(self._sequences, "sequences")

    @property
    def inbox(self) -> PostgresFiscalInboxStore:
        return self._require(self._inbox, "inbox")

    @property
    def outbox(self) -> PostgresFiscalOutboxStore:
        return self._require(self._outbox, "outbox")

    @property
    def outbox_ordering(self) -> SqliteFiscalOutboxOrderingStore:
        return self._require(self._outbox_ordering, "outbox_ordering")

    @property
    def delivery_audit(self) -> SqliteFiscalDeliveryAuditStore:
        return self._require(self._delivery_audit, "delivery_audit")

    @property
    def archive(self) -> SqliteFiscalArchiveStore:
        return self._require(self._archive, "archive")

    @property
    def bindings(self) -> SqliteBindingRepository:
        return self._require(self._bindings, "bindings")

    @property
    def lifecycle(self) -> SqliteLifecycleRepository:
        return self._require(self._lifecycle, "lifecycle")

    @property
    def reconciliations(self) -> SqliteReconciliationRepository:
        return self._require(self._reconciliations, "reconciliations")

    @property
    def control_plane(self) -> SqliteControlPlaneStore:
        return self._require(self._control_plane, "control_plane")

    @property
    def commercial(self) -> SqliteCommercialConfigurationStore:
        return self._require(self._commercial, "commercial")

    @property
    def secret_bindings(self) -> SqliteSecretBindingStore:
        return self._require(self._secret_bindings, "secret_bindings")

    def commit(self) -> None:
        if self._raw_connection is None:
            raise PersistenceStateError("unit of work is not active")
        self._raw_connection.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._raw_connection is None:
            raise PersistenceStateError("unit of work is not active")
        self._raw_connection.rollback()
        self._committed = False


_HUMAN_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS fm_human_accounts (
        account_id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        role TEXT NOT NULL,
        unit_ids_json TEXT,
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        session_epoch INTEGER NOT NULL CHECK (session_epoch >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS fm_human_accounts_tenant_idx ON fm_human_accounts (tenant_id)",
    """
    CREATE TABLE IF NOT EXISTS fm_web_sessions (
        session_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        session_token_sha256 TEXT NOT NULL UNIQUE,
        csrf_token_sha256 TEXT NOT NULL,
        session_epoch INTEGER NOT NULL CHECK (session_epoch >= 0),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)),
        FOREIGN KEY (account_id) REFERENCES fm_human_accounts(account_id)
    )
    """,
    ("CREATE INDEX IF NOT EXISTS fm_web_sessions_account_idx ON fm_web_sessions (account_id)"),
    (
        "CREATE INDEX IF NOT EXISTS fm_web_sessions_expiry_idx "
        "ON fm_web_sessions (expires_at, revoked)"
    ),
    """
    CREATE TABLE IF NOT EXISTS fm_password_resets (
        reset_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        token_sha256 TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL CHECK (used IN (0, 1)),
        FOREIGN KEY (account_id) REFERENCES fm_human_accounts(account_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_password_resets_account_idx "
        "ON fm_password_resets (account_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS fm_password_resets_expiry_idx "
        "ON fm_password_resets (expires_at, used)"
    ),
)
_PRICING_SCHEMA = (
    """
    ALTER TABLE fm_human_accounts
    ADD COLUMN IF NOT EXISTS platform_admin INTEGER NOT NULL DEFAULT 0
    CHECK (platform_admin IN (0, 1))
    """,
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_pricing_catalog_versions (
        version INTEGER PRIMARY KEY CHECK (version >= 1),
        configuration_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        published_at TEXT NOT NULL
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_pricing_catalog_published_idx "
        "ON fm_commercial_pricing_catalog_versions (published_at DESC)"
    ),
)
_COMMERCIAL_RELEASE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_release_versions (
        version INTEGER PRIMARY KEY CHECK (version >= 1),
        status TEXT NOT NULL,
        public_message TEXT,
        human_decision_reference TEXT,
        actor_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        published_at TEXT NOT NULL
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_release_published_idx "
        "ON fm_commercial_release_versions (published_at DESC)"
    ),
)

_COMMERCIAL_FULFILLMENT_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_event_receipts (
        provider_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        external_order_id TEXT NOT NULL,
        purchase_id TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        received_at TEXT NOT NULL,
        PRIMARY KEY (provider_id, event_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_event_purchase_idx "
        "ON fm_commercial_event_receipts (purchase_id, occurred_at)"
    ),
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_purchases (
        purchase_id TEXT PRIMARY KEY,
        provider_id TEXT NOT NULL,
        external_order_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        state TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_event_at TEXT NOT NULL,
        last_event_id TEXT NOT NULL,
        price_id TEXT,
        external_subscription_id TEXT,
        external_customer_id TEXT,
        buyer_email TEXT,
        tenant_id TEXT,
        account_id TEXT,
        UNIQUE (provider_id, external_order_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_purchases_state_idx "
        "ON fm_commercial_purchases (state, updated_at, purchase_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_purchases_tenant_idx "
        "ON fm_commercial_purchases (tenant_id, updated_at, purchase_id)"
    ),
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_subscriptions (
        subscription_id TEXT PRIMARY KEY,
        purchase_id TEXT NOT NULL UNIQUE,
        tenant_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        entitlement_ids_json TEXT NOT NULL,
        quotas_json TEXT NOT NULL,
        status TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        usage_json TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        external_subscription_id TEXT,
        last_event_id TEXT NOT NULL,
        last_event_at TEXT NOT NULL,
        UNIQUE (provider_id, external_subscription_id),
        FOREIGN KEY (purchase_id) REFERENCES fm_commercial_purchases(purchase_id),
        FOREIGN KEY (tenant_id) REFERENCES fm_control_plane_organizations(tenant_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_subscriptions_tenant_idx "
        "ON fm_commercial_subscriptions (tenant_id, status, last_event_at)"
    ),
)

_COMMERCIAL_CLAIM_SCHEMA = (
    """
    ALTER TABLE fm_commercial_purchases
    ADD COLUMN IF NOT EXISTS legal_name TEXT
    """,
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_claims (
        claim_id TEXT PRIMARY KEY,
        purchase_id TEXT NOT NULL UNIQUE,
        token_sha256 TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        FOREIGN KEY (purchase_id) REFERENCES fm_commercial_purchases(purchase_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_claims_expiry_idx "
        "ON fm_commercial_claims (expires_at, used_at)"
    ),
)


_COMMERCIAL_ACQUISITION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS fm_commercial_acquisitions (
        acquisition_id TEXT PRIMARY KEY,
        idempotency_sha256 TEXT NOT NULL UNIQUE,
        request_sha256 TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        price_id TEXT NOT NULL,
        buyer_email TEXT NOT NULL,
        legal_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        linked_purchase_id TEXT UNIQUE,
        FOREIGN KEY (linked_purchase_id) REFERENCES fm_commercial_purchases(purchase_id)
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_acquisitions_expiry_idx "
        "ON fm_commercial_acquisitions (expires_at, linked_purchase_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS fm_commercial_acquisitions_provider_idx "
        "ON fm_commercial_acquisitions (provider_id, plan_id, price_id)"
    ),
)

_COMMERCIAL_LIFECYCLE_SCHEMA = (
    """
    ALTER TABLE fm_commercial_purchases
    ADD COLUMN IF NOT EXISTS billing_status TEXT
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS fm_commercial_purchases_subscription_idx "
        "ON fm_commercial_purchases (provider_id, external_subscription_id) "
        "WHERE external_subscription_id IS NOT NULL"
    ),
)


def _translate_ddl(statement: str) -> str:
    return statement.replace(" BLOB ", " BYTEA ").replace(" BLOB\n", " BYTEA\n")


class PostgresFiscalDatabase:
    """Pooled PostgreSQL database handle with reproducible versioned migrations."""

    HUMAN_MIGRATION_VERSION = 6
    HUMAN_MIGRATION_NAME = "web03_human_identity_and_sessions"
    PRICING_MIGRATION_VERSION = 7
    PRICING_MIGRATION_NAME = "cl08_durable_pricing_and_platform_admin"
    COMMERCIAL_RELEASE_MIGRATION_VERSION = 8
    COMMERCIAL_RELEASE_MIGRATION_NAME = "cl09_commercial_release_authority"
    COMMERCIAL_FULFILLMENT_MIGRATION_VERSION = 9
    COMMERCIAL_FULFILLMENT_MIGRATION_NAME = "cl11_canonical_commercial_state"
    COMMERCIAL_CLAIM_MIGRATION_VERSION = 10
    COMMERCIAL_CLAIM_MIGRATION_NAME = "cl11_secure_customer_claim"
    COMMERCIAL_ACQUISITION_MIGRATION_VERSION = 11
    COMMERCIAL_ACQUISITION_MIGRATION_NAME = "cl11_first_party_acquisition"
    COMMERCIAL_LIFECYCLE_MIGRATION_VERSION = 12
    COMMERCIAL_LIFECYCLE_MIGRATION_NAME = "cl11_canonical_billing_lifecycle"

    def __init__(
        self,
        dsn: str,
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
    ) -> None:
        normalized = dsn.strip()
        if not normalized:
            raise FiscalValidationError("PostgreSQL DSN must not be blank")
        if not normalized.startswith(("postgresql://", "postgres://")):
            raise FiscalValidationError("PostgreSQL DSN must use postgres/postgresql scheme")
        if min_pool_size < 1 or max_pool_size < min_pool_size:
            raise FiscalValidationError("invalid PostgreSQL pool size")
        self._dsn = normalized
        self._pool: ConnectionPool[Any] = ConnectionPool(
            conninfo=normalized,
            min_size=min_pool_size,
            max_size=max_pool_size,
            open=False,
        )
        self._pool.open(wait=True)

    @property
    def dsn_redacted(self) -> str:
        return "postgresql://<redacted>"

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[_PostgresCompatConnection]:
        with self._pool.connection() as raw:
            yield _PostgresCompatConnection(raw)

    def initialize(self) -> tuple[int, ...]:
        with self._pool.connection() as raw:
            try:
                raw.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fm_schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                raw.execute("SELECT pg_advisory_xact_lock(638051840319)")
                rows = raw.execute(
                    "SELECT version FROM fm_schema_migrations ORDER BY version"
                ).fetchall()
                applied = {int(row[0]) for row in rows}
                new_versions: list[int] = []
                for migration in _MIGRATIONS:
                    if migration.version in applied:
                        continue
                    for statement in migration.statements:
                        raw.execute(_translate_ddl(statement))
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            migration.version,
                            migration.name,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(migration.version)
                if self.HUMAN_MIGRATION_VERSION not in applied:
                    for statement in _HUMAN_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.HUMAN_MIGRATION_VERSION,
                            self.HUMAN_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.HUMAN_MIGRATION_VERSION)
                if self.PRICING_MIGRATION_VERSION not in applied:
                    for statement in _PRICING_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.PRICING_MIGRATION_VERSION,
                            self.PRICING_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.PRICING_MIGRATION_VERSION)
                if self.COMMERCIAL_RELEASE_MIGRATION_VERSION not in applied:
                    for statement in _COMMERCIAL_RELEASE_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.COMMERCIAL_RELEASE_MIGRATION_VERSION,
                            self.COMMERCIAL_RELEASE_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.COMMERCIAL_RELEASE_MIGRATION_VERSION)
                if self.COMMERCIAL_FULFILLMENT_MIGRATION_VERSION not in applied:
                    for statement in _COMMERCIAL_FULFILLMENT_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.COMMERCIAL_FULFILLMENT_MIGRATION_VERSION,
                            self.COMMERCIAL_FULFILLMENT_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.COMMERCIAL_FULFILLMENT_MIGRATION_VERSION)
                if self.COMMERCIAL_CLAIM_MIGRATION_VERSION not in applied:
                    for statement in _COMMERCIAL_CLAIM_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.COMMERCIAL_CLAIM_MIGRATION_VERSION,
                            self.COMMERCIAL_CLAIM_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.COMMERCIAL_CLAIM_MIGRATION_VERSION)
                if self.COMMERCIAL_ACQUISITION_MIGRATION_VERSION not in applied:
                    for statement in _COMMERCIAL_ACQUISITION_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.COMMERCIAL_ACQUISITION_MIGRATION_VERSION,
                            self.COMMERCIAL_ACQUISITION_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.COMMERCIAL_ACQUISITION_MIGRATION_VERSION)
                if self.COMMERCIAL_LIFECYCLE_MIGRATION_VERSION not in applied:
                    for statement in _COMMERCIAL_LIFECYCLE_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        """
                        INSERT INTO fm_schema_migrations (version, name, applied_at)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.COMMERCIAL_LIFECYCLE_MIGRATION_VERSION,
                            self.COMMERCIAL_LIFECYCLE_MIGRATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(self.COMMERCIAL_LIFECYCLE_MIGRATION_VERSION)
                if FISCAL_SCOPE_VERSION not in applied:
                    for statement in FISCAL_SCOPE_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (
                            FISCAL_SCOPE_VERSION,
                            FISCAL_SCOPE_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(FISCAL_SCOPE_VERSION)
                if CUSTOMER_CONFIGURATION_VERSION not in applied:
                    for statement in CUSTOMER_CONFIGURATION_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        (
                            "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                            "VALUES (%s, %s, %s)"
                        ),
                        (
                            CUSTOMER_CONFIGURATION_VERSION,
                            CUSTOMER_CONFIGURATION_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(CUSTOMER_CONFIGURATION_VERSION)
                if COMMAND_COMMERCIAL_VERSION not in applied:
                    for statement in COMMAND_COMMERCIAL_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (
                            COMMAND_COMMERCIAL_VERSION,
                            COMMAND_COMMERCIAL_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(COMMAND_COMMERCIAL_VERSION)
                if COMMERCIAL_PERIOD_VERSION not in applied:
                    for statement in COMMERCIAL_PERIOD_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (
                            COMMERCIAL_PERIOD_VERSION,
                            COMMERCIAL_PERIOD_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(COMMERCIAL_PERIOD_VERSION)
                if SECRET_BINDING_VERSION not in applied:
                    for statement in SECRET_BINDING_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (SECRET_BINDING_VERSION, SECRET_BINDING_NAME,
                         datetime.now().astimezone().isoformat()),
                    )
                    new_versions.append(SECRET_BINDING_VERSION)
                if PUBLIC_TRIAL_RATE_VERSION not in applied:
                    for statement in PUBLIC_TRIAL_RATE_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (
                            PUBLIC_TRIAL_RATE_VERSION,
                            PUBLIC_TRIAL_RATE_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(PUBLIC_TRIAL_RATE_VERSION)
                if COGNITIVE_QUOTA_VERSION not in applied:
                    for statement in COGNITIVE_QUOTA_SCHEMA:
                        raw.execute(statement)
                    raw.execute(
                        "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                        "VALUES (%s, %s, %s)",
                        (
                            COGNITIVE_QUOTA_VERSION,
                            COGNITIVE_QUOTA_NAME,
                            datetime.now().astimezone().isoformat(),
                        ),
                    )
                    new_versions.append(COGNITIVE_QUOTA_VERSION)
                raw.commit()
                return tuple(new_versions)
            except Exception:
                raw.rollback()
                raise

    def applied_migrations(self) -> tuple[int, ...]:
        with self._pool.connection() as raw:
            try:
                rows = raw.execute(
                    "SELECT version FROM fm_schema_migrations ORDER BY version"
                ).fetchall()
            except UndefinedTable:
                raw.rollback()
                return ()
            return tuple(int(row[0]) for row in rows)

    def require_current_schema(self) -> tuple[int, ...]:
        """Check schema compatibility without DDL or migration side effects.

        In staging/production only the governed migration_guard orchestrator may
        call initialize(). Running services must fail closed on drift/missing
        versions instead of creating tables during startup.
        """
        applied = self.applied_migrations()
        required = tuple(range(1, COGNITIVE_QUOTA_VERSION + 1))
        if applied != required:
            raise PersistenceStateError(
                "PostgreSQL schema is not at the certified migration version"
            )

        # The fiscal ledger alone is insufficient: migration 19 also requires
        # both durable quota tables. This check must remain read-only.
        try:
            with self.connection() as connection:
                tables = connection.execute(
                    "SELECT to_regclass('public.fm_cognitive_token_counters'), "
                    "to_regclass('public.fm_cognitive_token_reservations')"
                ).fetchone()
            if tables is None or len(tables) != 2 or not all(tables):
                raise PersistenceStateError(
                    "PostgreSQL schema is not at the certified migration version"
                )
        except PersistenceStateError:
            raise
        except Exception as exc:
            raise PersistenceStateError(
                "PostgreSQL schema is not at the certified migration version"
            ) from exc
        return applied

    def unit_of_work(self) -> PostgresFiscalUnitOfWork:
        return PostgresFiscalUnitOfWork(self)

    def __call__(self) -> PostgresFiscalUnitOfWork:
        return self.unit_of_work()

    def human_accounts(self) -> PostgresHumanAccountRepository:
        return PostgresHumanAccountRepository(self)

    def human_administration(self) -> PostgresHumanAdministrationStore:
        return PostgresHumanAdministrationStore(self)

    def web_sessions(self) -> PostgresWebSessionRepository:
        return PostgresWebSessionRepository(self)

    def password_resets(self) -> PostgresPasswordResetRepository:
        return PostgresPasswordResetRepository(self)

    @contextmanager
    def first_platform_admin_bootstrap_guard(
        self, *, account_id: str, email: str
    ) -> Iterator[None]:
        """Serialize the one-time bootstrap; never grant authority to existing accounts.

        Lock is held across the canonical commercial provisioner and the final
        privilege/audit transaction. Only this canonical persistence adapter uses SQL.
        """
        with self._pool.connection() as raw:
            acquired = raw.execute("SELECT pg_try_advisory_lock(638051840337)").fetchone()
            raw.commit()
            if acquired is None or acquired[0] is not True:
                raise PersistenceStateError("first platform admin bootstrap lock unavailable")
            try:
                # Fail closed if another account/admin occupies this database.
                conflict = raw.execute(
                    """
                    SELECT 1 FROM fm_human_accounts
                    WHERE platform_admin <> 0 OR account_id <> %s OR email <> %s
                    LIMIT 1
                    """,
                    (account_id, email),
                ).fetchone()
                raw.commit()
                if conflict is not None:
                    raise PersistenceStateError("first platform admin bootstrap denied")
                yield
            finally:
                raw.rollback()
                raw.execute("SELECT pg_advisory_unlock(638051840337)")
                raw.commit()

    def promote_first_platform_admin(
        self, *, account_id: str, email: str, tenant_id: str, now: datetime
    ) -> None:
        """Commit elevation and audit in one canonical PostgreSQL unit of work."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise PersistenceStateError("bootstrap audit clock must be timezone aware")
        with self() as uow:
            raw = uow._raw_connection
            if raw is None:
                raise PersistenceStateError("bootstrap unit of work unavailable")
            raw.execute("SELECT pg_advisory_xact_lock(638051840338)")
            if (
                raw.execute(
                    "SELECT 1 FROM fm_human_accounts WHERE platform_admin <> 0 LIMIT 1"
                ).fetchone()
                is not None
            ):
                raise PersistenceStateError("platform administrator already exists")
            row = raw.execute(
                """
                SELECT tenant_id, role, enabled, platform_admin
                FROM fm_human_accounts WHERE account_id = %s AND email = %s FOR UPDATE
                """,
                (account_id, email),
            ).fetchone()
            if row is None or (
                str(row[0]) != tenant_id
                or str(row[1]) != PortalRole.OWNER.value
                or int(row[2]) != 1
                or int(row[3]) != 0
            ):
                raise PersistenceStateError("bootstrap owner identity unavailable")
            updated = raw.execute(
                """
                UPDATE fm_human_accounts SET platform_admin = 1
                WHERE account_id = %s AND email = %s AND tenant_id = %s
                    AND platform_admin = 0
                """,
                (account_id, email, tenant_id),
            )
            if updated.rowcount != 1:
                raise PersistenceStateError("bootstrap privilege update denied")
            uow.control_plane.append_audit(
                ControlPlaneAuditEvent(
                    event_id=uuid4().hex,
                    occurred_at=now,
                    actor_id="production-bootstrap",
                    action=ControlPlaneAuditAction.HUMAN_ACCOUNT_UPDATED,
                    target_type="human_account",
                    target_id=account_id,
                    correlation_id="production-first-platform-admin",
                    tenant_id=tenant_id,
                )
            )
            uow.commit()

    def pricing_catalog(self) -> PostgresPricingCatalogRepository:
        return PostgresPricingCatalogRepository(self)

    def commercial_release_catalog(self) -> PostgresCommercialReleaseRepository:
        return PostgresCommercialReleaseRepository(self)


class PostgresHumanAccountRepository:
    def __init__(self, database: PostgresFiscalDatabase) -> None:
        self._database = database

    @staticmethod
    def _account(row: tuple[object, ...]) -> HumanAccount:
        raw_units = row[5]
        unit_ids: frozenset[str] | None
        if raw_units is None:
            unit_ids = None
        else:
            decoded = json.loads(str(raw_units))
            if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
                raise PersistenceStateError("persisted human unit_ids_json is invalid")
            unit_ids = frozenset(cast(list[str], decoded))
        return HumanAccount(
            account_id=str(row[0]),
            email=str(row[1]),
            password_hash=str(row[2]),
            tenant_id=str(row[3]),
            role=PortalRole(str(row[4])),
            unit_ids=unit_ids,
            enabled=bool(int(cast(int, row[6]))),
            session_epoch=int(cast(int, row[7])),
            platform_admin=bool(int(cast(int, row[8]))),
        )

    def by_email(self, email: str) -> HumanAccount | None:
        normalized = email.strip().casefold()
        with self._database._pool.connection() as raw:
            row = raw.execute(
                """
                SELECT account_id, email, password_hash, tenant_id, role,
                       unit_ids_json, enabled, session_epoch, platform_admin
                FROM fm_human_accounts WHERE email = %s
                """,
                (normalized,),
            ).fetchone()
        return None if row is None else self._account(cast(tuple[object, ...], row))

    def by_id(self, account_id: str) -> HumanAccount | None:
        normalized = account_id.strip()
        with self._database._pool.connection() as raw:
            row = raw.execute(
                """
                SELECT account_id, email, password_hash, tenant_id, role,
                       unit_ids_json, enabled, session_epoch, platform_admin
                FROM fm_human_accounts WHERE account_id = %s
                """,
                (normalized,),
            ).fetchone()
        return None if row is None else self._account(cast(tuple[object, ...], row))

    def save(self, account: HumanAccount) -> None:
        if not isinstance(account, HumanAccount):
            raise ValueError("account must be HumanAccount")
        units_json = None if account.unit_ids is None else json.dumps(sorted(account.unit_ids))
        with self._database._pool.connection() as raw:
            try:
                raw.execute(
                    """
                    INSERT INTO fm_human_accounts (
                        account_id, email, password_hash, tenant_id, role, unit_ids_json,
                        enabled, session_epoch, platform_admin
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (account_id) DO UPDATE SET
                        email = EXCLUDED.email,
                        password_hash = EXCLUDED.password_hash,
                        tenant_id = EXCLUDED.tenant_id,
                        role = EXCLUDED.role,
                        unit_ids_json = EXCLUDED.unit_ids_json,
                        enabled = EXCLUDED.enabled,
                        session_epoch = EXCLUDED.session_epoch,
                        platform_admin = EXCLUDED.platform_admin
                    """,
                    (
                        account.account_id,
                        account.email,
                        account.password_hash,
                        account.tenant_id,
                        account.role.value,
                        units_json,
                        int(account.enabled),
                        account.session_epoch,
                        int(account.platform_admin),
                    ),
                )
                raw.commit()
            except IntegrityError as exc:
                raw.rollback()
                raise ValueError("email is already assigned to another account") from exc


class PostgresHumanAdministrationStore:
    """Atomic PostgreSQL adapter for tenant human-account administration."""

    def __init__(self, database: PostgresFiscalDatabase) -> None:
        self._database = database

    @staticmethod
    def _row_account(row: tuple[object, ...]) -> HumanAccount:
        return PostgresHumanAccountRepository._account(row)

    def by_email(self, email: str) -> HumanAccount | None:
        return PostgresHumanAccountRepository(self._database).by_email(email)

    def by_id(self, account_id: str) -> HumanAccount | None:
        return PostgresHumanAccountRepository(self._database).by_id(account_id)

    def list_for_tenant(self, tenant_id: str) -> tuple[HumanAccount, ...]:
        normalized = tenant_id.strip()
        with self._database._pool.connection() as raw:
            rows = raw.execute(
                """
                SELECT account_id, email, password_hash, tenant_id, role,
                       unit_ids_json, enabled, session_epoch, platform_admin
                FROM fm_human_accounts
                WHERE tenant_id = %s
                ORDER BY email, account_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(self._row_account(cast(tuple[object, ...], row)) for row in rows)

    def command_target(self, tenant_id: str, correlation_id: str) -> tuple[str, str] | None:
        with self._database._pool.connection() as raw:
            row = raw.execute(
                """
                SELECT action, target_id
                FROM fm_control_plane_audit
                WHERE tenant_id = %s AND correlation_id = %s
                ORDER BY occurred_at, event_id
                LIMIT 1
                """,
                (tenant_id.strip(), correlation_id.strip()),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])

    @staticmethod
    def _claim_command(
        raw: Connection[Any],
        *,
        tenant_id: str,
        correlation_id: str,
    ) -> None:
        raw.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (tenant_id + "|" + correlation_id,),
        )
        previous = raw.execute(
            """
            SELECT event_id
            FROM fm_control_plane_audit
            WHERE tenant_id = %s AND correlation_id = %s
            LIMIT 1
            FOR UPDATE
            """,
            (tenant_id, correlation_id),
        ).fetchone()
        if previous is not None:
            raise HumanAdministrationConflictError("idempotency key was already used")

    @staticmethod
    def _append_audit(
        raw: Connection[Any],
        *,
        action: ControlPlaneAuditAction,
        account: HumanAccount,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None:
        raw.execute(
            """
            INSERT INTO fm_control_plane_audit (
                event_id, occurred_at, actor_id, action, target_type,
                target_id, correlation_id, tenant_id, unit_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                f"audit-{uuid4().hex}",
                occurred_at.isoformat(),
                actor_id,
                action.value,
                "human-account",
                account.account_id,
                correlation_id,
                account.tenant_id,
            ),
        )

    def create(
        self,
        account: HumanAccount,
        *,
        actor_id: str,
        correlation_id: str,
        occurred_at: datetime,
    ) -> HumanAccount:
        units_json = None if account.unit_ids is None else json.dumps(sorted(account.unit_ids))
        try:
            with self._database._pool.connection() as raw:
                with raw.transaction():
                    self._claim_command(
                        raw,
                        tenant_id=account.tenant_id,
                        correlation_id=correlation_id,
                    )
                    collision = raw.execute(
                        """
                        SELECT account_id
                        FROM fm_human_accounts
                        WHERE account_id = %s OR email = %s
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (account.account_id, account.email),
                    ).fetchone()
                    if collision is not None:
                        raise HumanAdministrationConflictError("human account already exists")
                    raw.execute(
                        """
                        INSERT INTO fm_human_accounts (
                            account_id, email, password_hash, tenant_id, role, unit_ids_json,
                            enabled, session_epoch, platform_admin
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                        """,
                        (
                            account.account_id,
                            account.email,
                            account.password_hash,
                            account.tenant_id,
                            account.role.value,
                            units_json,
                            int(account.enabled),
                            account.session_epoch,
                        ),
                    )
                    self._append_audit(
                        raw,
                        action=ControlPlaneAuditAction.HUMAN_ACCOUNT_CREATED,
                        account=account,
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                        occurred_at=occurred_at,
                    )
        except IntegrityError as exc:
            raise HumanAdministrationConflictError("human account already exists") from exc
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
        units_json = None if account.unit_ids is None else json.dumps(sorted(account.unit_ids))
        with self._database._pool.connection() as raw:
            with raw.transaction():
                self._claim_command(
                    raw,
                    tenant_id=account.tenant_id,
                    correlation_id=correlation_id,
                )
                current_row = raw.execute(
                    """
                    SELECT account_id, email, password_hash, tenant_id, role,
                           unit_ids_json, enabled, session_epoch, platform_admin
                    FROM fm_human_accounts
                    WHERE account_id = %s
                    FOR UPDATE
                    """,
                    (account.account_id,),
                ).fetchone()
                if current_row is None:
                    raise HumanAdministrationNotFoundError("human account was not found")
                current = self._row_account(cast(tuple[object, ...], current_row))
                if current.tenant_id != account.tenant_id:
                    raise HumanAdministrationNotFoundError("human account was not found")
                if current.platform_admin:
                    raise HumanAdministrationConflictError(
                        "platform authority cannot be changed by tenant admin"
                    )
                if current.session_epoch != expected_session_epoch:
                    raise HumanAdministrationConflictError("human account version changed")

                if (
                    current.role is PortalRole.OWNER
                    and current.enabled
                    and (account.role is not PortalRole.OWNER or not account.enabled)
                ):
                    owner_rows = raw.execute(
                        """
                        SELECT account_id
                        FROM fm_human_accounts
                        WHERE tenant_id = %s AND role = %s AND enabled = 1
                        FOR UPDATE
                        """,
                        (account.tenant_id, PortalRole.OWNER.value),
                    ).fetchall()
                    if not any(str(row[0]) != current.account_id for row in owner_rows):
                        raise HumanAdministrationConflictError(
                            "tenant must retain at least one enabled owner"
                        )

                changed = raw.execute(
                    """
                    UPDATE fm_human_accounts
                    SET role = %s,
                        unit_ids_json = %s,
                        enabled = %s,
                        session_epoch = %s
                    WHERE account_id = %s AND tenant_id = %s AND session_epoch = %s
                    """,
                    (
                        account.role.value,
                        units_json,
                        int(account.enabled),
                        account.session_epoch,
                        account.account_id,
                        account.tenant_id,
                        expected_session_epoch,
                    ),
                )
                if changed.rowcount != 1:
                    raise HumanAdministrationConflictError("human account version changed")
                raw.execute(
                    "UPDATE fm_web_sessions SET revoked = 1 WHERE account_id = %s",
                    (account.account_id,),
                )
                raw.execute(
                    "UPDATE fm_password_resets SET used = 1 WHERE account_id = %s AND used = 0",
                    (account.account_id,),
                )
                self._append_audit(
                    raw,
                    action=ControlPlaneAuditAction.HUMAN_ACCOUNT_UPDATED,
                    account=account,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    occurred_at=occurred_at,
                )
        return account


class PostgresWebSessionRepository:
    def __init__(self, database: PostgresFiscalDatabase) -> None:
        self._database = database

    @staticmethod
    def _session(row: tuple[object, ...]) -> WebSessionRecord:
        return WebSessionRecord(
            session_id=str(row[0]),
            account_id=str(row[1]),
            session_token_sha256=str(row[2]),
            csrf_token_sha256=str(row[3]),
            session_epoch=int(cast(int, row[4])),
            created_at=datetime.fromisoformat(str(row[5])),
            expires_at=datetime.fromisoformat(str(row[6])),
            revoked=bool(int(cast(int, row[7]))),
        )

    def by_token_digest(self, session_token_sha256: str) -> WebSessionRecord | None:
        with self._database._pool.connection() as raw:
            row = raw.execute(
                """
                SELECT session_id, account_id, session_token_sha256, csrf_token_sha256,
                       session_epoch, created_at, expires_at, revoked
                FROM fm_web_sessions WHERE session_token_sha256 = %s
                """,
                (session_token_sha256,),
            ).fetchone()
        return None if row is None else self._session(cast(tuple[object, ...], row))

    def save(self, session: WebSessionRecord) -> None:
        if not isinstance(session, WebSessionRecord):
            raise ValueError("session must be WebSessionRecord")
        with self._database._pool.connection() as raw:
            raw.execute(
                """
                INSERT INTO fm_web_sessions (
                    session_id, account_id, session_token_sha256, csrf_token_sha256,
                    session_epoch, created_at, expires_at, revoked
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    account_id = EXCLUDED.account_id,
                    session_token_sha256 = EXCLUDED.session_token_sha256,
                    csrf_token_sha256 = EXCLUDED.csrf_token_sha256,
                    session_epoch = EXCLUDED.session_epoch,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at,
                    revoked = EXCLUDED.revoked
                """,
                (
                    session.session_id,
                    session.account_id,
                    session.session_token_sha256,
                    session.csrf_token_sha256,
                    session.session_epoch,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    int(session.revoked),
                ),
            )
            raw.commit()

    def revoke(self, session_id: str) -> None:
        with self._database._pool.connection() as raw:
            raw.execute(
                "UPDATE fm_web_sessions SET revoked = 1 WHERE session_id = %s",
                (session_id.strip(),),
            )
            raw.commit()

    def revoke_account(self, account_id: str) -> None:
        with self._database._pool.connection() as raw:
            raw.execute(
                "UPDATE fm_web_sessions SET revoked = 1 WHERE account_id = %s",
                (account_id.strip(),),
            )
            raw.commit()


class PostgresPasswordResetRepository:
    def __init__(self, database: PostgresFiscalDatabase) -> None:
        self._database = database

    @staticmethod
    def _record(row: tuple[object, ...]) -> PasswordResetRecord:
        return PasswordResetRecord(
            reset_id=str(row[0]),
            account_id=str(row[1]),
            token_sha256=str(row[2]),
            created_at=datetime.fromisoformat(str(row[3])),
            expires_at=datetime.fromisoformat(str(row[4])),
            used=bool(int(cast(int, row[5]))),
        )

    def by_token_digest(self, token_sha256: str) -> PasswordResetRecord | None:
        with self._database._pool.connection() as raw:
            row = raw.execute(
                """
                SELECT reset_id, account_id, token_sha256, created_at, expires_at, used
                FROM fm_password_resets WHERE token_sha256 = %s
                """,
                (token_sha256,),
            ).fetchone()
        return None if row is None else self._record(cast(tuple[object, ...], row))

    def save(self, record: PasswordResetRecord) -> None:
        if not isinstance(record, PasswordResetRecord):
            raise ValueError("record must be PasswordResetRecord")
        with self._database._pool.connection() as raw:
            raw.execute(
                """
                INSERT INTO fm_password_resets (
                    reset_id, account_id, token_sha256, created_at, expires_at, used
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (reset_id) DO UPDATE SET
                    account_id = EXCLUDED.account_id,
                    token_sha256 = EXCLUDED.token_sha256,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at,
                    used = EXCLUDED.used
                """,
                (
                    record.reset_id,
                    record.account_id,
                    record.token_sha256,
                    record.created_at.isoformat(),
                    record.expires_at.isoformat(),
                    int(record.used),
                ),
            )
            raw.commit()

    def mark_used(self, reset_id: str) -> None:
        with self._database._pool.connection() as raw:
            raw.execute(
                "UPDATE fm_password_resets SET used = 1 WHERE reset_id = %s",
                (reset_id.strip(),),
            )
            raw.commit()

    def invalidate_account(self, account_id: str) -> None:
        with self._database._pool.connection() as raw:
            raw.execute(
                """
                UPDATE fm_password_resets
                SET used = 1
                WHERE account_id = %s AND used = 0
                """,
                (account_id.strip(),),
            )
            raw.commit()


def production_database_from_env(
    environ: Iterable[tuple[str, str]] | None = None,
) -> PostgresFiscalDatabase:
    """Build production persistence from environment, failing closed on SQLite."""

    values = dict(os.environ.items() if environ is None else environ)
    backend = values.get("NFCORE_PERSISTENCE_BACKEND", "").strip().casefold()
    if backend != "postgres":
        raise PersistenceStateError("production persistence backend must be postgres")
    dsn = values.get("NFCORE_DATABASE_URL", "").strip()
    if not dsn:
        raise PersistenceStateError("NFCORE_DATABASE_URL is required for PostgreSQL")
    return PostgresFiscalDatabase(dsn)
