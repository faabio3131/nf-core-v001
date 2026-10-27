"""Normalized event evidence in the canonical fiscal archive, never in Portal receipts."""

import hashlib
import json
from datetime import datetime

from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.domain import FiscalValidationError

from .events import CancellationResult, InutilizationResult

EVENT_RESULT_MEDIA_TYPE = "application/vnd.nfcore.fiscal-event-result+json"


def event_archive_reference(operation: str, correlation_id: str) -> str:
    if operation not in {"cancelFiscalDocument", "inutilizeFiscalRange"} or not correlation_id:
        raise FiscalValidationError("event evidence requires operation and correlation")
    identity = json.dumps([operation, correlation_id], separators=(",", ":")).encode()
    return "fiscal-event:" + hashlib.sha256(identity).hexdigest()


def build_event_result_evidence(
    result: CancellationResult | InutilizationResult,
    *,
    archived_at: datetime,
    retention: RetentionPolicyMetadata,
) -> FiscalArchiveEntry:
    if not isinstance(result, (CancellationResult, InutilizationResult)):
        raise FiscalValidationError("validated fiscal event result is required")
    operation = (
        "cancelFiscalDocument" if isinstance(result, CancellationResult) else "inutilizeFiscalRange"
    )
    payload: dict[str, object] = {
        "version": 1,
        "operation": operation,
        "request_id": result.request_id,
        "status": result.status.value,
        "provider_name": result.provider.provider_name,
        "adapter_version": result.provider.adapter_version,
        "provider_request_id": result.provider_request_id,
        "event_protocol_reference": result.event_protocol_reference,
        "rejection_code": result.rejection_code,
    }
    if isinstance(result, CancellationResult):
        payload["access_key"] = result.access_key.value
    else:
        payload.update(model=result.model.value, series=result.series,
                       first_number=result.first_number, last_number=result.last_number)
    return FiscalArchiveEntry.build(
        scope=result.scope,
        document_reference=event_archive_reference(operation, result.scope.correlation_id),
        kind=FiscalArchiveKind.FISCAL_EVENT,
        content=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        media_type=EVENT_RESULT_MEDIA_TYPE,
        archived_at=archived_at,
        retention=retention,
    )
