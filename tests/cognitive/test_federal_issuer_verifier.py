"""T08 canonical issuer test: monthly profile and federal regime, no CRT inference."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from kordena_fiscal.cognitive.federal_benefits_api import build_federal_issuer_verifier
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
)

SCOPE = ExecutionScope(
    "tenant-a", "unit-a", FiscalEnvironment.HOMOLOGATION, "federal-test", "fm-nfcore",
)
ISSUER = Cnpj("09107283000140")
MONTH = date(2026, 11, 1)


def _profile():
    return FiscalProfile(
        profile_id="issuer", scope=SCOPE, cnpj=ISSUER,
        legal_name="Empresa Sintetica", tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", None, exempt=True),
        primary_cnae=CnaeCode("8011101"),
        address=FiscalAddress(
            street="Rua A", number="1", district="Centro", municipality_name="Cajamar",
            jurisdiction=BrazilianJurisdiction("SP", "3509205"), postal_code="07750000",
        ),
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _declaration(regime, effective):
    return FederalRegimeDeclaration(
        scope=SCOPE, crt=TaxRegimeCode.NORMAL,
        federal_income_tax_regime=regime, effective_from=effective,
        source_reference="ECF-2026-reviewed", issuer_cnpj=ISSUER,
    )


class Uow:
    def __init__(self, profile, *, alternate=None):
        self.profile = profile
        self.alternate = alternate
        self.calls = 0
        self.control_plane = self

    def resolve_profile(self, **kwargs):
        assert kwargs["tenant_id"] == SCOPE.tenant_id
        assert kwargs["unit_id"] == SCOPE.unit_id
        self.calls += 1
        return self.alternate if self.calls > 1 and self.alternate else self.profile


def _factory(profile, *, alternate=None):
    uow = Uow(profile, alternate=alternate)

    @contextmanager
    def make_uow():
        yield uow

    return make_uow


def test_verifier_uses_federal_declaration_not_normal_crt(monkeypatch):
    declaration = _declaration(
        FederalIncomeTaxRegime.LUCRO_REAL, datetime(2025, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (declaration,),
    )
    actual = build_federal_issuer_verifier(_factory(_profile()), SCOPE)(ISSUER.value, MONTH)
    assert actual.cnpj == ISSUER.value
    assert actual.cnae == "8011101"
    assert actual.regime is FederalIncomeTaxRegime.LUCRO_REAL
    assert actual.scope_identity == SCOPE.identity_material


def test_verifier_rejects_missing_federal_regime_evidence(monkeypatch):
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (),
    )
    with pytest.raises(FiscalValidationError, match="no federal regime"):
        build_federal_issuer_verifier(_factory(_profile()), SCOPE)(ISSUER.value, MONTH)


def test_verifier_rejects_profile_change_mid_competence(monkeypatch):
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (),
    )
    changed = replace(_profile(), version=2)
    with pytest.raises(FiscalValidationError, match="not stable"):
        build_federal_issuer_verifier(
            _factory(_profile(), alternate=changed), SCOPE,
        )(ISSUER.value, MONTH)


def test_verifier_rejects_regime_change_mid_competence(monkeypatch):
    earlier = _declaration(
        FederalIncomeTaxRegime.LUCRO_REAL, datetime(2025, 1, 1, tzinfo=UTC),
    )
    later = replace(
        _declaration(
            FederalIncomeTaxRegime.LUCRO_PRESUMIDO, datetime(2026, 11, 15, tzinfo=UTC),
        ),
        version=2,
    )
    earlier = replace(earlier, effective_to=later.effective_from)
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (earlier, later),
    )
    with pytest.raises(FiscalValidationError, match="changed"):
        build_federal_issuer_verifier(_factory(_profile()), SCOPE)(ISSUER.value, MONTH)


def test_verifier_rejects_wrong_issuer_and_foreign_scope(monkeypatch):
    declaration = _declaration(
        FederalIncomeTaxRegime.LUCRO_REAL, datetime(2025, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (declaration,),
    )
    verifier = build_federal_issuer_verifier(_factory(_profile()), SCOPE)
    with pytest.raises(FiscalValidationError, match="canonical issuer"):
        verifier("12345678000195", MONTH)


@pytest.mark.parametrize("mutation, expected", [
    ("valid", True), ("absent", None), ("cancelled", None), ("foreign", None),
    ("unified", False), ("partial", None),
])
def test_t08_reads_monthly_t07_option(monkeypatch, mutation, expected):
    profile = replace(_profile(), tax_regime=TaxRegimeCode.SIMPLES_NACIONAL)
    month = date(2027, 1, 1)
    declaration = replace(
        _declaration(FederalIncomeTaxRegime.LUCRO_REAL, profile.effective_from),
        federal_income_tax_regime=FederalIncomeTaxRegime.SIMPLES_NACIONAL,
        crt=profile.tax_regime,
    )
    monkeypatch.setattr(
        "kordena_fiscal.cognitive.federal_benefits_api.load_federal_regime_declarations",
        lambda factory, scope: (declaration,),
    )
    bound = dict(scope_identity=list(SCOPE.identity_material), issuer_cnpj=ISSUER.value,
                 profile_id=profile.profile_id, profile_version=profile.version,
                 crt=int(profile.tax_regime))
    receipt = dict(**bound, submitted_at="2026-10-30T12:00:00+00:00",
                   confirmed_at="2026-10-30T13:00:00+00:00", protocol_reference="TEST-RECEIPT")
    election = dict(**bound, mode="regular_separate", effective_from="2027-01-01T03:00:00+00:00",
                    regular_option_receipt_2027_h1=receipt, version=1, source_reference="fixture")
    if mutation == "cancelled":
        receipt["cancelled_at"] = "2026-11-03T12:00:00+00:00"
    if mutation == "foreign":
        receipt["issuer_cnpj"] = "12345678000195"
    if mutation == "partial":
        election["effective_to"] = "2027-01-16T03:00:00+00:00"
    if mutation == "unified":
        election.pop("regular_option_receipt_2027_h1")
        election.update(mode="simples_unified", refund_restriction_clear=True)

    class Store:
        def unique_monthly_snapshot(self, issuer, competence, schema):
            assert (issuer, competence) == (ISSUER.value, month)
            if mutation == "absent":
                return None
            return {"issuer_cnpj": issuer, "content": {
                "opened_month": "2025-01-01", "ibs_cbs_election": election,
            }}

    result = build_federal_issuer_verifier(_factory(profile), SCOPE, Store())(ISSUER.value, month)
    assert result.ibs_cbs_regular_authorized is expected
