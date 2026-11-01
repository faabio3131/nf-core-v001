"""Durable SQLite database, migrations and unit-of-work for FM Fiscal V2."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TypeVar

from kordena_fiscal.domain import FiscalValidationError

from .customer_configuration_schema import (
    CUSTOMER_CONFIGURATION_NAME,
    CUSTOMER_CONFIGURATION_SCHEMA,
    CUSTOMER_CONFIGURATION_VERSION,
)
from .fiscal_scope_schema import FISCAL_SCOPE_NAME, FISCAL_SCOPE_SCHEMA, FISCAL_SCOPE_VERSION
from .ports import PersistenceStateError
from .cognitive_quota_schema import (
    COGNITIVE_QUOTA_NAME,
    COGNITIVE_QUOTA_SCHEMA,
    COGNITIVE_QUOTA_VERSION,
)
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


@dataclass(frozen=True, slots=True)
class _Migration:
    version: int
    name: str
    statements: tuple[str, ...]


_MIGRATIONS = (
    _Migration(
        version=1,
        name="v2_07_durable_fiscal_state",
        statements=(
            """
            CREATE TABLE fm_idempotency_attempts (
                key TEXT NOT NULL,
                generation INTEGER NOT NULL,
                request_fingerprint TEXT NOT NULL,
                document_id TEXT NOT NULL,
                status TEXT NOT NULL,
                result_reference TEXT,
                rejection_reason TEXT,
                PRIMARY KEY (key, generation)
            )
            """,
            """
            CREATE TABLE fm_fiscal_sequences (
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                model INTEGER NOT NULL,
                series INTEGER NOT NULL,
                first_number INTEGER NOT NULL,
                max_number INTEGER,
                last_reserved INTEGER NOT NULL,
                PRIMARY KEY (
                    host_namespace, tenant_id, unit_id, environment, model, series
                )
            )
            """,
            """
            CREATE TABLE fm_fiscal_lifecycle (
                document_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                history_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE fm_fiscal_bindings (
                binding_id TEXT PRIMARY KEY,
                host_namespace TEXT NOT NULL,
                external_tenant_id TEXT NOT NULL,
                external_unit_id TEXT NOT NULL,
                fiscal_account_id TEXT NOT NULL,
                fiscal_unit_id TEXT NOT NULL,
                UNIQUE (host_namespace, external_tenant_id, external_unit_id)
            )
            """,
            """
            CREATE TABLE fm_fiscal_outbox (
                entry_id TEXT PRIMARY KEY,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                deduplication_key TEXT NOT NULL,
                payload BLOB NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                lease_until TEXT,
                last_error TEXT,
                completion_reference TEXT
            )
            """,
            """
            CREATE INDEX fm_fiscal_outbox_due_idx
            ON fm_fiscal_outbox (status, available_at, lease_until)
            """,
            """
            CREATE TABLE fm_fiscal_archive (
                entry_id TEXT PRIMARY KEY,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                document_reference TEXT NOT NULL,
                kind TEXT NOT NULL,
                content BLOB NOT NULL,
                content_sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                archived_at TEXT NOT NULL,
                retention_policy_id TEXT NOT NULL,
                retention_policy_version INTEGER NOT NULL,
                retain_until TEXT,
                legal_basis_reference TEXT,
                previous_manifest_sha256 TEXT
            )
            """,
            """
            CREATE INDEX fm_fiscal_archive_document_idx
            ON fm_fiscal_archive (
                host_namespace, tenant_id, unit_id, environment, document_reference
            )
            """,
            """
            CREATE TABLE fm_fiscal_reconciliation (
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                selected_document_id TEXT,
                issues_json TEXT NOT NULL,
                PRIMARY KEY (
                    host_namespace, tenant_id, unit_id, environment, source_type, source_id
                )
            )
            """,
        ),
    ),
    _Migration(
        version=2,
        name="v2_08_durable_inbox",
        statements=(
            """
            CREATE TABLE fm_fiscal_inbox (
                entry_id TEXT PRIMARY KEY,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                producer TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload BLOB NOT NULL,
                payload_sha256 TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                causation_id TEXT,
                idempotency_key TEXT,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                processed_at TEXT,
                outcome_reference TEXT,
                last_error TEXT,
                UNIQUE (
                    host_namespace, tenant_id, unit_id, environment, producer, event_id
                )
            )
            """,
            """
            CREATE INDEX fm_fiscal_inbox_status_idx
            ON fm_fiscal_inbox (status, received_at, entry_id)
            """,
        ),
    ),
    _Migration(
        version=3,
        name="v2_08_delivery_audit_and_ordering",
        statements=(
            """
            CREATE TABLE fm_fiscal_outbox_ordering (
                entry_id TEXT PRIMARY KEY,
                ordering_key TEXT NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES fm_fiscal_outbox(entry_id)
            )
            """,
            """
            CREATE INDEX fm_fiscal_outbox_ordering_key_idx
            ON fm_fiscal_outbox_ordering (ordering_key, entry_id)
            """,
            """
            CREATE TABLE fm_fiscal_delivery_attempts (
                entry_id TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                ordering_key TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                next_available_at TEXT,
                outcome_reference TEXT,
                last_error TEXT,
                PRIMARY KEY (entry_id, attempt_count),
                FOREIGN KEY (entry_id) REFERENCES fm_fiscal_outbox(entry_id)
            )
            """,
            """
            CREATE INDEX fm_fiscal_delivery_attempts_status_idx
            ON fm_fiscal_delivery_attempts (status, started_at, entry_id, attempt_count)
            """,
        ),
    ),
    _Migration(
        version=4,
        name="v2_11_control_plane_durable_state",
        statements=(
            """
            CREATE TABLE fm_control_plane_organizations (
                tenant_id TEXT PRIMARY KEY,
                legal_name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE fm_control_plane_units (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled_environments_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, unit_id),
                FOREIGN KEY (tenant_id)
                    REFERENCES fm_control_plane_organizations(tenant_id)
            )
            """,
            """
            CREATE TABLE fm_control_plane_secret_references (
                reference_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                UNIQUE (tenant_id, unit_id, environment, kind),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_control_plane_fiscal_profiles (
                profile_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                cnpj TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                tax_regime INTEGER NOT NULL,
                state_registration_state TEXT NOT NULL,
                state_registration_number TEXT,
                state_registration_exempt INTEGER NOT NULL,
                primary_cnae TEXT NOT NULL,
                street TEXT NOT NULL,
                address_number TEXT NOT NULL,
                district TEXT NOT NULL,
                municipality_name TEXT NOT NULL,
                state_code TEXT NOT NULL,
                municipality_ibge_code TEXT,
                postal_code TEXT NOT NULL,
                complement TEXT,
                effective_from TEXT NOT NULL,
                effective_to TEXT,
                trade_name TEXT,
                municipal_registration_number TEXT,
                PRIMARY KEY (profile_id, version),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE INDEX fm_control_plane_fiscal_profiles_effective_idx
            ON fm_control_plane_fiscal_profiles (
                host_namespace, tenant_id, unit_id, environment,
                effective_from, effective_to
            )
            """,
            """
            CREATE TABLE fm_control_plane_audit (
                event_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT
            )
            """,
            """
            CREATE INDEX fm_control_plane_audit_tenant_idx
            ON fm_control_plane_audit (tenant_id, occurred_at, event_id)
            """,
        ),
    ),
    _Migration(
        version=5,
        name="v2_15_zero_code_commercial_configuration",
        statements=(
            """
            CREATE TABLE fm_control_plane_secret_references_v2 (
                reference_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                provider_id TEXT NOT NULL DEFAULT '',
                UNIQUE (tenant_id, unit_id, environment, kind, provider_id),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            INSERT INTO fm_control_plane_secret_references_v2 (
                reference_id, kind, tenant_id, unit_id, environment, provider_id
            )
            SELECT reference_id, kind, tenant_id, unit_id, environment, ''
            FROM fm_control_plane_secret_references
            """,
            "DROP TABLE fm_control_plane_secret_references",
            (
                "ALTER TABLE fm_control_plane_secret_references_v2 "
                "RENAME TO fm_control_plane_secret_references"
            ),
            """
            CREATE TABLE fm_commercial_provider_bindings (
                binding_id TEXT NOT NULL UNIQUE,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                document_kind TEXT NOT NULL,
                state_code TEXT NOT NULL,
                municipality_ibge_code TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (
                    tenant_id, unit_id, environment, document_kind,
                    state_code, municipality_ibge_code, operation
                ),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_commercial_product_profiles (
                profile_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                host_namespace TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                commercial_code TEXT NOT NULL,
                description TEXT NOT NULL,
                ncm TEXT NOT NULL,
                commercial_unit TEXT NOT NULL,
                taxable_unit TEXT NOT NULL,
                origin INTEGER NOT NULL,
                cest TEXT,
                gtin TEXT,
                fiscal_benefit_code TEXT,
                ibs_cbs_classification_code TEXT,
                effective_from TEXT NOT NULL,
                effective_to TEXT,
                PRIMARY KEY (profile_id, version),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE INDEX fm_commercial_product_profiles_effective_idx
            ON fm_commercial_product_profiles (
                tenant_id, unit_id, environment, product_id,
                effective_from, effective_to
            )
            """,
            """
            CREATE TABLE fm_commercial_unit_modules (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                module_id TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, unit_id, environment, module_id),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_commercial_webhook_destinations (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, unit_id, environment, destination_id),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_commercial_provider_runtime_policies (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                policy_id TEXT NOT NULL,
                connect_timeout_seconds REAL NOT NULL,
                read_timeout_seconds REAL NOT NULL,
                max_attempts INTEGER NOT NULL,
                base_delay_seconds REAL NOT NULL,
                max_delay_seconds REAL NOT NULL,
                jitter_ratio REAL NOT NULL,
                circuit_failure_threshold INTEGER NOT NULL,
                circuit_recovery_seconds REAL NOT NULL,
                circuit_success_threshold INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, unit_id, environment, provider_id),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_commercial_numbering_configurations (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                model INTEGER NOT NULL,
                series INTEGER NOT NULL,
                first_number INTEGER NOT NULL,
                max_number INTEGER,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, unit_id, environment, model),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
            """
            CREATE TABLE fm_commercial_workload_credentials (
                credential_id TEXT PRIMARY KEY,
                caller_id TEXT NOT NULL,
                host_namespace TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                grants_json TEXT NOT NULL,
                secret_sha256 TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE fm_commercial_homologation_evidence (
                tenant_id TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                document_kind TEXT NOT NULL,
                state_code TEXT NOT NULL,
                municipality_ibge_code TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                provider_adapter_available INTEGER NOT NULL,
                credentials_reference_configured INTEGER NOT NULL,
                signer_capability INTEGER NOT NULL,
                csc_reference_configured INTEGER NOT NULL,
                transport_configured INTEGER NOT NULL,
                resilience_certified INTEGER NOT NULL,
                contract_tests_certified INTEGER NOT NULL,
                jurisdiction_mapping INTEGER NOT NULL,
                operation_supported INTEGER NOT NULL,
                requires_signer INTEGER NOT NULL,
                requires_csc INTEGER NOT NULL,
                external_evidence_id TEXT,
                external_official INTEGER NOT NULL,
                recorded_at TEXT,
                PRIMARY KEY (
                    tenant_id, unit_id, environment, provider_id, document_kind,
                    state_code, municipality_ibge_code, operation
                ),
                FOREIGN KEY (tenant_id, unit_id)
                    REFERENCES fm_control_plane_units(tenant_id, unit_id)
            )
            """,
        ),
    ),
)


class SqliteFiscalUnitOfWork:
    """One explicit local transaction spanning all durable fiscal repositories."""

    def __init__(self, database: SqliteFiscalDatabase) -> None:
        self._database = database
        self._connection: sqlite3.Connection | None = None
        self._committed = False
        self._idempotency: SqliteIdempotencyStore | None = None
        self._sequences: SqliteFiscalSequenceStore | None = None
        self._inbox: SqliteFiscalInboxStore | None = None
        self._outbox: SqliteFiscalOutboxStore | None = None
        self._outbox_ordering: SqliteFiscalOutboxOrderingStore | None = None
        self._delivery_audit: SqliteFiscalDeliveryAuditStore | None = None
        self._archive: SqliteFiscalArchiveStore | None = None
        self._bindings: SqliteBindingRepository | None = None
        self._lifecycle: SqliteLifecycleRepository | None = None
        self._reconciliations: SqliteReconciliationRepository | None = None
        self._control_plane: SqliteControlPlaneStore | None = None
        self._commercial: SqliteCommercialConfigurationStore | None = None
        self._secret_bindings: SqliteSecretBindingStore | None = None

    def __enter__(self) -> SqliteFiscalUnitOfWork:
        if self._connection is not None:
            raise PersistenceStateError("unit of work cannot be entered twice")
        connection = self._database._connect()
        connection.execute("BEGIN IMMEDIATE")
        self._connection = connection
        self._committed = False
        self._idempotency = SqliteIdempotencyStore(connection)
        self._sequences = SqliteFiscalSequenceStore(connection)
        self._inbox = SqliteFiscalInboxStore(connection)
        self._outbox = SqliteFiscalOutboxStore(connection)
        self._outbox_ordering = SqliteFiscalOutboxOrderingStore(connection)
        self._delivery_audit = SqliteFiscalDeliveryAuditStore(connection)
        self._archive = SqliteFiscalArchiveStore(connection)
        self._bindings = SqliteBindingRepository(connection)
        self._lifecycle = SqliteLifecycleRepository(connection)
        self._reconciliations = SqliteReconciliationRepository(connection)
        self._control_plane = SqliteControlPlaneStore(connection)
        self._commercial = SqliteCommercialConfigurationStore(connection)
        self._secret_bindings = SqliteSecretBindingStore(connection)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                connection.rollback()
        finally:
            connection.close()
            self._connection = None

    def _require(self, value: _T | None, name: str) -> _T:
        if self._connection is None or value is None:
            raise PersistenceStateError(f"unit of work {name} repository is not active")
        return value

    @property
    def idempotency(self) -> SqliteIdempotencyStore:
        return self._require(self._idempotency, "idempotency")

    @property
    def sequences(self) -> SqliteFiscalSequenceStore:
        return self._require(self._sequences, "sequences")

    @property
    def inbox(self) -> SqliteFiscalInboxStore:
        return self._require(self._inbox, "inbox")

    @property
    def outbox(self) -> SqliteFiscalOutboxStore:
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
        if self._connection is None:
            raise PersistenceStateError("unit of work is not active")
        self._connection.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._connection is None:
            raise PersistenceStateError("unit of work is not active")
        self._connection.rollback()
        self._committed = False


class SqliteFiscalDatabase:
    """Filesystem-backed database handle with controlled schema migration."""

    def __init__(self, path: str | Path) -> None:
        raw = str(path).strip()
        if not raw:
            raise FiscalValidationError("SQLite database path must not be blank")
        if raw == ":memory:":
            raise FiscalValidationError(
                "durable adapter rejects ':memory:'; use a filesystem database"
            )
        self._path = Path(raw).expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> tuple[int, ...]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fm_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            rows = connection.execute(
                "SELECT version FROM fm_schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row[0]) for row in rows}
            new_versions: list[int] = []
            for migration in _MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO fm_schema_migrations (version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        migration.version,
                        migration.name,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                new_versions.append(migration.version)
            if FISCAL_SCOPE_VERSION not in applied:
                for statement in FISCAL_SCOPE_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO fm_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (
                        FISCAL_SCOPE_VERSION,
                        FISCAL_SCOPE_NAME,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                new_versions.append(FISCAL_SCOPE_VERSION)
            if CUSTOMER_CONFIGURATION_VERSION not in applied:
                for statement in CUSTOMER_CONFIGURATION_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO fm_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (
                        CUSTOMER_CONFIGURATION_VERSION,
                        CUSTOMER_CONFIGURATION_NAME,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                new_versions.append(CUSTOMER_CONFIGURATION_VERSION)
            if SECRET_BINDING_VERSION not in applied:
                for statement in SECRET_BINDING_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO fm_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (SECRET_BINDING_VERSION, SECRET_BINDING_NAME,
                     datetime.now().astimezone().isoformat()),
                )
                new_versions.append(SECRET_BINDING_VERSION)
            if PUBLIC_TRIAL_RATE_VERSION not in applied:
                for statement in PUBLIC_TRIAL_RATE_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (
                        PUBLIC_TRIAL_RATE_VERSION,
                        PUBLIC_TRIAL_RATE_NAME,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                new_versions.append(PUBLIC_TRIAL_RATE_VERSION)
            if COGNITIVE_QUOTA_VERSION not in applied:
                for statement in COGNITIVE_QUOTA_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO fm_schema_migrations (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (
                        COGNITIVE_QUOTA_VERSION,
                        COGNITIVE_QUOTA_NAME,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                new_versions.append(COGNITIVE_QUOTA_VERSION)
            connection.commit()
            return tuple(new_versions)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def applied_migrations(self) -> tuple[int, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT version FROM fm_schema_migrations ORDER BY version"
            ).fetchall()
            return tuple(int(row[0]) for row in rows)
        except sqlite3.OperationalError:
            return ()
        finally:
            connection.close()

    def unit_of_work(self) -> SqliteFiscalUnitOfWork:
        return SqliteFiscalUnitOfWork(self)

    def __call__(self) -> SqliteFiscalUnitOfWork:
        return self.unit_of_work()
