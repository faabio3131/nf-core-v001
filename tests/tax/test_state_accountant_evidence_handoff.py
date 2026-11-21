"""T09 accountant handoff never treats source triage as legal certification."""
import json
from pathlib import Path

import pytest

from kordena_fiscal.tax.state_benefits import _UF_CODES

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _data(name: str) -> dict:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_27_cases_match_drafts_and_never_certify_without_professional_opinion():
    handoff = _data("NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json")
    drafts = _data("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    assert handoff["schema_version"] == "nfcore.t09.icms-legal-evidence-handoff/v1"
    assert not handoff["independent_professional_approval_received"]
    assert not any(handoff["authorizations"].values())
    assert handoff["state_count"] == 27
    cases = handoff["cases"]
    assert len(cases) == 27
    assert {c["uf"] for c in cases} == set(_UF_CODES)
    assert {c["candidate_id"] for c in cases} == {
        d["candidate_id"] for d in drafts["candidates"]
    }
    assert sum(c["source_clause_inspected"] for c in cases) == (
        handoff["official_source_direct_inspection_count"]
    )
    assert handoff["acts_fully_consolidated_count"] == 0
    assert handoff["accountant_opinions_count"] == 0


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_no_state_has_a_fabricated_digest_legal_decision_or_tax_credit(uf):
    packet = _data("NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json")
    item = next(c for c in packet["cases"] if c["uf"] == uf)
    assert item["source_content_sha256"] is None
    assert not item["legal_temporal_consolidation_complete"]
    assert not item["confaz_and_lc160_complete"]
    assert not item["individual_concession_verified"]
    assert not item["positive_legal_case_verified"]
    assert not item["negative_legal_case_verified"]
    assert item["accountant_review_document"] is None
    assert item["accountant_review_status"] == "pending"
    assert item["decision"] == "not_certified"
    assert item["enabled"] is False


def test_specific_legal_false_positives_stay_explicit():
    packet = _data("NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json")
    cases = {c["uf"]: c for c in packet["cases"]}
    assert "consumidor_final" in cases["SP"]["exclusion_scenarios"]
    assert "opcao_indeferida_ou_pendente" in cases["RS"]["exclusion_scenarios"]
    assert "divida_ativa_impeditiva" in cases["GO"]["exclusion_scenarios"]
    assert "sem_coordenacao_cohab" in cases["MG"]["exclusion_scenarios"]
    assert "decreto_antigo_revogado" in cases["PR"]["exclusion_scenarios"]
    assert "produto_art17_confundido_art25a" in cases["PI"]["exclusion_scenarios"]


def test_every_inspected_clause_has_official_readable_evidence():
    packet = _data("NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json")
    for item in packet["cases"]:
        if item["source_clause_inspected"]:
            assert item["official_sources_inspected"]
            assert item["identified_legal_provision"]
            assert item["legally_relevant_findings"]
            assert item["exclusion_scenarios"]
            for url in item["official_sources_inspected"]:
                assert url.startswith("https://")
            assert item["source_inspection_type"] != (
                "official_pointer_identified_not_integrally_inspected"
            )


def test_ac_financing_is_not_misclassified_as_presumed_credit():
    drafts = _data("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    row = next(r for r in drafts["candidates"] if r["uf"] == "AC")
    assert row["benefit_kind"] == "special_regime"
    assert "financiamento" in row["legal_temporal_notes"].lower()
    assert row["review_status"] == "draft"


def test_inspection_coverage_does_not_mask_unavailable_or_external_gates():
    h = _data("NFCORE_T09_ACCOUNTANT_EVIDENCE_HANDOFF_V1.json")
    assert h["official_source_direct_inspection_count"] == 24
    assert len(h["unavailable_or_incomplete_primary_source_ufs"]) == 3
    assert h["acts_fully_consolidated_count"] == 0
    assert h["accountant_opinions_count"] == 0
    assert "AL" in h["unavailable_or_incomplete_primary_source_ufs"]
    assert "RR" in h["unavailable_or_incomplete_primary_source_ufs"]
    assert "TO" in h["unavailable_or_incomplete_primary_source_ufs"]
    assert not h["independent_professional_approval_received"]


def test_ba_df_rj_ro_rn_have_explicit_legal_barriers_not_wide_universal_tax_rates():
    drafts = _data("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    by_uf = {r["uf"]: r for r in drafts["candidates"]}
    assert "24.401/2026" in " ".join(by_uf["BA"]["findings_verified_from_public_source"])
    assert "até 67%" in " ".join(by_uf["DF"]["findings_verified_from_public_source"])
    assert by_uf["DF"]["benefit_kind"] == "presumed_credit"
    assert by_uf["RJ"]["benefit_kind"] == "presumed_credit"
    assert "10.983/2025" in by_uf["RJ"]["legal_temporal_notes"]
    assert "GITEC/CRE/SEFIN" in " ".join(by_uf["RO"]["findings_verified_from_public_source"])
    assert "Consulta 015/2023" in " ".join(by_uf["RN"]["findings_verified_from_public_source"])
    assert all(by_uf[x]["review_status"] == "draft" for x in ["BA", "DF", "RJ", "RO", "RN"])
