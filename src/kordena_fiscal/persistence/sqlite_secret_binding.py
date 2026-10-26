"""Same DB-API repository used by the canonical SQLite/PostgreSQL UOW."""

from __future__ import annotations

import json
import sqlite3

from kordena_fiscal.security.secret_binding import SecretBinding

from .ports import PersistenceConflictError, PersistenceStateError


class SqliteSecretBindingStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, reference_id: str) -> SecretBinding | None:
        row = self._connection.execute(
            "SELECT revision, metadata_json FROM fm_secret_bindings WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            binding = SecretBinding.from_metadata(json.loads(row[1]))
            if binding.reference_id != reference_id or binding.revision != row[0]:
                raise ValueError
            return binding
        except Exception:
            raise PersistenceStateError("external secret binding is invalid") from None

    def list_active_signatures(
        self, *, workload_id: str, runtime_environment: str
    ) -> tuple[SecretBinding, ...]:
        """Canonical read-only registry for the single production Worker.

        The source is fm_secret_bindings, never a second tenant registry.
        Reject malformed rows instead of silently skipping corrupted authority.
        """
        rows = self._connection.execute(
            "SELECT reference_id, revision, metadata_json FROM fm_secret_bindings "
            "ORDER BY reference_id"
        ).fetchall()
        found = []
        for reference_id, revision, payload in rows:
            try:
                binding = SecretBinding.from_metadata(json.loads(payload))
                if binding.reference_id != reference_id or binding.revision != revision:
                    raise ValueError
            except Exception:
                raise PersistenceStateError("external secret binding registry invalid") from None
            if (
                binding.workload_id == workload_id
                and binding.runtime_environment == runtime_environment
                and binding.kind == "signature"
                and binding.state == "active"
            ):
                found.append(binding)
        return tuple(found)

    def put(self, binding: SecretBinding, *, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise PersistenceConflictError("invalid binding expected revision")
        if binding.revision != expected_revision + 1:
            raise PersistenceConflictError("invalid binding next revision")
        payload = json.dumps(binding.metadata(), sort_keys=True, separators=(",", ":"))
        if expected_revision == 0:
            try:
                self._connection.execute(
                    "INSERT INTO fm_secret_bindings (reference_id, revision, metadata_json) "
                    "VALUES (?, ?, ?)",
                    (binding.reference_id, binding.revision, payload),
                )
            except sqlite3.IntegrityError:
                raise PersistenceConflictError("external secret binding already exists") from None
        else:
            cursor = self._connection.execute(
                "UPDATE fm_secret_bindings SET revision = ?, metadata_json = ? "
                "WHERE reference_id = ? AND revision = ?",
                (binding.revision, payload, binding.reference_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise PersistenceConflictError("external secret binding revision conflict")
