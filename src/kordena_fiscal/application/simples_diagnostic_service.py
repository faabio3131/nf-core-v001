"""T05 application adapter for immutable T01 fiscal snapshots.

Only trusted server-side importers may create the reviewed snapshot and rule.
This service never accepts company facts or legal citations from the browser.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from kordena_fiscal.cognitive.contracts import stable_hash
from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalProfile, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.simples_diagnostic import (
    DIAGNOSTIC_VERSION,
    PayrollScenario,
    diagnose_simples,
)
from kordena_fiscal.tax.simples_nacional import (
    LEGAL_REFERENCES,
    RULE_DIGEST,
    Activity,
    MonthFacts,
    SimplesFacts,
)

SNAPSHOT_SCHEMA = "nfcore.simples-facts/2026-v1"
IssuerVerifier = Callable[[str, SimplesFacts], FiscalProfile | None]


def _month(row: dict[str, Any]) -> MonthFacts:
    return MonthFacts(
        date.fromisoformat(row["competence"]), row["domestic_cents"],
        row["export_cents"], row["payroll_cents"], row["evidence_reference"],
    )


def evaluate_snapshot(
    snapshot: dict[str, Any],
    rule: dict[str, Any],
    *,
    verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    """Decode reviewed facts, pin legal evidence and delegate all tax math."""
    try:
        content = snapshot["content"]
        policy = rule["content"]
        competence = date.fromisoformat(snapshot["competence"])
        if (
            content["schema_version"] != SNAPSHOT_SCHEMA
            or content["review_status"] != "reviewed"
            or not isinstance(content["review_reference"], str)
            or not content["review_reference"].strip()
            or policy["engine_rule_digest"] != RULE_DIGEST
            or policy["review_status"] != "reviewed"
            or not isinstance(policy["review_reference"], str)
            or not policy["review_reference"].strip()
            or rule["tax_code"] != "SIMPLES_NACIONAL"
        ):
            raise FiscalValidationError("reviewed Simples snapshot and policy required")
        facts = SimplesFacts(
            competence, date.fromisoformat(content["opened_month"]),
            content["uf"], Activity(content["activity"]),
            tuple(_month(row) for row in content["months"]),
            content["company_history_reference"], content["activity_reference"],
            content["optant_reference"],
        )
        raw_scenario = content.get("scenario")
        scenario = None if raw_scenario is None else PayrollScenario(
            _month(raw_scenario["next_month"]), raw_scenario["ordinary_domestic_base_cents"],
            raw_scenario["additional_pro_labore_cents"],
            raw_scenario.get("additional_tax_cost_cents"), raw_scenario.get("cost_reference"),
        )
        periods = (competence,) if scenario is None else (
            competence, scenario.next_month.competence,
        )
        citations = tuple(
            LegalCitation.model_validate(item) for item in policy["legal_citations"]
        )
        if not 1 <= len(citations) <= 8 or not {c.source_url for c in citations}.issuperset(
            LEGAL_REFERENCES
        ):
            raise FiscalValidationError("reviewed legal citations required")
        for period in periods:
            end = date(period.year + (period.month == 12), period.month % 12 + 1, 1)
            if (
                date.fromisoformat(rule["valid_from"]) > period
                or rule["valid_until"] is not None
                and date.fromisoformat(rule["valid_until"]) < end
                or any(
                    c.review_reference != policy["review_reference"]
                    or not c.covers(period.isoformat()) for c in citations
                )
            ):
                raise FiscalValidationError("Simples rule does not cover scenario competence")
        verify_issuer(snapshot["issuer_cnpj"], facts)
        result = diagnose_simples(
            facts, ordinary_domestic_base_cents=content["ordinary_domestic_base_cents"],
            scenario=scenario,
        )
        return {
            **result, "snapshot_id": snapshot["record_id"],
            "snapshot_version": snapshot["version"], "snapshot_digest": snapshot["digest"],
            "reviewed_rule_id": rule["record_id"], "reviewed_rule_version": rule["version"],
            "reviewed_rule_digest": rule["digest"],
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid reviewed Simples evidence") from exc


def evaluate_and_record(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    rule_id: str, rule_version: int, verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    """Persist only positive, costed hypothetical opportunities, not credits.

    Deterministic identity makes sequential retries replay the existing record.
    Concurrent duplicate inserts fail atomically through the T01 primary key.
    """
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    rule = store.record("fm_economy_benefits", rule_id, rule_version)
    if snapshot is None or rule is None:
        raise FiscalValidationError("scoped Simples evidence unavailable")
    result = evaluate_snapshot(snapshot, rule, verify_issuer=verify_issuer)
    scenario = result["scenario"]
    ids: dict[str, str] = {}
    if (
        scenario is not None and scenario["transition_v_to_iii"]
        and type(scenario["net_estimated_tax_saving_cents"]) is int
        and scenario["net_estimated_tax_saving_cents"] > 0
    ):
        calculation = stable_hash(result)
        for kind in ("opportunity", "simulation"):
            record_id = "simples-" + stable_hash({
                "kind": kind, "calculation": calculation,
            })
            payload = {
                "kind": kind, "rule_digest": rule["digest"],
                "snapshot_digest": snapshot["digest"],
                "rule_review_reference": rule["content"]["review_reference"],
                "calculation_status": "deterministic",
                "engine_version": DIAGNOSTIC_VERSION,
                "calculation_reference": calculation,
                "target_competence": scenario["target_competence"],
                "diagnostic": result,
            }
            estimated = scenario["net_estimated_tax_saving_cents"]
            previous = store.record("fm_economy_opportunities", record_id, 1)
            if previous is None:
                store.append_opportunity(
                    record_id=record_id, version=1, snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version, benefit_id=rule_id,
                    benefit_version=rule_version, estimated_cents=estimated, content=payload,
                )
            elif previous["content"] != payload or previous["estimated_cents"] != estimated:
                raise FiscalValidationError("Simples evaluation replay mismatch")
            ids[kind] = record_id
    return {**result, "evaluation_ids": ids}


def import_reviewed_inputs(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    competence: date, issuer: Cnpj, content: dict[str, Any],
    rule_id: str, rule_version: int, rule_content: dict[str, Any],
    verify_issuer: IssuerVerifier,
) -> dict[str, Any]:
    """Trusted operator import into the SAME scoped transaction, never public UI.

    Review assertions must come from a responsible fiscal reviewer, not this
    function. Source hashes must be obtained from the archived source bytes.
    No review is inferred or generated. IDs and content are immutable.
    """
    from kordena_fiscal.persistence.economy_store import _digest

    snapshot = {
        "record_id": snapshot_id, "version": snapshot_version,
        "competence": competence.isoformat(), "issuer_cnpj": issuer.value,
        "content": content, "digest": _digest(content)[1],
    }
    rule = {
        "record_id": rule_id, "version": rule_version, "tax_code": "SIMPLES_NACIONAL",
        "valid_from": "2026-01-01", "valid_until": "2027-01-01",
        "content": rule_content, "digest": _digest(rule_content)[1],
    }
    evaluate_snapshot(snapshot, rule, verify_issuer=verify_issuer)
    old_snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    old_rule = store.record("fm_economy_benefits", rule_id, rule_version)
    for old, new in ((old_snapshot, snapshot), (old_rule, rule)):
        if old is not None and any(old.get(key) != value for key, value in new.items()):
            raise FiscalValidationError("immutable reviewed input conflict; use new version")
    if old_snapshot is None:
        store.append_snapshot(
            record_id=snapshot_id, version=snapshot_version, competence=competence,
            issuer=issuer, content=content,
        )
    if old_rule is None:
        store.append_benefit(
            record_id=rule_id, version=rule_version, tax_code="SIMPLES_NACIONAL",
            jurisdiction="BR", normative_reference="LC123/2006; CGSN140/2018; CGSN54/2025",
            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1), content=rule_content,
        )
    return evaluate_and_record(
        store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
        rule_id=rule_id, rule_version=rule_version, verify_issuer=verify_issuer,
    )
