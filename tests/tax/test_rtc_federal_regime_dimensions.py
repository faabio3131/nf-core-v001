"""RTC-02: no inference of Lucro Real vs Presumido from CRT=3."""

from datetime import UTC, datetime

import pytest

from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime, FederalRegimeDeclaration


def _scope(tenant_id: str = "tenant-a") -> ExecutionScope:
    return ExecutionScope(
        tenant_id=tenant_id,
        unit_id="unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="rtc02-test",
    )


def _declaration(
    regime: FederalIncomeTaxRegime,
    *,
    scope: ExecutionScope | None = None,
    **overrides: object,
) -> FederalRegimeDeclaration:
    values: dict[str, object] = {
        "scope": scope or _scope(),
        "crt": TaxRegimeCode.NORMAL,
        "federal_income_tax_regime": regime,
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "source_reference": "documented-authority:synthetic-test",
    }
    values.update(overrides)
    return FederalRegimeDeclaration(**values)  # type: ignore[arg-type]


def test_normal_crt_does_not_collapse_presumido_and_real() -> None:
    presumido = _declaration(FederalIncomeTaxRegime.LUCRO_PRESUMIDO)
    real = _declaration(FederalIncomeTaxRegime.LUCRO_REAL)
    assert presumido.crt == real.crt == TaxRegimeCode.NORMAL
    assert presumido.federal_income_tax_regime != real.federal_income_tax_regime


def test_all_three_regimes_require_explicit_declaration() -> None:
    for regime in FederalIncomeTaxRegime:
        declaration = _declaration(regime)
        assert declaration.federal_income_tax_regime is regime
    with pytest.raises(FiscalValidationError, match="must be explicit"):
        _declaration(FederalIncomeTaxRegime.LUCRO_REAL, federal_income_tax_regime=None)


def test_scope_and_temporal_partition_fail_closed() -> None:
    declaration = _declaration(
        FederalIncomeTaxRegime.LUCRO_PRESUMIDO,
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
    )
    declaration.assert_effective_in_scope(_scope(), datetime(2026, 12, 31, tzinfo=UTC))
    with pytest.raises(FiscalValidationError, match="scope mismatch"):
        declaration.assert_effective_in_scope(_scope("tenant-b"), datetime(2026, 6, 1, tzinfo=UTC))
    with pytest.raises(FiscalValidationError, match="not effective"):
        declaration.assert_effective_in_scope(_scope(), datetime(2027, 1, 1, tzinfo=UTC))
    with pytest.raises(FiscalValidationError, match="timezone-aware"):
        declaration.assert_effective_in_scope(_scope(), datetime(2026, 6, 1))


def test_invalid_declaration_is_rejected() -> None:
    with pytest.raises(FiscalValidationError, match="source_reference"):
        _declaration(FederalIncomeTaxRegime.LUCRO_REAL, source_reference="")
    with pytest.raises(FiscalValidationError, match="version"):
        _declaration(FederalIncomeTaxRegime.LUCRO_REAL, version=0)
    with pytest.raises(FiscalValidationError, match="effective_to"):
        _declaration(
            FederalIncomeTaxRegime.LUCRO_REAL,
            effective_to=datetime(2025, 12, 31, tzinfo=UTC),
        )
