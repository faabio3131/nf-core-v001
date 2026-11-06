"""Durable provider-specific commercial persistence for Cakto.

The schema is intentionally separate from fiscal authority. It stores only sanitized
commercial metadata, hashes and entitlement state; webhook body secrets and raw customer
PII are never persisted.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, cast

from kordena_fiscal.product.cakto import (
    CaktoCommercialEntitlement,
    CaktoCommercialStore,
    CaktoCommercialTenant,
    CaktoEntitlementStatus,
    CaktoInboxStatus,
    CaktoPlanBinding,
    CaktoStateConflictError,
    CaktoWebhookEvent,
    CaktoWebhookInboxEntry,
)


class _Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class _Connection(Protocol):
    def execute(self, statement: str, parameters: Sequence[object] = ()) -> _Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class _ConnectionContext(Protocol):
    def __enter__(self) -> _Connection: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


ConnectionContextFactory = Callable[[], _ConnectionContext]

CAKTO_SCHEMA_VERSION = 3
CAKTO_SCHEMA_NAME = "cl11_cakto_canonical_reconciliation"
CAKTO_SCHEMA_V3_NAME = "nfv1_cakto_claim_automation_email"
CAKTO_SCHEMA_V1_NAME = "web11_cakto_commercial_activation"
CAKTO_SCHEMA_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS fm_cakto_plan_bindings (
        external_product_id TEXT NOT NULL,
        external_offer_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        entitlement_ids_json TEXT NOT NULL,
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        PRIMARY KEY (external_product_id, external_offer_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fm_cakto_webhook_inbox (
        event_key TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        order_id TEXT,
        external_product_id TEXT NOT NULL,
        external_offer_id TEXT,
        external_customer_id TEXT,
        order_status TEXT,
        occurred_at TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        received_at TEXT NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL,
        next_attempt_at TEXT,
        last_error TEXT,
        tenant_id TEXT,
        outcome_reference TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS fm_cakto_webhook_due_idx
    ON fm_cakto_webhook_inbox (status, next_attempt_at, received_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS fm_cakto_commercial_tenants (
        tenant_id TEXT PRIMARY KEY,
        external_customer_id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fm_cakto_entitlements (
        tenant_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        entitlement_ids_json TEXT NOT NULL,
        status TEXT NOT NULL,
        last_event_at TEXT NOT NULL,
        last_event_key TEXT NOT NULL,
        PRIMARY KEY (tenant_id, plan_id),
        FOREIGN KEY (tenant_id) REFERENCES fm_cakto_commercial_tenants(tenant_id)
    )
    """,
)
CAKTO_SCHEMA_V2_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE fm_cakto_webhook_inbox ADD COLUMN callback_token TEXT",
    "ALTER TABLE fm_cakto_webhook_inbox ADD COLUMN external_subscription_id TEXT",
    (
        "CREATE INDEX IF NOT EXISTS fm_cakto_webhook_subscription_idx "
        "ON fm_cakto_webhook_inbox (external_subscription_id, occurred_at)"
    ),
)

CAKTO_SCHEMA_V3_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE fm_cakto_webhook_inbox ADD COLUMN external_customer_email TEXT",
)

CAKTO_SCHEMA_STATEMENTS: tuple[str, ...] = (
    *CAKTO_SCHEMA_V1_STATEMENTS,
    *CAKTO_SCHEMA_V2_STATEMENTS,
    *CAKTO_SCHEMA_V3_STATEMENTS,
)



def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CaktoStateConflictError("persisted datetime must be timezone-aware")
    return value.isoformat()


def _dt(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise CaktoStateConflictError(f"persisted {field_name} must be text")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CaktoStateConflictError(f"persisted {field_name} is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CaktoStateConflictError(f"persisted {field_name} must be timezone-aware")
    return result


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaktoStateConflictError(f"persisted {field_name} must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CaktoStateConflictError("persisted optional value must be text or null")
    return value


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CaktoStateConflictError(f"persisted {field_name} must be integer")
    return value


def _json_tuple(value: object, field_name: str) -> tuple[str, ...]:
    text = _text(value, field_name)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CaktoStateConflictError(f"persisted {field_name} is invalid JSON") from exc
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise CaktoStateConflictError(f"persisted {field_name} must be string array")
    return tuple(cast(list[str], decoded))


class CaktoSqlCommercialStore(CaktoCommercialStore):
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def put_cakto_plan_binding(self, binding: CaktoPlanBinding) -> CaktoPlanBinding:
        self._connection.execute(
            """
            INSERT INTO fm_cakto_plan_bindings (
                external_product_id, external_offer_id, plan_id,
                entitlement_ids_json, enabled
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (external_product_id, external_offer_id) DO UPDATE SET
                plan_id = excluded.plan_id,
                entitlement_ids_json = excluded.entitlement_ids_json,
                enabled = excluded.enabled
            """,
            (
                binding.external_product_id,
                binding.external_offer_id,
                binding.plan_id,
                json.dumps(binding.entitlement_ids, separators=(",", ":")),
                1 if binding.enabled else 0,
            ),
        )
        return binding

    def list_cakto_plan_bindings(self) -> tuple[CaktoPlanBinding, ...]:
        rows = self._connection.execute(
            """
            SELECT external_product_id, external_offer_id, plan_id,
                   entitlement_ids_json, enabled
            FROM fm_cakto_plan_bindings
            ORDER BY plan_id, external_product_id, external_offer_id
            """
        ).fetchall()
        return tuple(self._binding(row) for row in rows)

    def resolve_cakto_plan_binding(
        self,
        product_id: str,
        offer_id: str | None,
    ) -> CaktoPlanBinding | None:
        if offer_id is not None:
            row = self._connection.execute(
                """
                SELECT external_product_id, external_offer_id, plan_id,
                       entitlement_ids_json, enabled
                FROM fm_cakto_plan_bindings
                WHERE external_product_id = ? AND external_offer_id = ?
                """,
                (product_id, offer_id),
            ).fetchone()
            return None if row is None else self._binding(row)
        rows = self._connection.execute(
            """
            SELECT external_product_id, external_offer_id, plan_id,
                   entitlement_ids_json, enabled
            FROM fm_cakto_plan_bindings
            WHERE external_product_id = ? AND enabled = 1
            ORDER BY external_offer_id
            LIMIT 2
            """,
            (product_id,),
        ).fetchall()
        return self._binding(rows[0]) if len(rows) == 1 else None

    def receive_cakto_event(
        self,
        entry: CaktoWebhookInboxEntry,
    ) -> tuple[CaktoWebhookInboxEntry, bool]:
        existing = self.get_cakto_event(entry.event_key)
        if existing is not None:
            self._validate_replay(existing, entry)
            return existing, True
        try:
            self._connection.execute(
                """
                INSERT INTO fm_cakto_webhook_inbox (
                    event_key, event_type, order_id, external_product_id,
                    external_offer_id, external_customer_id, order_status,
                    occurred_at, payload_sha256, received_at, status, attempt_count,
                    next_attempt_at, last_error, tenant_id, outcome_reference,
                   callback_token, external_subscription_id, external_customer_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.event_key,
                    entry.event_type.value,
                    entry.order_id,
                    entry.external_product_id,
                    entry.external_offer_id,
                    entry.external_customer_id,
                    entry.order_status,
                    _iso(entry.occurred_at),
                    entry.payload_sha256,
                    _iso(entry.received_at),
                    entry.status.value,
                    entry.attempt_count,
                    None if entry.next_attempt_at is None else _iso(entry.next_attempt_at),
                    entry.last_error,
                    entry.tenant_id,
                    entry.outcome_reference,
                    entry.callback_token,
                    entry.external_subscription_id,
                    entry.external_customer_email,
                ),
            )
        except sqlite3.IntegrityError:
            raced = self.get_cakto_event(entry.event_key)
            if raced is None:
                raise
            self._validate_replay(raced, entry)
            return raced, True
        return entry, False

    def get_cakto_event(self, event_key: str) -> CaktoWebhookInboxEntry | None:
        row = self._connection.execute(
            """
            SELECT event_key, event_type, order_id, external_product_id,
                   external_offer_id, external_customer_id, order_status,
                   occurred_at, payload_sha256, received_at, status, attempt_count,
                   next_attempt_at, last_error, tenant_id, outcome_reference,
                   callback_token, external_subscription_id, external_customer_email
            FROM fm_cakto_webhook_inbox WHERE event_key = ?
            """,
            (event_key,),
        ).fetchone()
        return None if row is None else self._event(row)

    def list_due_cakto_events(
        self,
        now: datetime,
        limit: int,
    ) -> tuple[CaktoWebhookInboxEntry, ...]:
        rows = self._connection.execute(
            """
            SELECT event_key, event_type, order_id, external_product_id,
                   external_offer_id, external_customer_id, order_status,
                   occurred_at, payload_sha256, received_at, status, attempt_count,
                   next_attempt_at, last_error, tenant_id, outcome_reference,
                   callback_token, external_subscription_id, external_customer_email
            FROM fm_cakto_webhook_inbox
            WHERE status IN (?, ?)
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY received_at, event_key
            LIMIT ?
            """,
            (
                CaktoInboxStatus.RECEIVED.value,
                CaktoInboxStatus.RETRY_WAIT.value,
                _iso(now),
                limit,
            ),
        ).fetchall()
        return tuple(self._event(row) for row in rows)

    def mark_cakto_processed(
        self,
        event_key: str,
        *,
        tenant_id: str | None,
        outcome_reference: str,
    ) -> CaktoWebhookInboxEntry:
        self._connection.execute(
            """
            UPDATE fm_cakto_webhook_inbox
            SET status = ?, next_attempt_at = NULL, last_error = NULL,
                tenant_id = ?, outcome_reference = ?
            WHERE event_key = ?
            """,
            (CaktoInboxStatus.PROCESSED.value, tenant_id, outcome_reference, event_key),
        )
        return self._required_event(event_key)

    def mark_cakto_retry(
        self,
        event_key: str,
        *,
        next_attempt_at: datetime,
        error: str,
    ) -> CaktoWebhookInboxEntry:
        self._connection.execute(
            """
            UPDATE fm_cakto_webhook_inbox
            SET status = ?, attempt_count = attempt_count + 1,
                next_attempt_at = ?, last_error = ?
            WHERE event_key = ?
            """,
            (CaktoInboxStatus.RETRY_WAIT.value, _iso(next_attempt_at), error, event_key),
        )
        return self._required_event(event_key)

    def mark_cakto_dead_letter(
        self,
        event_key: str,
        *,
        error: str,
    ) -> CaktoWebhookInboxEntry:
        self._connection.execute(
            """
            UPDATE fm_cakto_webhook_inbox
            SET status = ?, attempt_count = attempt_count + 1,
                next_attempt_at = NULL, last_error = ?
            WHERE event_key = ?
            """,
            (CaktoInboxStatus.DEAD_LETTER.value, error, event_key),
        )
        return self._required_event(event_key)

    def get_cakto_tenant_by_customer(
        self,
        external_customer_id: str,
    ) -> CaktoCommercialTenant | None:
        row = self._connection.execute(
            """
            SELECT tenant_id, external_customer_id, created_at
            FROM fm_cakto_commercial_tenants WHERE external_customer_id = ?
            """,
            (external_customer_id,),
        ).fetchone()
        return None if row is None else CaktoCommercialTenant(
            tenant_id=_text(row[0], "tenant_id"),
            external_customer_id=_text(row[1], "external_customer_id"),
            created_at=_dt(row[2], "created_at"),
        )

    def put_cakto_tenant(self, tenant: CaktoCommercialTenant) -> CaktoCommercialTenant:
        existing = self.get_cakto_tenant_by_customer(tenant.external_customer_id)
        if existing is not None:
            if existing != tenant:
                raise CaktoStateConflictError(
                    "Cakto customer is already bound to another tenant"
                )
            return existing
        try:
            self._connection.execute(
                """
                INSERT INTO fm_cakto_commercial_tenants (
                    tenant_id, external_customer_id, created_at
                ) VALUES (?, ?, ?)
                """,
                (tenant.tenant_id, tenant.external_customer_id, _iso(tenant.created_at)),
            )
        except sqlite3.IntegrityError as exc:
            raise CaktoStateConflictError("Cakto commercial tenant identity conflict") from exc
        return tenant

    def get_cakto_entitlement(
        self,
        tenant_id: str,
        plan_id: str,
    ) -> CaktoCommercialEntitlement | None:
        row = self._connection.execute(
            """
            SELECT tenant_id, plan_id, entitlement_ids_json, status,
                   last_event_at, last_event_key
            FROM fm_cakto_entitlements WHERE tenant_id = ? AND plan_id = ?
            """,
            (tenant_id, plan_id),
        ).fetchone()
        return None if row is None else CaktoCommercialEntitlement(
            tenant_id=_text(row[0], "tenant_id"),
            plan_id=_text(row[1], "plan_id"),
            entitlement_ids=_json_tuple(row[2], "entitlement_ids_json"),
            status=CaktoEntitlementStatus(_text(row[3], "status")),
            last_event_at=_dt(row[4], "last_event_at"),
            last_event_key=_text(row[5], "last_event_key"),
        )

    def put_cakto_entitlement(
        self,
        entitlement: CaktoCommercialEntitlement,
    ) -> CaktoCommercialEntitlement:
        current = self.get_cakto_entitlement(entitlement.tenant_id, entitlement.plan_id)
        if current is not None and entitlement.last_event_at < current.last_event_at:
            raise CaktoStateConflictError("cannot overwrite entitlement with stale event")
        self._connection.execute(
            """
            INSERT INTO fm_cakto_entitlements (
                tenant_id, plan_id, entitlement_ids_json, status,
                last_event_at, last_event_key
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, plan_id) DO UPDATE SET
                entitlement_ids_json = excluded.entitlement_ids_json,
                status = excluded.status,
                last_event_at = excluded.last_event_at,
                last_event_key = excluded.last_event_key
            """,
            (
                entitlement.tenant_id,
                entitlement.plan_id,
                json.dumps(entitlement.entitlement_ids, separators=(",", ":")),
                entitlement.status.value,
                _iso(entitlement.last_event_at),
                entitlement.last_event_key,
            ),
        )
        return entitlement

    @staticmethod
    def _binding(row: Sequence[object]) -> CaktoPlanBinding:
        return CaktoPlanBinding(
            external_product_id=_text(row[0], "external_product_id"),
            external_offer_id=_text(row[1], "external_offer_id"),
            plan_id=_text(row[2], "plan_id"),
            entitlement_ids=_json_tuple(row[3], "entitlement_ids_json"),
            enabled=bool(_integer(row[4], "enabled")),
        )

    @staticmethod
    def _event(row: Sequence[object]) -> CaktoWebhookInboxEntry:
        next_attempt_raw = row[12]
        next_attempt = (
            None
            if next_attempt_raw is None
            else _dt(next_attempt_raw, "next_attempt_at")
        )
        return CaktoWebhookInboxEntry(
            event_key=_text(row[0], "event_key"),
            event_type=CaktoWebhookEvent(_text(row[1], "event_type")),
            order_id=_optional_text(row[2]),
            external_product_id=_text(row[3], "external_product_id"),
            external_offer_id=_optional_text(row[4]),
            external_customer_id=_optional_text(row[5]),
            order_status=_optional_text(row[6]),
            occurred_at=_dt(row[7], "occurred_at"),
            payload_sha256=_text(row[8], "payload_sha256"),
            received_at=_dt(row[9], "received_at"),
            status=CaktoInboxStatus(_text(row[10], "status")),
            attempt_count=_integer(row[11], "attempt_count"),
            next_attempt_at=next_attempt,
            last_error=_optional_text(row[13]),
            tenant_id=_optional_text(row[14]),
            outcome_reference=_optional_text(row[15]),
            callback_token=_optional_text(row[16]),
            external_subscription_id=_optional_text(row[17]),
            external_customer_email=_optional_text(row[18]),
        )

    @staticmethod
    def _validate_replay(
        existing: CaktoWebhookInboxEntry,
        received: CaktoWebhookInboxEntry,
    ) -> None:
        immutable_existing = (
            existing.event_type,
            existing.order_id,
            existing.external_product_id,
            existing.external_offer_id,
            existing.external_customer_id,
            existing.callback_token,
            existing.external_subscription_id,
            existing.occurred_at,
            existing.payload_sha256,
        )
        immutable_received = (
            received.event_type,
            received.order_id,
            received.external_product_id,
            received.external_offer_id,
            received.external_customer_id,
            received.callback_token,
            received.external_subscription_id,
            received.occurred_at,
            received.payload_sha256,
        )
        if immutable_existing != immutable_received:
            raise CaktoStateConflictError(
                "Cakto event identity was replayed with different content"
            )

    def _required_event(self, event_key: str) -> CaktoWebhookInboxEntry:
        entry = self.get_cakto_event(event_key)
        if entry is None:
            raise CaktoStateConflictError("Cakto inbox entry does not exist")
        return entry


class CaktoSqlUnitOfWork:
    def __init__(self, acquire: ConnectionContextFactory) -> None:
        self._acquire = acquire
        self._context: _ConnectionContext | None = None
        self._connection: _Connection | None = None
        self._commercial: CaktoSqlCommercialStore | None = None
        self._committed = False

    def __enter__(self) -> Self:
        context = self._acquire()
        connection = context.__enter__()
        self._context = context
        self._connection = connection
        self._commercial = CaktoSqlCommercialStore(connection)
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection
        context = self._context
        if connection is None or context is None:
            return
        try:
            if exc_type is not None or not self._committed:
                connection.rollback()
        finally:
            context.__exit__(exc_type, exc, traceback)
            self._connection = None
            self._commercial = None
            self._context = None

    @property
    def commercial(self) -> CaktoSqlCommercialStore:
        if self._commercial is None:
            raise CaktoStateConflictError("Cakto unit of work is not active")
        return self._commercial

    def commit(self) -> None:
        if self._connection is None:
            raise CaktoStateConflictError("Cakto unit of work is not active")
        self._connection.commit()
        self._committed = True


class CaktoCommercialDatabase:
    """Schema owner and unit-of-work factory over any certified DB-API-like connection."""

    def __init__(self, acquire: ConnectionContextFactory) -> None:
        self._acquire = acquire

    def initialize(self) -> bool:
        context = self._acquire()
        connection = context.__enter__()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fm_cakto_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            rows = connection.execute(
                "SELECT version FROM fm_cakto_schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(cast(int | str, row[0])) for row in rows}
            changed = False
            migrations = (
                (1, CAKTO_SCHEMA_V1_NAME, CAKTO_SCHEMA_V1_STATEMENTS),
                (2, CAKTO_SCHEMA_NAME, CAKTO_SCHEMA_V2_STATEMENTS),
                (3, CAKTO_SCHEMA_V3_NAME, CAKTO_SCHEMA_V3_STATEMENTS),
            )
            for version, name, statements in migrations:
                if version in applied:
                    continue
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO fm_cakto_schema_migrations (version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        version,
                        name,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                changed = True
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            context.__exit__(None, None, None)

    def require_current_schema(self) -> tuple[int, ...]:
        """Require the governed Cakto schema without applying startup DDL."""
        try:
            with self._acquire() as connection:
                rows = connection.execute(
                    "SELECT version FROM fm_cakto_schema_migrations ORDER BY version"
                ).fetchall()
        except Exception:
            raise CaktoStateConflictError(
                "Cakto schema is not at the certified migration version"
            ) from None
        versions = tuple(int(cast(int | str, row[0])) for row in rows)
        if versions != tuple(range(1, CAKTO_SCHEMA_VERSION + 1)):
            raise CaktoStateConflictError(
                "Cakto schema is not at the certified migration version"
            )
        return versions

    def unit_of_work(self) -> CaktoSqlUnitOfWork:
        return CaktoSqlUnitOfWork(self._acquire)

    def __call__(self) -> CaktoSqlUnitOfWork:
        return self.unit_of_work()


class SqliteCaktoCommercialDatabase(CaktoCommercialDatabase):
    def __init__(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()

        @contextmanager
        def acquire() -> Iterator[_Connection]:
            connection = sqlite3.connect(resolved, timeout=30.0)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            try:
                yield cast(_Connection, connection)
            finally:
                connection.close()

        super().__init__(cast(ConnectionContextFactory, acquire))
        self.path = resolved


def postgres_cakto_commercial_database(database: object) -> CaktoCommercialDatabase:
    """Bind to PostgresFiscalDatabase.connection without importing its private facade type."""

    connection_method = getattr(database, "connection", None)
    if not callable(connection_method):
        raise CaktoStateConflictError("database does not expose a connection context")
    return CaktoCommercialDatabase(cast(ConnectionContextFactory, connection_method))
