import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from kordena_fiscal.compliance.rtc import (
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_calculation_preview import (
    calculate_2026_art12_base_preview,
    calculate_2026_audited_preview_bundle,
    calculate_2026_nominal_reference_preview,
    calculate_rule_bound_rtc_preview,
)
from kordena_fiscal.compliance.rtc_catalog import (
    VerifiedRtcClassificationCatalog,
    load_verified_rtc_classification_catalog,
    resolve_rule_with_verified_rtc_catalog,
    resolve_strict_rtc_2026_incidence_candidate,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalProductProfile,
    FiscalUnitCode,
    FiscalValidationError,
    Gtin,
    Money,
    NcmCode,
    ProductOrigin,
    TaxRegimeCode,
)
from kordena_fiscal.tax import (
    RecipientTaxProfile,
    TaxOperationType,
    TaxRule,
    TaxRuleAmbiguityError,
    TaxRuleContext,
    TaxRuleEngine,
    TaxRuleNotFoundError,
    TaxRuleOutcome,
    TaxRuleSelector,
)


def _instant(day: int) -> datetime:
    return datetime(2026, 9, day, 12, 0, tzinfo=UTC)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-synthetic",
        unit_id="unit-synthetic",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-tax-1",
    )


def _product(scope: ExecutionScope | None = None) -> FiscalProductProfile:
    return FiscalProductProfile(
        profile_id="product-profile-1",
        product_id="product-1",
        scope=scope or _scope(),
        commercial_code="SKU-001",
        description="Produto sintético",
        ncm=NcmCode("21069090"),
        commercial_unit=FiscalUnitCode("UN"),
        taxable_unit=FiscalUnitCode("UN"),
        origin=ProductOrigin.NATIONAL,
        effective_from=_instant(1),
        gtin=Gtin("SEM GTIN"),
    )


def _context(**overrides: object) -> TaxRuleContext:
    scope = overrides.pop("scope", _scope())
    assert isinstance(scope, ExecutionScope)
    values: dict[str, object] = {
        "scope": scope,
        "instant": _instant(10),
        "jurisdiction": BrazilianJurisdiction("SP", "3550308"),
        "tax_regime": TaxRegimeCode.SIMPLES_NACIONAL,
        "document_kind": FiscalDocumentKind.NFCE,
        "operation_type": TaxOperationType.SALE,
        "recipient_profile": RecipientTaxProfile.CONSUMER_FINAL,
        "product": _product(scope),
    }
    values.update(overrides)
    return TaxRuleContext(**values)  # type: ignore[arg-type]


def _outcome(cfop: str = "5102") -> TaxRuleOutcome:
    return TaxRuleOutcome(
        cfop=cfop,
        icms_code="102",
        pis_cst="49",
        cofins_cst="49",
        ibs_cbs_classification_code="000001",
        legal_notes=("Regra sintética de teste",),
    )


def _rule(
    rule_id: str,
    selector: TaxRuleSelector,
    *,
    cfop: str = "5102",
    start: int = 1,
    end: int | None = None,
    priority: int = 0,
    version: int = 1,
) -> TaxRule:
    return TaxRule(
        rule_id=rule_id,
        version=version,
        selector=selector,
        outcome=_outcome(cfop),
        source_normative="NORMA-SINTETICA-TESTE",
        effective_from=_instant(start),
        effective_to=_instant(end) if end is not None else None,
        priority=priority,
    )


def test_engine_prefers_more_specific_rule() -> None:
    generic = _rule("generic", TaxRuleSelector(), cfop="5101")
    state = _rule("state", TaxRuleSelector(state_code="SP"), cfop="5102")
    ncm = _rule(
        "state-ncm",
        TaxRuleSelector(state_code="SP", ncm_prefix="2106"),
        cfop="5103",
    )

    decision = TaxRuleEngine().resolve(_context(), [generic, state, ncm])

    assert decision.rule_id == "state-ncm"
    assert decision.outcome.cfop == "5103"
    assert decision.source_normative == "NORMA-SINTETICA-TESTE"
    assert decision.rank == (2, 4, 0)


def test_municipality_rule_beats_state_rule() -> None:
    state = _rule("state", TaxRuleSelector(state_code="SP"))
    municipality = _rule(
        "municipality",
        TaxRuleSelector(state_code="SP", municipality_ibge_code="3550308"),
        cfop="5103",
    )

    decision = TaxRuleEngine().resolve(_context(), [state, municipality])

    assert decision.rule_id == "municipality"


def test_engine_respects_effective_window() -> None:
    expired = _rule("expired", TaxRuleSelector(state_code="SP"), start=1, end=5)
    current = _rule("current", TaxRuleSelector(state_code="SP"), start=5)

    decision = TaxRuleEngine().resolve(_context(), [expired, current])

    assert decision.rule_id == "current"


def test_priority_breaks_tie_after_specificity() -> None:
    low = _rule("low", TaxRuleSelector(state_code="SP"), priority=1)
    high = _rule("high", TaxRuleSelector(state_code="SP"), priority=2)

    decision = TaxRuleEngine().resolve(_context(), [low, high])

    assert decision.rule_id == "high"
    assert decision.rank == (1, 0, 2)


def test_equal_winning_rank_is_rejected_as_ambiguous() -> None:
    first = _rule("first", TaxRuleSelector(state_code="SP"))
    second = _rule("second", TaxRuleSelector(state_code="SP"), version=2)

    with pytest.raises(TaxRuleAmbiguityError, match="ambiguous tax rules"):
        TaxRuleEngine().resolve(_context(), [first, second])


def test_no_match_fails_closed() -> None:
    rio = _rule("rio", TaxRuleSelector(state_code="RJ"))

    with pytest.raises(TaxRuleNotFoundError, match="no effective tax rule"):
        TaxRuleEngine().resolve(_context(), [rio])


def test_selector_matches_regime_document_operation_recipient_and_ncm() -> None:
    selector = TaxRuleSelector(
        state_code="SP",
        municipality_ibge_code="3550308",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        document_kind=FiscalDocumentKind.NFCE,
        operation_type=TaxOperationType.SALE,
        recipient_profile=RecipientTaxProfile.CONSUMER_FINAL,
        ncm_prefix="210690",
    )

    assert selector.matches(_context()) is True
    assert selector.matches(_context(tax_regime=TaxRegimeCode.NORMAL)) is False


def test_tax_context_rejects_product_from_another_scope() -> None:
    context_scope = _scope()
    other_scope = ExecutionScope(
        tenant_id="tenant-other",
        unit_id="unit-synthetic",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-other",
    )

    with pytest.raises(FiscalValidationError, match="same scope"):
        _context(scope=context_scope, product=_product(other_scope))


def test_tax_context_requires_effective_product_snapshot() -> None:
    scope = _scope()
    product = FiscalProductProfile(
        profile_id="future-product",
        product_id="product-1",
        scope=scope,
        commercial_code="SKU-001",
        description="Produto futuro sintético",
        ncm=NcmCode("21069090"),
        commercial_unit=FiscalUnitCode("UN"),
        taxable_unit=FiscalUnitCode("UN"),
        origin=ProductOrigin.NATIONAL,
        effective_from=_instant(20),
    )

    with pytest.raises(FiscalValidationError, match="not effective"):
        _context(scope=scope, product=product)


def test_rule_and_outcome_validate_required_shapes() -> None:
    with pytest.raises(FiscalValidationError, match="cfop"):
        _outcome("510")

    with pytest.raises(FiscalValidationError, match="source_normative"):
        TaxRule(
            rule_id="rule-1",
            version=1,
            selector=TaxRuleSelector(),
            outcome=_outcome(),
            source_normative=" ",
            effective_from=_instant(1),
        )

    with pytest.raises(FiscalValidationError, match="ncm_prefix"):
        TaxRuleSelector(ncm_prefix="2")

    with pytest.raises(FiscalValidationError, match="explicit state_code"):
        TaxRuleSelector(municipality_ibge_code="3550308")


def _synthetic_rtc_catalog() -> VerifiedRtcClassificationCatalog:
    # Synthetic fixtures still pass through the pinned bytes/digest validator.
    payload = json.dumps(
        {
            "schema_version": 1,
            "artifact_id": "IBSCBS-CCLASSTRIB",
            "artifact_version": "SYNTHETIC-v1",
            "records": [{"cst": "000", "cclass_trib": "000001"}],
        },
        sort_keys=True,
    ).encode("utf-8")
    baseline = RegulatoryBaseline(
        baseline_id="synthetic-rtc-tax-rule",
        version=1,
        captured_at=datetime(2026, 9, 10, tzinfo=UTC),
        artifacts=(
            RegulatoryArtifactPin(
                artifact_id="IBSCBS-CCLASSTRIB",
                kind=RegulatoryArtifactKind.CLASSIFICATION_TABLE,
                version="SYNTHETIC-v1",
                published_on=date(2026, 9, 1),
                source_reference="synthetic-test-only",
                checksum_sha256=sha256(payload).hexdigest(),
            ),
        ),
    )
    return load_verified_rtc_classification_catalog(baseline, payload)


def _rtc_rule(
    *, cst: str | None = "000", version: str | None = "SYNTHETIC-v1"
) -> TaxRule:
    rule = _rule("rtc-synthetic", TaxRuleSelector(state_code="SP", ncm_prefix="2106"))
    return replace(
        rule,
        outcome=replace(
            rule.outcome,
            ibs_cbs_cst_code=cst,
            ibs_cbs_classification_table_version=version,
        ),
    )


def test_rtc_rule_reuses_canonical_engine_and_verifies_exact_catalog_pair() -> None:
    decision, proof = resolve_rule_with_verified_rtc_catalog(
        engine=TaxRuleEngine(),
        context=_context(),
        rules=[_rtc_rule()],
        catalog=_synthetic_rtc_catalog(),
    )
    assert decision.rule_id == "rtc-synthetic"
    assert decision.source_normative == "NORMA-SINTETICA-TESTE"
    assert decision.rank == (2, 4, 0)
    assert (proof.cst_code, proof.classification_code) == ("000", "000001")
    assert proof.classification_table_version == "SYNTHETIC-v1"


@pytest.mark.parametrize(
    "cst,version,expected",
    (
        (None, "SYNTHETIC-v1", "explicit CST"),
        ("000", None, "explicit CST"),
        ("001", "SYNTHETIC-v1", "unrecognized RTC"),
        ("000", "OUTDATED-v0", "version mismatch"),
    ),
)
def test_rtc_rule_does_not_infer_absent_or_incompatible_classification(
    cst: str | None,
    version: str | None,
    expected: str,
) -> None:
    with pytest.raises(RegulatoryBaselineError, match=expected):
        resolve_rule_with_verified_rtc_catalog(
            engine=TaxRuleEngine(),
            context=_context(),
            rules=[_rtc_rule(cst=cst, version=version)],
            catalog=_synthetic_rtc_catalog(),
        )


def test_rtc_rule_rejects_unverified_catalog_input() -> None:
    with pytest.raises(RegulatoryBaselineError, match="verified RTC"):
        resolve_rule_with_verified_rtc_catalog(
            engine=TaxRuleEngine(),
            context=_context(),
            rules=[_rtc_rule()],
            catalog=None,  # type: ignore[arg-type]
        )


def test_rtc_rule_denies_fabricated_unpinned_catalog() -> None:
    fabricated = VerifiedRtcClassificationCatalog(
        artifact_version="SYNTHETIC-v1",
        allowed_pairs=frozenset({("000", "000001")}),
    )
    with pytest.raises(RegulatoryBaselineError, match="verified RTC"):
        resolve_rule_with_verified_rtc_catalog(
            engine=TaxRuleEngine(),
            context=_context(),
            rules=[_rtc_rule()],
            catalog=fabricated,
        )


def test_rtc_rule_preserves_fail_closed_no_match_and_ambiguous_resolution() -> None:
    context = _context()
    with pytest.raises(TaxRuleNotFoundError):
        resolve_rule_with_verified_rtc_catalog(
            engine=TaxRuleEngine(),
            context=context,
            rules=[_rule("rj", TaxRuleSelector(state_code="RJ"))],
            catalog=_synthetic_rtc_catalog(),
        )
    with pytest.raises(TaxRuleAmbiguityError):
        resolve_rule_with_verified_rtc_catalog(
            engine=TaxRuleEngine(),
            context=context,
            rules=[_rtc_rule(), replace(_rtc_rule(), rule_id="rtc-tie")],
            catalog=_synthetic_rtc_catalog(),
        )


def test_rtc_outcome_rejects_malformed_cst_without_changing_legacy_rules() -> None:
    assert _outcome().ibs_cbs_cst_code is None
    with pytest.raises(FiscalValidationError, match="ibs_cbs_cst_code"):
        replace(_outcome(), ibs_cbs_cst_code="01")
    with pytest.raises(FiscalValidationError, match="ibs_cbs_classification_table_version"):
        replace(_outcome(), ibs_cbs_classification_table_version=" ")


def _rule_bound_preview(*, rules: list[TaxRule] | None = None, day: int = 10):
    """Synthetic rate/classification evidence; no fiscal authorization."""
    payload = json.dumps({
        "schema_version": 1,
        "artifact_id": "RATE-SYNTHETIC",
        "artifact_version": "SYNTHETIC-v1",
        "component": "cbs",
        "rate_percent": "1.25",
        "quantum": "0.01",
        "rounding_mode": "ROUND_HALF_UP",
    }, sort_keys=True).encode("utf-8")
    baseline = RegulatoryBaseline(
        baseline_id="rtc-rule-bound-preview-synthetic", version=1,
        captured_at=datetime(2026, 9, 11, tzinfo=UTC),
        artifacts=(RegulatoryArtifactPin(
            artifact_id="RATE-SYNTHETIC", kind=RegulatoryArtifactKind.RATE_TABLE,
            version="SYNTHETIC-v1", published_on=date(2026, 9, 1),
            effective_from=date(2026, 9, 1), source_reference="synthetic-test-only",
            checksum_sha256=sha256(payload).hexdigest(),
        ),),
    )
    return calculate_rule_bound_rtc_preview(
        engine=TaxRuleEngine(), context=_context(instant=_instant(day)),
        rules=[_rtc_rule()] if rules is None else rules,
        baseline=baseline, rate_artifact_id="RATE-SYNTHETIC",
        rate_payload=payload, catalog=_synthetic_rtc_catalog(),
        tax_base=Money(Decimal("123.45")),
    )


def test_rtc04_preview_requires_canonical_rule_and_classification() -> None:
    decision, result = _rule_bound_preview()
    assert decision.rule_id == "rtc-synthetic"
    assert decision.source_normative == "NORMA-SINTETICA-TESTE"
    assert result.classification.cst_code == "000"
    assert result.classification.classification_code == "000001"
    assert result.tax_amount.amount == Decimal("1.54")


def test_rtc04_preview_denies_unmatched_territory() -> None:
    with pytest.raises(TaxRuleNotFoundError, match="no effective tax rule"):
        _rule_bound_preview(rules=[_rule("other-state", TaxRuleSelector(state_code="RJ"))])


def test_rtc04_preview_denies_ambiguous_rule() -> None:
    duplicate = replace(_rtc_rule(), rule_id="rtc-synthetic-duplicate")
    with pytest.raises(TaxRuleAmbiguityError, match="ambiguous"):
        _rule_bound_preview(rules=[_rtc_rule(), duplicate])


def test_rtc04_preview_denies_missing_classification_from_winner() -> None:
    with pytest.raises(RegulatoryBaselineError, match="explicit CST"):
        _rule_bound_preview(rules=[_rtc_rule(cst=None)])


def test_rtc04_preview_denies_expired_rule() -> None:
    expired = replace(_rtc_rule(), effective_to=_instant(9))
    with pytest.raises(TaxRuleNotFoundError, match="no effective tax rule"):
        _rule_bound_preview(rules=[expired])


# RTC-04/2026: nominal legal-reference arithmetic only; no XML, rounding or
# collection is certified by these fixtures. LC 214/2025, arts. 343/346/348.

def _rtc_2026_reference(**overrides: object):
    params: dict[str, object] = {
        "engine": TaxRuleEngine(),
        "context": _context(tax_regime=TaxRegimeCode.NORMAL),
        "rules": [_rtc_rule()],
        "catalog": _synthetic_rtc_catalog(),
        "tax_base": Money(Decimal("123.45")),
        "confirmed_standard_nonfuel_operation": True,
        "confirmed_no_differentiated_or_special_regime": True,
        "confirmed_tax_base_reviewed": True,
    }
    params.update(overrides)
    return calculate_2026_nominal_reference_preview(**params)  # type: ignore[arg-type]


def test_rtc_2026_statutory_nominal_reference_is_unrounded() -> None:
    result = _rtc_2026_reference()
    assert result.decision.rule_id == "rtc-synthetic"
    assert result.classification.classification_code == "000001"
    assert result.cbs_rate_percent == Decimal("0.9")
    assert result.ibs_state_rate_percent == Decimal("0.1")
    assert result.cbs_unrounded == Decimal("1.11105")
    assert result.ibs_state_unrounded == Decimal("0.12345")
    assert "343" in result.source_normative
    assert "348" in result.source_normative


@pytest.mark.parametrize("day", [1, 10])
def test_rtc_2026_reference_accepts_only_2026(day: int) -> None:
    # Recreate a valid context for 2027 to avoid product-snapshot expiry mistakes.
    original = _context(tax_regime=TaxRegimeCode.NORMAL)
    outside = replace(original, instant=datetime(2027, 1, day, tzinfo=UTC))
    with pytest.raises(RegulatoryBaselineError, match="only to 2026"):
        _rtc_2026_reference(context=outside)


def test_rtc_2026_reference_rejects_simples_nacional() -> None:
    with pytest.raises(RegulatoryBaselineError, match="Simples Nacional"):
        _rtc_2026_reference(context=_context())


@pytest.mark.parametrize("missing", [
    "confirmed_standard_nonfuel_operation",
    "confirmed_no_differentiated_or_special_regime",
    "confirmed_tax_base_reviewed",
])
def test_rtc_2026_reference_rejects_unreviewed_scope(missing: str) -> None:
    with pytest.raises(RegulatoryBaselineError, match="reviewed standard scope"):
        _rtc_2026_reference(**{missing: False})
    with pytest.raises(RegulatoryBaselineError, match="reviewed standard scope"):
        _rtc_2026_reference(**{missing: 1})


def test_rtc_2026_reference_denies_missing_or_ambiguous_rule() -> None:
    with pytest.raises(TaxRuleNotFoundError):
        _rtc_2026_reference(rules=[])
    duplicate = replace(_rtc_rule(), rule_id="rtc-duplicate")
    with pytest.raises(TaxRuleAmbiguityError):
        _rtc_2026_reference(rules=[_rtc_rule(), duplicate])


def test_rtc_2026_reference_denies_unverified_classification() -> None:
    with pytest.raises(RegulatoryBaselineError, match="version mismatch"):
        _rtc_2026_reference(rules=[_rtc_rule(version="UNVERIFIED-v1")])


def test_rtc_2026_reference_denies_negative_tax_base() -> None:
    with pytest.raises(FiscalValidationError, match="nonnegative"):
        _rtc_2026_reference(tax_base=Money(Decimal("-1.00")))


# RTC-04: Art. 12 (general-operation-base subset), non-issuable pre-rounding.
def _art12_preview(**overrides: object):
    params: dict[str, object] = {
        "engine": TaxRuleEngine(),
        "context": _context(tax_regime=TaxRegimeCode.NORMAL),
        "rules": [_rtc_rule()],
        "catalog": _synthetic_rtc_catalog(),
        "gross_operation_value": Money(Decimal("1000.00")),
        "unconditional_discount": Money(Decimal("100.00")),
        "ipi_excluded": Money(Decimal("20.00")),
        "ibs_cbs_excluded": Money(Decimal("0.00")),
        "legacy_taxes_excluded": Money(Decimal("80.00")),
        "public_lighting_contribution_excluded": Money(Decimal("0.00")),
        "confirmed_standard_nonfuel_operation": True,
        "confirmed_no_differentiated_or_special_regime": True,
        "confirmed_no_market_valuation_or_special_base": True,
        "confirmed_no_third_party_reimbursement": True,
        "confirmed_all_art12_exclusions_itemized": True,
        "confirmed_tax_base_reviewed": True,
    }
    params.update(overrides)
    return calculate_2026_art12_base_preview(**params)  # type: ignore[arg-type]


def test_art12_general_base_composition_and_nominal_2026_preview() -> None:
    result = _art12_preview()
    assert result.reviewed_base.amount == Decimal("800.00")
    assert result.nominal_reference.tax_base == result.reviewed_base
    assert result.nominal_reference.cbs_unrounded == Decimal("7.200")
    assert result.nominal_reference.ibs_state_unrounded == Decimal("0.800")
    assert "art. 12" in result.source_normative


def test_art12_includes_conditional_discount_and_charges_in_gross() -> None:
    # The charged operation amount already includes conditional price charges.
    result = _art12_preview(
        gross_operation_value=Money(Decimal("127.35")),
        unconditional_discount=Money(Decimal("2.00")),
        ipi_excluded=Money(Decimal("0.00")),
        legacy_taxes_excluded=Money(Decimal("0.00")),
    )
    assert result.reviewed_base.amount == Decimal("125.35")
    assert result.nominal_reference.cbs_unrounded == Decimal("1.12815")


@pytest.mark.parametrize("field", [
    "confirmed_no_market_valuation_or_special_base",
    "confirmed_no_third_party_reimbursement",
    "confirmed_all_art12_exclusions_itemized",
])
def test_art12_denies_unreviewed_exclusions_and_special_cases(field: str) -> None:
    for invalid in (False, 1, None):
        with pytest.raises(RegulatoryBaselineError, match="reviewed general-base"):
            _art12_preview(**{field: invalid})


@pytest.mark.parametrize("field", [
    "gross_operation_value",
    "unconditional_discount",
    "ipi_excluded",
    "ibs_cbs_excluded",
    "legacy_taxes_excluded",
    "public_lighting_contribution_excluded",
])
def test_art12_denies_invalid_money_fields(field: str) -> None:
    for invalid in (None, "100", Money(Decimal("-0.01"))):
        with pytest.raises(FiscalValidationError, match="finite nonnegative Money"):
            _art12_preview(**{field: invalid})


def test_art12_denies_exclusions_larger_than_gross() -> None:
    with pytest.raises(FiscalValidationError, match="exceed gross"):
        _art12_preview(unconditional_discount=Money(Decimal("1001.00")))


def test_art12_denies_double_deduction_of_itemized_legacy_taxes() -> None:
    with pytest.raises(FiscalValidationError, match="exceed gross"):
        _art12_preview(
            gross_operation_value=Money(Decimal("80.00")),
            legacy_taxes_excluded=Money(Decimal("80.00")),
        )


def test_art12_denies_2027_and_simples_contexts() -> None:
    old = _context(tax_regime=TaxRegimeCode.NORMAL)
    with pytest.raises(RegulatoryBaselineError, match="only to 2026"):
        _art12_preview(context=replace(old, instant=datetime(2027, 1, 1, tzinfo=UTC)))
    with pytest.raises(RegulatoryBaselineError, match="Simples Nacional"):
        _art12_preview(context=_context())


def test_art12_denies_ambiguous_tax_rule() -> None:
    duplicate = replace(_rtc_rule(), rule_id="duplicate")
    with pytest.raises(TaxRuleAmbiguityError):
        _art12_preview(rules=[_rtc_rule(), duplicate])


def test_art12_requires_explicit_tax_base_review_attestation() -> None:
    for invalid in (False, None, 1):
        with pytest.raises(RegulatoryBaselineError, match="reviewed standard scope"):
            _art12_preview(confirmed_tax_base_reviewed=invalid)


def _rtc_strict_rule() -> TaxRule:
    return replace(
        _rtc_rule(),
        selector=TaxRuleSelector(
            state_code="SP",
            tax_regime=TaxRegimeCode.NORMAL,
            document_kind=FiscalDocumentKind.NFCE,
            operation_type=TaxOperationType.SALE,
            recipient_profile=RecipientTaxProfile.CONSUMER_FINAL,
            ncm_prefix="2106",
        ),
    )


def _strict_incidence(**overrides: object):
    args: dict[str, object] = {
        "engine": TaxRuleEngine(),
        "context": _context(tax_regime=TaxRegimeCode.NORMAL),
        "rules": [_rtc_strict_rule()],
        "catalog": _synthetic_rtc_catalog(),
    }
    args.update(overrides)
    return resolve_strict_rtc_2026_incidence_candidate(**args)  # type: ignore[arg-type]


def test_rtc_2026_strict_incidence_preserves_canonical_decision() -> None:
    decision, classification = _strict_incidence()
    assert decision.rule_id == "rtc-synthetic"
    assert classification.classification_table_version == "SYNTHETIC-v1"


@pytest.mark.parametrize("field", [
    "state_code", "tax_regime", "document_kind",
    "operation_type", "recipient_profile", "ncm_prefix",
])
def test_rtc_2026_strict_incidence_rejects_wildcard_selector(field: str) -> None:
    rule = _rtc_strict_rule()
    with pytest.raises(RegulatoryBaselineError, match="explicit contextual selectors"):
        _strict_incidence(rules=[replace(rule, selector=replace(rule.selector, **{field: None}))])


def test_rtc_2026_strict_incidence_does_not_accept_wrong_region() -> None:
    with pytest.raises(TaxRuleNotFoundError):
        _strict_incidence(context=_context(
            tax_regime=TaxRegimeCode.NORMAL,
            jurisdiction=BrazilianJurisdiction("RJ", "3304557"),
        ))


def test_rtc_2026_strict_incidence_rejects_ambiguous_rule_and_bad_catalog() -> None:
    rule = _rtc_strict_rule()
    with pytest.raises(TaxRuleAmbiguityError):
        _strict_incidence(rules=[rule, replace(rule, rule_id="rtc-tie")])
    with pytest.raises(RegulatoryBaselineError, match="verified RTC"):
        _strict_incidence(catalog=None)


def test_rtc_2026_strict_incidence_rejects_next_year() -> None:
    with pytest.raises(RegulatoryBaselineError, match="only 2026"):
        _strict_incidence(context=replace(
            _context(tax_regime=TaxRegimeCode.NORMAL),
            instant=datetime(2027, 1, 2, tzinfo=UTC),
        ))


def _rtc2026_bundle(**overrides: object):
    payload = json.dumps({
        "schema_version": 1,
        "artifact_id": "SYNTHETIC-CBS-ROUND",
        "artifact_version": "SYNTHETIC-v1",
        "field_name": "vCBS",
        "quantum": "0.01",
        "rounding_mode": "ROUND_HALF_UP",
    }, sort_keys=True).encode("utf-8")
    note = RegulatoryArtifactPin(
        artifact_id="SYNTHETIC-CBS-ROUND",
        kind=RegulatoryArtifactKind.TECHNICAL_NOTE,
        version="SYNTHETIC-v1",
        published_on=date(2026, 1, 1),
        effective_from=date(2026, 1, 1),
        source_reference="synthetic-test-only",
        checksum_sha256=sha256(payload).hexdigest(),
    )
    baseline = RegulatoryBaseline(
        baseline_id="synthetic-cbs-rounding",
        version=1,
        captured_at=datetime(2026, 9, 10, tzinfo=UTC),
        artifacts=(note,),
    )
    values: dict[str, object] = {
        "engine": TaxRuleEngine(),
        "context": _context(tax_regime=TaxRegimeCode.NORMAL),
        "rules": [_rtc_strict_rule()],
        "catalog": _synthetic_rtc_catalog(),
        "gross_operation_value": Money(Decimal("123.45")),
        "unconditional_discount": Money(Decimal("0.00")),
        "ipi_excluded": Money(Decimal("0.00")),
        "ibs_cbs_excluded": Money(Decimal("0.00")),
        "legacy_taxes_excluded": Money(Decimal("0.00")),
        "public_lighting_contribution_excluded": Money(Decimal("0.00")),
        "confirmed_standard_nonfuel_operation": True,
        "confirmed_no_differentiated_or_special_regime": True,
        "confirmed_no_market_valuation_or_special_base": True,
        "confirmed_no_third_party_reimbursement": True,
        "confirmed_all_art12_exclusions_itemized": True,
        "confirmed_tax_base_reviewed": True,
        "rounding_baseline": baseline,
        "rounding_artifact_id": "SYNTHETIC-CBS-ROUND",
        "rounding_policy_payload": payload,
    }
    values.update(overrides)
    return calculate_2026_audited_preview_bundle(**values)  # type: ignore[arg-type]


def test_rtc2026_bundle_binds_strict_incidence_base_and_pinned_rounding() -> None:
    candidate = _rtc2026_bundle()
    assert candidate.decision.rule_id == "rtc-synthetic"
    assert candidate.base.reviewed_base.amount == Decimal("123.45")
    assert candidate.base.nominal_reference.cbs_unrounded == Decimal("1.11105")
    assert candidate.cbs_rounding_candidate.candidate == Decimal("1.11")
    assert candidate.cbs_rounding_candidate.authoritative is False
    assert candidate.authoritative is False


def test_rtc2026_bundle_denies_wildcard_rule() -> None:
    with pytest.raises(RegulatoryBaselineError, match="explicit contextual selectors"):
        _rtc2026_bundle(rules=[_rtc_rule()])


def test_rtc2026_bundle_denies_bad_base_review() -> None:
    with pytest.raises(RegulatoryBaselineError, match="reviewed standard scope"):
        _rtc2026_bundle(confirmed_tax_base_reviewed=False)


def test_rtc2026_bundle_denies_tampered_rounding_policy() -> None:
    with pytest.raises(RegulatoryBaselineError):
        _rtc2026_bundle(rounding_policy_payload=b"untrusted-not-a-note")


def test_rtc2026_bundle_denies_2027_context() -> None:
    context = replace(
        _context(tax_regime=TaxRegimeCode.NORMAL),
        instant=datetime(2027, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(RegulatoryBaselineError, match="only 2026"):
        _rtc2026_bundle(context=context)


def test_rtc2026_bundle_reuses_same_rule_generator() -> None:
    candidate = _rtc2026_bundle(rules=(r for r in [_rtc_strict_rule()]))
    assert candidate.base.nominal_reference.decision == candidate.decision
