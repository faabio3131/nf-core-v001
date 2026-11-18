"""Durable, single-use IRON A1 upload grant on the canonical NFCore PostgreSQL.

Only digests are stored. Consumption is an atomic UPDATE ... RETURNING; a failed
Vault validation consumes the grant and requires a new OWNER step-up in IRON.
Do not store, log, or return PKCS#12 bytes, passwords or the raw upload token.
"""
from __future__ import annotations

import hashlib
import secrets
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

IRON_A1_DELEGATION_VERSION = 23
IRON_A1_DELEGATION_NAME = "iron_a1_one_time_delegated_upload"
IRON_A1_DELEGATION_SCHEMA = (
    """CREATE TABLE fm_iron_a1_delegations (
        token_sha256 TEXT PRIMARY KEY,
        host_namespace TEXT NOT NULL,
        fiscal_tenant_id TEXT NOT NULL,
        fiscal_unit_id TEXT NOT NULL,
        environment TEXT NOT NULL,
        issuer_cnpj TEXT NOT NULL,
        allowed_origin TEXT NOT NULL,
        issued_by TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        consumed_at TEXT
    )""",
    "CREATE INDEX fm_iron_a1_delegations_expires_idx ON fm_iron_a1_delegations(expires_at)",
)

class _Executor(Protocol):
    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Any: ...
    def commit(self) -> None: ...

class IronA1DelegationStore:
    """Uses PostgresFiscalDatabase.connection(), never a second database."""

    def __init__(self, connection: Callable[[], AbstractContextManager[_Executor]]):
        self._connection = connection

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def issue(
        self, *, host_namespace: str, tenant_id: str, unit_id: str,
        environment: str, issuer_cnpj: str, allowed_origin: str,
        issued_by: str, now: datetime | None = None,
    ) -> tuple[str, datetime]:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Timezone-aware issuance required")
        token = secrets.token_urlsafe(48)
        expires = instant + timedelta(minutes=5)
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO fm_iron_a1_delegations
                   (token_sha256,host_namespace,fiscal_tenant_id,fiscal_unit_id,
                    environment,issuer_cnpj,allowed_origin,issued_by,issued_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (self._digest(token), host_namespace, tenant_id, unit_id,
                 environment, issuer_cnpj, allowed_origin, issued_by,
                 instant.isoformat(), expires.isoformat()),
            )
            conn.commit()
        return token, expires

    def consume(
        self, *, token: str, origin: str, now: datetime | None = None,
    ) -> dict[str, str] | None:
        if not isinstance(token, str) or not 40 <= len(token) <= 128 or not token.isascii():
            return None
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("Timezone-aware consumption required")
        with self._connection() as conn:
            row = conn.execute(
                """UPDATE fm_iron_a1_delegations SET consumed_at=?
                   WHERE token_sha256=? AND allowed_origin=? AND consumed_at IS NULL
                     AND expires_at>? AND environment='homologation'
                   RETURNING host_namespace,fiscal_tenant_id,fiscal_unit_id,
                             environment,issuer_cnpj""",
                (instant.isoformat(), self._digest(token), origin, instant.isoformat()),
            ).fetchone()
            conn.commit()
        if row is None:
            return None
        return dict(zip(("host_namespace","tenant_id","unit_id","environment","issuer_cnpj"), row))
