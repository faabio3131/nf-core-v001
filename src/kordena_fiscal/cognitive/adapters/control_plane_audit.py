"""Durable audit for the cognitive core on the platform's existing control-plane audit ledger.

No new table and no migration: ``fm_control_plane_audit.action`` is free text. Only ids, the
capability, the event name, the outcome and a context-hash prefix are written. Never prompts,
answers, secrets or personal data. An unavailable ledger raises, which the service treats as
"no audit, no model": the deterministic baseline is still served.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.control_plane.models import ControlPlaneAuditAction, ControlPlaneAuditEvent
from kordena_fiscal.persistence.ports import PersistenceConflictError

from ..ports import AdviceAuditEvent

UnitOfWorkFactory = Callable[[], AbstractContextManager[Any]]


class ControlPlaneAuditSink:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def emit(self, event: AdviceAuditEvent) -> None:
        digest = hashlib.sha256(
            f"{event.request_id}|{event.event}|{event.outcome}".encode()
        ).hexdigest()[:32]
        record = ControlPlaneAuditEvent(
            event_id=f"cog-{digest}",
            occurred_at=self._clock(),
            actor_id=event.actor_id,
            action=ControlPlaneAuditAction.COGNITIVE_ADVICE_RECORDED,
            target_type="cognitive-advice",
            target_id=(
                f"{event.request_id[:64]}|{event.capability.value}|{event.event}"
                f"|{event.outcome}|{event.context_hash[:16]}"
            )[:256],
            correlation_id=event.correlation_id,
            tenant_id=event.tenant_id,
            unit_id=event.unit_id or None,
        )
        try:
            with self._uow_factory() as uow:
                uow.control_plane.append_audit(record)
                uow.commit()
        except PersistenceConflictError:
            return  # the same request/event is already durable: idempotent retry
