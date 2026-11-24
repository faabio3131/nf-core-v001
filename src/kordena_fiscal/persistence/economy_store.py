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


def _validate_json(value: Any, depth: int = 0) -> None:
    """Fiscal values must be exact JSON integers or explicit decimal strings."""
    if depth > 32:
        raise FiscalValidationError("economy record JSON is too deeply nested")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise FiscalValidationError("economy record text contains a null byte")
        return
    if type(value) is int and -(2**63) <= value < 2**63:
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FiscalValidationError("economy record JSON keys must be text")
            _validate_json(key, depth + 1)
            _validate_json(item, depth + 1)
        return
    raise FiscalValidationError("economy record JSON requires exact values, not floats")


def _digest(content: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(content, Mapping):
        raise FiscalValidationError("economy record content must be a JSON object")
    _validate_json(dict(content))
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
        self._active = False

    def _require_active(self) -> None:
        if not self._active or self._conn.info.transaction_status.name != "INTRANS":
            raise FiscalValidationError("economy store requires an active scoped transaction")

    @property
    def scope_identity(self) -> tuple[str, ...]:
        """Read the canonical identity of the active scoped transaction."""
        self._require_active()
        return self._scope.identity_material

    @staticmethod
    @contextmanager
    def transaction(
        conn: Connection[Any], scope: ExecutionScope, *, runtime_role: str | None = None,
        read_only: bool = False,
    ) -> Iterator[EconomyStore]:
        if not scope.host_namespace:
            raise FiscalValidationError("economy requires bound fiscal host scope")
        if conn.info.transaction_status.name != "IDLE":
            raise FiscalValidationError("economy transaction requires idle connection")
        with conn.transaction():
            if read_only:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if runtime_role is not None:
                EconomyStore._text(runtime_role, "runtime role")
                conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(runtime_role)))
            privileged = conn.execute(
                "SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb "
                "FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            if privileged is None or privileged[0]:
                raise FiscalValidationError("economy runtime role must not bypass RLS")
            ownership = conn.execute(
                "SELECT count(*) FROM pg_class WHERE oid = ANY("
                "ARRAY(SELECT to_regclass(name)::oid FROM unnest(%s::text[]) AS name)) "
                "AND pg_has_role(current_user, relowner, 'MEMBER')",
                (list(TABLES),),
            ).fetchone()
            if ownership is None or ownership[0]:
                raise FiscalValidationError("economy runtime role must not own fiscal tables")
            settings = tuple(zip(SCOPE_COLUMNS.split(", "), scope.identity_material, strict=True))
            for key, value in settings:
                conn.execute("SELECT set_config(%s, %s, true)", ("nfcore.economy_" + key, value))
            store = EconomyStore(conn, scope)
            store._active = True
            try:
                yield store
            finally:
                store._active = False

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
        self._require_active()
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
        self._require_active()
        self._identity(record_id, version)
        if type(competence) is not date or competence.day != 1:
            raise FiscalValidationError("competence must use first day of month")
        if not isinstance(issuer, Cnpj):
            raise FiscalValidationError("invalid economy issuer")
        payload, digest = _digest(content)
        self._append(
            "fm_economy_snapshots",
            ("record_id", "version", "competence", "issuer_cnpj", "content", "digest"),
            (record_id, version, competence, issuer.value, Jsonb(json.loads(payload)), digest),
        )
        return digest

    def snapshot(self, record_id: str, version: int) -> dict[str, Any] | None:
        self._require_active()
        self._identity(record_id, version)
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
        if type(valid_from) is not date or (
            valid_until is not None
            and (type(valid_until) is not date or valid_until <= valid_from)
        ):
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
        if type(competence) is not date or competence.day != 1 or movement not in {
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

    def record(
        self, table: str, record_id: str, version: int | None = None,
    ) -> dict[str, Any] | None:
        """Exact immutable version, or newest version of a named record."""
        self._require_active()
        if table not in TABLES or table == "fm_economy_credit_entries":
            raise FiscalValidationError("invalid versioned economy table")
        self._identity(record_id, version if version is not None else 1)
        query = sql.SQL(
            "SELECT to_jsonb(r) FROM {} AS r WHERE host_namespace=%s AND tenant_id=%s "
            "AND unit_id=%s AND environment=%s AND record_id=%s "
            "AND (%s::int IS NULL OR version=%s::int) ORDER BY version DESC LIMIT 1"
        ).format(sql.Identifier(table))
        row = self._conn.execute(
            query, (*self._scope.identity_material, record_id, version, version),
        ).fetchone()
        if row is None:
            return None
        record = dict(row[0])
        if "content" in record:
            content = record["content"]
            if not isinstance(content, dict) or _digest(content)[1] != record["digest"]:
                raise FiscalValidationError("economy record integrity mismatch")
        return record


    def unique_monthly_snapshot(
        self, issuer: str, competence: date, schema: str,
    ) -> dict[str, Any] | None:
        """Resolve a unique reviewed history; a superseding row may invalidate it."""
        self._require_active()
        scope = self._scope.identity_material
        rows = self._conn.execute(
            """SELECT DISTINCT record_id FROM fm_economy_snapshots
               WHERE host_namespace=%s AND tenant_id=%s AND unit_id=%s AND environment=%s
                 AND issuer_cnpj=%s AND competence=%s AND content->>'schema_version'=%s
               LIMIT 2""",
            (*scope, issuer, competence, schema),
        ).fetchall()
        if len(rows) != 1:
            return None
        record = self.record("fm_economy_snapshots", rows[0][0])
        if (record is None or record["issuer_cnpj"] != issuer
                or record["competence"] != competence.isoformat()
                or record["content"].get("schema_version") != schema
                or record["content"].get("review_status") != "reviewed"):
            return None
        return record

    def benefit_version_at(self, record_id: str, competence: date) -> int | None:
        """The latest amendment effective before the end of this competence.

        An amendment beginning next month must not invalidate this month.
        A mid-month revocation DOES supersede a monthly candidate.
        """
        self._require_active()
        self._identity(record_id, 1)
        if type(competence) is not date or competence.day != 1:
            raise FiscalValidationError("invalid monthly state competence")
        following = date(
            competence.year + (competence.month == 12),
            competence.month % 12 + 1, 1,
        )
        row = self._conn.execute(
            """SELECT version FROM fm_economy_benefits
               WHERE host_namespace=%s AND tenant_id=%s AND unit_id=%s
                 AND environment=%s AND record_id=%s AND valid_from < %s
               ORDER BY version DESC LIMIT 1""",
            (*self._scope.identity_material, record_id, following),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def federal_benefit_candidates(
        self, *, competence: date, schema_version: str, limit: int = 500,
    ) -> tuple[dict[str, Any], ...]:
        """Rank effective amendments before checking schema or limiting records."""
        self._require_active()
        if (
            type(competence) is not date or competence.day != 1
            or not isinstance(schema_version, str)
            or not re.fullmatch(r"[a-zA-Z0-9./_-]{1,128}", schema_version)
            or type(limit) is not int or not 1 <= limit <= 500
        ):
            raise FiscalValidationError("invalid federal benefit catalog projection")
        following = date(
            competence.year + (competence.month == 12),
            competence.month % 12 + 1, 1,
        )
        rows = self._conn.execute(
            """WITH ranked AS (
                 SELECT to_jsonb(r) AS payload,
                        ROW_NUMBER() OVER (
                            PARTITION BY r.record_id ORDER BY r.version DESC
                        ) AS rank_version
                   FROM fm_economy_benefits AS r
                  WHERE r.host_namespace=%s AND r.tenant_id=%s AND r.unit_id=%s
                    AND r.environment=%s AND r.valid_from < %s
                    AND EXISTS (
                        SELECT 1 FROM fm_economy_benefits AS anchor
                         WHERE anchor.host_namespace=r.host_namespace
                           AND anchor.tenant_id=r.tenant_id
                           AND anchor.unit_id=r.unit_id
                           AND anchor.environment=r.environment
                           AND anchor.record_id=r.record_id
                           AND anchor.jurisdiction='BR'
                           AND anchor.content->>'schema_version'=%s
                    )
               )
               SELECT payload FROM ranked WHERE rank_version=1
               ORDER BY payload->>'record_id' LIMIT %s""",
            (*self._scope.identity_material, following, schema_version, limit),
        ).fetchall()
        results = tuple(dict(row[0]) for row in rows)
        for record in results:
            content = record.get("content")
            if not isinstance(content, dict) or _digest(content)[1] != record["digest"]:
                raise FiscalValidationError("federal candidate record integrity mismatch")
        return results

    def state_benefit_candidates(
        self, *, jurisdiction: str, competence: date, schema_version: str,
        limit: int = 500,
    ) -> tuple[tuple[dict[str, Any], ...], bool]:
        return self._regional_candidates(jurisdiction, competence, schema_version, limit, "ICMS")

    def municipal_benefit_candidates(
        self, *, jurisdiction: str, competence: date, schema_version: str,
        limit: int = 500,
    ) -> tuple[tuple[dict[str, Any], ...], bool]:
        return self._regional_candidates(jurisdiction, competence, schema_version, limit, "ISS")

    def _regional_candidates(
        self, jurisdiction: str, competence: date, schema_version: str, limit: int, tax_code: str,
    ) -> tuple[tuple[dict[str, Any], ...], bool]:
        """Select 1 effective candidate per T09 record before applying LIMIT.

        The latest version effective before next month wins, including revoked
        schemas. Later amendments do not erase historical opportunities.
        """
        self._require_active()
        if (
            type(competence) is not date or competence.day != 1
            or not isinstance(jurisdiction, str)
            or not re.fullmatch(r"[A-Z]{2}" if tax_code == "ICMS" else r"[0-9]{7}", jurisdiction)
            or not isinstance(schema_version, str)
            or not re.fullmatch(r"[a-zA-Z0-9./_-]{1,128}", schema_version)
            or type(limit) is not int or not 1 <= limit <= 500
        ):
            raise FiscalValidationError("invalid state benefit catalog projection")
        following = date(
            competence.year + (competence.month == 12),
            competence.month % 12 + 1, 1,
        )
        rows = self._conn.execute(
            """WITH ranked AS (
                 SELECT to_jsonb(r) AS payload,
                        ROW_NUMBER() OVER (
                            PARTITION BY r.record_id ORDER BY r.version DESC
                        ) AS rank_version
                   FROM fm_economy_benefits AS r
                  WHERE r.host_namespace=%s AND r.tenant_id=%s AND r.unit_id=%s
                    AND r.environment=%s AND r.valid_from < %s
                    AND EXISTS (
                        SELECT 1 FROM fm_economy_benefits AS anchor
                         WHERE anchor.host_namespace=r.host_namespace
                           AND anchor.tenant_id=r.tenant_id
                           AND anchor.unit_id=r.unit_id
                           AND anchor.environment=r.environment
                           AND anchor.record_id=r.record_id
                           AND anchor.jurisdiction=%s
                           AND anchor.content->>'schema_version'=%s
                    )
               )
               SELECT payload FROM ranked WHERE rank_version=1
                 AND payload->>'jurisdiction'=%s
                 AND payload->>'tax_code'=%s
               ORDER BY payload->>'record_id' LIMIT %s""",
            (*self._scope.identity_material, following, jurisdiction,
             schema_version, jurisdiction, tax_code, limit + 1),
        ).fetchall()
        truncated = len(rows) > limit
        results = tuple(dict(r[0]) for r in rows[:limit])
        for record in results:
            content = record.get("content")
            if not isinstance(content, dict) or _digest(content)[1] != record["digest"]:
                raise FiscalValidationError("state candidate record integrity mismatch")
        return results, truncated

    def accounting_review_request_version(self, record_id: str, request_id: str) -> int | None:
        """Resolve an idempotency key within one immutable accounting review stream."""
        self._require_active()
        self._identity(record_id, 1)
        self._text(request_id, "accounting review request")
        rows = self._conn.execute(
            """SELECT version FROM fm_economy_snapshots
               WHERE host_namespace=%s AND tenant_id=%s AND unit_id=%s AND environment=%s
                 AND record_id=%s AND content->>'schema_version'='nfcore.accounting-review/v1'
                 AND content->>'request_id'=%s LIMIT 2""",
            (*self._scope.identity_material, record_id, request_id),
        ).fetchall()
        if len(rows) > 1:
            raise FiscalValidationError("duplicate accounting review request")
        return int(rows[0][0]) if rows else None

    def lock_state_review_import(self, snapshot_id: str, benefit_id: str) -> None:
        """Serialize same-scope imports across PostgreSQL transactions."""
        self._require_active()
        self._identity(snapshot_id, 1)
        self._identity(benefit_id, 1)
        key = "|".join((*self._scope.identity_material, snapshot_id, benefit_id))
        self._conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,),
        )

    def records(
        self, table: str, *, limit: int = 100, schema_version: str | None = None,
        jurisdiction: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Read-only bounded scope projection; filter reviewed schema before LIMIT.

        The optional filter is only valid on canonical benefit JSON; other economy
        tables must not have their projections or security semantics changed.
        """
        self._require_active()
        if table not in TABLES or type(limit) is not int or not 1 <= limit <= 500:
            raise FiscalValidationError("invalid economy projection")
        if schema_version is not None and (
            table != "fm_economy_benefits"
            or not isinstance(schema_version, str)
            or not 1 <= len(schema_version) <= 128
            or not re.fullmatch(r"[a-zA-Z0-9./_-]+", schema_version)
        ):
            raise FiscalValidationError("invalid economy benefit schema filter")
        if jurisdiction is not None and (
            table != "fm_economy_benefits"
            or not isinstance(jurisdiction, str)
            or not re.fullmatch(r"[A-Z]{2}", jurisdiction)
        ):
            raise FiscalValidationError("invalid economy benefit jurisdiction filter")
        condition = (
            sql.SQL(" AND r.content->>'schema_version' = %s")
            if schema_version is not None else sql.SQL("")
        )
        state_condition = (
            sql.SQL(" AND r.jurisdiction = %s")
            if jurisdiction is not None else sql.SQL("")
        )
        statement = sql.SQL(
            "SELECT to_jsonb(r) FROM {} AS r WHERE host_namespace=%s AND tenant_id=%s "
            "AND unit_id=%s AND environment=%s{}{} "
            "ORDER BY created_at DESC, record_id LIMIT %s"
        ).format(sql.Identifier(table), condition, state_condition)
        params: tuple[Any, ...] = (*self._scope.identity_material,)
        if schema_version is not None:
            params = (*params, schema_version)
        if jurisdiction is not None:
            params = (*params, jurisdiction)
        rows = self._conn.execute(statement, (*params, limit)).fetchall()
        result = tuple(dict(row[0]) for row in rows)
        for record in result:
            if "content" in record:
                content = record["content"]
                if not isinstance(content, dict) or _digest(content)[1] != record["digest"]:
                    raise FiscalValidationError("economy record integrity mismatch")
        return result
