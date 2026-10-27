"""Normalized event evidence in the canonical fiscal archive, never in Portal receipts."""

import hashlib
import json
from datetime import datetime

from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.domain import FiscalValidationError

from .events import CancellationResult, FiscalEventStatus, InutilizationResult

EVENT_RESULT_MEDIA_TYPE = "application/vnd.nfcore.fiscal-event-result+json"


def event_result_projection(entry: FiscalArchiveEntry) -> dict[str, object] | None:
    """Expose only normalized outcome metadata through existing authorized surfaces."""
    if (
        entry.kind is not FiscalArchiveKind.FISCAL_EVENT
        or entry.media_type != EVENT_RESULT_MEDIA_TYPE
    ):
        return None
    try:
        data = json.loads(entry.content)
        if (
            not isinstance(data, dict) or data.get("version") != 1
            or data.get("operation") not in {"cancelFiscalDocument", "inutilizeFiscalRange"}
            or data.get("status") not in {status.value for status in FiscalEventStatus}
        ):
            raise ValueError("invalid event evidence")
        projection: dict[str, object] = {
            "operation": data["operation"], "status": data["status"],
        }
        for name in ("event_protocol_reference", "rejection_code"):
            value = data.get(name)
            if value is not None and (not isinstance(value, str) or len(value) > 512):
                raise ValueError("invalid event metadata")
            if value is not None:
                projection[name] = value
        if data["operation"] == "inutilizeFiscalRange":
            for name in ("model", "series", "first_number", "last_number"):
                if type(data.get(name)) is not int:
                    raise ValueError("invalid event range")
                projection[name] = data[name]
        return projection
    except (ValueError, TypeError) as exc:
        raise FiscalValidationError("invalid normalized event evidence") from exc


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
