import json
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from kordena_fiscal.compliance.rtc import (
    RegulatoryArtifactKind,
    RegulatoryArtifactPin,
    RegulatoryBaseline,
    RegulatoryBaselineError,
)
from kordena_fiscal.compliance.rtc_catalog import (
    VerifiedRtcClassificationCatalog,
    load_verified_rtc_classification_catalog,
    resolve_rule_with_verified_rtc_catalog,
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
