from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from kordena_fiscal.control_plane import SecretReference
from kordena_fiscal.control_plane.commercial_models import HomologationEvidenceRecord
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway import ProviderOperation
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.controlled_pilots import ControlledPilotScope


def test_v2_15_closure_keeps_database_migrations_explicit_and_stable(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "v2-15-closure.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    assert database.initialize() == ()


def test_v2_15_closure_secret_reference_surface_contains_no_secret_material_fields() -> None:
    names = {field.name for field in fields(SecretReference)}
    assert names == {
        "reference_id",
        "kind",
        "tenant_id",
        "unit_id",
        "environment",
        "provider_id",
    }
    assert names.isdisjoint({"secret", "password", "private_key", "pfx", "token", "csc_value"})


def test_v2_15_closure_external_official_evidence_cannot_be_invented() -> None:
    with pytest.raises(FiscalValidationError, match="external_evidence_id"):
        HomologationEvidenceRecord(
            tenant_id="tenant-closure",
            unit_id="unit-closure",
            environment=FiscalEnvironment.HOMOLOGATION,
            provider_id="provider-closure",
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            operation="authorize",
            provider_adapter_available=True,
            credentials_reference_configured=True,
            signer_capability=False,
            csc_reference_configured=False,
            transport_configured=True,
            resilience_certified=True,
            contract_tests_certified=True,
            jurisdiction_mapping=True,
            operation_supported=True,
            external_official=True,
        )


def test_v2_15_closure_pilot_and_readiness_never_promote_production() -> None:
    production_scope = ExecutionScope(
        host_namespace="fm.synthetic-closure",
        tenant_id="tenant-closure",
        unit_id="unit-closure",
        environment=FiscalEnvironment.PRODUCTION,
        correlation_id="corr-closure",
    )
    with pytest.raises(FiscalValidationError, match="HOMOLOGATION"):
        ControlledPilotScope(
            pilot_id="pilot-closure",
            scope=production_scope,
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=BrazilianJurisdiction("SP"),
            provider_id="provider-closure",
            allowed_operations=frozenset({ProviderOperation.AUTHORIZE}),
        )

    runtime_files = (
        Path("src/kordena_fiscal/runtime/controlled_pilots.py"),
        Path("src/kordena_fiscal/runtime/homologation_readiness.py"),
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    assert "PRODUCTION_APPROVED" not in combined
    assert "if tenant_id ==" not in combined
    assert "if customer ==" not in combined
