"""SP Art41/Art52 and CAT35/2017: source-anchored examples, NOT taxpayer grants.

RC 33644/2026 supplies an example CNAE, CFOP and NCM, but explicitly
does not certify eligibility. All evidence below is SYNTHETIC.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    _COMMON_EVIDENCE,
    _ROUTE_EVIDENCE,
    FACTS_SCHEMA,
    RULE_SCHEMA,
    ReviewedStateIssuer,
    assess_state_rule,
    decode_facts,
    decode_rule,
)

DOCS = Path(__file__).resolve().parents[2] / "docs"
REVIEW = "synthetic-sp-art41-research-not-authorized"
CN = "12345678000195"
REQ = [
    "sp_textile_art52_ncm_scope_review",
    "sp_textile_manufacturer_review",
    "sp_taxable_internal_sale",
    "sp_not_final_consumer",
    "sp_rudfto_option_in_effect",
    "sp_no_real_or_symbolic_return",
    "sp_other_credit_reversal",
    "sp_taxpayer_regular_or_guarantee",
    "sp_outsourced_manufacture_credential_if_applicable",
]


def _documents():
    return json.loads(
        (DOCS / "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json").read_text(
            encoding="utf-8"
        )
    ), json.loads(
        (DOCS / "NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json")
        .read_text(encoding="utf-8")
    )


def _hypothesis(month, *, ncm="61159500", cfop="5101",
                operation="domestic_sale", cnae="1421500", omitted=(),
                effective="2023-01-15", evidence_changes=None):
    # Only one NCM/CNAE example is taken from the consultation, not a full
    # statutory allowlist. The route itself is still pending CONFAZ proof.
    policy = {
        "schema_version": RULE_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": "SP",
        "benefit_kind": "presumed_credit",
        "legal_path": "lc160_reinstituted",
        "confaz_normative_reference": "Convenio ICMS 190/2017",
        "state_normative_reference": "RICMS-SP Anexo III art41 com Anexo II art52",
        "valid_from": effective,
        "valid_until": "2027-01-01",
        "legal_valid_until_inclusive": "2026-12-31",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "allowlist",
        "allowed_cnaes": ["1421500"],
        "ncm_scope": "allowlist",
        "allowed_ncms": ["61159500"],
        "allowed_cfops": ["5101"],
        "allowed_operations": ["domestic_sale"],
        "individual_concession_required": False,
        "required_evidence": REQ,
    }
    evidence = {
        key: "synthetic-necessary-condition-only"
        for key in (
            *_COMMON_EVIDENCE,
            *_ROUTE_EVIDENCE["lc160_reinstituted"],
            *REQ,
        )
        if key not in omitted
    }
    if evidence_changes:
        evidence.update(evidence_changes)
    facts = {
        "schema_version": FACTS_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": "SP",
        "activity_cnae": cnae,
        "operation_ncm": ncm,
        "operation_cfop": cfop,
        "operation": operation,
        "evidence": evidence,
        "individual_concession": {
            "status": "not_required",
            "competence": month.isoformat(),
            "review_reference": REVIEW,
            "document_reference": "synthetic-not-actual-option",
        },
    }
    issuer = ReviewedStateIssuer(
        CN, "SP", "1421500", FederalIncomeTaxRegime.LUCRO_REAL,
        True, ("nfcore", "tenant-synthetic", "unit-synthetic", "t09-sp"),
    )
    return assess_state_rule(
        decode_rule(policy), decode_facts(facts), issuer, month
    )


def test_sp_captured_state_portal_bytes_have_real_manifest_digests():
    dossiers, manifest = _documents()
    row = next(item for item in dossiers["dossiers"] if item["uf"] == "SP")
    source = row["sp_vertical_checkpoint_20261122"]
    assert len(source["source_captures"]) == 2
    for capture in source["source_captures"]:
        matched = next(
            x for x in manifest["files"] if x["nome"] == capture["filename"]
        )
        assert matched["uf"] == "SP"
        assert matched["sha256"] == capture["sha256_of_captured_bytes"]
        assert matched["bytes"] == capture["bytes"]
        assert capture["source_url"].startswith(
            "https://legislacao.fazenda.sp.gov.br/"
        )
    assert source["uncaptured_primary_act"]["original_publication_bytes_sha256"] is None
    assert source["independent_review_passed"] is False
    assert row["internal_acceptance"] is False
    assert row["import_authorized"] is False


def test_sp_consultation_scenario_can_only_return_advisory_potential():
    outcome = _hypothesis(date(2026, 11, 1))
    assert outcome["status"] == "potential"
    assert outcome["advisory_only"] is True
    assert outcome["eligibility_certified"] is False
    assert outcome["issuance_authorized"] is False
    assert outcome["tax_calculation_authorized"] is False
    assert outcome["approved_cents"] is None


@pytest.mark.parametrize("missing", [
    "sp_textile_art52_ncm_scope_review",
    "sp_textile_manufacturer_review",
    "sp_taxable_internal_sale",
    "sp_not_final_consumer",
    "sp_rudfto_option_in_effect",
    "sp_no_real_or_symbolic_return",
    "sp_other_credit_reversal",
    "sp_taxpayer_regular_or_guarantee",
    "sp_outsourced_manufacture_credential_if_applicable",
    "confaz_registry_deposit_review",
    "icms_st_applicability_review",
    "difal_applicability_review",
])
def test_sp_absent_statutory_or_route_review_prevents_potential(missing):
    outcome = _hypothesis(date(2026, 11, 1), omitted=(missing,))
    assert outcome["status"] == "insufficient_basis"
    assert outcome["reason_codes"] == [f"missing:{missing}"]
    assert outcome["eligibility_certified"] is False


@pytest.mark.parametrize("changes,reason", [
    ({"ncm": "63090000"}, "ncm_excluded"),
    ({"ncm": None}, "ncm_missing"),
    ({"cfop": "6101"}, "cfop_excluded"),
    ({"operation": "interstate_sale"}, "operation_excluded"),
    ({"cnae": "1412601"}, "canonical_cnae_mismatch"),
])
def test_sp_out_of_scope_example_cannot_be_assumed_eligible(changes, reason):
    outcome = _hypothesis(date(2026, 11, 1), **changes)
    assert outcome["status"] in ("insufficient_basis", "not_applicable")
    assert outcome["reason_codes"] == [reason]
    assert outcome["tax_calculation_authorized"] is False


@pytest.mark.parametrize("month", [date(2023, 1, 1), date(2027, 1, 1)])
def test_sp_incomplete_month_or_post_2026_is_not_automatically_effective(month):
    outcome = _hypothesis(month)
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == ["state_rule_not_effective_entire_month"]


def test_sp_formal_rudfto_option_is_not_a_taxpayer_grant():
    dossiers, _ = _documents()
    row = next(item for item in dossiers["dossiers"] if item["uf"] == "SP")
    scope = row["sp_vertical_checkpoint_20261122"]
    assert "RUDFTO" in scope["normative_individual_requirement"]
    assert scope["normative_grant_requirement_verified"] is False
    assert scope["fiscal_activation_authorized"] is False
