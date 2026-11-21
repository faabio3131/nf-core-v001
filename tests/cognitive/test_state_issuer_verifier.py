"""T09 issuer UF and state registration come from FiscalProfile, never HTTP."""
from dataclasses import replace

import pytest

from kordena_fiscal.cognitive.state_benefits_api import build_state_issuer_verifier
from kordena_fiscal.domain import FiscalValidationError, StateRegistration
from kordena_fiscal.tax.federal_benefits import ReviewedFederalIssuer
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

from .test_federal_issuer_verifier import (
    ISSUER,
    MONTH,
    SCOPE,
    _factory,
    _profile,
)


def _federal(factory, scope):
    assert scope == SCOPE
    return lambda cnpj, month: ReviewedFederalIssuer(
        cnpj=cnpj, cnae="8011101",
        regime=FederalIncomeTaxRegime.LUCRO_REAL,
        scope_identity=scope.identity_material,
    )


def test_state_issuer_is_bound_to_canonical_uf_regime_and_registration(monkeypatch):
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.state_benefits_api.build_federal_issuer_verifier",
        _federal,
    )
    issuer_profile = replace(
        _profile(), state_registration=StateRegistration("SP", "1234567"),
    )
    actual = build_state_issuer_verifier(_factory(issuer_profile), SCOPE)(
        ISSUER.value, MONTH,
    )
    assert actual.uf == "SP"
    assert actual.primary_cnae == "8011101"
    assert actual.state_registration_present is True
    assert actual.regime is FederalIncomeTaxRegime.LUCRO_REAL
    assert actual.scope_identity == SCOPE.identity_material


def test_exempt_state_registration_never_becomes_verified_icms_status(monkeypatch):
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.state_benefits_api.build_federal_issuer_verifier",
        _federal,
    )
    actual = build_state_issuer_verifier(_factory(_profile()), SCOPE)(
        ISSUER.value, MONTH,
    )
    assert actual.state_registration_present is False


def test_state_issuer_conflict_fails_closed_without_second_authority(monkeypatch):
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.state_benefits_api.build_federal_issuer_verifier",
        _federal,
    )
    issuer_profile = replace(
        _profile(), state_registration=StateRegistration("SP", "1234567"),
    )
    fake = _factory(issuer_profile)
    verifier = build_state_issuer_verifier(fake, SCOPE)
    with pytest.raises(FiscalValidationError, match="canonical"):
        verifier("12345678000195", MONTH)
