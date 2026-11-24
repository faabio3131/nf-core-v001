"""Osasco's municipal key is resolved by the canonical scoped secret authority."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.control_plane import (
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    MunicipalRegistration,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import OSASCO_RTC_PROVIDER_ID
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.osasco_credentials import build_osasco_scoped_key_resolver
from kordena_fiscal.vault.contracts import (
    EphemeralCscMaterial,
    EphemeralProviderCredentialsMaterial,
    SecretMaterialTypeError,
    SecretResolutionService,
)

_KEY = "12345678-1234-1234-1234-123456789012"


def _setup(tmp_path: Path) -> tuple[
    ExecutionScope, SqliteFiscalDatabase, SecretResolutionService, Mock,
]:
    db = SqliteFiscalDatabase(tmp_path / "osasco-provider-key.sqlite")
    db.initialize()
    scope = ExecutionScope(
        "org-osasco", "unit-osasco", FiscalEnvironment.HOMOLOGATION,
        "key-lookup", "fm-nfcore",
    )
    with db() as uow:
        uow.control_plane.add_organization(FiscalOrganization(
            tenant_id=scope.tenant_id, legal_name="Issuer synthetic",
        ))
        uow.control_plane.add_unit(FiscalUnitRegistration(
            tenant_id=scope.tenant_id, unit_id=scope.unit_id,
            display_name="Osasco synthetic",
            enabled_environments=frozenset({FiscalEnvironment.HOMOLOGATION}),
        ))
        uow.control_plane.add_profile(FiscalProfile(
            profile_id="issuer-osasco-synthetic",
            scope=scope, cnpj=Cnpj("11222333000181"),
            legal_name="Osasco Test Issuer Ltda", tax_regime=TaxRegimeCode.NORMAL,
            state_registration=StateRegistration("SP", "123456789"),
            municipal_registration=MunicipalRegistration("123456"),
            primary_cnae=CnaeCode("6201501"),
            address=FiscalAddress(
                street="Rua Sintetica", number="10", district="Centro",
                municipality_name="Osasco",
                jurisdiction=BrazilianJurisdiction("SP", "3534401"),
                postal_code="06018090",
            ),
            effective_from=datetime.now(UTC) - timedelta(days=1),
        ))
        uow.control_plane.add_secret_reference(SecretReference(
            reference_id="ref:osasco-municipal-auth",
            kind=SecretReferenceKind.CREDENTIALS,
            tenant_id=scope.tenant_id, unit_id=scope.unit_id,
            environment=scope.environment, provider_id=OSASCO_RTC_PROVIDER_ID,
        ))
        uow.commit()
    vault = Mock()
    vault.resolve.return_value = EphemeralProviderCredentialsMaterial(
        reference_id="ref:osasco-municipal-auth", credential_bytes=_KEY.encode("ascii"),
    )
    secrets = SecretResolutionService(unit_of_work_factory=db, vault=vault)
    return scope, db, secrets, vault


def test_osasco_key_uses_correct_scope_provider_and_existing_control_plane(
    tmp_path: Path,
) -> None:
    scope, db, secrets, vault = _setup(tmp_path)
    resolver = build_osasco_scoped_key_resolver(
        unit_of_work_factory=db, secrets=secrets, workload_id="nfcore-api",
    )
    assert resolver(scope, "11222333000181") == _KEY
    vault.resolve.assert_called_once()
    reference, context = vault.resolve.call_args.args
    assert reference.provider_id == OSASCO_RTC_PROVIDER_ID
    assert context.scope.identity_partition_key == scope.identity_partition_key
    assert context.workload_id == "nfcore-api"


def test_osasco_cannot_read_key_for_another_taxpayer_or_unit(tmp_path: Path) -> None:
    scope, db, secrets, vault = _setup(tmp_path)
    resolver = build_osasco_scoped_key_resolver(
        unit_of_work_factory=db, secrets=secrets, workload_id="nfcore-api",
    )
    with pytest.raises(FiscalValidationError, match="taxpayer"):
        resolver(scope, "00944029000121")
    vault.resolve.assert_not_called()
    another_unit = ExecutionScope(
        scope.tenant_id, "unit-other", scope.environment, "other", scope.host_namespace,
    )
    with pytest.raises(FiscalValidationError):
        resolver(another_unit, "11222333000181")
    vault.resolve.assert_not_called()


def test_osasco_fails_on_wrong_secret_type_or_credential_shape(tmp_path: Path) -> None:
    scope, db, secrets, vault = _setup(tmp_path)
    resolver = build_osasco_scoped_key_resolver(
        unit_of_work_factory=db, secrets=secrets, workload_id="nfcore-api",
    )
    vault.resolve.return_value = EphemeralProviderCredentialsMaterial(
        reference_id="ref:osasco-municipal-auth", credential_bytes=b"wrong-size",
    )
    with pytest.raises(FiscalValidationError, match="shape"):
        resolver(scope, "11222333000181")
    vault.resolve.return_value = EphemeralCscMaterial(
        reference_id="ref:osasco-municipal-auth", code=b"wrong-kind",
    )
    with pytest.raises(SecretMaterialTypeError, match="inconsistent"):
        resolver(scope, "11222333000181")
