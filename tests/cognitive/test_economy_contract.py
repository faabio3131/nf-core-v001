"""T02 structured economy contract regression: synthetic evidence only."""
import json
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from kordena_fiscal.cognitive import CognitiveAdviceService, default_baselines
from kordena_fiscal.cognitive.contracts import (
    AdviceStatus,
    Capability,
    Evidence,
    EvidenceKind,
    SectionKind,
    stable_hash,
)
from kordena_fiscal.cognitive.economy_contract import (
    AGENTS,
    LEGAL_ORIGIN,
    ORIGIN,
    REVIEW_ACTIONS,
    EconomyAdvice,
    LegalCitation,
    project_economy,
)
from kordena_fiscal.cognitive.ports import ProviderSection

from .conftest import Recorder, ScriptedModel, make_request, make_scope

SH = "a" * 64
RH = "b" * 64
DH = "c" * 64


def legal() -> dict[str, Any]:
    return {
        "act": "Norma sintética de teste", "provision": "Artigo de teste",
        "source_url": "https://www.gov.br/receitafederal/pt-br",
        "source_sha256": DH, "published_on": "2025-01-01", "valid_from": "2026-01-01",
        "valid_until": "2027-01-01", "review_reference": "test-review",
    }


def facts(capability: Capability) -> tuple[Evidence, ...]:
    scope = make_scope()
    common = {
        "scope_hash": stable_hash(scope.identity_material), "rule_id": "rule",
        "rule_version": "2", "rule_digest": RH,
    }
    return (
        Evidence(
            "eval", EvidenceKind.ECONOMY_EVALUATION, scope.tenant_id, scope.unit_id, ORIGIN,
            {
                **common, "record_id": "candidate", "version": "1", "digest": DH,
                "snapshot_id": "snapshot", "snapshot_version": "3", "snapshot_digest": SH,
                "kind": AGENTS[capability], "competence": "2026-11-01", "tax_code": "ICMS",
                "engine_version": "engine-v1", "calculation_reference": "calc-1",
                "estimated_cents": "12000",
            },
        ),
        Evidence(
            "legal", EvidenceKind.ECONOMY_LEGAL, scope.tenant_id, scope.unit_id, LEGAL_ORIGIN,
            {**common, **legal()},
        ),
    )


def request(capability: Capability = Capability.OPPORTUNITY_RADAR):
    return replace(make_request(capability=capability, evidence=facts(capability)),
                   subject_id="candidate")


@pytest.mark.parametrize("capability", tuple(AGENTS))
def test_all_three_agents_versioned_json_legal_and_estimate(capability):
    req = request(capability)
    advice = CognitiveAdviceService(baselines=default_baselines()).advise(req)
    structured = project_economy(req, advice)
    wire = structured.model_dump_json()
    assert EconomyAdvice.model_validate_json(wire) == structured
    assert structured.schema_version == "nfcore.cognitive.economy/v1"
    assert structured.agent == AGENTS[capability] and structured.status == "potential"
    candidate = structured.candidates[0]
    assert candidate.estimated_cents == 12000
    assert candidate.approved_cents is None and candidate.realized_cents is None
    assert candidate.legal_citations[0].source_sha256 == DH
    assert candidate.rule.version == 2 and candidate.snapshot.version == 3
    assert structured.advice_only and structured.requires_human_approval
    assert structured.review_actions == (REVIEW_ACTIONS[0],)
    schema = EconomyAdvice.model_json_schema()
    assert schema["properties"]["schema_version"]["const"] == structured.schema_version
    assert schema["$defs"]["EconomyCandidate"]["properties"]["legal_citations"]["minItems"] == 1


@pytest.mark.parametrize("mutation", [
    "missing_legal", "untrusted", "foreign_unit", "foreign_scope", "wrong_rule",
    "expired", "partial_month", "invalid_url", "wrong_kind", "invalid_amount",
    "missing_calc", "wrong_subject", "no_review",
])
def test_insufficient_or_denied_evidence_never_generates_candidate(mutation):
    req = request()
    evaluation, citation = req.evidence
    if mutation == "missing_legal":
        req = replace(req, evidence=(evaluation,))
    elif mutation == "untrusted":
        req = replace(req, evidence=(evaluation, replace(citation, trusted=False)))
    elif mutation == "foreign_unit":
        req = replace(req, evidence=(evaluation, replace(citation, unit_id="other")))
    elif mutation == "wrong_subject":
        req = replace(req, subject_id="other")
    else:
        changes = {
            "foreign_scope": ("scope_hash", "f" * 64),
            "wrong_rule": ("rule_digest", "f" * 64),
            "expired": ("valid_until", "2026-11-01"),
            "partial_month": ("valid_until", "2026-11-15"),
            "invalid_url": ("source_url", "https://www.gov.br.evil.example/"),
            "wrong_kind": ("kind", "credit"),
            "invalid_amount": ("estimated_cents", "-1"),
            "missing_calc": ("calculation_reference", ""),
            "no_review": ("review_reference", ""),
        }
        key, value = changes[mutation]
        if mutation in {"wrong_kind", "invalid_amount", "missing_calc"}:
            evaluation = replace(evaluation, data={**evaluation.data, key: value})
        else:
            citation = replace(citation, data={**citation.data, key: value})
        req = replace(req, evidence=(evaluation, citation))
    model = ScriptedModel()
    recorder = Recorder()
    result = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=recorder,
    ).advise(req)
    assert not project_economy(req, result).candidates
    assert result.status in {AdviceStatus.INSUFFICIENT_BASIS, AdviceStatus.DENIED}
    assert model.calls == 0


def test_model_cannot_supply_facts_legal_amounts_or_approval():
    req = request()
    model = ScriptedModel(sections=(
        ProviderSection(SectionKind.FACT, "Crédito aprovado.", ("eval", "legal")),
        ProviderSection(SectionKind.ACTION, "Aplicar o crédito de R$ 9.999,00.", ("eval", "legal")),
        ProviderSection(SectionKind.ACTION, REVIEW_ACTIONS[1], ("eval",)),
        ProviderSection(SectionKind.ACTION, REVIEW_ACTIONS[2], ("eval", "legal")),
    ))
    recorder = Recorder()
    result = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=recorder,
    ).advise(req)
    output = project_economy(req, result)
    assert output.review_actions == (REVIEW_ACTIONS[2],)
    assert output.candidates[0].estimated_cents == 12000
    assert result.provenance.guard_findings
    assert model.calls == 1
    assert recorder.events[0].event == "advice.model_call_started"
    assert all(item.kind is not SectionKind.FACT or "aprovado." not in item.text
               for item in result.sections)


def test_wire_contract_forbids_approval_or_missing_citations():
    req = request()
    result = CognitiveAdviceService(baselines=default_baselines()).advise(req)
    payload = project_economy(req, result).model_dump(mode="json")
    for key, value in (
        ("approved_cents", 12000), ("realized_cents", 12000),
        ("estimated_cents", 1.25), ("legal_citations", []), ("execute", True),
    ):
        candidate = {**payload["candidates"][0], key: value}
        with pytest.raises(ValidationError):
            EconomyAdvice.model_validate_json(json.dumps({**payload, "candidates": [candidate]}))


def test_citation_malformed_or_future():
    with pytest.raises(ValidationError):
        LegalCitation.model_validate({**legal(), "published_on": "9999-01-01"})
    with pytest.raises(ValidationError):
        LegalCitation.model_validate({**legal(), "valid_from": date(2026, 1, 1)})


def test_provider_unavailable_preserves_deterministic_candidate():
    from kordena_fiscal.cognitive.ports import ModelProviderUnavailable

    req = request()
    model = ScriptedModel(error=ModelProviderUnavailable())
    result = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=Recorder(),
    ).advise(req)
    assert result.status is AdviceStatus.BASELINE_ONLY
    assert result.provenance.degraded_reason == "provider_unavailable"
    assert project_economy(req, result).candidates[0].estimated_cents == 12000


def test_denied_capability_does_not_call_model():
    req = replace(request(), granted_capabilities=frozenset())
    model = ScriptedModel()
    recorder = Recorder()
    result = CognitiveAdviceService(
        baselines=default_baselines(), model=model, audit=recorder,
    ).advise(req)
    assert result.status is AdviceStatus.DENIED
    assert not project_economy(req, result).candidates
    assert model.calls == 0
    assert recorder.events
