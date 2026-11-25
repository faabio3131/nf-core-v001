"""Persist T17 estimates in the existing scoped T01 snapshot store."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from typing import Any

from kordena_fiscal.application.historical_audit import (
    MAX_INPUT_BYTES,
    SOURCE_CHUNK_BYTES,
    TABLE,
    record_id,
    source_bundle,
)
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.historical_audit import IssuerContext, analyze_month, closed_months
from kordena_fiscal.tax.tax_recovery import (
    SCHEMA,
    RecoveryBatch,
    estimate,
    invoice_dates,
    selic_reference,
)
from kordena_fiscal.tax.unused_credits import Batch, detect

SOURCE_SCHEMA = "nfcore.tax-recovery-source/v1"
PAGE_SCHEMA = "nfcore.tax-recovery-page/v1"


def _raw(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _children(
    store: EconomyStore, row: dict[str, Any], kind: str, schema: str
) -> list[dict[str, Any]]:
    result = []
    content = row["content"]
    for index, ref in enumerate(content[f"{kind}_refs"]):
        key = f"{row['record_id']}-{kind}-{index}"
        child = store.record(TABLE, key, row["version"])
        if (
            child is None
            or ref != {"record_id": key, "version": row["version"], "digest": child["digest"]}
            or child["issuer_cnpj"] != row["issuer_cnpj"]
            or child["competence"] != row["competence"]
            or child["content"]["schema_version"] != schema
            or child["content"]["input_sha256"] != content["input_sha256"]
        ):
            raise FiscalValidationError("T16 child integrity mismatch")
        result.append(child["content"])
    return result


def _verified_t16(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    facts: RecoveryBatch,
    context: IssuerContext,
    as_of: date,
) -> tuple[Batch, list[dict[str, Any]], dict[str, Any]]:
    key = f"unused-credits-{issuer.value}-{period.isoformat()}"
    row = store.record(TABLE, key)
    if (
        row is None
        or row["version"] != facts.t16_version
        or row["digest"] != facts.t16_digest
        or row["issuer_cnpj"] != issuer.value
        or row["competence"] != period.isoformat()
    ):
        raise FiscalValidationError("current scoped T16 snapshot required")
    index = row["content"]
    if (
        index["schema_version"] != "nfcore.unused-credits/v1"
        or index["issuer_context"] != context.model_dump()
        or index["as_of"] != as_of.isoformat()
        or index["credit_recognized"] is not False
    ):
        raise FiscalValidationError("T16 context or cutoff changed; refresh T16")
    raw = b"".join(
        base64.b64decode(part["data_b64"], validate=True)
        for part in _children(store, row, "source", "nfcore.unused-credit-source/v1")
    )
    if len(raw) > MAX_INPUT_BYTES or hashlib.sha256(raw).hexdigest() != index["input_sha256"]:
        raise FiscalValidationError("T16 original source digest mismatch")
    batch = Batch.model_validate_json(raw)
    if batch.competence != period.isoformat():
        raise FiscalValidationError("T16 source competence mismatch")
    computed = detect(batch, issuer, context, as_of)
    findings = computed.pop("findings")
    stored = [
        finding
        for page in _children(store, row, "page", "nfcore.unused-credit-page/v1")
        for finding in page["findings"]
    ]
    if (
        stored != findings
        or index["finding_count"] != len(findings)
        or any(index.get(key) != value for key, value in computed.items())
    ):
        raise FiscalValidationError("T16 candidate recomputation mismatch")
    return batch, findings, index


def _payments(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    context: IssuerContext,
    as_of: date,
    t16: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    historical = store.record(TABLE, record_id(issuer, period))
    if t16["historical_digest"] is None:
        if historical is not None:
            raise FiscalValidationError("historical snapshot changed; refresh T16")
        return {}
    if (
        historical is None
        or historical["digest"] != t16["historical_digest"]
        or historical["issuer_cnpj"] != issuer.value
        or historical["competence"] != period.isoformat()
        or historical["content"]["issuer_context"] != context.model_dump()
        or historical["content"]["schema_version"] != "nfcore.historical-audit/v1"
    ):
        raise FiscalValidationError("historical snapshot changed; refresh T16")
    original = source_bundle(store, issuer, period, historical)
    report = analyze_month(original, issuer, period, context, as_of=as_of)
    if historical["content"]["as_of"] != as_of.isoformat():
        return {}
    if original.collection != "direct" or original.regime == "simples_nacional":
        return {}
    # A positive T15 undue-payment candidate may overlap T16. Do not attribute
    # another amount until the separate assessment has no existing difference.
    if any(
        historical["content"].get(name) != report[name]
        for name in ("groups", "receipts", "competence", "credit_recognized", "realized_cents")
    ):
        raise FiscalValidationError("T15 payment recomputation mismatch")
    taxes = {
        group["tax"]: group
        for group in report["groups"]
        if group["status"] == "no_difference" and group["paid_candidate_cents"] == 0
    }
    # No inferred split between multiple payments: require one fully reconciled
    # receipt for each supported tax component.
    payment_counts = {
        tax: sum(1 for payment in original.payments if payment.allocations.get(tax, 0) > 0)
        for tax in taxes
    }
    receipts = {row["receipt_id"]: row for row in report["receipts"]}
    return {
        (payment.receipt_id, tax): {
            "receipt_id": payment.receipt_id,
            "paid_on": payment.paid_on,
            "sha256": receipts[payment.receipt_id]["sha256"],
            "allocated_cents": amount,
            "historical_digest": historical["digest"],
            "assessment_reference": taxes[tax]["assessment_reference"],
        }
        for payment in original.payments
        for tax, amount in payment.allocations.items()
        if tax in taxes
        and tax in {"pis", "cofins"}
        and amount > 0
        and payment_counts[tax] == 1
        and amount == taxes[tax]["reviewed_due_cents"]
    }


def import_recovery(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    version: int,
    facts: RecoveryBatch,
    *,
    context: IssuerContext,
    as_of: date,
) -> dict[str, Any]:
    if (
        store.scope_identity[-1] != "homologation"
        or facts.competence != period.isoformat()
        or type(version) is not int
        or not 1 <= version <= 2147483647
    ):
        raise FiscalValidationError("invalid non-production recovery scope or version")
    closed_months(period, as_of)
    raw = _raw(facts.model_dump())
    if len(raw) > MAX_INPUT_BYTES:
        raise FiscalValidationError("recovery source exceeds maximum size")
    key = f"tax-recovery-{issuer.value}-{period.isoformat()}"
    # The existing scope lock also serializes T15/T16 evidence changes.
    store.lock_state_review_import(key, key)
    batch, findings, index = _verified_t16(store, issuer, period, facts, context, as_of)
    payments = _payments(store, issuer, period, context, as_of, index)
    report = estimate(facts, issuer, context, as_of, findings, invoice_dates(batch), payments)
    fingerprint = hashlib.sha256(raw).hexdigest()
    binding = {
        "schema_version": SCHEMA,
        "competence": facts.competence,
        "recipient": issuer.value,
        "as_of": as_of.isoformat(),
        "issuer_context": context.model_dump(),
        "input_sha256": fingerprint,
        "t16_version": facts.t16_version,
        "t16_digest": facts.t16_digest,
        "historical_digest": index["historical_digest"],
        "selic": selic_reference(),
        "advisory_only": True,
        "credit_recognized": False,
        "realized_cents": None,
    }
    previous = store.record(TABLE, key)
    if previous is not None and previous["version"] == version:
        if any(previous["content"].get(k) != v for k, v in binding.items()):
            raise FiscalValidationError("immutable recovery version conflict")
        return {"version": version, "snapshot_digest": previous["digest"], "replay": True}
    if version != (previous["version"] + 1 if previous else 1):
        raise FiscalValidationError("expected next recovery version")

    def append(name: str, content: dict[str, Any]) -> dict[str, Any]:
        digest = store.append_snapshot(
            record_id=name, version=version, competence=period, issuer=issuer, content=content
        )
        return {"record_id": name, "version": version, "digest": digest}

    sources = [
        append(
            f"{key}-source-{offset // SOURCE_CHUNK_BYTES}",
            {
                "schema_version": SOURCE_SCHEMA,
                "input_sha256": fingerprint,
                "data_b64": base64.b64encode(raw[offset : offset + SOURCE_CHUNK_BYTES]).decode(),
            },
        )
        for offset in range(0, len(raw), SOURCE_CHUNK_BYTES)
    ]
    pages = [
        append(
            f"{key}-page-{offset // 100}",
            {
                "schema_version": PAGE_SCHEMA,
                "input_sha256": fingerprint,
                "findings": report[offset : offset + 100],
            },
        )
        for offset in range(0, len(report), 100)
    ]
    totals: dict[str, dict[str, int]] = {}
    counts: dict[str, int] = {}
    for row in report:
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1
        if status == "potential":
            total = totals.setdefault(row["tax"], {})
            for name in ("principal_cents", "adjustment_cents", "estimated_cents"):
                total[name] = total.get(name, 0) + row[name]
    result = append(
        key,
        binding
        | {
            "source_refs": sources,
            "page_refs": pages,
            "finding_count": len(report),
            "status_counts": counts,
            "partial_totals_cents": totals,
        },
    )
    return {
        "version": version,
        "snapshot_digest": result["digest"],
        "replay": False,
        "finding_count": len(report),
        "status_counts": counts,
    }
