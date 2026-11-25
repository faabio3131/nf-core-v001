"""Reviewed non-production credit detection stored as immutable T01 evidence."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from kordena_fiscal.application.historical_audit import (
    MAX_INPUT_BYTES,
    SOURCE_CHUNK_BYTES,
    TABLE,
    record_id,
    source_bundle,
)
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.tax.historical_audit import IssuerContext, analyze_month
from kordena_fiscal.tax.unused_credits import Batch, detect


@dataclass(frozen=True)
class VerifiedCreditUnit:
    """Internal scoped result of the canonical historical CNPJ uniqueness query.

    Not an authentication token; obtain immediately before each service transaction.
    """

    scope_identity: tuple[str, ...]
    issuer: Cnpj

    def require(self, scope_identity: tuple[str, ...], issuer: Cnpj) -> None:
        if self.scope_identity != scope_identity or self.issuer != issuer:
            raise FiscalValidationError("verified credit recipient scope mismatch")


def verify_credit_unit(
    db: PostgresFiscalDatabase, scope: ExecutionScope, issuer: Cnpj
) -> VerifiedCreditUnit:
    """An issuer shared by multiple historic unit profiles needs allocation review."""
    with db.connection() as conn:
        rows = conn.execute(
            """SELECT DISTINCT unit_id FROM fm_control_plane_fiscal_profiles
               WHERE host_namespace=? AND tenant_id=? AND environment=? AND cnpj=?
               LIMIT 2""",
            (scope.host_namespace, scope.tenant_id, scope.environment.value, issuer.value),
        ).fetchall()
    if len(rows) != 1 or rows[0][0] != scope.unit_id:
        raise FiscalValidationError("ambiguous credit recipient unit")
    return VerifiedCreditUnit(scope.identity_material, issuer)


def import_credits(
    store: EconomyStore,
    issuer: Cnpj,
    period: date,
    version: int,
    facts: Batch,
    *,
    context: IssuerContext,
    as_of: date,
) -> dict[str, Any]:
    if period.isoformat() != facts.competence or type(version) is not int or version < 1:
        raise FiscalValidationError("invalid unused-credit period/version")
    raw = json.dumps(facts.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_INPUT_BYTES:
        raise FiscalValidationError("unused-credit source exceeds maximum size")
    key = f"unused-credits-{issuer.value}-{period.isoformat()}"
    historical_id = record_id(issuer, period)
    store.lock_state_review_import(historical_id, historical_id)
    store.lock_state_review_import(key, key)
    historical = store.record(TABLE, historical_id)
    historical_digest = None
    if historical is not None:
        if historical["content"]["issuer_context"] != context.model_dump():
            raise FiscalValidationError("historical issuer context changed")
        prior = source_bundle(store, issuer, period, historical)
        # Rebuild the historical output from original source bytes before linking it.
        analyze_month(prior, issuer, period, context, as_of=as_of)
        historical_digest = historical["digest"]
    fingerprint = hashlib.sha256(raw).hexdigest()
    previous = store.record(TABLE, key)
    binding = {
        "input_sha256": fingerprint,
        "historical_digest": historical_digest,
        "issuer_context": context.model_dump(),
        "as_of": as_of.isoformat(),
    }
    if previous is not None and previous["version"] == version:
        if any(previous["content"].get(k) != v for k, v in binding.items()):
            raise FiscalValidationError("immutable unused-credit version conflict")
        return {"version": version, "snapshot_digest": previous["digest"], "replay": True}
    if version != (previous["version"] + 1 if previous else 1):
        raise FiscalValidationError("expected next unused-credit version")
    report = detect(facts, issuer, context, as_of)
    sources: list[dict[str, Any]] = []
    for offset in range(0, len(raw), SOURCE_CHUNK_BYTES):
        part = raw[offset : offset + SOURCE_CHUNK_BYTES]
        child = f"{key}-source-{len(sources)}"
        digest = store.append_snapshot(
            record_id=child,
            version=version,
            competence=period,
            issuer=issuer,
            content={
                "schema_version": "nfcore.unused-credit-source/v1",
                "input_sha256": fingerprint,
                "data_b64": base64.b64encode(part).decode(),
            },
        )
        sources.append({"record_id": child, "version": version, "digest": digest})
    pages: list[dict[str, Any]] = []
    findings = report.pop("findings")
    for offset in range(0, len(findings), 100):
        child = f"{key}-page-{len(pages)}"
        digest = store.append_snapshot(
            record_id=child,
            version=version,
            competence=period,
            issuer=issuer,
            content={
                "schema_version": "nfcore.unused-credit-page/v1",
                "input_sha256": fingerprint,
                "findings": findings[offset : offset + 100],
            },
        )
        pages.append({"record_id": child, "version": version, "digest": digest})
    digest = store.append_snapshot(
        record_id=key,
        version=version,
        competence=period,
        issuer=issuer,
        content=report
        | binding
        | {"source_refs": sources, "page_refs": pages, "finding_count": len(findings)},
    )
    return {
        "version": version,
        "snapshot_digest": digest,
        "replay": False,
        "finding_count": len(findings),
    }
