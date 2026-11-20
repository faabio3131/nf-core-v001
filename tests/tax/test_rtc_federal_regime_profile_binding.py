"""RTC-02 contract: corporate income-tax regime must match issuer profile scope/CRT."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

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
    SimplesIbsCbsElection,
    SimplesIbsCbsMode,
    SimplesOpeningOptionReceipt,
    SimplesRegularOptionReceipt2027H1,
    SimplesRegularOptionReceipt2027H2,
    SimplesRenunciationReceipt2027H2,
    resolve_federal_regime_for_profile,
    resolve_federal_regime_timeline,
    resolve_simples_ibs_cbs_mode,
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


def _simples_profile(scope: ExecutionScope | None = None) -> FiscalProfile:
    selected = scope or _scope()
    return replace(
        _profile(selected, crt=TaxRegimeCode.SIMPLES_NACIONAL),
        effective_to=None,
    )


def _simples_election(
    profile: FiscalProfile,
    *,
    mode: SimplesIbsCbsMode = SimplesIbsCbsMode.SIMPLES_UNIFIED,
    effective_from: datetime = datetime(2027, 1, 1, 3, tzinfo=UTC),
    effective_to: datetime | None = None,
) -> SimplesIbsCbsElection:
    return SimplesIbsCbsElection(
        scope=profile.scope,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        crt=profile.tax_regime,
        mode=mode,
        effective_from=effective_from,
        effective_to=effective_to,
        source_reference="synthetic-evidence:competent-authority-review-required",
    )


def _simples_receipt(
    profile: FiscalProfile,
    *,
    submitted_at: datetime = datetime(2026, 10, 30, 12, tzinfo=UTC),
    confirmed_at: datetime = datetime(2026, 10, 30, 13, tzinfo=UTC),
    cancelled_at: datetime | None = None,
) -> SimplesRegularOptionReceipt2027H1:
    return SimplesRegularOptionReceipt2027H1(
        scope=profile.scope,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        crt=profile.tax_regime,
        submitted_at=submitted_at,
        confirmed_at=confirmed_at,
        protocol_reference="TEST-CGSN-PROTOCOL-NOT-REAL",
        cancelled_at=cancelled_at,
    )


def test_simples_2026_is_non_rtc_without_authorizing_nfse_omission() -> None:
    profile = _simples_profile()
    assert resolve_simples_ibs_cbs_mode(
        profile, (), datetime(2026, 12, 31, 23, tzinfo=UTC)
    ) is SimplesIbsCbsMode.NOT_EFFECTIVE_IN_SIMPLES_2026


def test_simples_2027_requires_evidence_and_supports_either_collection_choice() -> None:
    profile = _simples_profile()
    instant = datetime(2027, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(FiscalValidationError, match="explicit effective"):
        resolve_simples_ibs_cbs_mode(profile, (), instant)
    for mode in (
        SimplesIbsCbsMode.SIMPLES_UNIFIED,
        SimplesIbsCbsMode.REGULAR_SEPARATE,
    ):
        assert resolve_simples_ibs_cbs_mode(
            profile, (_simples_election(profile, mode=mode),), instant,
            regular_option_receipt_2027_h1=(
                _simples_receipt(profile)
                if mode is SimplesIbsCbsMode.REGULAR_SEPARATE else None
            ),
        ) is mode


def test_simples_ibs_cbs_guard_rejects_cross_tenant_and_profile_version() -> None:
    profile = _simples_profile()
    other = _simples_profile(_scope("tenant-other"))
    instant = datetime(2027, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(FiscalValidationError, match="scope mismatch"):
        resolve_simples_ibs_cbs_mode(profile, (_simples_election(other),), instant)
    modified = replace(_simples_election(profile), profile_version=2)
    with pytest.raises(FiscalValidationError, match="snapshot mismatch"):
        resolve_simples_ibs_cbs_mode(profile, (modified,), instant)


def test_simples_ibs_cbs_guard_rejects_overlap_gaps_and_earlier_periods() -> None:
    profile = _simples_profile()
    instant = datetime(2027, 6, 1, tzinfo=UTC)
    first = _simples_election(
        profile,
        effective_to=datetime(2027, 7, 1, 3, tzinfo=UTC),
    )
    overlapping = _simples_election(
        profile,
        effective_from=datetime(2027, 6, 1, 3, tzinfo=UTC),
    )
    with pytest.raises(FiscalValidationError, match="overlapping"):
        resolve_simples_ibs_cbs_mode(profile, (first, overlapping), instant)
    with pytest.raises(FiscalValidationError, match="explicit effective"):
        resolve_simples_ibs_cbs_mode(
            profile,
            (_simples_election(profile, effective_from=instant + timedelta(days=1)),),
            instant,
        )
    with pytest.raises(FiscalValidationError, match="cannot predate"):
        resolve_simples_ibs_cbs_mode(
            profile,
            (_simples_election(profile, effective_from=datetime(2026, 12, 31, 3, tzinfo=UTC)),),
            instant,
        )


def test_simples_excess_sublimit_crt2_resolves_explicit_ibscbs_mode() -> None:
    profile = replace(
        _simples_profile(),
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
    )
    instant = datetime(2027, 1, 1, 12, tzinfo=UTC)
    for mode in (
        SimplesIbsCbsMode.SIMPLES_UNIFIED,
        SimplesIbsCbsMode.REGULAR_SEPARATE,
    ):
        election = _simples_election(profile, mode=mode)
        assert resolve_simples_ibs_cbs_mode(
            profile, (election,), instant,
            regular_option_receipt_2027_h1=(
                _simples_receipt(profile)
                if mode is SimplesIbsCbsMode.REGULAR_SEPARATE else None
            ),
        ) is mode
    with pytest.raises(FiscalValidationError, match="explicit effective"):
        resolve_simples_ibs_cbs_mode(profile, (), instant)
    assert resolve_simples_ibs_cbs_mode(
        profile, (), datetime(2026, 12, 31, 12, tzinfo=UTC)
    ) is SimplesIbsCbsMode.NOT_EFFECTIVE_IN_SIMPLES_2026


def test_crt1_and_crt2_elections_cannot_cross_issuer_snapshot() -> None:
    base = _simples_profile()
    excess = replace(base, tax_regime=TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT)
    with pytest.raises(FiscalValidationError, match="CRT mismatch"):
        resolve_simples_ibs_cbs_mode(
            excess, (_simples_election(base),), datetime(2027, 1, 1, 12, tzinfo=UTC)
        )
    with pytest.raises(FiscalValidationError, match="CRT mismatch"):
        resolve_simples_ibs_cbs_mode(
            base, (_simples_election(excess),), datetime(2027, 1, 1, 12, tzinfo=UTC)
        )


def test_simples_mode_must_not_be_inferred_from_normal_crt_or_mei() -> None:
    instant = datetime(2027, 1, 1, 12, tzinfo=UTC)
    for crt in (TaxRegimeCode.NORMAL, TaxRegimeCode.MEI):
        other = replace(_simples_profile(), tax_regime=crt)
        with pytest.raises(FiscalValidationError, match="CRT=1 or CRT=2"):
            resolve_simples_ibs_cbs_mode(other, (), instant)


def test_simples_mode_rejects_naive_dates_and_unverified_mode() -> None:
    profile = _simples_profile()
    with pytest.raises(FiscalValidationError, match="timezone-aware"):
        resolve_simples_ibs_cbs_mode(profile, (), datetime(2027, 1, 1))
    with pytest.raises(FiscalValidationError, match="invalid Simples IBS/CBS election mode"):
        _simples_election(profile, mode=SimplesIbsCbsMode.NOT_EFFECTIVE_IN_SIMPLES_2026)


def test_regular_2027_h1_requires_confirmed_external_receipt() -> None:
    profile = _simples_profile()
    date_in_h1 = datetime(2027, 3, 1, tzinfo=UTC)
    election = _simples_election(profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE)
    with pytest.raises(FiscalValidationError, match="external receipt"):
        resolve_simples_ibs_cbs_mode(profile, (election,), date_in_h1)
    assert resolve_simples_ibs_cbs_mode(
        profile, (election,), date_in_h1,
        regular_option_receipt_2027_h1=_simples_receipt(profile),
    ) is SimplesIbsCbsMode.REGULAR_SEPARATE


@pytest.mark.parametrize(
    "submitted_at",
    (
        datetime(2026, 8, 31, 12, tzinfo=UTC),
        datetime(2026, 10, 31, 12, tzinfo=UTC),
    ),
)
def test_regular_2027_h1_rejects_filing_outside_cgsn_window(
    submitted_at: datetime,
) -> None:
    profile = _simples_profile()
    with pytest.raises(FiscalValidationError, match="filing window"):
        _simples_receipt(
            profile,
            submitted_at=submitted_at,
            confirmed_at=submitted_at + timedelta(hours=1),
        )


def test_regular_2027_h1_rejects_confirmation_before_submission() -> None:
    profile = _simples_profile()
    with pytest.raises(FiscalValidationError, match="confirmation precedes submission"):
        _simples_receipt(
            profile,
            submitted_at=datetime(2026, 10, 30, 12, tzinfo=UTC),
            confirmed_at=datetime(2026, 10, 29, 12, tzinfo=UTC),
        )


def test_regular_2027_h1_cancellation_fails_closed() -> None:
    profile = _simples_profile()
    receipt = _simples_receipt(
        profile, cancelled_at=datetime(2026, 11, 3, 12, tzinfo=UTC)
    )
    with pytest.raises(FiscalValidationError, match="cancelled"):
        resolve_simples_ibs_cbs_mode(
            profile,
            (_simples_election(profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE),),
            datetime(2027, 3, 1, tzinfo=UTC),
            regular_option_receipt_2027_h1=receipt,
        )
    with pytest.raises(FiscalValidationError, match="cancellation outside window"):
        _simples_receipt(
            profile, cancelled_at=datetime(2026, 11, 2, 12, tzinfo=UTC)
        )


def test_regular_2027_h1_denies_receipt_from_other_issuer_or_crt() -> None:
    profile = _simples_profile()
    election = _simples_election(
        profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE
    )
    instant = datetime(2027, 1, 3, tzinfo=UTC)
    with pytest.raises(FiscalValidationError, match="scope mismatch"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant,
            regular_option_receipt_2027_h1=_simples_receipt(
                _simples_profile(_scope("foreign-tenant"))
            ),
        )
    with pytest.raises(FiscalValidationError, match="CRT mismatch"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant,
            regular_option_receipt_2027_h1=_simples_receipt(
                replace(profile, tax_regime=TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT)
            ),
        )


def test_regular_option_not_extrapolated_into_2027_second_semester() -> None:
    profile = _simples_profile()
    with pytest.raises(FiscalValidationError, match="period not verified"):
        resolve_simples_ibs_cbs_mode(
            profile,
            (_simples_election(profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE),),
            datetime(2027, 7, 1, 12, tzinfo=UTC),
            regular_option_receipt_2027_h1=_simples_receipt(profile),
        )


def test_simples_unified_choice_requires_no_regular_option_receipt() -> None:
    profile = _simples_profile()
    assert resolve_simples_ibs_cbs_mode(
        profile, (_simples_election(profile),), datetime(2027, 7, 1, 12, tzinfo=UTC)
    ) is SimplesIbsCbsMode.SIMPLES_UNIFIED


def test_regular_2027_h2_new_option_and_confirmed_continuation() -> None:
    profile = _simples_profile()
    instant = datetime(2027, 7, 1, 12, tzinfo=UTC)
    election = _simples_election(profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE)
    prior = _simples_receipt(profile)
    common = dict(
        scope=profile.scope, profile_id=profile.profile_id, profile_version=profile.version,
        crt=profile.tax_regime, protocol_reference="synthetic-h2",
        confirmed_at=datetime(2027, 6, 1, 12, tzinfo=UTC),
    )
    fresh = SimplesRegularOptionReceipt2027H2(
        **common, submitted_at=datetime(2027, 3, 10, 12, tzinfo=UTC),
    )
    continued = SimplesRegularOptionReceipt2027H2(
        **common, prior_protocol_reference=prior.protocol_reference,
    )
    for receipt in (fresh, continued):
        assert resolve_simples_ibs_cbs_mode(
            profile, (election,), instant, regular_option_receipt_2027_h1=prior,
            regular_option_receipt_2027_h2=receipt,
        ) is SimplesIbsCbsMode.REGULAR_SEPARATE
    with pytest.raises(FiscalValidationError, match="prior reviewed"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant, regular_option_receipt_2027_h2=continued,
        )
    with pytest.raises(FiscalValidationError, match="filing window"):
        SimplesRegularOptionReceipt2027H2(
            **common, submitted_at=datetime(2027, 4, 1, 12, tzinfo=UTC),
        )
    with pytest.raises(FiscalValidationError, match="cancelled"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant,
            regular_option_receipt_2027_h2=replace(
                fresh, cancelled_at=datetime(2027, 5, 15, 12, tzinfo=UTC),
            ),
        )


def test_h2_renunciation_requires_prior_protocol_and_not_cancelled() -> None:
    profile = _simples_profile()
    prior = _simples_receipt(profile)
    election = _simples_election(profile)
    instant = datetime(2027, 7, 1, 12, tzinfo=UTC)
    receipt = SimplesRenunciationReceipt2027H2(
        profile.scope, profile.profile_id, profile.version, profile.tax_regime,
        datetime(2027, 3, 15, 12, tzinfo=UTC), datetime(2027, 3, 15, 13, tzinfo=UTC),
        "renunciation-fixture", prior.protocol_reference,
    )
    with pytest.raises(FiscalValidationError, match="renunciation"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant, regular_option_receipt_2027_h1=prior,
        )
    assert resolve_simples_ibs_cbs_mode(
        profile, (election,), instant, regular_option_receipt_2027_h1=prior,
        renunciation_receipt=receipt,
    ) is SimplesIbsCbsMode.SIMPLES_UNIFIED
    with pytest.raises(FiscalValidationError, match="cancelled"):
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant, regular_option_receipt_2027_h1=prior,
            renunciation_receipt=replace(
                receipt, cancelled_at=datetime(2027, 5, 31, 12, tzinfo=UTC),
            ),
        )


def test_opening_april_option_covers_second_semester() -> None:
    profile = _simples_profile()
    opening = SimplesOpeningOptionReceipt(
        profile.scope, profile.profile_id, profile.version, profile.tax_regime,
        date(2027, 4, 10), datetime(2027, 4, 10, 12, tzinfo=UTC),
        datetime(2027, 4, 10, 13, tzinfo=UTC), "regular", "simples", "mat",
    )
    election = _simples_election(
        profile, mode=SimplesIbsCbsMode.REGULAR_SEPARATE,
        effective_from=datetime(2027, 4, 10, 3, tzinfo=UTC),
    )
    assert resolve_simples_ibs_cbs_mode(
        profile, (election,), datetime(2027, 7, 1, 12, tzinfo=UTC), opening_receipt=opening,
    ) is SimplesIbsCbsMode.REGULAR_SEPARATE
    with pytest.raises(FiscalValidationError, match="simultaneous"):
        replace(opening, registered_on=date(2027, 4, 9))
