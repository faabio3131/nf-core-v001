from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.contingency import FiscalOutboxService
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalEnvironment,
    FiscalUnitId,
    HostNamespace,
    HostScope,
    SourceReference,
)
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.numbering import FiscalSequenceKey, FiscalSequencePolicy
from kordena_fiscal.persistence.ports import PersistenceStateError
from kordena_fiscal.persistence.postgres import (
    PostgresFiscalDatabase,
    production_database_from_env,
)
from kordena_fiscal.reconciliation import FiscalReconciliationResult, ReconciliationStatus
from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanAuthenticationError,
    HumanIdentityService,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_recovery import PasswordRecoveryService

NOW = datetime(2026, 9, 14, 18, 0, tzinfo=UTC)
DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"


def _dsn() -> str:
    value = os.environ.get(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is required for real PostgreSQL certification")
    return value


@pytest.fixture
def database() -> Iterator[PostgresFiscalDatabase]:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    database = PostgresFiscalDatabase(dsn, min_pool_size=1, max_pool_size=12)
    assert database.initialize() == tuple(range(1, 20))
    try:
        yield database
    finally:
        database.close()


def _scope(*, tenant_id: str = "tenant-a", unit_id: str = "unit-a") -> ExecutionScope:
    return ExecutionScope(
        host_namespace="nfcore",
        tenant_id=tenant_id,
        unit_id=unit_id,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=f"corr-{tenant_id}-{unit_id}",
    )


def _binding() -> FiscalAccountBinding:
    return FiscalAccountBinding(
        binding_id="binding-postgres",
        host_scope=HostScope(
            namespace=HostNamespace("nfcore"),
            tenant_id="tenant-external",
            unit_id="unit-external",
        ),
        fiscal_account_id=FiscalAccountId("tenant-a"),
        fiscal_unit_id=FiscalUnitId("unit-a"),
    )


def test_postgres_migrations_are_real_reproducible_and_fail_closed(
    database: PostgresFiscalDatabase,
) -> None:
    assert database.initialize() == ()
    assert database.applied_migrations() == tuple(range(1, 20))
    assert database.dsn_redacted == "postgresql://<redacted>"

    with pytest.raises(PersistenceStateError, match="backend must be postgres"):
        production_database_from_env((("NFCORE_PERSISTENCE_BACKEND", "sqlite"),))
    with pytest.raises(PersistenceStateError, match="DATABASE_URL"):
        production_database_from_env((("NFCORE_PERSISTENCE_BACKEND", "postgres"),))


def test_postgres_uow_commit_rollback_and_core_state_parity(
    database: PostgresFiscalDatabase,
) -> None:
    scope = _scope()
    binding = _binding()
    key = IdempotencyKey("a" * 64)
    fingerprint = "b" * 64
    sequence_key = FiscalSequenceKey.from_scope(
        scope,
        model=ElectronicInvoiceModel.NFCE,
        series=1,
    )
    source = SourceReference("sale", "sale-postgres")

    with database.unit_of_work() as uow:
        uow.bindings.add(binding)
        reservation = uow.idempotency.reserve(key, fingerprint, "doc-postgres")
        assert reservation.replay is False
        assert uow.sequences.reserve_next(sequence_key, FiscalSequencePolicy()).number == 1
        outbox = FiscalOutboxService(uow.outbox).enqueue(
            scope=scope,
            operation="authorize",
            deduplication_key="doc-postgres",
            payload=b"signed-postgres-payload",
            created_at=NOW,
        )
        archive = FiscalArchiveEntry.build(
            scope=scope,
            document_reference="doc-postgres",
            kind=FiscalArchiveKind.AUTHORIZED_XML,
            content=b"<xml>postgres</xml>",
            media_type="application/xml",
            archived_at=NOW,
            retention=RetentionPolicyMetadata(policy_id="default", policy_version=1),
        )
        uow.archive.append(archive)
        reconciliation = FiscalReconciliationResult(
            status=ReconciliationStatus.MATCHED,
            scope=scope,
            source=source,
            fingerprint="c" * 64,
            selected_document_id="doc-postgres",
            issues=(),
        )
        uow.reconciliations.save(reconciliation)
        uow.commit()

    with database.unit_of_work() as uow:
        assert uow.bindings.resolve(binding.host_scope) == binding
        assert uow.idempotency.reserve(key, fingerprint, "ignored-replay").replay is True
        assert uow.sequences.last_reserved(sequence_key) == 1
        assert uow.outbox.get(outbox.entry.entry_id) == outbox.entry
        assert uow.archive.get(archive.entry_id) == archive
        assert uow.reconciliations.get(scope, source) == reconciliation
        uow.commit()

    rollback_binding = FiscalAccountBinding(
        binding_id="binding-rollback",
        host_scope=HostScope(
            namespace=HostNamespace("nfcore"),
            tenant_id="rollback-tenant",
            unit_id="rollback-unit",
        ),
        fiscal_account_id=FiscalAccountId("tenant-a"),
        fiscal_unit_id=FiscalUnitId("unit-a"),
    )
    with database.unit_of_work() as uow:
        uow.bindings.add(rollback_binding)

    with database.unit_of_work() as uow:
        with pytest.raises(PersistenceStateError, match="no durable fiscal binding"):
            uow.bindings.resolve(rollback_binding.host_scope)


def test_postgres_tenant_partition_does_not_cross_archive_queries(
    database: PostgresFiscalDatabase,
) -> None:
    scope_a = _scope(tenant_id="tenant-a", unit_id="unit-a")
    scope_b = _scope(tenant_id="tenant-b", unit_id="unit-a")
    archive = FiscalArchiveEntry.build(
        scope=scope_a,
        document_reference="doc-isolated",
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=b"<xml>tenant-a</xml>",
        media_type="application/xml",
        archived_at=NOW,
        retention=RetentionPolicyMetadata(policy_id="default", policy_version=1),
    )
    with database.unit_of_work() as uow:
        uow.archive.append(archive)
        uow.commit()
    with database.unit_of_work() as uow:
        assert uow.archive.list_for_document(scope_a, "doc-isolated") == (archive,)
        assert uow.archive.list_for_document(scope_b, "doc-isolated") == ()


def test_postgres_sequence_allocation_is_safe_under_concurrency(
    database: PostgresFiscalDatabase,
) -> None:
    key = FiscalSequenceKey.from_scope(
        _scope(),
        model=ElectronicInvoiceModel.NFCE,
        series=9,
    )

    def reserve() -> int:
        with database.unit_of_work() as uow:
            number = uow.sequences.reserve_next(key, FiscalSequencePolicy()).number
            uow.commit()
            return number

    with ThreadPoolExecutor(max_workers=8) as executor:
        numbers = list(executor.map(lambda _: reserve(), range(8)))

    assert sorted(numbers) == list(range(1, 9))
    assert len(set(numbers)) == 8


def test_postgres_idempotency_is_deterministic_under_concurrency(
    database: PostgresFiscalDatabase,
) -> None:
    key = IdempotencyKey("d" * 64)

    def reserve() -> bool:
        with database.unit_of_work() as uow:
            result = uow.idempotency.reserve(key, "e" * 64, "doc-concurrent")
            uow.commit()
            return result.replay

    with ThreadPoolExecutor(max_workers=8) as executor:
        replays = list(executor.map(lambda _: reserve(), range(8)))

    assert replays.count(False) == 1
    assert replays.count(True) == 7


def test_postgres_human_accounts_sessions_and_reset_survive_repository_restart(
    database: PostgresFiscalDatabase,
) -> None:
    hasher = ScryptPasswordHasher()
    accounts = database.human_accounts()
    sessions = database.web_sessions()
    resets = database.password_resets()
    account = HumanAccount(
        account_id="account-postgres",
        email="owner@nfcore.example",
        password_hash=hasher.hash("old-password-nfcore-2026"),
        tenant_id="tenant-a",
        role=PortalRole.OWNER,
        unit_ids=frozenset({"unit-a"}),
    )
    accounts.save(account)
    identity = HumanIdentityService(
        accounts=accounts,
        sessions=sessions,
        password_hasher=hasher,
    )
    issued = identity.login(
        email=account.email,
        password="old-password-nfcore-2026",
        now=NOW,
    )

    restarted_identity = HumanIdentityService(
        accounts=database.human_accounts(),
        sessions=database.web_sessions(),
        password_hasher=hasher,
    )
    authenticated = restarted_identity.authenticate_session(
        session_token=issued.session_token,
        now=NOW + timedelta(minutes=1),
    )
    assert authenticated.account.account_id == account.account_id

    recovery = PasswordRecoveryService(
        accounts=database.human_accounts(),
        sessions=database.web_sessions(),
        resets=resets,
        password_hasher=hasher,
    )
    reset = recovery.request_reset(email=account.email, now=NOW + timedelta(minutes=2))
    assert reset is not None
    recovery.complete_reset(
        reset_token=reset.reset_token,
        new_password="new-password-nfcore-2026",
        now=NOW + timedelta(minutes=3),
    )

    with pytest.raises(HumanAuthenticationError, match="web session is not usable"):
        restarted_identity.authenticate_session(
            session_token=issued.session_token,
            now=NOW + timedelta(minutes=4),
        )

    renewed = HumanIdentityService(
        accounts=database.human_accounts(),
        sessions=database.web_sessions(),
        password_hasher=hasher,
    ).login(
        email=account.email,
        password="new-password-nfcore-2026",
        now=NOW + timedelta(minutes=4),
    )
    assert renewed.account.session_epoch == 1

    with database.connection() as connection:
        session_row = connection.execute(
            "SELECT session_token_sha256 FROM fm_web_sessions WHERE session_id = ?",
            (authenticated.session_id,),
        ).fetchone()
        reset_row = connection.execute(
            "SELECT token_sha256 FROM fm_password_resets WHERE account_id = ?",
            (account.account_id,),
        ).fetchone()
    assert session_row is not None and session_row[0] != issued.session_token
    assert reset_row is not None and reset_row[0] != reset.reset_token
