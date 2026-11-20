"""T06 reviewed scoped snapshot projection; never changes a fiscal value."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kordena_fiscal.application.simples_rtc_bridge import (
    NfseComparisonPlan,
    execute_nfse_comparisons,
    plan_nfse_comparisons,
    project_rtc_rates,
)
from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalProfile, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.tax.regimes import (
    SimplesIbsCbsElection,
    SimplesIbsCbsMode,
    SimplesOpeningOptionReceipt,
    SimplesRegularOptionReceipt2027H1,
    SimplesRegularOptionReceipt2027H2,
    SimplesRenunciationReceipt2027H2,
    resolve_simples_ibs_cbs_mode,
)
from kordena_fiscal.tax.rfb_regime_regular_calculator import RfbRegimeRegularCalculatorClient
from kordena_fiscal.tax.rfb_simples_calculator import RfbSimplesCalculatorClient
from kordena_fiscal.tax.simples_cash import reconcile_cash_detail, verify_cash_continuity
from kordena_fiscal.tax.simples_comparison import compare_assessment
from kordena_fiscal.tax.simples_nacional import (
    TRANSITION_PARTITION_DIGEST,
    Activity,
    MonthFacts,
    SimplesFacts,
)
from kordena_fiscal.tax.simples_segregation import (
    SOURCE,
    TRANSITION_SPECIAL_TAXES,
    TRANSITION_VERSION,
    VERSION,
    FederalTreatment,
    LocalTreatment,
    Market,
    RevenueLine,
    assess_segregated,
    classify_revenue,
)

SCHEMA = "nfcore.simples-segregation-facts/2026-v1"
TRANSITION_SCHEMA = "nfcore.simples-segregation-facts/2027-v1"
IssuerVerifier = Callable[[str, SimplesFacts], FiscalProfile | None]
TAX_CODE = "SIMPLES_SEGREGATION"
JURISDICTION = "BR"
NORMATIVE_REFERENCE = "CGSN140/2018 art.25"



def _verify_cash_history(
    store: EconomyStore, snapshot: dict[str, Any],
) -> None:
    try:
        _verify_cash_predecessor(store, snapshot)
    except FiscalValidationError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise FiscalValidationError("invalid reviewed cash history") from exc


def _verify_cash_predecessor(
    store: EconomyStore, snapshot: dict[str, Any],
) -> None:
    content = snapshot["content"]
    if content.get("basis") != "cash":
        return
    competence = date.fromisoformat(snapshot["competence"])
    register = content["cash_register"]
    if competence.month == 1 or competence == date.fromisoformat(content["opened_month"]):
        reference = register.get("opening_reference")
        if not isinstance(reference, str) or not reference.strip():
            raise FiscalValidationError("reviewed cash opening reference required")
        if competence == date.fromisoformat(content["opened_month"]) and any(
            date.fromisoformat(row["issued_on"]) < competence
            for row in register["installments"]
        ):
            raise FiscalValidationError("opening business cannot have historical installments")
        return
    ref = register.get("previous_snapshot")
    if not isinstance(ref, dict) or set(ref) != {"record_id", "version", "digest"}:
        raise FiscalValidationError("previous scoped cash snapshot required")
    previous = store.record("fm_economy_snapshots", ref["record_id"], ref["version"])
    month = date(competence.year, competence.month - 1, 1)
    if (previous is None or previous["digest"] != ref["digest"]
            or previous["issuer_cnpj"] != snapshot["issuer_cnpj"]
            or previous["competence"] != month.isoformat()
            or previous["content"].get("schema_version") != SCHEMA
            or previous["content"].get("basis") != "cash"
            or previous["content"].get("review_status") != "reviewed"):
        raise FiscalValidationError("previous scoped cash snapshot mismatch")
    if previous["content"]["cash_register"]["closing_event"] != "none":
        raise FiscalValidationError("cash register already closed")
    verify_cash_continuity(competence, register, previous["content"]["cash_register"])


def _reviewed_mode(
    profile: FiscalProfile | None, snapshot: dict[str, Any], competence: date,
    scope_identity: tuple[str, ...], facts: SimplesFacts,
) -> SimplesIbsCbsMode:
    if not isinstance(profile, FiscalProfile) or (
        tuple(profile.scope.identity_material) != scope_identity
        or profile.cnpj.value != snapshot["issuer_cnpj"]
    ):
        raise FiscalValidationError("canonical profile required for 2027 IBS/CBS election")
    evidence = snapshot["content"]["ibs_cbs_election"]

    def bound(raw: dict[str, Any]) -> None:
        if (raw["scope_identity"] != list(scope_identity)
                or raw["issuer_cnpj"] != snapshot["issuer_cnpj"]
                or (raw["profile_id"], raw["profile_version"]) != profile.snapshot_key
                or type(raw["profile_version"]) is not int
                or type(raw["crt"]) is not int
                or raw["crt"] != int(profile.tax_regime)):
            raise FiscalValidationError("reviewed IBS/CBS evidence scope/profile mismatch")

    bound(evidence)
    election = SimplesIbsCbsElection(
        scope=profile.scope, profile_id=evidence["profile_id"],
        profile_version=evidence["profile_version"], crt=TaxRegimeCode(evidence["crt"]),
        mode=SimplesIbsCbsMode(evidence["mode"]),
        effective_from=datetime.fromisoformat(evidence["effective_from"]),
        effective_to=(datetime.fromisoformat(evidence["effective_to"])
                      if evidence.get("effective_to") is not None else None),
        source_reference=evidence["source_reference"], version=evidence["version"],
    )
    receipt = None
    receipt_data = evidence.get("regular_option_receipt_2027_h1")
    if receipt_data is not None:
        bound(receipt_data)
        receipt = SimplesRegularOptionReceipt2027H1(
            scope=profile.scope, profile_id=receipt_data["profile_id"],
            profile_version=receipt_data["profile_version"], crt=TaxRegimeCode(receipt_data["crt"]),
            submitted_at=datetime.fromisoformat(receipt_data["submitted_at"]),
            confirmed_at=datetime.fromisoformat(receipt_data["confirmed_at"]),
            protocol_reference=receipt_data["protocol_reference"],
            cancelled_at=(datetime.fromisoformat(receipt_data["cancelled_at"])
                          if receipt_data.get("cancelled_at") is not None else None),
        )
    receipt_h2 = None
    raw_h2 = evidence.get("regular_option_receipt_2027_h2")
    if raw_h2 is not None:
        bound(raw_h2)
        receipt_h2 = SimplesRegularOptionReceipt2027H2(
            scope=profile.scope, profile_id=raw_h2["profile_id"],
            profile_version=raw_h2["profile_version"], crt=TaxRegimeCode(raw_h2["crt"]),
            confirmed_at=datetime.fromisoformat(raw_h2["confirmed_at"]),
            protocol_reference=raw_h2["protocol_reference"],
            submitted_at=(datetime.fromisoformat(raw_h2["submitted_at"])
                          if raw_h2.get("submitted_at") is not None else None),
            prior_protocol_reference=raw_h2.get("prior_protocol_reference"),
            cancelled_at=(datetime.fromisoformat(raw_h2["cancelled_at"])
                          if raw_h2.get("cancelled_at") is not None else None),
        )
    opening = None
    raw_opening = evidence.get("opening_receipt")
    if raw_opening is not None:
        bound(raw_opening)
        opening = SimplesOpeningOptionReceipt(
            scope=profile.scope, profile_id=raw_opening["profile_id"],
            profile_version=raw_opening["profile_version"],
            crt=TaxRegimeCode(raw_opening["crt"]),
            registered_on=date.fromisoformat(raw_opening["registered_on"]),
            submitted_at=datetime.fromisoformat(raw_opening["submitted_at"]),
            confirmed_at=datetime.fromisoformat(raw_opening["confirmed_at"]),
            protocol_reference=raw_opening["protocol_reference"],
            simples_protocol_reference=raw_opening["simples_protocol_reference"],
            registration_reference=raw_opening["registration_reference"],
            next_semester_cancelled_at=(
                datetime.fromisoformat(raw_opening["next_semester_cancelled_at"])
                if raw_opening.get("next_semester_cancelled_at") is not None else None
            ),
            cancellation_reference=raw_opening.get("cancellation_reference"),
        )
        if opening.registered_on != facts.registered_on:
            raise FiscalValidationError("opening option does not match reviewed registration")
    if facts.registered_on is not None:
        registration_ref = snapshot["content"].get("registration_reference")
        if (not isinstance(registration_ref, str) or not registration_ref.strip()
                or opening is not None and registration_ref != opening.registration_reference):
            raise FiscalValidationError("reviewed registration evidence required")
    renunciation = None
    raw_renunciation = evidence.get("renunciation_receipt_2027_h2")
    if raw_renunciation is not None:
        bound(raw_renunciation)
        renunciation = SimplesRenunciationReceipt2027H2(
            scope=profile.scope, profile_id=raw_renunciation["profile_id"],
            profile_version=raw_renunciation["profile_version"],
            crt=TaxRegimeCode(raw_renunciation["crt"]),
            submitted_at=datetime.fromisoformat(raw_renunciation["submitted_at"]),
            confirmed_at=datetime.fromisoformat(raw_renunciation["confirmed_at"]),
            protocol_reference=raw_renunciation["protocol_reference"],
            prior_protocol_reference=raw_renunciation["prior_protocol_reference"],
            cancelled_at=(datetime.fromisoformat(raw_renunciation["cancelled_at"])
                          if raw_renunciation.get("cancelled_at") is not None else None),
        )
    if election.mode is SimplesIbsCbsMode.SIMPLES_UNIFIED:
        active_receipt = receipt if competence.month <= 6 else receipt_h2
        if active_receipt is not None and active_receipt.cancelled_at is None:
            raise FiscalValidationError("unresolved regular option conflicts with unified mode")
        if evidence.get("refund_restriction_clear") is not True:
            raise FiscalValidationError("reviewed CGSN art. 40-E eligibility required")
    start = datetime.combine(competence, time.min, tzinfo=ZoneInfo("America/Sao_Paulo"))
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    if facts.registered_on is not None and facts.opened_month == competence:
        start = datetime.combine(facts.registered_on, time.min, tzinfo=start.tzinfo)
        if election.effective_from.astimezone(start.tzinfo).date() > facts.registered_on:
            raise FiscalValidationError("opening election does not cover registration date")
        start = max(start, profile.effective_from)
        if opening is not None:
            start = max(start, opening.confirmed_at)
        if start >= end:
            raise FiscalValidationError("opening option confirmed outside competence")
    modes = {
        resolve_simples_ibs_cbs_mode(
            profile, (election,), instant, regular_option_receipt_2027_h1=receipt,
            regular_option_receipt_2027_h2=receipt_h2,
            opening_receipt=opening, renunciation_receipt=renunciation,
        ) for instant in (start, end - timedelta(microseconds=1))
    }
    if len(modes) != 1:
        raise FiscalValidationError("IBS/CBS option does not cover the complete competence")
    return modes.pop()


def _transition_treatments(row: dict[str, Any]) -> tuple[str, ...]:
    treatments = row["transition_treatments"]
    if not isinstance(treatments, dict) or set(treatments) != set(TRANSITION_SPECIAL_TAXES):
        raise FiscalValidationError("complete per-tax transition classification required")
    if any(not isinstance(value, str) for value in treatments.values()):
        raise FiscalValidationError("invalid transition classification")
    return tuple(treatments[tax] for tax in TRANSITION_SPECIAL_TAXES)


def evaluate_segregation(
    store: EconomyStore, *, snapshot_id: str, snapshot_version: int,
    rule_id: str, rule_version: int, verify_issuer: IssuerVerifier,
    assessment: bool = False,
    rtc_simples: RfbSimplesCalculatorClient | None = None,
    rtc_regular: RfbRegimeRegularCalculatorClient | None = None,
) -> dict[str, Any]:
    snapshot = store.record("fm_economy_snapshots", snapshot_id, snapshot_version)
    rule = store.record("fm_economy_benefits", rule_id, rule_version)
    if snapshot is None or rule is None:
        raise FiscalValidationError("scoped segregation evidence unavailable")
    _verify_cash_history(store, snapshot)
    return _evaluate(
        snapshot, rule, verify_issuer=verify_issuer, assessment=assessment,
        scope_identity=store.scope_identity, rtc_simples=rtc_simples, rtc_regular=rtc_regular,
    )


def _evaluate(
    snapshot: dict[str, Any], rule: dict[str, Any], *,
    verify_issuer: IssuerVerifier, scope_identity: tuple[str, ...],
    assessment: bool = False,
    rtc_simples: RfbSimplesCalculatorClient | None = None,
    rtc_regular: RfbRegimeRegularCalculatorClient | None = None,
) -> dict[str, Any]:
    try:
        content = snapshot["content"]
        policy = rule["content"]
        competence = date.fromisoformat(snapshot["competence"])
        end = date(competence.year + (competence.month == 12), competence.month % 12 + 1, 1)
        transition = competence.year == 2027
        if competence.year not in {2026, 2027}:
            raise FiscalValidationError("unsupported segregation competence")
        if (
            content["schema_version"] != (TRANSITION_SCHEMA if transition else SCHEMA)
            or content["review_status"] != "reviewed"
            or not isinstance(content["review_reference"], str)
            or not content["review_reference"].strip()
            or policy["review_status"] != "reviewed"
            or policy["engine_version"] != (TRANSITION_VERSION if transition else VERSION)
            or transition and policy.get("engine_partition_digest") != TRANSITION_PARTITION_DIGEST
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
            date.fromisoformat(content["registered_on"]) if "registered_on" in content else None,
        )
        profile = verify_issuer(snapshot["issuer_cnpj"], facts)
        mode = (
            _reviewed_mode(profile, snapshot, competence, scope_identity, facts)
            if transition else None
        )
        if transition and content["basis"] != "accrual":
            raise FiscalValidationError("cash recognition unavailable from 2027")
        if not transition and "ibs_cbs_election" in content:
            raise FiscalValidationError("IBS/CBS election is not a 2026 assessment input")
        rows = content["lines"]
        if not isinstance(rows, list) or len(rows) > 10000:
            raise FiscalValidationError("bounded reviewed revenue lines required")
        lines = tuple(RevenueLine(
            row["line_id"], row["cents"], Activity(row["activity"]), Market(row["market"]),
            FederalTreatment(row["federal"]), LocalTreatment(row["local"]),
            row["evidence_reference"], row["treatment_reference"],
            _transition_treatments(row) if transition or "transition_treatments" in row else None,
        ) for row in rows)
        cash = content["basis"] == "cash"
        if content["basis"] not in {"cash", "accrual"}:
            raise FiscalValidationError("unknown recognition basis")
        if (
            content["domestic_cents"] > facts.months[-1].domestic_cents
            or content["export_cents"] > facts.months[-1].export_cents
        ):
            raise FiscalValidationError("unit revenue exceeds company totals")
        result = classify_revenue(
            competence, lines, domestic_cents=content["domestic_cents"],
            export_cents=content["export_cents"],
        )
        if cash:
            cash_lines, reconciliation, outstanding = reconcile_cash_detail(
                competence, content["cash_register"],
            )
            if reconciliation["accrued"] != content["domestic_cents"] + content["export_cents"]:
                raise FiscalValidationError("cash accrual total does not reconcile")
            accrued_groups: dict[tuple[str, ...], int] = {}
            for row in content["cash_register"]["installments"]:
                if date.fromisoformat(row["issued_on"]) >= competence:
                    key = tuple(row[k] for k in ("activity", "market", "federal", "local"))
                    accrued_groups[key] = accrued_groups.get(key, 0) + row["principal_cents"]
            classified_groups: dict[tuple[str, ...], int] = {}
            for line in lines:
                key = (line.activity.value, line.market.value, line.federal.value, line.local.value)
                classified_groups[key] = classified_groups.get(key, 0) + line.cents
            if result["status"] != "classified" or accrued_groups != classified_groups:
                raise FiscalValidationError("cash and accrual classifications do not reconcile")
            domestic = sum(line.cents for line in cash_lines if line.market is Market.DOMESTIC)
            exported = sum(line.cents for line in cash_lines if line.market is Market.EXPORT)
            if assessment:
                result = assess_segregated(
                    facts, cash_lines, domestic_cents=domestic, export_cents=exported, cash=True,
                    cash_closing_event=content["cash_register"]["closing_event"],
                    local_outstanding=outstanding,
                )
            result = {**result, "cash_reconciliation": reconciliation}
        elif assessment:
            result = assess_segregated(
                facts, lines, domestic_cents=content["domestic_cents"],
                export_cents=content["export_cents"], mode=mode,
            )
        if assessment and transition and isinstance(profile, FiscalProfile):
            local = result.get("local_direct_collection")
            if result.get("status") == "estimated" and isinstance(local, dict) and (
                (local.get("status") == "outside_das") != (int(profile.tax_regime) == 2)
            ):
                raise FiscalValidationError("reviewed sublimite conflicts with canonical CRT")
        plans: tuple[NfseComparisonPlan, ...] = ()
        if "rtc_nfse_operations" in content:
            if not transition or mode is None:
                raise FiscalValidationError("RTC NFS-e comparison requires reviewed 2027 mode")
            if result.get("status") not in {"classified", "estimated"}:
                raise FiscalValidationError("RTC comparison requires valid classification")
            plans = plan_nfse_comparisons(facts, lines, mode, content["rtc_nfse_operations"])
        if assessment and transition and result.get("status") == "estimated":
            if mode is None:
                raise FiscalValidationError("reviewed IBS/CBS mode required")
            result = {**result, "rtc_projection": project_rtc_rates(facts, lines, mode)}
        if assessment:
            # Bind even zero-activity/blocked assessments to the complete reviewed
            # inputs and canonical transaction scope, without a recursive digest.
            facts_payload = {k: v for k, v in content.items() if k != "pgdas_reference"}
            result = {**result, "digest": _digest({
                "engine_digest": result["digest"],
                "rtc_projection": result.get("rtc_projection"),
                "scope": list(scope_identity),
                "issuer": snapshot["issuer_cnpj"],
                "competence": snapshot["competence"],
                "facts_digest": _digest(facts_payload)[1],
                "rule_digest": rule["digest"],
                "rule_valid_from": rule["valid_from"],
                "rule_valid_until": rule["valid_until"],
            })[1]}
        if assessment and "pgdas_reference" in content and "segregation_digest" in result:
            result = {**result, "pgdas_comparison": compare_assessment(
                result, content["pgdas_reference"],
                segregation_digest=str(result["segregation_digest"]),
                competence=competence.isoformat(),
            )}
        if assessment and transition and result.get("status") == "estimated":
            result = {**result, "rtc_nfse_comparison": execute_nfse_comparisons(
                plans, rtc_simples, rtc_regular,
            )}
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
    verify_issuer: IssuerVerifier,
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
    transition = competence.year == 2027
    valid_from = date(2027 if transition else 2026, 1, 1)
    valid_until = date(valid_from.year + 1, 1, 1)
    normative = "CGSN190/2026 art.21-26" if transition else NORMATIVE_REFERENCE
    rule = {
        "record_id": rule_id, "version": rule_version, "tax_code": TAX_CODE,
        "valid_from": valid_from.isoformat(), "valid_until": valid_until.isoformat(),
        "jurisdiction": JURISDICTION, "normative_reference": normative,
        "content": rule_content, "digest": _digest(rule_content)[1],
    }
    result = _evaluate(
        snapshot, rule, verify_issuer=verify_issuer, scope_identity=store.scope_identity,
    )
    _verify_cash_history(store, snapshot)
    # Validate optional comparison evidence before inserting immutable records.
    if "pgdas_reference" in content:
        assessment_result = _evaluate(
            snapshot, rule, verify_issuer=verify_issuer, assessment=True,
            scope_identity=store.scope_identity,
        )
        if assessment_result.get("pgdas_comparison", {}).get("status") not in {
            "match", "divergent",
        }:
            raise FiscalValidationError("PGDAS comparison requires an estimated assessment")
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
            jurisdiction=JURISDICTION, normative_reference=normative,
            valid_from=valid_from, valid_until=valid_until, content=rule_content,
        )
    return result
