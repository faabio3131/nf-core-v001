"""Interim audit sink: structured log lines with ids and hashes only.

NOT a durable audit store. It satisfies the rule "no audit, no model" for pilots and is meant to
be replaced by the platform audit ledger before commercial go-live (tracked as a known debt).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from ..ports import AdviceAuditEvent

_LOG = logging.getLogger("nfcore.cognitive.audit")


class LoggingAuditSink:
    def emit(self, event: AdviceAuditEvent) -> None:
        record = asdict(event)
        record["capability"] = event.capability.value
        _LOG.info("%s", json.dumps(record, ensure_ascii=False, sort_keys=True))
