"""T09 internal legal AI curation and external accountant are independent gates."""
import json
import re
from pathlib import Path

import pytest

from kordena_fiscal.tax.state_benefits import _UF_CODES

DOCS = Path(__file__).resolve().parents[2] / "docs"


def _document(name):
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def test_legal_ai_work_items_are_complete_geographically_not_legally():
    queue = _document("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")
    drafts = _document("NFCORE_T09_STATE_BENEFIT_DRAFT_CANDIDATES_V1.json")
    assert queue["schema_version"] == "nfcore.t09.normative-consolidation-queue/v1"
    assert queue["agent_deployment_status"] == "runbook_defined_not_an_autonomous_running_agent"
    assert queue["internal_curatorial_stage"] == "IN_PROGRESS"
    assert len(queue["work_items"]) == 27
    assert {x["uf"] for x in queue["work_items"]} == set(_UF_CODES)
    assert {x["candidate_id"] for x in queue["work_items"]} == {
        y["candidate_id"] for y in drafts["candidates"]
    }
    assert len({x["candidate_id"] for x in queue["work_items"]}) == 27


def test_professional_opinion_is_explicitly_external_and_not_forged():
    queue = _document("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")
    opinion = queue["external_opinion"]
    assert opinion["classification"] == "EXTERNAL_DEPENDENCY"
    assert opinion["responsible_role"] == (
        "independent_accountant_designated_by_product_owner"
    )
    assert opinion["state"] == "PENDING_NOT_RECEIVED"
    assert opinion["signature_received"] is False
    assert opinion["external_review_not_required_to_document_internal_research"]
    assert opinion["mandatory_before_legal_benefit_approval"]
    assert opinion["mandatory_before_fiscal_activation"]
    assert not any(queue["safety"].values())


@pytest.mark.parametrize("uf", sorted(_UF_CODES))
def test_each_legal_ai_job_is_fail_closed_until_original_act_and_signoff(uf):
    queue = _document("NFCORE_T09_NORMATIVE_CONSOLIDATION_WORK_QUEUE_V1.json")
    item = next(x for x in queue["work_items"] if x["uf"] == uf)
    assert item["current_state"] == "AWAITING_COMPLETE_NORMATIVE_CONSOLIDATION"
    digest = item["source_publication_and_original_bytes_digest"]
    if digest is not None:
        assert re.fullmatch(r"[a-f0-9]{64}", digest)
        research = _document("NFCORE_T09_DOSSIE_RECONCILIATION_V1.json")
        dossier = next(x for x in research["dossiers"] if x["uf"] == uf)
        source = dossier.get("sp_vertical_checkpoint_20261122", {}).get(
            "primary_art41_source"
        )
        assert source is not None, f"{uf}: no linked official original capture"
        assert source["source_sha256"] == digest
        assert source["raw_source_digest_calculated_from_bytes"] is True
        assert source["full_chain_complete"] is False
    assert not item["full_amendment_chain_verified"]
    assert not item["applicability_by_competence_verified"]
    assert not item["confaz_legal_route_verified"]
    assert not item["taxpayer_grant_required_and_verified"]
    assert not item["scope_and_negative_cases_legally_grounded"]
    assert not item["independent_agent_counter_review_passed"]
    assert not item["technical_tests_certified_for_real_act"]
    assert not item["internal_curatorial_accepted"]
    assert item["accountant_external_opinion"] == "PENDING_NOT_RECEIVED"
    assert item["legally_importable"] is False
    assert item["eligible_for_fiscal_application"] is False
