"""T06 reviewed scoped snapshot projection; never changes a fiscal value."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.tax.simples_nacional import Activity, MonthFacts, SimplesFacts
from kordena_fiscal.tax.simples_segregation import (
    SOURCE,
    VERSION,
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    classify_revenue,
)

SCHEMA = "nfcore.simples-segregation-facts/2026-v1"
TAX_CODE = "SIMPLES_SEGREGATION"
JURISDICTION = "BR"
NORMATIVE_REFERENCE = "CGSN140/2018 art.25"


def evaluate_segregation(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    rule_id: str, rule_version: int, verify_issuer: Callable[[str, SimplesFacts], None],
) -> dict[str, Any]:
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    rule = store.record("fm_economy_benefits", rule_id, rule_version)
    if snapshot is None or rule is None:
        raise FiscalValidationError("scoped segregation evidence unavailable")
    return _evaluate(snapshot, rule, verify_issuer=verify_issuer)


def _evaluate(
    snapshot: dict[str, Any], rule: dict[str, Any], *,
    verify_issuer: Callable[[str, SimplesFacts], None],
) -> dict[str, Any]:
    try:
        content = snapshot["content"]
        policy = rule["content"]
        competence = date.fromisoformat(snapshot["competence"])
        end = date(competence.year + (competence.month == 12), competence.month % 12 + 1, 1)
        if (
            content["schema_version"] != SCHEMA
            or content["review_status"] != "reviewed"
            or not isinstance(content["review_reference"], str)
            or not content["review_reference"].strip()
            or policy["review_status"] != "reviewed"
            or policy["engine_version"] != VERSION
            or rule["tax_code"] != TAX_CODE
            or date.fromisoformat(rule["valid_from"]) > competence
            or rule["valid_until"] is not None and date.fromisoformat(rule["valid_until"]) < end
        ):
            raise FiscalValidationError("reviewed segregation policy required")
        citations = tuple(LegalCitation.model_validate(c) for c in policy["legal_citations"])
        if not 1 <= len(citations) <= 8 or SOURCE not in {c.source_url for c in citations}:
            raise FiscalValidationError("official segregation citation required")
        if any(
            not c.covers(competence.isoformat())
            or c.review_reference != policy["review_reference"] for c in citations
        ):
            raise FiscalValidationError("segregation citation validity mismatch")
        facts = SimplesFacts(
            competence, date.fromisoformat(content["opened_month"]), content["uf"],
            Activity(content["activity"]),
            tuple(MonthFacts(
                date.fromisoformat(row["competence"]), row["domestic_cents"],
                row["export_cents"], row["payroll_cents"], row["evidence_reference"],
            ) for row in content["months"]),
            content["company_history_reference"], content["activity_reference"],
            content["optant_reference"],
        )
        verify_issuer(snapshot["issuer_cnpj"], facts)
        rows = content["lines"]
        if not isinstance(rows, list) or len(rows) > 10000:
            raise FiscalValidationError("bounded reviewed revenue lines required")
        lines = tuple(RevenueLine(
            row["line_id"], row["cents"], Activity(row["activity"]), Market(row["market"]),
            FederalTreatment(row["federal"]), LocalTreatment(row["local"]),
            row["evidence_reference"], row["treatment_reference"],
        ) for row in rows)
        if content["basis"] != "accrual":
            raise FiscalValidationError("cash basis reconciliation not yet certified")
        if (
            content["domestic_cents"] > facts.months[-1].domestic_cents
            or content["export_cents"] > facts.months[-1].export_cents
        ):
            raise FiscalValidationError("unit revenue exceeds company totals")
        result = classify_revenue(
            competence, lines, domestic_cents=content["domestic_cents"],
            export_cents=content["export_cents"],
        )
        return {
            **result, "snapshot_id": snapshot["record_id"], "snapshot_version": snapshot["version"],
            "snapshot_digest": snapshot["digest"], "rule_id": rule["record_id"],
            "rule_version": rule["version"], "rule_digest": rule["digest"],
            "advisory_only": True,
        }
    except FiscalValidationError:
        # Preserve domain failures before handling malformed input (ValueError).
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid reviewed segregation evidence") from exc


def import_reviewed_segregation(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    competence: date, issuer: Cnpj, content: dict[str, Any],
    rule_id: str, rule_version: int, rule_content: dict[str, Any],
    verify_issuer: Callable[[str, SimplesFacts], None],
) -> dict[str, Any]:
    """Import atomically through T01; identical versions replay, conflicts fail.

    Trusted operational caller only. Review references are supplied by the
    responsible reviewer, not inferred by the classifier.
    """
    snapshot = {
        "record_id": snapshot_id, "version": snapshot_version,
        "competence": competence.isoformat(), "issuer_cnpj": issuer.value,
        "content": content, "digest": _digest(content)[1],
    }
    rule = {
        "record_id": rule_id, "version": rule_version, "tax_code": TAX_CODE,
        "valid_from": "2026-01-01", "valid_until": "2027-01-01",
        "jurisdiction": JURISDICTION, "normative_reference": NORMATIVE_REFERENCE,
        "content": rule_content, "digest": _digest(rule_content)[1],
    }
    result = _evaluate(snapshot, rule, verify_issuer=verify_issuer)
    old_snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    old_rule = store.record("fm_economy_benefits", rule_id, rule_version)
    for old, proposed in ((old_snapshot, snapshot), (old_rule, rule)):
        if old is not None and any(old.get(k) != v for k, v in proposed.items()):
            raise FiscalValidationError("immutable segregation input conflict; use new version")
    if old_snapshot is None:
        store.append_snapshot(
            record_id=snapshot_id, version=snapshot_version, competence=competence,
            issuer=issuer, content=content,
        )
    if old_rule is None:
        store.append_benefit(
            record_id=rule_id, version=rule_version, tax_code=TAX_CODE,
            jurisdiction=JURISDICTION, normative_reference=NORMATIVE_REFERENCE,
            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1), content=rule_content,
        )
    return result
