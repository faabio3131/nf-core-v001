"""T08 service gates: trusted immutable import, scoped records and legal provenance."""
from datetime import date

import pytest

from kordena_fiscal.application.federal_benefits_service import (
    evaluate_federal_benefit,
    import_reviewed_federal_benefit,
)
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import _digest
from kordena_fiscal.tax.federal_benefits import (
    FACTS_SCHEMA,
    PROGRAMS,
    RULE_SCHEMA,
    ReviewedFederalIssuer,
)
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

SCOPE = ("fm-nfcore", "tenant-a", "unit-a", "homologation")
COMPETENCE = date(2026, 11, 1)
ISSUER = "12345678000195"


def bundle():
    program = PROGRAMS["LEI_DO_BEM"]
    return dict(
        snapshot_id="federal-snapshot", snapshot_version=1,
        competence=COMPETENCE, issuer=Cnpj(ISSUER),
        content={
            "schema_version": FACTS_SCHEMA, "review_status": "reviewed",
            "review_reference": "facts-review",
            "activity_cnae": "6201501", "operation_ncm": None,
            "operation": "rd_innovation", "evidence": {
                key: "proof-" + key for key in program.minimum_evidence
            },
        },
        benefit_id="lei-do-bem", benefit_version=1,
        benefit_content={
            "schema_version": RULE_SCHEMA, "review_status": "reviewed",
            "review_reference": "policy-review",
            "program_code": program.code, "operation": program.operation,
            "allowed_regimes": ["lucro_real"],
            "cnae_scope": "reviewed_any", "allowed_cnaes": [],
            "ncm_scope": "reviewed_any", "allowed_ncms": [],
            "required_evidence": [],
            "valid_from": "2026-01-01", "valid_until": "2027-01-01",
            "legal_citations": [{
                "act": program.legal_act,
                "provision": "cap. III",
                "source_url": program.official_url,
                # Synthetic digest: deliberately NOT proof of official source.
                "source_sha256": "a" * 64,
                "published_on": "2020-01-01",
                "valid_from": "2026-01-01",
                "valid_until": "2027-01-01",
                "review_reference": "policy-review",
            }],
        },
    )


def verify(issuer, competence):
    assert issuer == ISSUER
    assert competence == COMPETENCE
    return ReviewedFederalIssuer(
        issuer, "6201501", FederalIncomeTaxRegime.LUCRO_REAL, SCOPE,
    )


class FakeStore:
    scope_identity = SCOPE

    def __init__(self):
        self.rows = {}

    def record(self, table, record_id, version=None):
        if version is None:
            matches = [value for (name, rid, _), value in self.rows.items()
                       if name == table and rid == record_id]
            return max(matches, key=lambda row: row["version"]) if matches else None
        return self.rows.get((table, record_id, version))

    def benefit_version_at(self, record_id, competence):
        following = date(competence.year + (competence.month == 12),
                         competence.month % 12 + 1, 1)
        return max((
            version for (table, rid, version), row in self.rows.items()
            if table == "fm_economy_benefits" and rid == record_id
            and date.fromisoformat(row["valid_from"]) < following
        ), default=None)

    def federal_benefit_candidates(self, *, competence, schema_version, limit=500):
        ids = {
            rid for (table, rid, _), row in self.rows.items()
            if table == "fm_economy_benefits"
            and row["jurisdiction"] == "BR"
            and row["content"].get("schema_version") == schema_version
        }
        result = []
        for rid in sorted(ids):
            version = self.benefit_version_at(rid, competence)
            if version is not None:
                result.append(self.record("fm_economy_benefits", rid, version))
        return tuple(result[:limit])

    def records(self, table, *, limit=100, schema_version=None):
        return tuple(
            row for (name, _, _), row in self.rows.items()
            if name == table and (
                schema_version is None or row.get("content", {}).get("schema_version")
                == schema_version
            )
        )[:limit]

    def append_snapshot(self, *, record_id, version, competence, issuer, content):
        self.rows[("fm_economy_snapshots", record_id, version)] = {
            "record_id": record_id, "version": version,
            "competence": competence.isoformat(), "issuer_cnpj": issuer.value,
            "content": content, "digest": _digest(content)[1],
        }

    def append_benefit(self, *, record_id, version, tax_code, jurisdiction,
                       normative_reference, valid_from, valid_until, content):
        self.rows[("fm_economy_benefits", record_id, version)] = {
            "record_id": record_id, "version": version,
            "tax_code": tax_code, "jurisdiction": jurisdiction,
            "normative_reference": normative_reference,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat() if valid_until else None,
            "content": content, "digest": _digest(content)[1],
        }


def test_reviewed_import_is_immutable_and_advisory_only():
    store = FakeStore()
    first = import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    assert first["status"] == "potential"
    assert first["tax_calculation_authorized"] is False
    assert first["tax_reporting_authorized"] is False
    assert first["approved_cents"] is None
    assert first["benefit_digest"] == _digest(bundle()["benefit_content"])[1]
    assert first == import_reviewed_federal_benefit(
        store, **bundle(), verify_issuer=verify,
    )
    assert len(store.rows) == 2
    assert first == evaluate_federal_benefit(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        benefit_id="lei-do-bem", benefit_version=1, verify_issuer=verify,
    )
    tampered = bundle()
    tampered["content"]["evidence"]["reviewed_rd_project"] = "different-proof"
    with pytest.raises(FiscalValidationError, match="immutable"):
        import_reviewed_federal_benefit(store, **tampered, verify_issuer=verify)
    assert len(store.rows) == 2


def test_missing_or_foreign_records_never_leak_evidence():
    store = FakeStore()
    with pytest.raises(FiscalValidationError, match="unavailable"):
        evaluate_federal_benefit(
            store, snapshot_id="federal-snapshot", snapshot_version=1,
            benefit_id="lei-do-bem", benefit_version=1, verify_issuer=verify,
        )
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    store.scope_identity = ("fm-nfcore", "tenant-b", "unit-a", "homologation")
    with pytest.raises(FiscalValidationError, match="canonical"):
        evaluate_federal_benefit(
            store, snapshot_id="federal-snapshot", snapshot_version=1,
            benefit_id="lei-do-bem", benefit_version=1, verify_issuer=verify,
        )


@pytest.mark.parametrize("change", [
    {"review_status": "draft"},
    {"legal_citations": []},
    {"valid_from": "2027-01-01"},
    {"review_reference": "wrong-reference"},
])
def test_policy_review_and_validity_fail_closed(change):
    row = bundle()
    row["benefit_content"].update(change)
    store = FakeStore()
    with pytest.raises(FiscalValidationError):
        import_reviewed_federal_benefit(store, **row, verify_issuer=verify)
    assert store.rows == {}


def test_cannot_use_an_unrelated_or_forged_legal_source():
    row = bundle()
    row["benefit_content"]["legal_citations"][0]["source_url"] = (
        "https://www.gov.br/receitafederal/pt-br/"
    )
    with pytest.raises(FiscalValidationError, match="primary official"):
        import_reviewed_federal_benefit(FakeStore(), **row, verify_issuer=verify)
    row["benefit_content"]["legal_citations"][0]["source_url"] = (
        "https://attacker.example.org/"
    )
    with pytest.raises(FiscalValidationError):
        import_reviewed_federal_benefit(FakeStore(), **row, verify_issuer=verify)


def test_canonical_cnae_or_scope_conflict_rejected():
    def wrong_cnae(issuer, competence):
        return ReviewedFederalIssuer(
            issuer, "1111111", FederalIncomeTaxRegime.LUCRO_REAL, SCOPE,
        )
    with pytest.raises(FiscalValidationError, match="canonical"):
        import_reviewed_federal_benefit(
            FakeStore(), **bundle(), verify_issuer=wrong_cnae,
        )



def test_newer_reviewed_policy_blocks_stale_candidate_for_same_month():
    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    first = bundle()
    replacement = first["benefit_content"].copy()
    replacement["review_status"] = "revoked"
    store.append_benefit(
        record_id="lei-do-bem", version=2, tax_code="IRPJ_CSLL",
        jurisdiction="BR", normative_reference=PROGRAMS["LEI_DO_BEM"].legal_act,
        valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
        content=replacement,
    )
    with pytest.raises(FiscalValidationError, match="superseded"):
        evaluate_federal_benefit(
            store, snapshot_id="federal-snapshot", snapshot_version=1,
            benefit_id="lei-do-bem", benefit_version=1, verify_issuer=verify,
        )



def test_search_federal_benefits_discovers_scoped_reviewed_program():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    with pytest.raises(FiscalValidationError, match="unavailable"):
        search_federal_benefits(
            store, snapshot_id="federal-snapshot", snapshot_version=1,
            verify_issuer=verify,
        )
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["status"] == "advisory"
    assert result["counts"]["potential"] == 1
    assert result["results"][0]["program_code"] == "LEI_DO_BEM"
    assert result["results"][0]["issuance_authorized"] is False
    assert result["results"][0]["estimated_cents"] is None
    assert result["complete_national_coverage"] is False
    assert result["coverage_truncated"] is False
    assert result == search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )


def test_search_excludes_different_tax_benefits_and_never_replays_revoked_version():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    store.append_benefit(
        record_id="ordinary-simples-rule", version=1, tax_code="SIMPLES",
        jurisdiction="BR", normative_reference="CGSN-140",
        valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
        content={"schema_version": "other.domain.rule/v1"},
    )
    assert search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )["counts"]["potential"] == 1
    revoked = bundle()["benefit_content"] | {"review_status": "revoked"}
    store.append_benefit(
        record_id="lei-do-bem", version=2, tax_code="IRPJ_CSLL",
        jurisdiction="BR", normative_reference=PROGRAMS["LEI_DO_BEM"].legal_act,
        valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
        content=revoked,
    )
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["counts"]["potential"] == 0
    assert result["counts"]["review_required"] == 1
    assert result["results"][0]["benefit_version"] == 2
    assert result["results"][0]["reason_codes"] == ["rule_not_reviewed"]
    assert result["status"] == "review_required"


def test_search_denies_foreign_scope_and_enforces_bounded_coverage():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    assert search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify, limit=1,
    )["coverage_truncated"] is True
    store.scope_identity = ("fm-nfcore", "foreign", "unit-a", "homologation")
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["counts"]["potential"] == 0
    assert result["counts"]["review_required"] == 1
    for invalid in (True, -1, 0, 501):
        with pytest.raises(FiscalValidationError, match="limit"):
            search_federal_benefits(
                store, snapshot_id="federal-snapshot", snapshot_version=1,
                verify_issuer=verify, limit=invalid,
            )



def test_federal_search_distinguishes_absent_reviewed_catalog_from_no_eligibility():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    row = bundle()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        competence=row["competence"], issuer=row["issuer"], content=row["content"],
    )
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["status"] == "no_reviewed_catalog"
    assert result["results"] == []
    assert result["complete_national_coverage"] is False
    assert result["review_required"] is True


@pytest.mark.parametrize("valid_from, valid_until", [
    (date(2026, 11, 15), date(2026, 11, 22)),
    (date(2026, 10, 1), date(2026, 11, 1)),
    (date(2026, 11, 1), date(2026, 11, 30)),
])
def test_new_version_overlapping_any_part_of_month_blocks_old_version(
    valid_from, valid_until,
):
    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    store.append_benefit(
        record_id="lei-do-bem", version=2, tax_code="IRPJ_CSLL",
        jurisdiction="BR", normative_reference=PROGRAMS["LEI_DO_BEM"].legal_act,
        valid_from=valid_from, valid_until=valid_until,
        content=bundle()["benefit_content"] | {"review_status": "revoked"},
    )
    with pytest.raises(FiscalValidationError, match="superseded"):
        evaluate_federal_benefit(
            store, snapshot_id="federal-snapshot", snapshot_version=1,
            benefit_id="lei-do-bem", benefit_version=1, verify_issuer=verify,
        )


def test_new_policy_with_changed_schema_does_not_reactivate_old_benefit():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    store.append_benefit(
        record_id="lei-do-bem", version=2, tax_code="IRPJ_CSLL",
        jurisdiction="BR", normative_reference=PROGRAMS["LEI_DO_BEM"].legal_act,
        valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
        content={"schema_version": "nfcore.revoked/v1", "review_status": "revoked"},
    )
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["counts"]["potential"] == 0
    assert result["counts"]["review_required"] == 1
    assert result["results"][0]["reason_codes"] == ["newer_policy_not_reviewed"]


def test_non_federal_noise_does_not_consume_federal_search_limit():
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    for index in range(501):
        store.append_benefit(
            record_id=f"unrelated-{index}", version=1, tax_code="SIMPLES",
            jurisdiction="BR", normative_reference="CGSN-140",
            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
            content={"schema_version": "nfcore.simples-unrelated/v1"},
        )
    result = search_federal_benefits(
        store, snapshot_id="federal-snapshot", snapshot_version=1,
        verify_issuer=verify,
    )
    assert result["counts"]["potential"] == 1
    assert result["coverage_truncated"] is False
    assert result["results"][0]["benefit_id"] == "lei-do-bem"



@pytest.mark.parametrize("revoked", [True, False])
def test_effective_version_is_not_hidden_by_future_version(revoked):
    from kordena_fiscal.application.federal_benefits_service import search_federal_benefits

    store = FakeStore()
    first = import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
    for version, start, status in (
        (2, date(2026, 6, 1), "revoked"),
        (3, date(2027, 1, 1), "reviewed"),
    ):
        if version == 2 and not revoked:
            continue
        store.append_benefit(
            record_id="lei-do-bem", version=version, tax_code="IRPJ_CSLL",
            jurisdiction="BR", normative_reference=PROGRAMS["LEI_DO_BEM"].legal_act,
            valid_from=start, valid_until=date(2028, 1, 1),
            content=bundle()["benefit_content"] | {
                "review_status": status, "valid_from": start.isoformat(),
                "valid_until": "2028-01-01",
            },
        )
    args = dict(snapshot_id="federal-snapshot", snapshot_version=1, verify_issuer=verify)
    if revoked:
        with pytest.raises(FiscalValidationError, match="superseded"):
            evaluate_federal_benefit(
                store, **args, benefit_id="lei-do-bem", benefit_version=1,
            )
        with pytest.raises(FiscalValidationError, match="superseded"):
            import_reviewed_federal_benefit(store, **bundle(), verify_issuer=verify)
        result = search_federal_benefits(store, **args)
        assert result["counts"]["potential"] == 0
        assert result["results"][0]["benefit_version"] == 2
    else:
        assert evaluate_federal_benefit(
            store, **args, benefit_id="lei-do-bem", benefit_version=1,
        ) == first
        assert search_federal_benefits(store, **args)["results"] == [first]


def test_economy_json_rejects_real_nul_not_literal_escape():
    for content in ({"value": "a\x00b"}, {"a\x00b": "value"}, {"nested": ["\x00"]}):
        with pytest.raises(FiscalValidationError, match="null byte"):
            _digest(content)
    assert _digest({"value": r"a\x00b"})[1]
