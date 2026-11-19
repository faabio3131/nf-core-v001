"""Governed floor for the National DPS serial of one legal issuer.

Used when an issuer already sent DPS numbers through another system (for
example the public Emissor Nacional) or after a restore that may sit behind
numbers already transmitted. The next reservation must start after the last
number really used, otherwise SEFIN rejects a duplicate DPS identifier.

The floor is monotonic (never lowers a counter), owned by one fiscal unit,
idempotent per exact command, and audited in the existing configuration
command ledger plus the tenant-scoped fiscal archive in the SAME transaction.
No new table, migration, provider call or numbering authority is introduced.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    RetentionPolicyMetadata,
)
from kordena_fiscal.domain import ExecutionScope, FiscalValidationError
from kordena_fiscal.persistence.ports import PersistenceConflictError
from kordena_fiscal.persistence.sqlite_dps import validate_dps_floor_key

DPS_FLOOR_MEDIA_TYPE = "application/vnd.nfcore.dps-counter-floor.v1+json"
_RETENTION = RetentionPolicyMetadata("nfcore-fiscal-archive", 1)


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise FiscalValidationError(f"{field} is required (max {limit} chars)")
    return value.strip()


def raise_dps_counter_floor(
    factory: Callable[[], Any],
    *,
    scope: ExecutionScope,
    issuer_cnpj: str,
    municipality_ibge: str,
    series: int,
    last_used_number: int,
    approved_by: str,
    approval_reference: str,
    occurred_at: datetime,
) -> Mapping[str, object]:
    """Raise the counter floor once per exact approved command and audit it."""
    validate_dps_floor_key(scope, issuer_cnpj, municipality_ibge, series, last_used_number)
    approver = _text(approved_by, "approved_by", 128)
    reference = _text(approval_reference, "approval_reference", 256)
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise FiscalValidationError("occurred_at must be timezone-aware")
    command = {
        "issuer_cnpj": issuer_cnpj,
        "municipality_ibge": municipality_ibge,
        "environment": scope.environment.value,
        "series": series,
        "last_used_number": last_used_number,
        "approved_by": approver,
        "approval_reference": reference,
    }
    fingerprint = hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    command_key = "dps-counter-floor:" + fingerprint
    with factory() as uow:
        replay = uow.commercial.reserve_configuration_command(
            scope, command_key, fingerprint,
        )
        if replay is not None:
            receipt = uow.commercial.configuration_receipt(scope, command_key)
            if receipt is None:
                raise PersistenceConflictError("DPS floor command is incomplete")
            return {**dict(receipt), "replay": True}
        outcome = uow.dps_sequences.raise_floor(
            scope=scope, issuer_cnpj=issuer_cnpj, municipality_ibge=municipality_ibge,
            series=series, last_used_number=last_used_number,
        )
        result: dict[str, object] = {
            "previous_last_number": outcome.previous_last_number,
            "last_number": outcome.last_number,
            "next_number": outcome.last_number + 1,
            "changed": outcome.changed,
            "evidence_reference": command_key,
        }
        evidence = {
            **command,
            **result,
            "host_namespace": scope.host_namespace,
            "tenant_id": scope.tenant_id,
            "unit_id": scope.unit_id,
            "occurred_at": occurred_at.isoformat(),
        }
        uow.archive.append(FiscalArchiveEntry.build(
            scope=scope, document_reference=command_key,
            kind=FiscalArchiveKind.OTHER,
            content=json.dumps(evidence, sort_keys=True).encode("utf-8"),
            media_type=DPS_FLOOR_MEDIA_TYPE, archived_at=occurred_at,
            retention=_RETENTION,
        ))
        uow.commercial.complete_configuration_command(scope, command_key, result)
        uow.commit()
    return {**result, "replay": False}
