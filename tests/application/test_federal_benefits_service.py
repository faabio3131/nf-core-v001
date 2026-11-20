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
    FACTS_SCHEMA, PROGRAMS, RULE_SCHEMA, ReviewedFederalIssuer,
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

    def record(self, table, record_id, version):
        return self.rows.get((table, record_id, version))

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
