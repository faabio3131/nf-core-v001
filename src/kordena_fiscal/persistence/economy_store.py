"""Scope-bound PostgreSQL repository primitives for economy fiscal T01.

The caller must supply a scope derived from an authenticated, authorized request.
The connection must be dedicated to the transaction and use the restricted
runtime role. Do not expose SQL or scope-setting capability to clients or AI.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from psycopg import Connection

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalValidationError

from .economy_schema import SCOPE_COLUMNS


def _digest(content: Mapping[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(
        dict(content), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    encoded = serialized.encode("utf-8")
    if len(encoded) > 1_048_576:
        raise FiscalValidationError("economy snapshot exceeds allowed size")
    return serialized, hashlib.sha256(encoded).hexdigest()


class EconomyStore:
    """Append/read primitives in one explicitly scoped transaction."""

    def __init__(self, conn: Connection[Any], scope: ExecutionScope) -> None:
        self._conn = conn
        self._scope = scope

    @staticmethod
    @contextmanager
    def transaction(
        conn: Connection[Any], scope: ExecutionScope,
    ) -> Iterator[EconomyStore]:
        if not scope.host_namespace:
            raise FiscalValidationError("economy requires bound fiscal host scope")
        if conn.info.transaction_status.name != "IDLE":
            raise FiscalValidationError("economy transaction requires idle connection")
        with conn.transaction():
            privileged = conn.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            if privileged is None or privileged[0]:
                raise FiscalValidationError("economy runtime role must not bypass RLS")
            settings = tuple(zip(SCOPE_COLUMNS.split(", "), scope.identity_material, strict=True))
            for key, value in settings:
                conn.execute("SELECT set_config(%s, %s, true)", ("nfcore.economy_" + key, value))
            yield EconomyStore(conn, scope)

    def append_snapshot(
        self, *, record_id: str, version: int, competence: date,
        issuer: Cnpj, content: Mapping[str, Any],
    ) -> str:
        if not record_id.strip() or type(version) is not int or version < 1:
            raise FiscalValidationError("invalid snapshot identity")
        if competence.day != 1:
            raise FiscalValidationError("competence must use first day of month")
        payload, digest = _digest(content)
        values = (
            *self._scope.identity_material, record_id, version, competence,
            issuer.value, payload, digest, datetime.now(UTC),
        )
        self._conn.execute(
            f"""INSERT INTO fm_economy_snapshots
                ({SCOPE_COLUMNS}, record_id, version, competence, issuer_cnpj,
                 content, digest, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            values,
        )
        return digest

    def snapshot(self, record_id: str, version: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT content, digest FROM fm_economy_snapshots
               WHERE host_namespace=%s AND tenant_id=%s AND unit_id=%s AND environment=%s
                 AND record_id=%s AND version=%s""",
            (*self._scope.identity_material, record_id, version),
        ).fetchone()
        if row is None:
            return None
        payload = row[0]
        if not isinstance(payload, dict) or _digest(payload)[1] != row[1]:
            raise FiscalValidationError("economy snapshot integrity mismatch")
        return dict(payload)
