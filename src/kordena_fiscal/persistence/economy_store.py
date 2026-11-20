"""Scope-bound PostgreSQL repository primitives for economy fiscal T01.

The caller must supply a scope derived from an authenticated, authorized request.
The connection must be dedicated to the transaction and use the restricted
runtime role. Do not expose SQL or scope-setting capability to clients or AI.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalValidationError

from .economy_schema import SCOPE_COLUMNS, TABLES


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

    @staticmethod
    def _identity(record_id: str, version: int) -> None:
        if (
            not isinstance(record_id, str) or not record_id.strip()
            or len(record_id) > 128 or type(version) is not int or version < 1
        ):
            raise FiscalValidationError("invalid economy record identity")

    @staticmethod
    def _text(value: str, field: str) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise FiscalValidationError(f"invalid economy {field}")

    @staticmethod
    def _cents(value: int, *, positive: bool = False) -> None:
        if type(value) is not int or not int(positive) <= value <= 2**63 - 1:
            raise FiscalValidationError("invalid economy amount in integer cents")

    def _append(
        self, table: str, columns: tuple[str, ...], values: tuple[Any, ...]
    ) -> None:
        if table not in TABLES:
            raise FiscalValidationError("unknown economy persistence table")
        names = (*SCOPE_COLUMNS.split(", "), *columns, "created_at")
        # Identifiers are composed by psycopg, values are always bound parameters.
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, names)),
            sql.SQL(", ").join(sql.Placeholder() for _ in names),
        )
        self._conn.execute(
            statement, (*self._scope.identity_material, *values, datetime.now(UTC)),
        )

    def append_snapshot(
        self, *, record_id: str, version: int, competence: date,
        issuer: Cnpj, content: Mapping[str, Any],
    ) -> str:
        self._identity(record_id, version)
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


    def append_benefit(
        self, *, record_id: str, version: int, tax_code: str, jurisdiction: str,
        normative_reference: str, valid_from: date, valid_until: date | None,
        content: Mapping[str, Any],
    ) -> str:
        self._identity(record_id, version)
        self._text(tax_code, "tax code")
        self._text(jurisdiction, "jurisdiction")
        self._text(normative_reference, "normative reference")
        if valid_until is not None and valid_until <= valid_from:
            raise FiscalValidationError("invalid benefit validity")
        payload, digest = _digest(content)
        self._append(
            "fm_economy_benefits",
            ("record_id", "version", "tax_code", "jurisdiction", "normative_reference",
             "valid_from", "valid_until", "content", "digest"),
            (record_id, version, tax_code, jurisdiction, normative_reference,
             valid_from, valid_until, Jsonb(json.loads(payload)), digest),
        )
        return digest

    def append_opportunity(
        self, *, record_id: str, version: int, snapshot_id: str, snapshot_version: int,
        benefit_id: str | None, benefit_version: int | None,
        estimated_cents: int, content: Mapping[str, Any],
    ) -> str:
        self._identity(record_id, version)
        self._identity(snapshot_id, snapshot_version)
        if (benefit_id is None) != (benefit_version is None):
            raise FiscalValidationError("opportunity benefit reference is incomplete")
        if benefit_id is not None and benefit_version is not None:
            self._identity(benefit_id, benefit_version)
        self._cents(estimated_cents)
        payload, digest = _digest(content)
        self._append(
            "fm_economy_opportunities",
            ("record_id", "version", "snapshot_id", "snapshot_version", "benefit_id",
             "benefit_version", "estimated_cents", "content", "digest"),
            (record_id, version, snapshot_id, snapshot_version, benefit_id, benefit_version,
             estimated_cents, Jsonb(json.loads(payload)), digest),
        )
        return digest

    def append_credit_entry(
        self, *, record_id: str, opportunity_id: str, opportunity_version: int,
        tax_code: str, competence: date, movement: str, amount_cents: int,
        evidence_reference: str,
    ) -> None:
        """Storage primitive only; T18 must enforce balanced postings and limits."""
        self._identity(record_id, 1)
        self._identity(opportunity_id, opportunity_version)
        self._text(tax_code, "tax code")
        self._text(evidence_reference, "evidence reference")
        self._cents(amount_cents, positive=True)
        if competence.day != 1 or movement not in {
            "identified", "reserved", "released", "compensated", "reversed",
        }:
            raise FiscalValidationError("invalid credit entry")
        self._append(
            "fm_economy_credit_entries",
            ("record_id", "opportunity_id", "opportunity_version", "tax_code",
             "competence", "movement", "amount_cents", "evidence_reference"),
            (record_id, opportunity_id, opportunity_version, tax_code,
             competence, movement, amount_cents, evidence_reference),
        )

    def append_dossier(
        self, *, record_id: str, version: int, opportunity_id: str,
        opportunity_version: int, archive_reference: str, digest: str,
    ) -> None:
        self._identity(record_id, version)
        self._identity(opportunity_id, opportunity_version)
        self._text(archive_reference, "archive reference")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise FiscalValidationError("invalid dossier digest")
        self._append(
            "fm_economy_dossiers",
            ("record_id", "version", "opportunity_id", "opportunity_version",
             "archive_reference", "digest"),
            (record_id, version, opportunity_id, opportunity_version,
             archive_reference, digest),
        )

    def records(self, table: str, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        """Read-only bounded scope projection; public API must enforce its own RBAC."""
        if table not in TABLES or type(limit) is not int or not 1 <= limit <= 500:
            raise FiscalValidationError("invalid economy projection")
        statement = sql.SQL(
            "SELECT to_jsonb(r) FROM {} AS r WHERE host_namespace=%s AND tenant_id=%s "
            "AND unit_id=%s AND environment=%s ORDER BY created_at DESC, record_id LIMIT %s"
        ).format(sql.Identifier(table))
        rows = self._conn.execute(statement, (*self._scope.identity_material, limit)).fetchall()
        return tuple(dict(row[0]) for row in rows)
