"""T09 negative/conditional cases for EACH of the 27 research candidates.

All policy and issuer records below are SYNTHETIC. A "potential" result proves
only that the deterministic triage reached its advisory state, never that a
real benefit, grant, product classification, fiscal credit or entitlement exists.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime
from kordena_fiscal.tax.state_benefits import (
    _COMMON_EVIDENCE,
    _ROUTE_EVIDENCE,
    _UF_CODES,
    FACTS_SCHEMA,
    RULE_SCHEMA,
    ReviewedStateIssuer,
    assess_state_rule,
    decode_facts,
    decode_rule,
)

DOCS = Path(__file__).resolve().parents[2] / "docs"
REVIEW = "t09-synthetic-27-uf-negative-tests"
MONTH = date(2026, 11, 1)


def _dossiers() -> dict[str, dict]:
    content = json.loads(
        (DOCS / "NFCORE_T09_DOSSIE_RECONCILIATION_V1.json").read_text(
            encoding="utf-8"
        )
    )
    return {item["uf"]: item for item in content["dossiers"]}


def _hypothetical_case(
    uf: str,
    *,
    missing: tuple[str, ...] = (),
    month: date = MONTH,
    concession_status: str = "active",
    issuer_uf: str | None = None,
    operation: str = "domestic_sale",
    cfop: str = "5102",
) -> dict:
    """Synthetic permit and sources; NEVER legal permission in a real business."""
    evidence_name = _dossiers()[uf]["required_review_evidence"]
    required = [
        *_COMMON_EVIDENCE,
        *_ROUTE_EVIDENCE["state_statute"],
        evidence_name,
    ]
    rule = decode_rule({
        "schema_version": RULE_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": uf,
        "benefit_kind": "special_regime",
        "legal_path": "state_statute",
        "state_normative_reference": "t09 synthetic hypothesis not a statute",
        "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "legal_valid_until_inclusive": "2026-12-31",
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "reviewed_any",
        "allowed_cnaes": [],
        "ncm_scope": "reviewed_any",
        "allowed_ncms": [],
        "allowed_cfops": ["5102"],
        "allowed_operations": ["domestic_sale"],
        "individual_concession_required": True,
        "required_evidence": [evidence_name],
    })
    data = decode_facts({
        "schema_version": FACTS_SCHEMA,
        "review_status": "reviewed",
        "review_reference": REVIEW,
        "uf": uf,
        "activity_cnae": "6201501",
        "operation_ncm": "84713012",
        "operation_cfop": cfop,
        "operation": operation,
        "evidence": {
            k: "synthetic-placeholder-not-authoritative"
            for k in required if k not in missing
        },
        "individual_concession": {
            "status": concession_status,
            "competence": month.isoformat(),
            "review_reference": REVIEW,
            "document_reference": "synthetic-no-real-concession",
            "issuer_cnpj": "12345678000195",
            "uf": uf,
            "valid_from": "2026-01-01",
            "valid_until": "2026-12-31",
        },
    })
    issuer = ReviewedStateIssuer(
        cnpj="12345678000195",
        uf=issuer_uf or uf,
        primary_cnae="6201501",
        regime=FederalIncomeTaxRegime.LUCRO_REAL,
        state_registration_present=True,
        scope_identity=("t09", "tenant-synthetic", "unit-synthetic", uf),
    )
    return assess_state_rule(rule, data, issuer, month)


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_exact_uf_condition_required_for_each_candidate(uf: str):
    dossier = _dossiers()[uf]
    assert dossier["candidate_id"].startswith(f"{uf}-")
    assert dossier["source_pointers"]
    assert all(p.startswith("https://") for p in dossier["source_pointers"])
    assert dossier["conditional_positive"] and dossier["negative"]
    assert dossier["required_review_evidence"]
    outcome = _hypothetical_case(
        uf, missing=(dossier["required_review_evidence"],)
    )
    assert outcome["status"] == "insufficient_basis"
    assert outcome["reason_codes"] == [
        f"missing:{dossier['required_review_evidence']}"
    ]
    assert outcome["tax_calculation_authorized"] is False
    assert outcome["issuance_authorized"] is False
    assert outcome["eligibility_certified"] is False


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_unapproved_or_revoked_individual_grant_never_passes(uf: str):
    outcome = _hypothetical_case(uf, concession_status="revoked")
    assert outcome["status"] == "insufficient_basis"
    assert outcome["reason_codes"] == ["individual_concession_revoked"]
    assert outcome["tax_calculation_authorized"] is False


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_jurisdiction_and_interstate_mismatch_rejected_for_every_uf(uf: str):
    other = "SP" if uf != "SP" else "RJ"
    wrong_state = _hypothetical_case(uf, issuer_uf=other)
    assert wrong_state["status"] == "not_applicable"
    assert wrong_state["reason_codes"] == ["state_jurisdiction_mismatch"]
    interstate = _hypothetical_case(
        uf, operation="interstate_sale", cfop="6102"
    )
    assert interstate["status"] == "not_applicable"
    assert interstate["reason_codes"] == ["operation_excluded"]


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_no_candidate_can_be_extended_to_a_future_competence(uf: str):
    outcome = _hypothetical_case(uf, month=date(2027, 1, 1))
    assert outcome["status"] == "not_applicable"
    assert outcome["reason_codes"] == [
        "state_rule_not_effective_entire_month"
    ]


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_even_complete_synthetic_condition_yields_only_advisory(uf: str):
    outcome = _hypothetical_case(uf)
    assert outcome["status"] == "potential"
    assert outcome["advisory_only"] is True
    assert outcome["tax_calculation_authorized"] is False
    assert outcome["issuance_authorized"] is False
    assert outcome["eligibility_certified"] is False
    assert outcome["approved_cents"] is None
    assert _dossiers()[uf]["internal_acceptance"] is False


def test_all_27_simulation_cases_have_unique_audit_identity():
    dossiers = _dossiers()
    assert len(dossiers) == len(_UF_CODES) == 27
    assert set(dossiers) == set(_UF_CODES)
    assert len({d["candidate_id"] for d in dossiers.values()}) == 27
