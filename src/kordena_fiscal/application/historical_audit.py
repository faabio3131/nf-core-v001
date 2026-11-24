"""Persist T15 evidence and derived item findings in the existing T01 store.

The immutable monthly index points to exact versions/digests of source chunks
and finding pages. No credit, benefit, payment or ledger writes occur here.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from datetime import date
from typing import Any

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.tax.historical_audit import (
    SCHEMA,
    TAXES,
    IssuerContext,
    Month,
    analyze_month,
    closed_months,
)

SOURCE_SCHEMA = "nfcore.historical-audit-source-chunk/v1"
PAGE_SCHEMA = "nfcore.historical-audit-finding-page/v1"
TABLE = "fm_economy_snapshots"
SOURCE_CHUNK_BYTES = 262144
MAX_INPUT_BYTES = 32 * 1024 * 1024
PAGE_SIZE = 100


def record_id(issuer: Cnpj, period: date) -> str:
    return f"historical-audit-{issuer.value}-{period.isoformat()}"


def _source(facts: Month) -> bytes:
    raw = json.dumps(
        facts.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES:
        raise FiscalValidationError("historical monthly bundle exceeds 32 MiB")
    return raw


def _append(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    name: str,
    version: int,
    content: dict[str, Any],
) -> dict[str, Any]:
    digest = store.append_snapshot(
        record_id=name, version=version, competence=period, issuer=issuer, content=content
    )
    return {"record_id": name, "version": version, "digest": digest}


def import_month(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    version: int,
    facts: Month,
    *,
    context: IssuerContext,
    as_of: date,
) -> dict[str, Any]:
    closed_months(period, as_of)
    if type(version) is not int or not 1 <= version <= 2147483647:
        raise FiscalValidationError("invalid historical version")
    key = record_id(issuer, period)
    raw = _source(facts)
    input_digest = hashlib.sha256(raw).hexdigest()
    store.lock_state_review_import(key, key)
    existing = store.record(TABLE, key)
    if existing is not None and (
        existing["issuer_cnpj"] != issuer.value
        or existing["competence"] != period.isoformat()
        or existing["content"].get("schema_version") != SCHEMA
    ):
        raise FiscalValidationError("historical index identity mismatch")
    if existing is not None and existing["version"] == version:
        if (
            existing["content"]["input_sha256"] != input_digest
            or existing["content"]["issuer_context"] != context.model_dump()
        ):
            raise FiscalValidationError("immutable historical version conflict")
        return {"snapshot_digest": existing["digest"], "version": version, "replay": True}
    if version != (existing["version"] + 1 if existing else 1):
        raise FiscalValidationError("expected next immutable historical version")
    report = analyze_month(facts, issuer, period, context, as_of=as_of)
    source_refs = []
    for i in range(0, len(raw), SOURCE_CHUNK_BYTES):
        part = raw[i : i + SOURCE_CHUNK_BYTES]
        chunk = i // SOURCE_CHUNK_BYTES
        source_refs.append(
            _append(
                store,
                issuer,
                period,
                f"{key}-source-{chunk}",
                version,
                {
                    "schema_version": SOURCE_SCHEMA,
                    "review_status": "reviewed",
                    "index": chunk,
                    "input_sha256": input_digest,
                    "data_b64": base64.b64encode(part).decode("ascii"),
                    "sha256": hashlib.sha256(part).hexdigest(),
                },
            )
        )
    rows: list[dict[str, Any]] = []
    for document in report.pop("documents"):
        header = {k: v for k, v in document.items() if k != "findings"}
        if document["findings"]:
            rows.extend(header | item for item in document["findings"])
        else:
            rows.append(
                header
                | {"item_number": None, "tax": None, "reason": "document_" + document["status"]}
            )
    page_refs = []
    for i in range(0, len(rows), PAGE_SIZE):
        page = i // PAGE_SIZE
        page_refs.append(
            _append(
                store,
                issuer,
                period,
                f"{key}-page-{page}",
                version,
                {
                    "schema_version": PAGE_SCHEMA,
                    "review_status": "reviewed",
                    "index": page,
                    "input_sha256": input_digest,
                    "rows": rows[i : i + PAGE_SIZE],
                },
            )
        )
    report.update(
        {
            "review_status": "reviewed",
            "input_sha256": input_digest,
            "issuer_context": context.model_dump(),
            "as_of": as_of.isoformat(),
            "source_refs": source_refs,
            "page_refs": page_refs,
            "finding_count": len(rows),
        }
    )
    ref = _append(store, issuer, period, key, version, report)
    return {
        "snapshot_digest": ref["digest"],
        "version": version,
        "replay": False,
        "document_count": report["document_count"],
        "item_count": report["item_count"],
    }


def _index(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
) -> dict[str, Any] | None:
    row = store.unique_monthly_snapshot(issuer.value, period, SCHEMA)
    if row is None:
        return None
    if row["record_id"] != record_id(issuer, period):
        raise FiscalValidationError("unexpected historical index identity")
    data = row["content"]
    if (
        data["competence"] != period.isoformat()
        or data["schema_version"] != SCHEMA
        or [group["tax"] for group in data["groups"]] != list(TAXES)
        or data["credit_recognized"] is not False
        or data["realized_cents"] is not None
        or len(data["page_refs"]) != (data["finding_count"] + PAGE_SIZE - 1) // PAGE_SIZE
    ):
        raise FiscalValidationError("invalid historical index")
    return row


def _ref_content(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    row: dict[str, Any],
    *,
    kind: str,
    index: int,
) -> dict[str, Any]:
    payload = row["content"]
    refs = payload["source_refs" if kind == "source" else "page_refs"]
    if type(index) is not int or not 0 <= index < len(refs):
        raise FiscalValidationError("invalid historical page or source index")
    ref = refs[index]
    expected = f"{row['record_id']}-{kind}-{index}"
    child = store.record(TABLE, expected, row["version"])
    if (
        child is None
        or ref["record_id"] != expected
        or ref["version"] != row["version"]
        or ref["digest"] != child["digest"]
        or child["issuer_cnpj"] != issuer.value
        or child["competence"] != period.isoformat()
        or child["content"]["schema_version"]
        != (SOURCE_SCHEMA if kind == "source" else PAGE_SCHEMA)
        or child["content"]["index"] != index
        or child["content"]["input_sha256"] != payload["input_sha256"]
    ):
        raise FiscalValidationError("historical child integrity mismatch")
    return dict(child["content"])


def source_bundle(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    row: dict[str, Any],
) -> Month:
    """Restricted engineering/reviewer reconstruction, never a browser endpoint."""
    chunks = []
    for i in range(len(row["content"]["source_refs"])):
        part = _ref_content(store, issuer, period, row, kind="source", index=i)
        data = base64.b64decode(part["data_b64"], validate=True)
        if hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise FiscalValidationError("historical source chunk integrity mismatch")
        chunks.append(data)
    raw = b"".join(chunks)
    if (
        len(raw) > MAX_INPUT_BYTES
        or hashlib.sha256(raw).hexdigest() != row["content"]["input_sha256"]
    ):
        raise FiscalValidationError("historical source digest mismatch")
    return Month.model_validate_json(raw)


def window_report(
    store: EconomyStore,
    issuer: Cnpj,
    end: date,
    today: date,
    profiles: dict[date, IssuerContext | None],
) -> tuple[dict[str, Any], dict[date, dict[str, Any]]]:
    periods = closed_months(end, today)
    months: list[dict[str, Any]] = []
    indexed: dict[date, dict[str, Any]] = {}
    ids: Counter[str] = Counter()
    hashes: Counter[str] = Counter()
    for period in periods:
        profile = profiles.get(period)
        row = _index(store, issuer, period) if profile is not None else None
        if row is None:
            months.append(
                {
                    "competence": period.isoformat(),
                    "status": "issuer_history_unavailable" if profile is None else "missing",
                    "snapshot": None,
                    "groups": [],
                    "document_count": None,
                    "item_count": None,
                    "finding_count": None,
                    "pages": 0,
                }
            )
            continue
        content = row["content"]
        if profile is None or content["issuer_context"] != profile.model_dump():
            months.append(
                {
                    "competence": period.isoformat(),
                    "status": "issuer_history_changed",
                    "snapshot": None,
                    "groups": [],
                    "document_count": None,
                    "item_count": None,
                    "finding_count": None,
                    "pages": 0,
                }
            )
            continue
        indexed[period] = row
        for receipt in content["receipts"]:
            ids[receipt["receipt_id"]] += 1
            hashes[receipt["sha256"]] += 1
        groups = [dict(group) for group in content["groups"]]
        months.append(
            {
                "competence": period.isoformat(),
                "status": "reviewed_scope"
                if all(g["reconciled"] for g in groups)
                else "insufficient_basis",
                "snapshot": {k: row[k] for k in ("record_id", "version", "digest")},
                "review_reference": content["review_reference"],
                "coverage_reference": content["coverage_reference"],
                "as_of": content["as_of"],
                "issuer_context": content["issuer_context"],
                "groups": groups,
                "document_count": content["document_count"],
                "item_count": content["item_count"],
                "finding_count": content["finding_count"],
                "pages": len(content["page_refs"]),
            }
        )
    totals = {tax: {"classified_months": 0, "paid_candidate_cents": 0} for tax in TAXES}
    for month in months:
        row = indexed.get(date.fromisoformat(month["competence"]))
        if row is None:
            continue
        duplicate = any(
            ids[x["receipt_id"]] > 1 or hashes[x["sha256"]] > 1 for x in row["content"]["receipts"]
        )
        month["duplicate_receipt_in_window"] = duplicate
        for group in month["groups"]:
            if duplicate:
                group["status"] = "duplicate_receipt_in_window"
                group["paid_candidate_cents"] = None
            if group["paid_candidate_cents"] is not None:
                totals[group["tax"]]["classified_months"] += 1
                totals[group["tax"]]["paid_candidate_cents"] += group["paid_candidate_cents"]
    for values in totals.values():
        if values["classified_months"] == 0:
            values["paid_candidate_cents"] = None  # type: ignore[assignment]
    reviewed = sum(m["status"] == "reviewed_scope" for m in months)
    return (
        {
            "schema_version": SCHEMA,
            "window_start": periods[0].isoformat(),
            "window_end": end.isoformat(),
            "competences": 60,
            "reviewed_months": reviewed,
            "available_months": len(indexed),
            "status": "reviewed_scope" if reviewed == 60 else "partial_basis",
            "months": months,
            "partial_totals_by_tax": totals,
            "advisory_only": True,
            "credit_recognized": False,
            "realized_cents": None,
        },
        indexed,
    )


def finding_page(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    row: dict[str, Any],
    month: dict[str, Any],
    page: int,
    expected_digest: str,
) -> dict[str, Any]:
    if row["digest"] != expected_digest:
        raise FiscalValidationError("historical snapshot changed")
    child = _ref_content(store, issuer, period, row, kind="page", index=page)
    rows = [dict(x) for x in child["rows"]]
    if month.get("duplicate_receipt_in_window"):
        for finding in rows:
            if finding.get("paid_candidate_cents") is not None:
                finding["paid_candidate_cents"] = None
                finding["status"] = "assessment_difference_payment_unconfirmed"
    return {
        "competence": period.isoformat(),
        "snapshot": month["snapshot"],
        "page": page,
        "next_page": page + 1 if page + 1 < month["pages"] else None,
        "rows": rows,
        "advisory_only": True,
        "credit_recognized": False,
    }
