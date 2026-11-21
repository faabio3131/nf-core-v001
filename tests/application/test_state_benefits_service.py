"""T09 scoped reviewed state-benefit import/search and T01 invariants."""
import hashlib
import hmac
import json
from datetime import date

import pytest

from kordena_fiscal.application.state_benefits_service import (
    evaluate_state_benefit,
    import_reviewed_state_benefit,
    search_state_benefits,
)
from kordena_fiscal.application.state_review_gate import REVIEW_KEY_ENV, review_claims
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import _digest
from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    _COMMON_EVIDENCE,
    _ROUTE_EVIDENCE,
    FACTS_SCHEMA,
    RULE_SCHEMA,
    ReviewedStateIssuer,
)

MONTH = date(2026, 11, 1)
SCOPE = ("fm-nfcore", "tenant-a", "unit-a", "homologation")


def policy(uf="SP", *, path="state_statute"):
    return {
        "schema_version": RULE_SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-review-T09",
        "uf": uf, "benefit_kind": "base_reduction", "legal_path": path,
        "state_normative_reference": "Decreto Estadual Sintetico 123/2026",
        "state_official_source_url": "https://www.gov.br/testes/sintetico/ato-estadual",
        "valid_from": "2026-01-01", "valid_until": "2027-01-01",
        "legal_valid_until_inclusive": "2026-12-31",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "allowlist", "allowed_cnaes": ["6201501"],
        "ncm_scope": "allowlist", "allowed_ncms": ["84713012"],
        "allowed_cfops": ["5102"], "allowed_operations": ["domestic_sale"],
        "required_evidence": [],
        "confaz_normative_reference": (
            "Convênio ICMS 190/2017" if path != "state_statute" else None
        ),
        "legal_citations": [],
    }


def facts(uf="SP", *, path="state_statute"):
    return {
        "schema_version": FACTS_SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-review-T09",
        "uf": uf, "activity_cnae": "6201501",
        "operation_ncm": "84713012", "operation_cfop": "5102",
        "operation": "domestic_sale", "evidence": {
            key: "reviewed-synthetic-" + key
            for key in (*_COMMON_EVIDENCE, *_ROUTE_EVIDENCE[path])
        },
    }

CNPJ = "12345678000195"

KEY_T09 = "test-only-internal-review-hmac-key-xxxxxxxxxxxxxxxxxxxxxxxxxxx"


@pytest.fixture(autouse=True)
def _isolated_state_review_test_key(monkeypatch):
    monkeypatch.setenv(REVIEW_KEY_ENV, KEY_T09)


def _sign_review(policy, case_facts, *, scope=SCOPE, cn=CNPJ, month=MONTH,
                 benefit_id="t09-state-rule", version=1):
    claims = review_claims(
        policy=policy, facts=case_facts, scope_identity=scope,
        issuer_cnpj=cn, competence=month, benefit_id=benefit_id,
        benefit_version=version,
    )
    signed = {
        "claims": claims,
        "reviewer_id": "synthetic-authorized-reviewer",
        "approved_at": "2026-11-20T10:00:00+00:00",
        "decision": "internal_curatorial_accepted",
    }
    serialized = json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    signed["signature_hmac_sha256"] = hmac.new(
        KEY_T09.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    policy["internal_review_approval"] = signed


def _verified_bytes_for_synthetic_test(policy):
    # Only in tests: actual CLI requires a manifest with matching original bytes.
    return len({row["source_url"] for row in policy["legal_citations"]})


def _import_test(store, **kwargs):
    return import_reviewed_state_benefit(
        store, **kwargs, verified_source_bytes=_verified_bytes_for_synthetic_test,
    )



def bundle(uf="SP", *, path="state_statute"):
    p = policy(uf, path=path)
    p["legal_citations"] = [{
        "act": p["state_normative_reference"],
        "provision": "Sintetico / T09 teste, NAO norma real",
        "source_url": p["state_official_source_url"],
        "source_sha256": "a" * 64,
        "published_on": "2025-01-01",
        "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "review_reference": p["review_reference"],
    }]
    if path != "state_statute":
        p["legal_citations"].append({
            "act": "Convênio ICMS 190/2017",
            "provision": "Teste sintético de rota CONFAZ",
            "source_url": "https://www.gov.br/confaz/legislacao/sintetica",
            "source_sha256": "b" * 64,
            "published_on": "2025-01-01",
            "valid_from": "2026-01-01",
            "valid_until": "2027-01-01",
            "review_reference": p["review_reference"],
        })
    case_facts = facts(uf, path=path)
    _sign_review(p, case_facts)
    return {
        "snapshot_id": "t09-facts", "snapshot_version": 1,
        "competence": MONTH, "issuer": Cnpj(CNPJ),
        "content": case_facts,
        "benefit_id": "t09-state-rule", "benefit_version": 1,
        "benefit_content": p,
    }


def verifier(cnpj, competence):
    assert cnpj == CNPJ and competence == MONTH
    return ReviewedStateIssuer(
        cnpj, "SP", "6201501", FederalIncomeTaxRegime.LUCRO_REAL, True, SCOPE,
    )


class FakeStore:
    scope_identity = SCOPE

    def __init__(self):
        self.rows = {}

    def record(self, table, record_id, version=None):
        matches = [
            row for (name, rid, ver), row in self.rows.items()
            if name == table and rid == record_id
            and (version is None or version == ver)
        ]
        return max(matches, key=lambda row: row["version"]) if matches else None

    def records(self, table, *, limit=100, schema_version=None, jurisdiction=None):
        return tuple(
            row for (name, _, _), row in self.rows.items()
            if name == table
            and (schema_version is None
                 or row.get("content", {}).get("schema_version") == schema_version)
            and (jurisdiction is None or row.get("jurisdiction") == jurisdiction)
        )[:limit]

    def benefit_version_at(self, record_id, competence):
        following = date(
            competence.year + (competence.month == 12),
            competence.month % 12 + 1, 1,
        )
        versions = [
            row["version"] for (table, rid, _), row in self.rows.items()
            if table == "fm_economy_benefits" and rid == record_id
            and date.fromisoformat(row["valid_from"]) < following
        ]
        return max(versions) if versions else None

    def state_benefit_candidates(self, *, jurisdiction, competence,
                                 schema_version, limit=500):
        following = date(
            competence.year + (competence.month == 12),
            competence.month % 12 + 1, 1,
        )
        eligible_ids = {
            rid for (table, rid, _), row in self.rows.items()
            if table == "fm_economy_benefits"
            and row["jurisdiction"] == jurisdiction
            and row["content"].get("schema_version") == schema_version
        }
        latest = {}
        for (table, rid, _), row in self.rows.items():
            if (
                table != "fm_economy_benefits" or rid not in eligible_ids
                or date.fromisoformat(row["valid_from"]) >= following
            ):
                continue
            if rid not in latest or latest[rid]["version"] < row["version"]:
                latest[rid] = row
        candidates = sorted(
            (r for r in latest.values()
             if r["jurisdiction"] == jurisdiction and r["tax_code"] == "ICMS"),
            key=lambda r: r["record_id"],
        )
        return tuple(candidates[:limit]), len(candidates) > limit

    def lock_state_review_import(self, snapshot_id, benefit_id):
        return None

    def append_snapshot(self, *, record_id, version, competence, issuer, content):
        self.rows[("fm_economy_snapshots", record_id, version)] = {
            "record_id": record_id, "version": version,
            "issuer_cnpj": issuer.value, "competence": competence.isoformat(),
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


def test_state_import_and_replay_are_immutable_and_advisory():
    store = FakeStore()
    first = _import_test(store, **bundle(), verify_issuer=verifier)
    assert first["status"] == "potential"
    assert first["approved_cents"] is None
    assert first["realized_cents"] is None
    assert first["issuance_authorized"] is False
    assert first["tax_reporting_authorized"] is False
    assert first == _import_test(
        store, **bundle(), verify_issuer=verifier,
    )
    assert len(store.rows) == 2
    assert first == evaluate_state_benefit(
        store, snapshot_id="t09-facts", snapshot_version=1,
        benefit_id="t09-state-rule", benefit_version=1, verify_issuer=verifier,
    )
    tampered = bundle()
    tampered["benefit_content"]["allowed_cfops"] = ["6102"]
    _sign_review(tampered["benefit_content"], tampered["content"])
    with pytest.raises(FiscalValidationError, match="immutable"):
        _import_test(store, **tampered, verify_issuer=verifier)


def test_state_legislation_missing_or_invalid_never_creates_a_candidate():
    for corrupted in (
        {"legal_citations": []},
        {"state_official_source_url": "https://attacker.example.org/"},
        {"review_status": "draft"},
    ):
        row = bundle()
        row["benefit_content"].update(corrupted)
        store = FakeStore()
        with pytest.raises(FiscalValidationError):
            _import_test(
                store, **row, verify_issuer=verifier,
            )
        assert not store.rows


def test_state_source_citations_must_cover_full_month_and_match_primary_act():
    row = bundle()
    row["benefit_content"]["legal_citations"][0]["valid_until"] = "2026-11-15"
    with pytest.raises(FiscalValidationError):
        _import_test(FakeStore(), **row, verify_issuer=verifier)
    row = bundle()
    row["benefit_content"]["legal_citations"][0]["act"] = "Other State Act"
    with pytest.raises(FiscalValidationError, match="primary"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)


def test_state_jurisdiction_mismatch_produces_no_fiscal_entitlement():
    store = FakeStore()
    first = _import_test(store, **bundle(), verify_issuer=verifier)
    assert first["status"] == "potential"
    store.scope_identity = ("fm-nfcore", "foreign", "unit-a", "homologation")
    with pytest.raises(FiscalValidationError, match="canonical"):
        evaluate_state_benefit(
            store, snapshot_id="t09-facts", snapshot_version=1,
            benefit_id="t09-state-rule", benefit_version=1, verify_issuer=verifier,
        )


@pytest.mark.parametrize("path", ["confaz_convention", "lc160_reinstituted"])
def test_state_confaz_paths_require_both_local_and_national_citations(path):
    store = FakeStore()
    first = _import_test(
        store, **bundle(path=path), verify_issuer=verifier,
    )
    assert first["status"] == "potential"
    modified = bundle(path=path)
    modified["benefit_content"]["legal_citations"].pop()
    _sign_review(modified["benefit_content"], modified["content"])
    with pytest.raises(FiscalValidationError, match="CONFAZ"):
        _import_test(
            FakeStore(), **modified, verify_issuer=verifier,
        )


def test_latest_revocation_cannot_reactivate_old_state_rule():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    store.append_benefit(
        record_id="t09-state-rule", version=2, tax_code="ICMS",
        jurisdiction="SP", normative_reference="Revogacao sintetica",
        valid_from=date(2026, 11, 15), valid_until=date(2027, 1, 1),
        content={"schema_version": "nfcore.revoked/v1", "review_status": "revoked"},
    )
    with pytest.raises(FiscalValidationError, match="replaced"):
        evaluate_state_benefit(
            store, snapshot_id="t09-facts", snapshot_version=1,
            benefit_id="t09-state-rule", benefit_version=1, verify_issuer=verifier,
        )
    result = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert result["counts"]["potential"] == 0
    assert result["counts"]["review_required"] == 1


def test_uf_and_schema_filter_run_before_limit_and_exclude_other_tax_rules():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    for i in range(501):
        store.append_benefit(
            record_id=f"other-{i}", version=1, tax_code="ICMS",
            jurisdiction="RJ" if i % 2 else "SP",
            normative_reference="Sintetica",
            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
            content={"schema_version": "other-benefit/v1"},
        )
    search = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert search["counts"]["potential"] == 1
    assert search["results"][0]["uf"] == "SP"
    assert search["coverage_truncated"] is False
    assert search["complete_state_benefit_coverage"] is False


def test_empty_state_catalog_validates_issuer_before_answering():
    row = bundle()
    store = FakeStore()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        issuer=row["issuer"], competence=row["competence"], content=row["content"],
    )
    calls = []

    def tracked(cnpj, competence):
        calls.append((cnpj, competence))
        return verifier(cnpj, competence)

    result = search_state_benefits(
        store, snapshot_id=row["snapshot_id"], snapshot_version=1,
        verify_issuer=tracked,
    )
    assert result["status"] == "no_reviewed_catalog"
    assert calls == [(CNPJ, MONTH)]


@pytest.mark.parametrize("changed_fact", [
    {"uf": "RJ"},
    {"activity_cnae": "1111111"},
])
def test_empty_state_catalog_rejects_snapshot_with_noncanonical_facts(changed_fact):
    row = bundle()
    row["content"].update(changed_fact)
    store = FakeStore()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        issuer=row["issuer"], competence=row["competence"], content=row["content"],
    )
    with pytest.raises(FiscalValidationError, match="canonical state issuer mismatch"):
        search_state_benefits(
            store, snapshot_id=row["snapshot_id"], snapshot_version=1,
            verify_issuer=verifier,
        )


def test_empty_state_catalog_rejects_untrusted_issuer_scope():
    row = bundle()
    store = FakeStore()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        issuer=row["issuer"], competence=row["competence"], content=row["content"],
    )

    def wrong_scope(cnpj, competence):
        assert cnpj == CNPJ and competence == MONTH
        return ReviewedStateIssuer(
            cnpj, "SP", "6201501", FederalIncomeTaxRegime.LUCRO_REAL, True,
            ("fm-nfcore", "other-tenant", "unit-a", "homologation"),
        )

    with pytest.raises(FiscalValidationError, match="canonical state issuer mismatch"):
        search_state_benefits(
            store, snapshot_id=row["snapshot_id"], snapshot_version=1,
            verify_issuer=wrong_scope,
        )


def test_empty_state_catalog_rejects_nonmonthly_competence():
    row = bundle()
    store = FakeStore()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        issuer=row["issuer"], competence=date(2026, 11, 15),
        content=row["content"],
    )
    with pytest.raises(FiscalValidationError, match="monthly state competence"):
        search_state_benefits(
            store, snapshot_id=row["snapshot_id"], snapshot_version=1,
            verify_issuer=verifier,
        )


def test_no_reviewed_state_rules_does_not_mean_no_benefits_exist():
    row = bundle()
    store = FakeStore()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        issuer=row["issuer"], competence=row["competence"], content=row["content"],
    )
    result = search_state_benefits(
        store, snapshot_id=row["snapshot_id"], snapshot_version=1,
        verify_issuer=verifier,
    )
    assert result["status"] == "no_reviewed_catalog"
    assert result["results"] == []
    assert result["complete_state_benefit_coverage"] is False


def test_service_import_without_trusted_source_byte_verifier_fails_closed():
    row = bundle()
    with pytest.raises(FiscalValidationError, match="source byte verifier"):
        import_reviewed_state_benefit(
            FakeStore(), **row, verify_issuer=verifier,
        )


def test_service_rejects_unsigned_or_tampered_curatorial_approval():
    row = bundle()
    row["benefit_content"].pop("internal_review_approval")
    with pytest.raises(FiscalValidationError, match="approval is absent"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)

    row = bundle()
    row["content"]["evidence"]["state_act_review"] = "invented-state-reference"
    with pytest.raises(FiscalValidationError, match="approval claims mismatch"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)

    row = bundle()
    row["benefit_content"]["internal_review_approval"]["signature_hmac_sha256"] = "f" * 64
    with pytest.raises(FiscalValidationError, match="signature mismatch"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)


def test_review_receipt_is_tenant_and_competence_bound():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    store.scope_identity = ("fm-nfcore", "tenant-b", "unit-a", "homologation")
    with pytest.raises(FiscalValidationError):
        evaluate_state_benefit(
            store, snapshot_id="t09-facts", snapshot_version=1,
            benefit_id="t09-state-rule", benefit_version=1,
            verify_issuer=lambda c, d: ReviewedStateIssuer(
                c, "SP", "6201501", FederalIncomeTaxRegime.LUCRO_REAL,
                True, store.scope_identity,
            ),
        )


def test_confaz_act_must_match_exact_rule_reference():
    row = bundle(path="confaz_convention")
    row["benefit_content"]["legal_citations"][1]["act"] = "Convênio ICMS 999/2026"
    _sign_review(row["benefit_content"], row["content"])
    with pytest.raises(FiscalValidationError, match="exact CONFAZ"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)


def test_facts_must_share_review_reference_with_policy():
    row = bundle()
    row["content"]["review_reference"] = "different-review-reference"
    _sign_review(row["benefit_content"], row["content"])
    with pytest.raises(FiscalValidationError, match="review references mismatch"):
        _import_test(FakeStore(), **row, verify_issuer=verifier)


def test_future_version_does_not_suppress_historical_month():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    store.append_benefit(
        record_id="t09-state-rule", version=2, tax_code="ICMS",
        jurisdiction="SP", normative_reference="Future synthetic adjustment",
        valid_from=date(2026, 12, 1), valid_until=date(2027, 12, 1),
        content={"schema_version": "nfcore.revoked/v1", "review_status": "revoked"},
    )
    assert evaluate_state_benefit(
        store, snapshot_id="t09-facts", snapshot_version=1,
        benefit_id="t09-state-rule", benefit_version=1, verify_issuer=verifier,
    )["status"] == "potential"
    search = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert search["counts"]["potential"] == 1
    assert search["coverage_truncated"] is False


def test_intermediate_amendment_blocks_old_version_even_with_future_revision():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    for version, first in ((2, date(2026, 11, 15)), (3, date(2027, 1, 1))):
        store.append_benefit(
            record_id="t09-state-rule", version=version, tax_code="ICMS",
            jurisdiction="SP", normative_reference="Synthetic amendment",
            valid_from=first, valid_until=date(2028, 1, 1),
            content={"schema_version": "nfcore.revoked/v1", "review_status": "revoked"},
        )
    with pytest.raises(FiscalValidationError, match="replaced"):
        evaluate_state_benefit(
            store, snapshot_id="t09-facts", snapshot_version=1,
            benefit_id="t09-state-rule", benefit_version=1, verify_issuer=verifier,
        )
    search = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert search["counts"]["potential"] == 0
    assert search["counts"]["review_required"] == 1


def test_over_500_versions_in_same_uf_do_not_truncate_one_candidate():
    store = FakeStore()
    _import_test(store, **bundle(), verify_issuer=verifier)
    for version in range(2, 503):
        store.append_benefit(
            record_id="t09-state-rule", version=version, tax_code="ICMS",
            jurisdiction="SP", normative_reference="Future synthetic amendment",
            valid_from=date(2027, 1, 1), valid_until=date(2028, 1, 1),
            content={"schema_version": "nfcore.revoked/v1", "review_status": "revoked"},
        )
    result = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert result["counts"]["potential"] == 1
    assert len(result["results"]) == 1
    assert result["coverage_truncated"] is False


def test_501_distinct_current_candidates_produce_explicit_truncation():
    store = FakeStore()
    row = bundle()
    store.append_snapshot(
        record_id=row["snapshot_id"], version=row["snapshot_version"],
        competence=row["competence"], issuer=row["issuer"], content=row["content"],
    )
    for index in range(501):
        other = f"t09-state-{index:04d}"
        store.append_benefit(
            record_id=other, version=1, tax_code="ICMS", jurisdiction="SP",
            normative_reference="Synthetic non approved",
            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
            content={
                "schema_version": RULE_SCHEMA, "review_status": "draft",
            },
        )
    result = search_state_benefits(
        store, snapshot_id="t09-facts", snapshot_version=1,
        verify_issuer=verifier,
    )
    assert result["coverage_truncated"] is True
    assert result["status"] == "review_required"
    assert len(result["results"]) == 500
    assert result["counts"]["potential"] == 0


def test_service_rejects_fake_boolean_or_failed_source_byte_verification():
    row = bundle()
    with pytest.raises(FiscalValidationError, match="source bytes are not all verified"):
        import_reviewed_state_benefit(
            FakeStore(), **row, verify_issuer=verifier,
            verified_source_bytes=lambda _: True,
        )

    def failed_source_read(_):
        raise ValueError("private path details must not escape validation")

    with pytest.raises(FiscalValidationError, match="source verification failed"):
        import_reviewed_state_benefit(
            FakeStore(), **row, verify_issuer=verifier,
            verified_source_bytes=failed_source_read,
        )
