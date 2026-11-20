"""RTC-02: declared federal regime is durable, dated, CRT-consistent and audited."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier

import pytest

from kordena_fiscal.application.federal_regime_store import (
    FEDERAL_REGIME_MEDIA_TYPE,
    declare_federal_regime,
    federal_regime_status,
    load_federal_regime_declarations,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

SCOPE = ExecutionScope("tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION, "c", "fm-nfcore")
JAN = datetime(2026, 1, 1, tzinfo=UTC)
JUL = datetime(2026, 7, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 19, tzinfo=UTC)


def _profile(crt: TaxRegimeCode = TaxRegimeCode.NORMAL) -> FiscalProfile:
    return FiscalProfile(
        profile_id="issuer", scope=SCOPE, cnpj=Cnpj("09107283000140"),
        legal_name="Empresa Sintetica", tax_regime=crt,
        state_registration=StateRegistration("SP", None, exempt=True),
        primary_cnae=CnaeCode("8011101"),
        address=FiscalAddress(
            street="Rua A", number="1", district="Centro", municipality_name="Cajamar",
            jurisdiction=BrazilianJurisdiction("SP", "3509205"), postal_code="07750000",
        ),
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def db(tmp_path):
    database = SqliteFiscalDatabase(tmp_path / "regime.sqlite")
    database.initialize()
    return database


def _declare(db, regime, start, *, key="k1", crt=TaxRegimeCode.NORMAL, source="ECF 2026"):
    return declare_federal_regime(
        db, scope=SCOPE, crt=crt, issuer_cnpj=_profile(crt).cnpj,
        federal_income_tax_regime=regime,
        effective_from=start, source_reference=source, actor="acct-1",
        idempotency_key=key, occurred_at=NOW,
    )


def test_presumido_is_declared_and_visible_without_inferring_from_crt(db) -> None:
    assert federal_regime_status(db, SCOPE, _profile(), NOW) == {
        "federal_regime_status": "declaration_not_configured",
    }
    result = _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    assert result["version"] == 1 and result["replay"] is False
    status = federal_regime_status(db, SCOPE, _profile(), NOW)
    assert status["federal_regime_status"] == "declared"
    assert status["federal_income_tax_regime"] == "lucro_presumido"
    with db() as uow:
        entries = uow.archive.list_for_document(SCOPE, str(result["evidence_reference"]))
    assert len(entries) == 1 and entries[0].media_type == FEDERAL_REGIME_MEDIA_TYPE


def test_crt_and_regime_must_be_consistent(db) -> None:
    with pytest.raises(FiscalValidationError):
        _declare(
            db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN,
            crt=TaxRegimeCode.SIMPLES_NACIONAL,
        )
    with pytest.raises(FiscalValidationError):
        _declare(db, FederalIncomeTaxRegime.SIMPLES_NACIONAL, JAN)
    assert load_federal_regime_declarations(db, SCOPE) == ()


def test_change_of_regime_keeps_history_and_closes_previous_period(db) -> None:
    _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN, key="k1")
    _declare(db, FederalIncomeTaxRegime.LUCRO_REAL, JUL, key="k2")
    history = load_federal_regime_declarations(db, SCOPE)
    assert [(d.federal_income_tax_regime, d.version) for d in history] == [
        (FederalIncomeTaxRegime.LUCRO_PRESUMIDO, 1), (FederalIncomeTaxRegime.LUCRO_REAL, 2),
    ]
    assert history[0].effective_to == JUL
    assert federal_regime_status(db, SCOPE, _profile(), NOW)["federal_income_tax_regime"] == (
        "lucro_real"
    )
    assert federal_regime_status(db, SCOPE, _profile(), datetime(2026, 3, 1, tzinfo=UTC))[
        "federal_income_tax_regime"
    ] == "lucro_presumido"
    with pytest.raises(FiscalValidationError, match="start after"):
        _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN, key="k3")


def test_exact_retry_replays_and_changed_retry_conflicts(db) -> None:
    first = _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    again = _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    assert again["replay"] is True and again["version"] == first["version"]
    with pytest.raises(PersistenceConflictError):
        _declare(db, FederalIncomeTaxRegime.LUCRO_REAL, JAN)
    assert len(load_federal_regime_declarations(db, SCOPE)) == 1


def test_profile_crt_change_makes_old_declaration_inconsistent(db) -> None:
    _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    status = federal_regime_status(db, SCOPE, _profile(TaxRegimeCode.SIMPLES_NACIONAL), NOW)
    assert status == {"federal_regime_status": "declaration_inconsistent_with_profile"}


def test_declaration_store_denies_cross_host_scope(db) -> None:
    _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    other = replace(SCOPE, host_namespace="other-host")
    with pytest.raises(FiscalValidationError, match="canonical portal scope"):
        load_federal_regime_declarations(db, other)
    with pytest.raises(FiscalValidationError, match="canonical portal scope"):
        declare_federal_regime(
            db, scope=other, crt=TaxRegimeCode.NORMAL, issuer_cnpj=_profile().cnpj,
            federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_REAL,
            effective_from=JUL, source_reference="Other host", actor="acct-1",
            idempotency_key="foreign", occurred_at=NOW,
        )
    assert len(load_federal_regime_declarations(db, SCOPE)) == 1


def test_distinct_commands_cannot_commit_same_effective_date(db) -> None:
    barrier = Barrier(2)

    def submit(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN, key=f"race-{index}")
        except (FiscalValidationError, PersistenceConflictError):
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, (1, 2))) == ["committed", "conflict"]
    assert [d.version for d in load_federal_regime_declarations(db, SCOPE)] == [1]
    with db() as uow:
        assert uow.commercial.configuration_version(SCOPE, "federal_regime", "issuer") == 1
    result = _declare(db, FederalIncomeTaxRegime.LUCRO_REAL, JUL, key="after-race")
    assert result["version"] == 2


def test_previous_issuer_regime_is_not_inherited_by_new_cnpj(db) -> None:
    _declare(db, FederalIncomeTaxRegime.LUCRO_PRESUMIDO, JAN)
    stored = load_federal_regime_declarations(db, SCOPE)
    assert stored[0].issuer_cnpj == _profile().cnpj
    replacement = replace(_profile(), cnpj=Cnpj("12345678000195"))
    assert federal_regime_status(db, SCOPE, replacement, NOW) == {
        "federal_regime_status": "declaration_inconsistent_with_profile",
    }
