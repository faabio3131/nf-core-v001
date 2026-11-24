"""T02 — versioned, authority-free structured economy advice.

Only an immutable, scoped deterministic evaluation and its pinned legal evidence
can populate a candidate. Model output cannot create candidates or legal sources.
The contract neither determines eligibility nor grants fiscal approval.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .baseline import Baseline, insufficient
from .contracts import (
    AdviceRequest,
    AdviceResult,
    AdviceSection,
    AdviceStatus,
    Capability,
    EvidenceKind,
    SectionKind,
    stable_hash,
)

SCHEMA_VERSION: Literal["nfcore.cognitive.economy/v1"] = "nfcore.cognitive.economy/v1"
CAPABILITIES = frozenset({
    Capability.OPPORTUNITY_RADAR, Capability.CREDIT_RECOVERY, Capability.TAX_SIMULATION,
})
AgentKind = Literal["opportunity", "credit", "simulation"]
AGENTS: dict[Capability, AgentKind] = {
    Capability.OPPORTUNITY_RADAR: "opportunity",
    Capability.CREDIT_RECOVERY: "credit",
    Capability.TAX_SIMULATION: "simulation",
}
ORIGIN = "economy:canonical-evaluation/v1"
LEGAL_ORIGIN = "economy:reviewed-rule/v1"
REVIEW_ACTIONS = (
    "Solicitar revisão contábil das evidências.",
    "Conferir a vigência e os requisitos da norma.",
    "Conferir a memória de cálculo no motor fiscal.",
    "Solicitar documentos complementares ao responsável fiscal.",
)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=1, le=2147483647)]
Cents = Annotated[int, Field(ge=0, le=9223372036854775807)]
Day = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class VersionedReference(ContractModel):
    record_id: Identifier
    version: Version
    digest: Digest


class LegalCitation(ContractModel):
    act: Text
    provision: Text
    source_url: Text
    source_sha256: Digest
    published_on: Day
    valid_from: Day
    valid_until: Day | None
    review_reference: Text

    @model_validator(mode="after")
    def validate_citation(self) -> Self:
        url = urlsplit(self.source_url)
        hostname = url.hostname or ""
        if (
            url.scheme != "https" or url.username or url.password
            or url.port is not None
            or not (hostname == "gov.br" or hostname.endswith((".gov.br", ".leg.br", ".jus.br")))
            or not url.path.startswith("/")
            or any(ch.isspace() for ch in self.source_url)
        ):
            raise ValueError("legal citation requires an official HTTPS source reference")
        if not all(field.strip() == field and field for field in (
            self.act, self.provision, self.review_reference,
        )):
            raise ValueError("legal citation fields must be nonblank")
        publication = date.fromisoformat(self.published_on)
        start = date.fromisoformat(self.valid_from)
        if self.valid_until is not None and date.fromisoformat(self.valid_until) <= start:
            raise ValueError("invalid legal validity interval")
        if publication > date.today():
            raise ValueError("future legal publication cannot be cited")
        return self

    def covers(self, competence: str) -> bool:
        # Exact day-of-fact is not available in T01; conservatively require
        # the rule to cover the whole competence, not just its first day.
        month = date.fromisoformat(competence)
        following = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        return (
            date.fromisoformat(self.valid_from) <= month
            and (self.valid_until is None or date.fromisoformat(self.valid_until) >= following)
        )


class EconomyCandidate(ContractModel):
    kind: AgentKind
    evaluation: VersionedReference
    snapshot: VersionedReference
    rule: VersionedReference
    scope_hash: Digest
    competence: Day
    tax_code: Identifier
    engine_version: Identifier
    calculation_reference: Identifier
    estimated_cents: Cents
    legal_citations: Annotated[tuple[LegalCitation, ...], Field(min_length=1, max_length=8)]
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=2, max_length=9)]
    status: Literal["potential"] = "potential"
    approved_cents: None = None
    realized_cents: None = None

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if date.fromisoformat(self.competence).day != 1:
            raise ValueError("competence must be the first day of a month")
        if any(not citation.covers(self.competence) for citation in self.legal_citations):
            raise ValueError("citation does not cover the whole competence")
        if not all(value.strip() for value in (self.tax_code, self.engine_version,
                                               self.calculation_reference)):
            raise ValueError("calculation references must be nonblank")
        if len(self.evidence_ids) != len(self.legal_citations) + 1:
            raise ValueError("each legal citation requires its own evidence id")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate evidence identifiers")
        return self


class EconomyAdvice(ContractModel):
    schema_version: Literal["nfcore.cognitive.economy/v1"] = SCHEMA_VERSION
    agent: AgentKind
    status: Literal["potential", "insufficient_basis", "denied"]
    advice_only: Literal[True] = True
    requires_human_approval: Literal[True] = True
    candidates: Annotated[tuple[EconomyCandidate, ...], Field(max_length=1)]
    review_actions: Annotated[tuple[str, ...], Field(max_length=4)]

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if (self.status == "potential") != bool(self.candidates):
            raise ValueError("candidate status does not match evaluation evidence")
        if any(item.kind != self.agent for item in self.candidates):
            raise ValueError("candidate is for a different agent")
        if any(action not in REVIEW_ACTIONS for action in self.review_actions):
            raise ValueError("unsupported review action")
        if not self.candidates and self.review_actions:
            raise ValueError("review actions require cited evaluation")
        return self


def _candidate_from_request(request: AdviceRequest) -> EconomyCandidate | None:
    if request.capability not in CAPABILITIES or request.subject_id is None:
        return None
    scope_hash = stable_hash(request.scope.identity_material)
    evaluations = [
        e for e in request.evidence if e.kind is EvidenceKind.ECONOMY_EVALUATION
        and e.trusted and e.origin == ORIGIN
    ]
    legal = [
        e for e in request.evidence if e.kind is EvidenceKind.ECONOMY_LEGAL
        and e.trusted and e.origin == LEGAL_ORIGIN
    ]
    if len(evaluations) != 1 or not 1 <= len(legal) <= 8:
        return None
    evaluation = evaluations[0]
    try:
        data = evaluation.data
        if (
            data["record_id"] != request.subject_id
            or data["kind"] != AGENTS[request.capability]
            or any(
                e.tenant_id != request.scope.tenant_id or e.unit_id != request.scope.unit_id
                or e.data.get("scope_hash") != scope_hash
                for e in (evaluation, *legal)
            )
        ):
            return None
        ids = (evaluation.evidence_id, *(e.evidence_id for e in legal))
        citations = []
        for evidence in legal:
            item = dict(evidence.data)
            if (
                item.pop("rule_id") != data["rule_id"]
                or item.pop("rule_version") != data["rule_version"]
                or item.pop("rule_digest") != data["rule_digest"]
            ):
                return None
            item.pop("scope_hash")
            citations.append(LegalCitation.model_validate({
                **item, "valid_until": item["valid_until"] or None,
            }))
        return EconomyCandidate.model_validate({
            "kind": data["kind"],
            "evaluation": {
                "record_id": data["record_id"], "version": int(data["version"]),
                "digest": data["digest"],
            },
            "snapshot": {
                "record_id": data["snapshot_id"], "version": int(data["snapshot_version"]),
                "digest": data["snapshot_digest"],
            },
            "rule": {
                "record_id": data["rule_id"], "version": int(data["rule_version"]),
                "digest": data["rule_digest"],
            },
            "scope_hash": scope_hash, "competence": data["competence"],
            "tax_code": data["tax_code"], "engine_version": data["engine_version"],
            "calculation_reference": data["calculation_reference"],
            "estimated_cents": int(data["estimated_cents"]),
            "legal_citations": tuple(citations), "evidence_ids": ids,
        })
    except (KeyError, TypeError, ValueError, ValidationError, OverflowError):
        return None


def economy_baseline(request: AdviceRequest) -> Baseline:
    candidate = _candidate_from_request(request)
    if candidate is None:
        return insufficient(
            "Não há avaliação determinística com base legal e vigência comprováveis "
            "no escopo solicitado. Nenhuma oportunidade ou crédito foi reconhecido."
        )
    ids = candidate.evidence_ids
    return Baseline(
        status=AdviceStatus.BASELINE_ONLY,
        sections=(
            AdviceSection(
                SectionKind.FACT,
                "Avaliação registrada pelo motor fiscal; valor somente potencial. "
                "Não houve aprovação, compensação ou realização.", ids,
            ),
            AdviceSection(SectionKind.ACTION, REVIEW_ACTIONS[0], ids),
            AdviceSection(
                SectionKind.SOURCE,
                "Base legal vinculada às versões e evidências estruturadas da avaliação.", ids,
            ),
        ),
        model_eligible=True,
    )


def economy_model_action_allowed(request: AdviceRequest, text: str, ids: tuple[str, ...]) -> bool:
    candidate = _candidate_from_request(request)
    return bool(
        candidate is not None and text.strip() in REVIEW_ACTIONS
        and set(ids) == set(candidate.evidence_ids)
    )


def project_economy(request: AdviceRequest, result: AdviceResult) -> EconomyAdvice:
    candidate = _candidate_from_request(request)
    denied = result.status is AdviceStatus.DENIED
    available = (
        not denied and candidate is not None
        and result.status in {AdviceStatus.ADVISED, AdviceStatus.BASELINE_ONLY}
    )
    actions = tuple(dict.fromkeys(
        section.text for section in result.sections
        if section.kind is SectionKind.ACTION and section.text in REVIEW_ACTIONS
    ))[:4] if available else ()
    return EconomyAdvice.model_validate({
        "agent": AGENTS[request.capability],
        "status": "denied" if denied else "potential" if available else "insufficient_basis",
        "candidates": (candidate,) if available else (),
        "review_actions": actions,
    })
