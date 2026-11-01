"""Evidence provider built on the portal's own authorized read path.

The cognitive core gets no direct database access: it reads the same projections the Portal
shows to the authenticated human (``HumanPortalExecutor.surface``), whose tenant/unit scoping
is resolved server-side. Anything the portal does not project is simply not evidence.

Known gaps in the CURRENT projections (reported, not worked around):
- the ``errors`` surface exposes ``rejection_code`` only for fiscal *events* (cancel,
  inutilization), not for issuance rejections;
- no surface exposes the tax decision per document, so ``suggest_classification`` receives
  no evidence here until a read projection is added to the portal executor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.security.human_identity import AuthenticatedHuman

from .contracts import (
    MAX_EVIDENCE_VALUE_CHARS,
    Capability,
    Evidence,
    EvidenceKind,
)

_MAX_ROWS = 25


class SurfaceReader(Protocol):
    def surface(
        self,
        *,
        surface_id: str,
        authority: AuthenticatedHuman,
        unit_id: str | None = None,
        environment: FiscalEnvironment | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Mapping[str, Any]]: ...


def _s(value: object) -> str:
    return str(value)[:MAX_EVIDENCE_VALUE_CHARS]


class PortalSurfaceEvidenceProvider:
    def __init__(self, reader: SurfaceReader) -> None:
        self._reader = reader

    def collect(
        self,
        *,
        authority: AuthenticatedHuman,
        capability: Capability,
        unit_id: str,
        environment: FiscalEnvironment,
        subject_id: str | None,
    ) -> tuple[Evidence, ...]:
        tenant = authority.tenant_id

        def rows(surface: str) -> Sequence[Mapping[str, Any]]:
            return self._reader.surface(
                surface_id=surface,
                authority=authority,
                unit_id=unit_id,
                environment=environment,
                limit=_MAX_ROWS,
                offset=0,
            )

        def matches(row: Mapping[str, Any]) -> bool:
            if subject_id is None:
                return True
            return subject_id in {
                str(row.get("entry_id", "")),
                str(row.get("document_id", "")),
                str(row.get("source_id", "")),
            }

        def make(eid: str, kind: EvidenceKind, origin: str, data: dict[str, str]) -> Evidence:
            return Evidence(
                evidence_id=eid, kind=kind, tenant_id=tenant, unit_id=unit_id,
                origin=origin, data=data,
            )

        out: list[Evidence] = []
        if capability is Capability.EXPLAIN_REJECTION:
            for index, row in enumerate(r for r in rows("errors") if matches(r)):
                if row.get("rejection_code"):
                    out.append(make(f"rej:{index}", EvidenceKind.REJECTION, "portal:errors",
                                    {"code": _s(row["rejection_code"]),
                                     "operation": _s(row.get("operation", ""))}))
                if row.get("state"):
                    out.append(make(f"doc:{index}", EvidenceKind.DOCUMENT_STATE,
                                    "portal:errors", {"state": _s(row["state"])}))
        elif capability is Capability.EXPLAIN_RECONCILIATION:
            for index, row in enumerate(r for r in rows("reconciliation") if matches(r)):
                out.append(make(f"rec:{index}", EvidenceKind.RECONCILIATION_ISSUE,
                                "portal:reconciliation", {"status": _s(row.get("status", ""))}))
                for position, code in enumerate(row.get("issue_codes") or ()):
                    data = {"issue_code": _s(code)}
                    if row.get("document_id"):
                        data["document_id"] = _s(row["document_id"])
                    out.append(make(f"rec:{index}:{position}",
                                    EvidenceKind.RECONCILIATION_ISSUE,
                                    "portal:reconciliation", data))
        elif capability is Capability.ANSWER_ACCOUNTANT_QUESTION:
            for index, row in enumerate(rows("reconciliation")[:5]):
                out.append(make(f"rec:{index}", EvidenceKind.RECONCILIATION_ISSUE,
                                "portal:reconciliation", {"status": _s(row.get("status", ""))}))
            for index, row in enumerate(rows("errors")[:5]):
                if row.get("state"):
                    out.append(make(f"doc:{index}", EvidenceKind.DOCUMENT_STATE,
                                    "portal:errors", {"state": _s(row["state"])}))
        return tuple(out)
