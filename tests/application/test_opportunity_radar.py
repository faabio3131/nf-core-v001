from datetime import date

import pytest

from kordena_fiscal.application.opportunity_radar import ISS_FACTS, ISS_RULE, scan_benefits

MONTH = date(2026, 11, 1)
CITY = "3509205"
ISSUER = "12345678000195"


def rule():
    return {"schema_version": ISS_RULE, "modality": "rate_reduction", "review_status": "reviewed",
            "review_reference": "fixture-review", "citation": {
                "act": "Ato de teste", "provision": "Art. 1", "review_reference": "fixture-review",
                "published_on": "2020-01-01", "valid_from": "2020-01-01", "valid_until": None,
                "source_url": "https://example.gov.br/fixture", "source_sha256": "a" * 64}}


def assessment(digest, before=2000, after=1000):
    return {"criteria_verified": True, "iss_incidence_ibge_code": CITY,
            "rule_digest": digest, "modality": "rate_reduction", "review_reference": "rev-test",
            "ordinary_iss_cents": before, "incentivized_iss_cents": after}


def no_verifier(*args):
    pytest.fail("No federal/state snapshot is available")


class Store:
    def __init__(self):
        self.entries = {"x": assessment("a"), "zero": assessment("b", 0, 0),
                        "unknown": assessment("c", None, None)}
        self.policy = rule()

    def unique_monthly_snapshot(self, issuer, month, schema):
        if (issuer, month, schema) != (ISSUER, MONTH, ISS_FACTS):
            return None
        return {"record_id": "facts", "version": 1, "digest": "snap",
                "content": {"schema_version": ISS_FACTS, "review_status": "reviewed",
                            "municipality_ibge_code": CITY, "assessments": self.entries}}

    def municipal_benefit_candidates(self, *, jurisdiction, competence, schema_version):
        assert (jurisdiction, competence, schema_version) == (CITY, MONTH, ISS_RULE)
        return [{"record_id": name, "version": 1, "digest": digest, "tax_code": "ISS",
                 "jurisdiction": CITY, "content": self.policy, "valid_from": "2020-01-01",
                 "valid_until": None, "normative_reference": "Ato de teste"}
                for name, digest in (("unknown", "c"), ("zero", "b"), ("x", "a"))], True


def scan(store, municipality=CITY, month=MONTH):
    return scan_benefits(store, ISSUER, municipality, month, no_verifier, no_verifier)


def test_known_estimates_rank_before_zero_and_unknown_and_keep_evidence():
    report = scan(Store())
    assert [r["estimated_cents"] for r in report["opportunities"]] == [1000, 0, None]
    assert report["opportunities"][0]["citation"]["source_sha256"] == "a" * 64
    assert report["coverage"]["municipal"]["coverage_truncated"] is True
    assert report["coverage"]["state"]["status"] == "insufficient_basis"


@pytest.mark.parametrize(("field", "value"), [
    ("rule_digest", "different"), ("iss_incidence_ibge_code", "3550308"),
    ("criteria_verified", False), ("modality", "exemption"), ("ordinary_iss_cents", True),
    ("incentivized_iss_cents", 9999),
])
def test_invalid_company_or_calculation_evidence_blocks_candidate(field, value):
    store = Store()
    store.entries["x"][field] = value
    assert "x" not in {r["benefit_id"] for r in scan(store)["opportunities"]}


def test_draft_or_expired_rule_and_other_company_location_are_blocked():
    store = Store()
    assert not scan(store, "3550308")["opportunities"]
    assert not scan(store, month=date(2026, 12, 1))["opportunities"]
    store.policy["review_status"] = "draft"
    assert not scan(store)["opportunities"]
    store.policy = rule()
    store.policy["citation"]["valid_until"] = "2026-11-15"
    assert not scan(store)["opportunities"]


def test_scan_combines_source_specific_snapshots_and_excludes_blocked_rows(monkeypatch):
    store = Store()
    monthly = store.unique_monthly_snapshot

    def lookup(issuer, month, schema):
        if schema == ISS_FACTS:
            return monthly(issuer, month, schema)
        return {"record_id": schema, "version": 3}

    def catalog(name, amount):
        def search(store, *, snapshot_id, snapshot_version, verify_issuer):
            assert name in snapshot_id and snapshot_version == 3
            return {"status": "review_required", "coverage_truncated": False, "results": [
                {"benefit_id": name, "estimated_cents": amount, "status": "potential"},
                {"benefit_id": "blocked", "estimated_cents": 100000, "status": "review_required"},
            ]}
        return search

    from kordena_fiscal.application.opportunity_radar import federal, state
    monkeypatch.setattr(store, "unique_monthly_snapshot", lookup)
    monkeypatch.setattr(federal, "search_federal_benefits", catalog("federal", 2000))
    monkeypatch.setattr(state, "search_state_benefits", catalog("state", None))
    report = scan(store)
    assert [item["benefit_id"] for item in report["opportunities"]] == [
        "federal", "x", "zero", "unknown", "state",
    ]
