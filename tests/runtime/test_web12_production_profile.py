from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalDocumentKind
from kordena_fiscal.gateway.production_activation import (
    ProductionActivationKey,
    ProductionActivationRecord,
    ProductionActivationState,
    ProductionExecutionAuthority,
)
from kordena_fiscal.gateway.provider import ProviderOperation
from kordena_fiscal.runtime.api import create_runtime_app
from kordena_fiscal.runtime.config import RuntimeSettings

NOW = datetime(2026, 9, 15, 21, 30, tzinfo=UTC)


def _authority() -> ProductionExecutionAuthority:
    record = ProductionActivationRecord(
        key=ProductionActivationKey(
            tenant_id="tenant-a",
            unit_id="unit-a",
            provider_id="provider-a",
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=BrazilianJurisdiction("SP"),
            operation=ProviderOperation.QUERY,
        ),
        state=ProductionActivationState.ACTIVE,
        approval_reference="change-control-001",
        external_evidence_id="official-homologation-001",
        changed_by="fiscal-authority-admin",
        changed_at=NOW,
        correlation_id="corr-production-authority",
    )
    return ProductionExecutionAuthority((record,))


def test_runtime_profile_is_fail_closed_without_production_authority() -> None:
    client = TestClient(create_runtime_app(RuntimeSettings.from_mapping({})))

    response = client.get("/runtime/profile")

    assert response.status_code == 200
    assert response.json()["fiscal_production_activated"] is False
    # Signed trial and anonymous public trial are distinct runtime capabilities.
    assert response.json()["commercial_trial_configured"] is False
    assert response.json()["public_trial_configured"] is False
    assert response.json()["fiscal_production_active_grants"] == 0


def test_runtime_profile_reports_only_explicitly_injected_active_authority() -> None:
    client = TestClient(
        create_runtime_app(
            RuntimeSettings.from_mapping({}),
            production_authority=_authority(),
        )
    )

    response = client.get("/runtime/profile")

    assert response.status_code == 200
    assert response.json()["fiscal_production_activated"] is True
    assert response.json()["fiscal_production_active_grants"] == 1
