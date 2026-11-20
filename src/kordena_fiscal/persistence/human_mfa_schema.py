"""Migration 24: second factor for portal humans (additive tables only).

Optional for running services until NFCORE_HUMAN_MFA=enabled: the API then
requires this version and fails closed without it. Nothing here alters the
existing account or session tables.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol, cast

from kordena_fiscal.security.human_mfa import (
    CHALLENGE_MAX_FAILURES,
    MfaChallenge,
    MfaFactor,
    TrustedDevice,
)

HUMAN_MFA_VERSION = 24
HUMAN_MFA_NAME = "human_mfa_totp_step_up"
HUMAN_MFA_SCHEMA = (
    """CREATE TABLE fm_human_mfa_factors (
        account_id TEXT PRIMARY KEY REFERENCES fm_human_accounts(account_id),
        secret_ciphertext TEXT NOT NULL,
        confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
        created_at TEXT NOT NULL,
        confirmed_at TEXT,
        last_step BIGINT
    )""",
    """CREATE TABLE fm_human_mfa_recovery_codes (
        account_id TEXT NOT NULL REFERENCES fm_human_accounts(account_id),
        code_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        used_at TEXT,
        PRIMARY KEY (account_id, code_sha256)
    )""",
    """CREATE TABLE fm_human_mfa_challenges (
        token_sha256 TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES fm_human_accounts(account_id),
        purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'enroll')),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        failures INTEGER NOT NULL CHECK (failures >= 0),
        used INTEGER NOT NULL CHECK (used IN (0, 1))
    )""",
    "CREATE INDEX fm_human_mfa_challenges_expiry_idx ON fm_human_mfa_challenges (expires_at)",
    """CREATE TABLE fm_human_mfa_trusted_devices (
        token_sha256 TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES fm_human_accounts(account_id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL CHECK (revoked IN (0, 1))
    )""",
    "CREATE INDEX fm_human_mfa_devices_account_idx ON fm_human_mfa_trusted_devices (account_id)",
    """CREATE TABLE fm_human_mfa_step_ups (
        session_id TEXT PRIMARY KEY REFERENCES fm_web_sessions(session_id),
        account_id TEXT NOT NULL REFERENCES fm_human_accounts(account_id),
        verified_at TEXT NOT NULL
    )""",
    """CREATE TABLE fm_human_mfa_tenant_policy (
        tenant_id TEXT PRIMARY KEY,
        require_all INTEGER NOT NULL CHECK (require_all IN (0, 1)),
        updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
)


class _Executor(Protocol):
    def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> Any: ...
    def commit(self) -> None: ...


def _dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


class PostgresHumanMfaStore:
    """Every guarded transition is one conditional UPDATE (no read-then-write)."""

    def __init__(self, connection: Callable[[], AbstractContextManager[_Executor]]) -> None:
        self._connection = connection

    def _one(self, sql: str, params: tuple[object, ...]) -> tuple[object, ...] | None:
        with self._connection() as raw:
            row = raw.execute(sql, params).fetchone()
        return None if row is None else cast(tuple[object, ...], row)

    def _write(self, sql: str, params: tuple[object, ...]) -> int:
        with self._connection() as raw:
            cursor = raw.execute(sql, params)
            raw.commit()
            return int(cursor.rowcount)

    def factor(self, account_id: str) -> MfaFactor | None:
        row = self._one(
            "SELECT account_id, secret_ciphertext, confirmed, created_at, confirmed_at, "
            "last_step FROM fm_human_mfa_factors WHERE account_id = %s", (account_id,),
        )
        if row is None:
            return None
        return MfaFactor(
            account_id=str(row[0]), secret_ciphertext=str(row[1]),
            confirmed=bool(int(cast(int, row[2]))), created_at=_dt(row[3]),
            confirmed_at=None if row[4] is None else _dt(row[4]),
            last_step=None if row[5] is None else int(cast(int, row[5])),
        )

    def save_factor(self, factor: MfaFactor) -> None:
        self._write(
            "INSERT INTO fm_human_mfa_factors (account_id, secret_ciphertext, confirmed, "
            "created_at, confirmed_at, last_step) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (account_id) DO UPDATE SET secret_ciphertext = "
            "EXCLUDED.secret_ciphertext, confirmed = EXCLUDED.confirmed, created_at = "
            "EXCLUDED.created_at, confirmed_at = EXCLUDED.confirmed_at, last_step = "
            "EXCLUDED.last_step",
            (factor.account_id, factor.secret_ciphertext, int(factor.confirmed),
             factor.created_at.isoformat(),
             None if factor.confirmed_at is None else factor.confirmed_at.isoformat(),
             factor.last_step),
        )

    def delete_factor(self, account_id: str) -> None:
        with self._connection() as raw:
            raw.execute("DELETE FROM fm_human_mfa_recovery_codes WHERE account_id = %s",
                        (account_id,))
            raw.execute("UPDATE fm_human_mfa_trusted_devices SET revoked = 1 "
                        "WHERE account_id = %s", (account_id,))
            raw.execute("DELETE FROM fm_human_mfa_factors WHERE account_id = %s",
                        (account_id,))
            raw.commit()

    def advance_step(self, account_id: str, step: int) -> bool:
        return self._write(
            "UPDATE fm_human_mfa_factors SET last_step = %s WHERE account_id = %s "
            "AND confirmed = 1 AND (last_step IS NULL OR last_step < %s)",
            (step, account_id, step),
        ) == 1

    def replace_recovery_codes(
        self, account_id: str, digests: tuple[str, ...], now: datetime,
    ) -> None:
        with self._connection() as raw:
            raw.execute("DELETE FROM fm_human_mfa_recovery_codes WHERE account_id = %s",
                        (account_id,))
            for digest in digests:
                raw.execute(
                    "INSERT INTO fm_human_mfa_recovery_codes (account_id, code_sha256, "
                    "created_at, used_at) VALUES (%s, %s, %s, NULL)",
                    (account_id, digest, now.isoformat()),
                )
            raw.commit()

    def consume_recovery_code(self, account_id: str, digest: str, now: datetime) -> bool:
        return self._write(
            "UPDATE fm_human_mfa_recovery_codes SET used_at = %s WHERE account_id = %s "
            "AND code_sha256 = %s AND used_at IS NULL",
            (now.isoformat(), account_id, digest),
        ) == 1

    def remaining_recovery_codes(self, account_id: str) -> int:
        row = self._one(
            "SELECT count(*) FROM fm_human_mfa_recovery_codes WHERE account_id = %s "
            "AND used_at IS NULL", (account_id,),
        )
        return 0 if row is None else int(cast(int, row[0]))

    def save_challenge(self, challenge: MfaChallenge) -> None:
        self._write(
            "INSERT INTO fm_human_mfa_challenges (token_sha256, account_id, purpose, "
            "created_at, expires_at, failures, used) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (challenge.token_sha256, challenge.account_id, challenge.purpose,
             challenge.created_at.isoformat(), challenge.expires_at.isoformat(),
             challenge.failures, int(challenge.used)),
        )

    def challenge(self, token_sha256: str) -> MfaChallenge | None:
        row = self._one(
            "SELECT token_sha256, account_id, purpose, created_at, expires_at, failures, "
            "used FROM fm_human_mfa_challenges WHERE token_sha256 = %s", (token_sha256,),
        )
        if row is None:
            return None
        return MfaChallenge(
            token_sha256=str(row[0]), account_id=str(row[1]), purpose=str(row[2]),
            created_at=_dt(row[3]), expires_at=_dt(row[4]),
            failures=int(cast(int, row[5])), used=bool(int(cast(int, row[6]))),
        )

    def record_challenge_failure(self, token_sha256: str) -> int:
        with self._connection() as raw:
            row = raw.execute(
                "UPDATE fm_human_mfa_challenges SET failures = failures + 1 "
                "WHERE token_sha256 = %s RETURNING failures", (token_sha256,),
            ).fetchone()
            raw.commit()
        return CHALLENGE_MAX_FAILURES if row is None else int(cast(int, row[0]))

    def consume_challenge(self, token_sha256: str) -> bool:
        return self._write(
            "UPDATE fm_human_mfa_challenges SET used = 1 WHERE token_sha256 = %s "
            "AND used = 0 AND failures < %s", (token_sha256, CHALLENGE_MAX_FAILURES),
        ) == 1

    def save_trusted_device(self, device: TrustedDevice) -> None:
        self._write(
            "INSERT INTO fm_human_mfa_trusted_devices (token_sha256, account_id, "
            "created_at, expires_at, revoked) VALUES (%s, %s, %s, %s, %s)",
            (device.token_sha256, device.account_id, device.created_at.isoformat(),
             device.expires_at.isoformat(), int(device.revoked)),
        )

    def trusted_device(self, token_sha256: str) -> TrustedDevice | None:
        row = self._one(
            "SELECT token_sha256, account_id, created_at, expires_at, revoked "
            "FROM fm_human_mfa_trusted_devices WHERE token_sha256 = %s", (token_sha256,),
        )
        if row is None:
            return None
        return TrustedDevice(
            token_sha256=str(row[0]), account_id=str(row[1]), created_at=_dt(row[2]),
            expires_at=_dt(row[3]), revoked=bool(int(cast(int, row[4]))),
        )

    def revoke_trusted_devices(self, account_id: str) -> None:
        self._write("UPDATE fm_human_mfa_trusted_devices SET revoked = 1 "
                    "WHERE account_id = %s", (account_id,))

    def record_step_up(self, session_id: str, account_id: str, at: datetime) -> None:
        self._write(
            "INSERT INTO fm_human_mfa_step_ups (session_id, account_id, verified_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (session_id) DO UPDATE SET "
            "verified_at = EXCLUDED.verified_at "
            "WHERE fm_human_mfa_step_ups.account_id = EXCLUDED.account_id",
            (session_id, account_id, at.isoformat()),
        )

    def step_up_at(self, session_id: str) -> datetime | None:
        row = self._one("SELECT verified_at FROM fm_human_mfa_step_ups WHERE session_id = %s",
                        (session_id,))
        return None if row is None else _dt(row[0])

    def tenant_requires_all(self, tenant_id: str) -> bool:
        row = self._one("SELECT require_all FROM fm_human_mfa_tenant_policy "
                        "WHERE tenant_id = %s", (tenant_id,))
        return row is not None and bool(int(cast(int, row[0])))

    def set_tenant_requires_all(
        self, tenant_id: str, value: bool, actor_account_id: str, now: datetime,
    ) -> None:
        self._write(
            "INSERT INTO fm_human_mfa_tenant_policy (tenant_id, require_all, updated_by, "
            "updated_at) VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id) DO UPDATE SET "
            "require_all = EXCLUDED.require_all, updated_by = EXCLUDED.updated_by, "
            "updated_at = EXCLUDED.updated_at",
            (tenant_id, int(value), actor_account_id, now.isoformat()),
        )
