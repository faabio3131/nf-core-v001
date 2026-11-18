"""DPS legal-issuer serial reservation and canonical preparation invariants.

No real certificates, credentials, transmissions or production migrations.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from kordena_fiscal.application import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.issuance import NfseCanonicalDocument, NfseServiceLine
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
RETENTION = RetentionPolicyMetadata("dps-serial-test", 1)


def _document(
    number: int,
    *,
    tenant: str = "tenant-a",
    unit: str = "unit-a",
    series: int = 1,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
) -> NfseCanonicalDocument:
    scope = ExecutionScope(tenant, unit, environment, f"dps-corr-{number}", "nfcore")
    municipal = BrazilianJurisdiction("MG", "3106200")
    issuer = FiscalProfile(
        profile_id="issuer-nfse",
        scope=scope,
        cnpj=Cnpj("12345678000195"),
        legal_name="Synthetic Numbering Services Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("MG", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Teste", number="100", district="Centro",
            municipality_name="Belo Horizonte", jurisdiction=municipal,
            postal_code="30110000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return NfseCanonicalDocument(
        document_id=f"nfse-dps-serial-{number}",
        scope=scope,
        source=SourceReference("service-order", f"order-{number}"),
        issued_at=NOW,
        competence_date=NOW.date(),
        issuer=issuer,
        service_jurisdiction=municipal,
        services=(NfseServiceLine(
            line_number=1,
            municipal_service_code="0107",
            national_taxation_code="010701",
            description="Synthetic software service",
            gross_amount=Money(Decimal("125.00")),
            iss_amount=Money(Decimal("2.50")),
        ),),
        dps_series=series,
    )


def _prepare(database: SqliteFiscalDatabase, document: NfseCanonicalDocument):
    return FiscalApplicationService(database).prepare_nfse_authorization(
        document, occurred_at=NOW, retention=RETENTION,
    )


def test_dps_serials_increment_and_replay_survives_process_restart(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "dps-sequence.sqlite")
    database.initialize()
    first = _document(1)
    second = _document(2)
    one = _prepare(database, first)
    two = _prepare(database, second)
    assert not one.replay and not two.replay
    assert (one.request.document.dps_series, one.request.document.dps_number) == (1, 1)
    assert (two.request.document.dps_series, two.request.document.dps_number) == (1, 2)
    reopened = SqliteFiscalDatabase(database.path)
    assert _prepare(reopened, first).replay
    assert _prepare(reopened, first).request.document.dps_number == 1
    assert _prepare(reopened, second).request.document.dps_number == 2
    assert FiscalApplicationService(reopened).load_prepared_nfse_authorization(
        first.scope, first.document_id,
    ) == one.request
    assert 22 in database.applied_migrations()


def test_dps_series_and_environment_counters_are_independent(tmp_path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-series.sqlite")
    db.initialize()
    assert _prepare(db, _document(1)).request.document.dps_number == 1
    series_2 = _document(2, series=2)
    assert _prepare(db, series_2).request.document.dps_number == 1
    assert _prepare(db, _document(3, series=2)).request.document.dps_number == 2
    assert _prepare(
        db, _document(4, environment=FiscalEnvironment.PRODUCTION),
    ).request.document.dps_number == 1


@pytest.mark.parametrize("partition", [("other-tenant", "unit-a"), ("tenant-a", "unit-b")])
def test_dps_legal_cnpj_sequence_cannot_be_taken_over_by_another_scope(
    tmp_path, partition: tuple[str, str],
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-ownership.sqlite")
    db.initialize()
    _prepare(db, _document(1))
    foreign = _document(2, tenant=partition[0], unit=partition[1])
    with pytest.raises(PersistenceConflictError, match="already owned"):
        _prepare(db, foreign)
    assert _prepare(db, _document(3)).request.document.dps_number == 2


def test_dps_replay_cannot_change_issuer_series_or_document_content(tmp_path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-replay.sqlite")
    db.initialize()
    document = _document(1)
    _prepare(db, document)
    with pytest.raises(PersistenceConflictError, match="replay conflicts"):
        _prepare(db, replace(document, dps_series=2))
    changed_service = replace(
        document.services[0], description="Different service content",
    )
    with pytest.raises(PersistenceConflictError, match="replay conflicts"):
        _prepare(db, replace(document, services=(changed_service,)))
    assert _prepare(db, _document(2)).request.document.dps_number == 2


def test_dps_assignment_from_untrusted_caller_is_refused(tmp_path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-untrusted.sqlite")
    db.initialize()
    with pytest.raises(FiscalValidationError, match="assigned exclusively"):
        _prepare(db, replace(_document(1), dps_number=987654321))
    assert _prepare(db, _document(1)).request.document.dps_number == 1


def test_dps_counter_is_rolled_back_with_failed_canonical_transaction(tmp_path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-rollback.sqlite")
    db.initialize()
    document = _document(1)
    from kordena_fiscal.issuance.nfe_nfse import build_nfse_request_fingerprint

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        with db() as uow:
            result = uow.dps_sequences.reserve(
                document, input_fingerprint=build_nfse_request_fingerprint(document),
            )
            assert result.number == 1
            raise RuntimeError("synthetic interruption")
    assert _prepare(db, document).request.document.dps_number == 1


def test_concurrent_sqlite_writers_never_duplicate_legal_dps_serial(tmp_path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "dps-concurrency.sqlite")
    db.initialize()
    documents = tuple(_document(i) for i in range(1, 9))
    with ThreadPoolExecutor(max_workers=4) as workers:
        prepared = tuple(workers.map(lambda d: _prepare(db, d), documents))
    numbers = [result.request.document.dps_number for result in prepared]
    assert sorted(numbers) == list(range(1, 9))
    assert len(set(numbers)) == 8


def test_concurrent_postgres_workers_do_not_allocate_duplicate_dps_numbers() -> None:
    """Real PG row/advisory locks, not a mocked concurrent sequence store."""
    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Dedicated NFCORE_TEST_POSTGRES_DSN is required")
    with psycopg.connect(dsn, autocommit=True) as connection:
        if not connection.info.dbname.endswith("_test"):
            pytest.fail("Refusing destructive test isolation outside a _test database")
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    db = PostgresFiscalDatabase(dsn, min_pool_size=1, max_pool_size=10)
    try:
        applied = db.initialize()
        assert 22 in applied
        assert db.require_current_schema() == (*range(1, 20), 22, 23)
        documents = tuple(_document(i) for i in range(1, 9))
        with ThreadPoolExecutor(max_workers=4) as workers:
            prepared = tuple(workers.map(lambda d: _prepare(db, d), documents))
        assert sorted(result.request.document.dps_number for result in prepared) == list(
            range(1, 9)
        )
        for document in documents:
            assert _prepare(db, document).replay
    finally:
        db.close()
