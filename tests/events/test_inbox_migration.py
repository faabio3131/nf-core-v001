from __future__ import annotations

import sqlite3

from kordena_fiscal.persistence import SqliteFiscalDatabase


def _remove_v5(connection: sqlite3.Connection) -> None:
    # Reconstruct the earlier schema, not just its migration ledger.
    # COG-02 is a newer additive schema; remove its dependent rows/tables first.
    connection.execute("DROP TABLE fm_cognitive_token_reservations")
    connection.execute("DROP TABLE fm_cognitive_token_counters")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 19")
    connection.execute("DROP TABLE fm_public_trial_rate_windows")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 18")
    connection.execute("DROP TABLE fm_secret_bindings")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 17")
    connection.execute("DROP TABLE fm_configuration_commands")
    connection.execute("DROP TABLE fm_configuration_revisions")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 14")
    connection.execute("DROP INDEX fm_idempotency_document_idx")
    connection.execute("DROP INDEX fm_fiscal_lifecycle_scope_idx")
    connection.execute("DROP INDEX fm_fiscal_outbox_scope_idx")
    connection.execute("DROP INDEX fm_fiscal_archive_scope_idx")
    for column in ("host_namespace", "tenant_id", "unit_id", "environment"):
        connection.execute(f"ALTER TABLE fm_fiscal_lifecycle DROP COLUMN {column}")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 13")

    for table in (
        "fm_commercial_homologation_evidence",
        "fm_commercial_workload_credentials",
        "fm_commercial_numbering_configurations",
        "fm_commercial_provider_runtime_policies",
        "fm_commercial_webhook_destinations",
        "fm_commercial_unit_modules",
        "fm_commercial_product_profiles",
        "fm_commercial_provider_bindings",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DROP TABLE fm_control_plane_secret_references")
    connection.execute(
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
        """
    )
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 5")


def _remove_v4(connection: sqlite3.Connection) -> None:
    connection.execute("DROP INDEX fm_control_plane_audit_tenant_idx")
    connection.execute("DROP TABLE fm_control_plane_audit")
    connection.execute("DROP INDEX fm_control_plane_fiscal_profiles_effective_idx")
    connection.execute("DROP TABLE fm_control_plane_fiscal_profiles")
    connection.execute("DROP TABLE fm_control_plane_secret_references")
    connection.execute("DROP TABLE fm_control_plane_units")
    connection.execute("DROP TABLE fm_control_plane_organizations")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 4")


def _remove_v3(connection: sqlite3.Connection) -> None:
    connection.execute("DROP INDEX fm_fiscal_delivery_attempts_status_idx")
    connection.execute("DROP TABLE fm_fiscal_delivery_attempts")
    connection.execute("DROP INDEX fm_fiscal_outbox_ordering_key_idx")
    connection.execute("DROP TABLE fm_fiscal_outbox_ordering")
    connection.execute("DELETE FROM fm_schema_migrations WHERE version = 3")


def test_v2_07_database_upgrades_through_all_later_migrations_without_reapplying_v1(
    tmp_path,
) -> None:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-upgrade.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    # Reconstruct the exact migration-ledger state of a certified V2-07 database:
    # migration 1 remains; V2-08 and V2-11 migrations are absent.
    with sqlite3.connect(database.path) as connection:
        _remove_v5(connection)
        _remove_v4(connection)
        _remove_v3(connection)
        connection.execute("DROP INDEX fm_fiscal_inbox_status_idx")
        connection.execute("DROP TABLE fm_fiscal_inbox")
        connection.execute("DELETE FROM fm_schema_migrations WHERE version = 2")
        connection.commit()

    assert database.applied_migrations() == (1,)
    assert database.initialize() == (2, 3, 4, 5, 13, 14, 17, 18, 19)
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "fm_fiscal_inbox" in tables
    assert "fm_fiscal_outbox_ordering" in tables
    assert "fm_fiscal_delivery_attempts" in tables
    assert "fm_control_plane_organizations" in tables
    assert "fm_control_plane_fiscal_profiles" in tables


def test_v2_08_inbox_checkpoint_upgrades_delivery_audit_and_control_plane(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-v2-08-upgrade.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        _remove_v5(connection)
        _remove_v4(connection)
        _remove_v3(connection)
        connection.commit()

    assert database.applied_migrations() == (1, 2)
    assert database.initialize() == (3, 4, 5, 13, 14, 17, 18, 19)
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "fm_fiscal_inbox" in tables
    assert "fm_fiscal_outbox_ordering" in tables
    assert "fm_fiscal_delivery_attempts" in tables
    assert "fm_control_plane_units" in tables
    assert "fm_control_plane_audit" in tables


def test_v2_08_final_checkpoint_applies_only_control_plane_v4(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "fm-fiscal-v2-08-final-upgrade.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    with sqlite3.connect(database.path) as connection:
        _remove_v5(connection)
        _remove_v4(connection)
        connection.commit()

    assert database.applied_migrations() == (1, 2, 3)
    assert database.initialize() == (4, 5, 13, 14, 17, 18, 19)
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
