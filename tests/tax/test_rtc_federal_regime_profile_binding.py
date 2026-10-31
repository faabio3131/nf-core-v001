"""RTC-02 contract: corporate income-tax regime must match issuer profile scope/CRT."""

from datetime import UTC, datetime

import pytest

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
from kordena_fiscal.tax.regimes import (
    FederalIncomeTaxRegime,
    FederalRegimeDeclaration,
    resolve_federal_regime_for_profile,
    resolve_federal_regime_timeline,
)

_NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _scope(tenant: str = "tenant-a") -> ExecutionScope:
    return ExecutionScope(
        tenant_id=tenant,
        unit_id="unit-1",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="rtc02-binding-synthetic",
    )


def _profile(scope: ExecutionScope, *, crt: TaxRegimeCode = TaxRegimeCode.NORMAL) -> FiscalProfile:
    return FiscalProfile(
        profile_id="issuer-synthetic",
        scope=scope,
        cnpj=Cnpj("12.345.678/0001-95"),
        legal_name="Emissor de Teste Ltda",
        tax_regime=crt,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("5611-2/01"),
        address=FiscalAddress(
            street="Rua Exemplo",
            number="100",
            district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
    )


def _declaration(
    scope: ExecutionScope,
    federal: FederalIncomeTaxRegime,
    *,
    crt: TaxRegimeCode = TaxRegimeCode.NORMAL,
) -> FederalRegimeDeclaration:
    return FederalRegimeDeclaration(
        scope=scope,
        crt=crt,
        federal_income_tax_regime=federal,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        source_reference="synthetic-approved-corporate-regime-evidence",
    )


def test_normal_crt_resolves_presumido_and_real_only_from_explicit_evidence() -> None:
    scope = _scope()
    profile = _profile(scope)
    for regime in (FederalIncomeTaxRegime.LUCRO_PRESUMIDO, FederalIncomeTaxRegime.LUCRO_REAL):
        result = resolve_federal_regime_for_profile(profile, _declaration(scope, regime), _NOW)
        assert result is regime


def test_cross_tenant_declaration_is_denied() -> None:
    with pytest.raises(FiscalValidationError, match="scope mismatch"):
        resolve_federal_regime_for_profile(
            _profile(_scope("tenant-a")),
            _declaration(_scope("tenant-b"), FederalIncomeTaxRegime.LUCRO_REAL),
            _NOW,
        )


def test_conflicting_crt_is_denied() -> None:
    scope = _scope()
    with pytest.raises(FiscalValidationError, match="CRT does not match"):
        resolve_federal_regime_for_profile(
            _profile(scope),
            _declaration(
                scope, FederalIncomeTaxRegime.SIMPLES_NACIONAL, crt=TaxRegimeCode.SIMPLES_NACIONAL
            ),
            _NOW,
        )


def test_expired_issuer_profile_is_denied() -> None:
    scope = _scope()
    with pytest.raises(FiscalValidationError, match="profile is not effective"):
        resolve_federal_regime_for_profile(
            _profile(scope),
            _declaration(scope, FederalIncomeTaxRegime.LUCRO_REAL),
            datetime(2027, 1, 1, tzinfo=UTC),
        )


def test_missing_declaration_is_denied() -> None:
    with pytest.raises(FiscalValidationError, match="declaration is required"):
        resolve_federal_regime_for_profile(
            _profile(_scope()),
            None,  # type: ignore[arg-type]
            _NOW,
        )


def test_regime_timeline_uses_explicit_periods_at_boundary() -> None:
    scope = _scope()
    profile = _profile(scope)
    first = FederalRegimeDeclaration(
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_PRESUMIDO,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 7, 1, tzinfo=UTC),
        source_reference="synthetic-presumido",
    )
    second = FederalRegimeDeclaration(
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_REAL,
        effective_from=datetime(2026, 7, 1, tzinfo=UTC),
        source_reference="synthetic-real",
        version=2,
    )
    assert resolve_federal_regime_timeline(
        profile, (second, first), datetime(2026, 6, 30, tzinfo=UTC)
    ) is FederalIncomeTaxRegime.LUCRO_PRESUMIDO
    assert resolve_federal_regime_timeline(
        profile, (second, first), datetime(2026, 7, 1, tzinfo=UTC)
    ) is FederalIncomeTaxRegime.LUCRO_REAL


def test_regime_timeline_rejects_overlaps_even_if_one_is_not_current() -> None:
    scope = _scope()
    a = _declaration(scope, FederalIncomeTaxRegime.LUCRO_REAL)
    b = _declaration(scope, FederalIncomeTaxRegime.LUCRO_PRESUMIDO)
    with pytest.raises(FiscalValidationError, match="overlap"):
        resolve_federal_regime_timeline(_profile(scope), (a, b), _NOW)


def test_regime_timeline_rejects_cross_tenant_collection() -> None:
    scope = _scope()
    a = _declaration(scope, FederalIncomeTaxRegime.LUCRO_REAL)
    b = _declaration(_scope("other"), FederalIncomeTaxRegime.LUCRO_REAL)
    with pytest.raises(FiscalValidationError, match="scope mismatch"):
        resolve_federal_regime_timeline(_profile(scope), (a, b), _NOW)


def test_regime_timeline_fails_closed_on_gap_or_empty_input() -> None:
    scope = _scope()
    with pytest.raises(FiscalValidationError, match="no federal regime declarations"):
        resolve_federal_regime_timeline(_profile(scope), (), _NOW)
    later = FederalRegimeDeclaration(
        scope=scope,
        crt=TaxRegimeCode.NORMAL,
        federal_income_tax_regime=FederalIncomeTaxRegime.LUCRO_REAL,
        effective_from=datetime(2026, 11, 1, tzinfo=UTC),
        source_reference="synthetic-later",
    )
    with pytest.raises(FiscalValidationError, match="no unambiguous"):
        resolve_federal_regime_timeline(_profile(scope), (later,), _NOW)


def test_regime_timeline_checks_effective_crt_against_issuer_profile() -> None:
    scope = _scope()
    mismatched = _declaration(
        scope, FederalIncomeTaxRegime.SIMPLES_NACIONAL,
        crt=TaxRegimeCode.SIMPLES_NACIONAL,
    )
    with pytest.raises(FiscalValidationError, match="CRT does not match"):
        resolve_federal_regime_timeline(_profile(scope), (mismatched,), _NOW)
