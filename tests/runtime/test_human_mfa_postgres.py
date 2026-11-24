"""Migration 24 and the PostgreSQL MFA store, in an isolated schema."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest

from kordena_fiscal.security.human_identity import (
    HumanAccount,
    PortalRole,
    ScryptPasswordHasher,
    WebSessionRecord,
)
from kordena_fiscal.security.human_mfa import HumanMfaError, HumanMfaService
from kordena_fiscal.security.totp import totp_at


def test_postgres_mfa_store_migration_and_atomic_transitions() -> None:
    dsn = os.getenv("NFCORE_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("NFCORE_TEST_POSTGRES_DSN required for PostgreSQL test")
    import base64

    import psycopg
    from psycopg import sql

    from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

    schema = "mfa24_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    uri = urlsplit(dsn)
    query = dict(parse_qsl(uri.query, keep_blank_values=True))
    query["options"] = f"-c search_path={schema}"
    database = None
    try:
        database = PostgresFiscalDatabase(
            urlunsplit(uri._replace(query=urlencode(query, quote_via=quote))),
            max_pool_size=8,
        )
        applied = database.initialize()
        assert 24 not in applied  # opt-in: the v23 release boundary is unchanged
        assert database.initialize(enable_mfa=True) == (24,)
        assert database.applied_migrations()[-1] == 24

        accounts = database.human_accounts()
        owner = HumanAccount(
            account_id="acc-owner", email="dono@empresa.com.br",
            password_hash=ScryptPasswordHasher().hash("Senha-forte-para-teste-1"),
            tenant_id="tenant-a", role=PortalRole.OWNER,
        )
        accounts.save(owner)
        now = datetime.now(UTC)
        database.web_sessions().save(WebSessionRecord(
            session_id="sess-1", account_id=owner.account_id, session_token_sha256="a" * 64,
            csrf_token_sha256="b" * 64, session_epoch=0, created_at=now,
            expires_at=now + timedelta(hours=1),
        ))
        store = database.human_mfa()
        mfa = HumanMfaService(store=store, encryption_key=bytes(range(32)))
        enrollment = mfa.start_enrollment(owner, now)
        raw = enrollment.secret_base32
        secret = base64.b32decode(raw + "=" * (-len(raw) % 8))
        codes = mfa.confirm_enrollment(owner, totp_at(secret, now - timedelta(seconds=30)), now)
        assert store.remaining_recovery_codes(owner.account_id) == 10

        # Same code from two workers: exactly one wins.
        code = totp_at(secret, now)

        def attempt(_: int) -> bool:
            try:
                mfa.verify(owner, code, now)
                return True
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=6) as pool:
            assert list(pool.map(attempt, range(6))).count(True) == 1
        assert store.consume_recovery_code(
            owner.account_id, "x" * 64, now,
        ) is False
        assert mfa.verify(owner, codes[0], now) == "recovery"
        with pytest.raises(HumanMfaError):
            mfa.verify(owner, codes[0], now)

        token, _ = mfa.open_challenge(owner, now)
        for _ in range(5):
            mfa.fail_challenge(token)
        with pytest.raises(HumanMfaError):
            mfa.challenge_account(token, now)

        device, _ = mfa.issue_trusted_device(owner, now)
        assert mfa.is_trusted_device(owner, device, now)
        mfa.step_up(owner, "sess-1", totp_at(secret, now + timedelta(seconds=30)),
                    now + timedelta(seconds=30))
        assert mfa.has_recent_step_up("sess-1", now + timedelta(minutes=2))
        assert not mfa.has_recent_step_up("sess-1", now + timedelta(minutes=10))
        mfa.set_tenant_requires_all(owner, True, now)
        assert store.tenant_requires_all("tenant-a")
        mfa.reset(owner.account_id)
        assert not mfa.is_enrolled(owner.account_id)
        assert not mfa.is_trusted_device(owner, device, now)
        with database.connection() as connection:
            stored = connection.execute(
                "SELECT secret_ciphertext FROM fm_human_mfa_factors").fetchall()
        assert stored == []
    finally:
        if database is not None:
            database.close()
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_schema_gate_treats_24_as_drift_unless_mfa_is_enabled(monkeypatch) -> None:
    from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

    class Probe(PostgresFiscalDatabase):
        def __init__(self, applied):
            self._applied = applied

        def applied_migrations(self):
            return self._applied

        def connection(self):
            raise RuntimeError("catalog reached")

    with_mfa = Probe((*range(1, 20), 22, 23, 24))
    monkeypatch.delenv("NFCORE_HUMAN_MFA", raising=False)
    with pytest.raises(Exception, match="certified migration"):
        with_mfa.require_current_schema()
    monkeypatch.setenv("NFCORE_HUMAN_MFA", "enabled")
    with pytest.raises(Exception, match="certified migration"):
        Probe((*range(1, 20), 22, 23)).require_current_schema()
    with pytest.raises(Exception) as reached:
        with_mfa.require_current_schema()  # passes the ledger, then reads catalogs
    assert "certified migration" in str(reached.value)
    assert isinstance(reached.value.__cause__, RuntimeError)
