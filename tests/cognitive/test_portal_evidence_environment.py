"""REC-22: Portal evidence must reject foreign fiscal environment rows."""

from __future__ import annotations

from typing import cast
from types import SimpleNamespace

import pytest

from kordena_fiscal.cognitive import Capability, EvidenceKind
from kordena_fiscal.cognitive.portal_evidence import PortalSurfaceEvidenceProvider
from kordena_fiscal.domain import FiscalEnvironment
from kordena_fiscal.security.human_identity import AuthenticatedHuman


class _Reader:
    def __init__(self, records: list[dict[str, str]]) -> None:
        self.records = records
        self.calls: list[tuple[str, FiscalEnvironment]] = []

    def surface(
        self, *, surface_id: str, authority: AuthenticatedHuman,
        unit_id: str | None = None, environment: FiscalEnvironment | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict[str, str]]:
        assert authority.tenant_id == "tenant-a"
        assert unit_id == "unit-a" and limit == 25 and offset == 0
        assert environment is not None
        self.calls.append((surface_id, environment))
        return self.records


@pytest.mark.parametrize("bad_field,bad_value", [
    ("tenant_id", "tenant-b"),
    ("unit_id", "unit-b"),
    ("environment", "production"),
    ("environment", "unexpected-environment"),
])
def test_portal_evidence_excludes_foreign_scoped_records(
    bad_field: str, bad_value: str,
) -> None:
    row = {
        "tenant_id": "tenant-a", "unit_id": "unit-a",
        "environment": "homologation", "rejection_code": "204", "state": "rejected",
    }
    row[bad_field] = bad_value
    reader = _Reader([row])
    authority = cast(AuthenticatedHuman, SimpleNamespace(tenant_id="tenant-a"))
    evidence = PortalSurfaceEvidenceProvider(reader).collect(
        authority=authority, capability=Capability.EXPLAIN_REJECTION,
        unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
        subject_id=None,
    )
    assert evidence == ()
    assert reader.calls == [("errors", FiscalEnvironment.HOMOLOGATION)]


def test_portal_evidence_allows_matching_environment_and_legacy_scoped_rows() -> None:
    valid = {
        "tenant_id": "tenant-a", "unit_id": "unit-a",
        "environment": "homologation", "rejection_code": "204", "state": "rejected",
    }
    legacy = {key: value for key, value in valid.items() if key != "environment"}
    reader = _Reader([valid, legacy])
    authority = cast(AuthenticatedHuman, SimpleNamespace(tenant_id="tenant-a"))
    evidence = PortalSurfaceEvidenceProvider(reader).collect(
        authority=authority, capability=Capability.EXPLAIN_REJECTION,
        unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
        subject_id=None,
    )
    assert len(evidence) == 4
    assert [item.kind for item in evidence] == [
        EvidenceKind.REJECTION, EvidenceKind.DOCUMENT_STATE,
        EvidenceKind.REJECTION, EvidenceKind.DOCUMENT_STATE,
    ]
    assert all(item.tenant_id == "tenant-a" and item.unit_id == "unit-a" for item in evidence)
