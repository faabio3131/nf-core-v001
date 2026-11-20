"""Durable federal income-tax regime declarations (RTC-02), no new table.

The CRT of the NF-e cannot tell Lucro Presumido from Lucro Real. The issuer's
federal regime is therefore an explicit, human-declared, effective-dated fact.

Declarations are immutable rows in the existing scope-bound configuration
command ledger, each with a fiscal-archive evidence entry in the SAME
transaction. A later declaration closes the previous one at its own
effective_from (derived when loading), so history is never rewritten and the
timeline can never overlap. The CRT is taken from the effective issuer profile
(server-owned), never from the browser, and must be consistent with the regime.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    RetentionPolicyMetadata,
)
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.tax.regimes import (
    FederalIncomeTaxRegime,
    FederalRegimeDeclaration,
    resolve_federal_regime_timeline,
)

FEDERAL_REGIME_PREFIX = "federal-regime:"
FEDERAL_REGIME_MEDIA_TYPE = "application/vnd.nfcore.federal-regime-declaration.v1+json"
_RETENTION = RetentionPolicyMetadata("nfcore-fiscal-archive", 1)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field} must be timezone-aware")
    return value


def load_federal_regime_declarations(
    factory: Callable[[], Any], scope: ExecutionScope,
) -> tuple[FederalRegimeDeclaration, ...]:
    """Ordered declarations with each one closed by its successor."""
    _require_portal_scope(scope)
    with factory() as uow:
        receipts = uow.commercial.list_configuration_receipts(scope, FEDERAL_REGIME_PREFIX)
    return _decode_declarations(scope, receipts)


def _require_portal_scope(scope: ExecutionScope) -> None:
    # The configuration ledger is keyed by tenant/unit/environment, not host.
    # Only its canonical Portal namespace may write or read this timeline.
    if scope.host_namespace != "fm-nfcore":
        raise FiscalValidationError("federal regime requires canonical portal scope")


def _decode_declarations(
    scope: ExecutionScope, receipts: tuple[Mapping[str, object], ...],
) -> tuple[FederalRegimeDeclaration, ...]:
    rows = []
    for receipt in receipts:
        try:
            rows.append((
                _aware(datetime.fromisoformat(str(receipt["effective_from"])), "stored effective_from"),
                int(str(receipt["version"])),
                TaxRegimeCode(int(str(receipt["crt"]))),
                FederalIncomeTaxRegime(str(receipt["federal_income_tax_regime"])),
                str(receipt["source_reference"]),
            ))
        except (KeyError, TypeError, ValueError):
            raise FiscalValidationError("Stored federal regime declaration is invalid") from None
    rows.sort(key=lambda row: (row[0], row[1]))
    declarations: list[FederalRegimeDeclaration] = []
    for effective_from, version, crt, regime, source in rows:
        if version != len(declarations) + 1:
            raise FiscalValidationError("Stored federal regime versions are not sequential")
        if declarations:
            previous = declarations[-1]
            if effective_from <= previous.effective_from:
                raise FiscalValidationError("Stored federal regime timeline is ambiguous")
            declarations[-1] = replace(previous, effective_to=effective_from)
        declarations.append(FederalRegimeDeclaration(
            scope=scope, crt=crt, federal_income_tax_regime=regime,
            effective_from=effective_from, source_reference=source, version=version,
        ))
    return tuple(declarations)


def declare_federal_regime(
    factory: Callable[[], Any],
    *,
    scope: ExecutionScope,
    crt: TaxRegimeCode,
    federal_income_tax_regime: FederalIncomeTaxRegime,
    effective_from: datetime,
    source_reference: str,
    actor: str,
    idempotency_key: str,
    occurred_at: datetime,
) -> dict[str, object]:
    """Append one human declaration; an exact retry replays, a changed one conflicts."""
    _aware(effective_from, "effective_from")
    _aware(occurred_at, "occurred_at")
    if not isinstance(actor, str) or not actor.strip():
        raise FiscalValidationError("actor is required")
    key = (idempotency_key or "").strip()
    if not key or len(key) > 256:
        raise FiscalValidationError("idempotency key required")
    _require_portal_scope(scope)
    # Domain consistency (CRT x regime, dates, source) before any write.
    candidate = FederalRegimeDeclaration(
        scope=scope, crt=crt, federal_income_tax_regime=federal_income_tax_regime,
        effective_from=effective_from, source_reference=source_reference,
    )
    command = {
        "crt": int(crt),
        "federal_income_tax_regime": federal_income_tax_regime.value,
        "effective_from": effective_from.isoformat(),
        "source_reference": candidate.source_reference,
        "actor": actor.strip()[:128],
    }
    fingerprint = hashlib.sha256(json.dumps(
        {**command, "idempotency_key": key}, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    command_key = FEDERAL_REGIME_PREFIX + hashlib.sha256(key.encode()).hexdigest()
    with factory() as uow:
        # Same key + same content replays; same key + other content raises
        # PersistenceConflictError inside the ledger itself.
        replay = uow.commercial.reserve_configuration_command(scope, command_key, fingerprint)
        if replay is not None:
            return {**dict(replay), "replay": True}
        # The existing configuration revision CAS serializes distinct command
        # keys on PostgreSQL as well as SQLite. Read the timeline only after
        # winning the revision and in the SAME transaction as the evidence.
        revision = uow.commercial.configuration_version(scope, "federal_regime", "issuer")
        uow.commercial.advance_configuration_version(
            scope, "federal_regime", "issuer", revision,
        )
        existing = _decode_declarations(
            scope, uow.commercial.list_configuration_receipts(scope, FEDERAL_REGIME_PREFIX),
        )
        version = max((item.version for item in existing), default=0) + 1
        if existing and effective_from <= existing[-1].effective_from:
            raise FiscalValidationError(
                "New federal regime must start after the current declaration"
            )
        result: dict[str, object] = {
            **command, "version": version, "fingerprint": fingerprint,
            "evidence_reference": command_key,
        }
        uow.archive.append(FiscalArchiveEntry.build(
            scope=scope, document_reference=command_key, kind=FiscalArchiveKind.OTHER,
            content=json.dumps({**result, "declared_at": occurred_at.isoformat()},
                               sort_keys=True).encode("utf-8"),
            media_type=FEDERAL_REGIME_MEDIA_TYPE, archived_at=occurred_at,
            retention=_RETENTION,
        ))
        uow.commercial.complete_configuration_command(scope, command_key, result)
        uow.commit()
    return {**result, "replay": False}


def federal_regime_status(
    factory: Callable[[], Any], scope: ExecutionScope, profile: Any, instant: datetime,
) -> dict[str, object]:
    """Read model for the Portal; never infers the regime from the CRT."""
    try:
        declarations = load_federal_regime_declarations(factory, scope)
    except FiscalValidationError:
        return {"federal_regime_status": "declaration_invalid"}
    if not declarations:
        return {"federal_regime_status": "declaration_not_configured"}
    try:
        regime = resolve_federal_regime_timeline(profile, declarations, instant)
    except FiscalValidationError:
        return {"federal_regime_status": "declaration_inconsistent_with_profile"}
    current = next(
        item for item in reversed(declarations) if item.effective_from <= instant
    )
    return {
        "federal_regime_status": "declared",
        "federal_income_tax_regime": regime.value,
        "federal_regime_effective_from": current.effective_from.isoformat(),
        "federal_regime_version": current.version,
        "federal_regime_source_reference": current.source_reference,
    }
