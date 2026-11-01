from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    RetentionPolicyMetadata,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)


def _scope(*, tenant: str = "tenant-hardening", unit: str = "unit-hardening") -> ExecutionScope:
    return ExecutionScope(
        host_namespace="fm.hardening",
        tenant_id=tenant,
        unit_id=unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id=f"corr-{tenant}-{unit}",
    )


def test_v2_14_migrations_and_restart_are_idempotent(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "v2-14-closure.sqlite3")

    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    assert database.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    assert restarted.applied_migrations() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)


def test_v2_14_archive_tampering_fails_closed() -> None:
    entry = FiscalArchiveEntry.build(
        scope=_scope(),
        document_reference="nfe:hardening:closure",
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=b"<synthetic-authorized/>",
        media_type="application/xml",
        archived_at=NOW,
        retention=RetentionPolicyMetadata(
            policy_id="synthetic-hardening-retention",
            policy_version=1,
        ),
    )

    with pytest.raises(FiscalValidationError, match="does not match"):
        replace(entry, content=b"<tampered/>")


def test_v2_14_scope_partition_identity_stays_distinct() -> None:
    left = _scope(tenant="tenant-a", unit="unit-a")
    other_tenant = _scope(tenant="tenant-b", unit="unit-a")
    other_unit = _scope(tenant="tenant-a", unit="unit-b")

    assert left.partition_key != other_tenant.partition_key
    assert left.partition_key != other_unit.partition_key
    assert other_tenant.partition_key != other_unit.partition_key


def test_v2_14_structural_secret_and_domain_boundary_scan() -> None:
    root = Path(__file__).resolve().parents[2]
    source_root = root / "src" / "kordena_fiscal"

    secret_files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pfx", ".p12", ".pem", ".key"}
    ]
    assert secret_files == []

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
    )
    assert "BEGIN " + "PRIVATE KEY" not in source_text

    domain_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (source_root / "domain").rglob("*.py")
    )
    for forbidden_import in (
        "kordena_fiscal.observability",
        "kordena_fiscal.vault",
        "kordena_fiscal.gateway",
        "kordena_fiscal.signing",
        "kordena_fiscal.resilience",
        "kordena_fiscal.homologation",
        "cryptography",
    ):
        assert forbidden_import not in domain_text
