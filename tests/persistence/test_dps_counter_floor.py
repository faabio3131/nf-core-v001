"""Governed DPS counter floor: monotonic, owned, idempotent and audited."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_nfse_dps_numbering import _document, _prepare

from kordena_fiscal.application.dps_counter_floor import (
    DPS_FLOOR_MEDIA_TYPE,
    raise_dps_counter_floor,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError

AT = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
CNPJ = "12345678000195"
IBGE = "3106200"


def _scope(tenant: str = "tenant-a", unit: str = "unit-a") -> ExecutionScope:
    return ExecutionScope(tenant, unit, FiscalEnvironment.HOMOLOGATION, "floor-corr", "nfcore")


def _floor(db, number: int, *, scope: ExecutionScope | None = None, ref: str = "ticket-1"):
    return raise_dps_counter_floor(
        db, scope=scope or _scope(), issuer_cnpj=CNPJ, municipality_ibge=IBGE,
        series=1, last_used_number=number, approved_by="Fabio (owner)",
        approval_reference=ref, occurred_at=AT,
    )


@pytest.fixture
def db(tmp_path):
    database = SqliteFiscalDatabase(tmp_path / "floor.sqlite")
    database.initialize()
    return database


def test_floor_before_first_use_makes_next_reservation_follow_external_numbers(db) -> None:
    result = _floor(db, 41)
    assert {k: v for k, v in result.items() if k != "evidence_reference"} == {
        "previous_last_number": None, "last_number": 41, "next_number": 42,
        "changed": True, "replay": False,
    }
    assert _prepare(db, _document(1)).request.document.dps_number == 42


def test_floor_never_lowers_or_reuses_a_reserved_number(db) -> None:
    for number in (1, 2, 3):
        _prepare(db, _document(number))
    lower = _floor(db, 2, ref="stale-ticket")
    assert lower["changed"] is False and lower["last_number"] == 3
    assert _prepare(db, _document(4)).request.document.dps_number == 4
    higher = _floor(db, 100, ref="after-restore")
    assert higher["previous_last_number"] == 4 and higher["changed"] is True
    assert _prepare(db, _document(5)).request.document.dps_number == 101


def test_exact_command_replays_without_second_effect_and_is_archived(db) -> None:
    first = _floor(db, 10)
    _prepare(db, _document(1))  # consumes 11
    replay = _floor(db, 10)
    assert replay["replay"] is True and replay["last_number"] == first["last_number"]
    assert replay["evidence_reference"] == first["evidence_reference"]
    assert _prepare(db, _document(2)).request.document.dps_number == 12
    with db() as uow:
        entries = uow.archive.list_for_document(_scope(), first["evidence_reference"])
    assert len(entries) == 1
    assert entries[0].media_type == DPS_FLOOR_MEDIA_TYPE
    assert b'"approved_by": "Fabio (owner)"' in entries[0].content
    assert b'"previous_last_number": null' in entries[0].content


def test_counter_owned_by_another_unit_is_refused(db) -> None:
    _floor(db, 5)
    with pytest.raises(PersistenceConflictError, match="another fiscal unit"):
        _floor(db, 9, scope=_scope(unit="unit-b"))


@pytest.mark.parametrize(
    ("number", "approver", "reference"),
    [(0, "x", "y"), (True, "x", "y"), (5, " ", "y"), (5, "x", ""), (999999999999999, "x", "y")],
)
def test_invalid_floor_commands_fail_closed(db, number, approver, reference) -> None:
    with pytest.raises(FiscalValidationError):
        raise_dps_counter_floor(
            db, scope=_scope(), issuer_cnpj=CNPJ, municipality_ibge=IBGE, series=1,
            last_used_number=number, approved_by=approver,
            approval_reference=reference, occurred_at=AT,
        )
    assert _prepare(db, _document(1)).request.document.dps_number == 1


def test_cli_dry_run_validates_without_database(capsys) -> None:
    from pathlib import Path
    from runpy import run_path

    script = Path(__file__).resolve().parents[2] / "scripts/admin/raise_dps_counter_floor.py"
    main = run_path(str(script))["main"]
    args = [
        "--tenant", "t", "--unit", "u", "--environment", "homologation",
        "--cnpj", CNPJ, "--ibge", IBGE, "--series", "1", "--last-used", "57",
        "--approved-by", "Fabio", "--reference", "ticket",
    ]
    assert main(args) == 0
    assert '"next_reservation_at_least": 58' in capsys.readouterr().out
    with pytest.raises(FiscalValidationError):
        main([*args[:-6], "--last-used", "0", "--approved-by", "Fabio", "--reference", "t"])


def test_postgres_floor_then_reservation_uses_real_locks() -> None:
    import os

    import psycopg

    from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Dedicated NFCORE_TEST_POSTGRES_DSN is required")
    with psycopg.connect(dsn, autocommit=True) as connection:
        if not connection.info.dbname.endswith("_test"):
            pytest.fail("Refusing destructive test isolation outside a _test database")
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    database = PostgresFiscalDatabase(dsn, min_pool_size=1, max_pool_size=4)
    try:
        database.initialize()
        assert _floor(database, 200)["next_number"] == 201
        assert _prepare(database, _document(1)).request.document.dps_number == 201
        assert _floor(database, 150, ref="stale")["changed"] is False
        assert _prepare(database, _document(2)).request.document.dps_number == 202
    finally:
        database.close()
