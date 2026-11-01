from __future__ import annotations

import sqlite3

import pytest

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    ControlPlanePermission,
    DurableControlPlaneService,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.vault import (
    EphemeralCertificateMaterial,
    EphemeralCscMaterial,
    EphemeralProviderCredentialsMaterial,
    InMemorySyntheticFiscalSecretVault,
    SecretMaterialTypeError,
    SecretResolutionContext,
    SecretResolutionService,
    SecretUnavailableError,
    SecretUsagePurpose,
)

HOST = "fm.kordena"
TENANT = "tenant-vault"
UNIT = "unit-vault"
PROVIDER = "synthetic-provider"
CERT_REF = "ref:fm-fiscal/tenant-vault/unit-vault/hml-certificate"
CSC_REF = "ref:fm-fiscal/tenant-vault/unit-vault/hml-csc"
CREDENTIALS_REF = "ref:fm-fiscal/tenant-vault/unit-vault/hml-provider-credentials"
SYNTHETIC_CERTIFICATE_BYTES = b"SYNTHETIC-PKCS12-NOT-A-REAL-CERTIFICATE"


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="v2-12-global-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.AUDIT_READ,
            }
        ),
        global_scope=True,
    )


def _tenant_admin(tenant_id: str = TENANT) -> AdminPrincipal:
    return AdminPrincipal(
        actor_id=f"v2-12-{tenant_id}-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.AUDIT_READ,
            }
        ),
        tenant_ids=frozenset({tenant_id}),
    )


def _database(tmp_path, name: str = "vault-boundary.sqlite3") -> SqliteFiscalDatabase:
    database = SqliteFiscalDatabase(tmp_path / name)
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    return database


def _scope(
    *,
    host: str = HOST,
    tenant: str = TENANT,
    unit: str = UNIT,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace=host,
        tenant_id=tenant,
        unit_id=unit,
        environment=environment,
        correlation_id="corr-vault-resolution",
    )


def _context(
    *,
    host: str = HOST,
    tenant: str = TENANT,
    unit: str = UNIT,
    environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    purpose: SecretUsagePurpose = SecretUsagePurpose.DOCUMENT_SIGNING,
    kind: SecretReferenceKind = SecretReferenceKind.CERTIFICATE,
    provider_id: str | None = None,
) -> SecretResolutionContext:
    return SecretResolutionContext(
        scope=_scope(
            host=host,
            tenant=tenant,
            unit=unit,
            environment=environment,
        ),
        purpose=purpose,
        kind=kind,
        workload_id="fiscal-runtime",
        provider_id=provider_id,
    )


def _onboard_and_bind(
    database: SqliteFiscalDatabase,
    *,
    environments: frozenset[FiscalEnvironment] = frozenset(
        {FiscalEnvironment.HOMOLOGATION}
    ),
) -> tuple[SecretReference, SecretReference, SecretReference]:
    service = DurableControlPlaneService(database)
    service.onboard_organization(
        actor=_global_admin(),
        tenant_id=TENANT,
        legal_name="Synthetic Vault Tenant Ltda",
        correlation_id="corr-org-vault",
    )
    service.onboard_unit(
        actor=_tenant_admin(),
        registration=FiscalUnitRegistration(
            tenant_id=TENANT,
            unit_id=UNIT,
            display_name="Synthetic Vault Unit",
            enabled_environments=environments,
        ),
        correlation_id="corr-unit-vault",
    )
    certificate = SecretReference(
        reference_id=CERT_REF,
        kind=SecretReferenceKind.CERTIFICATE,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
    )
    csc = SecretReference(
        reference_id=CSC_REF,
        kind=SecretReferenceKind.CSC,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=PROVIDER,
    )
    credentials = SecretReference(
        reference_id=CREDENTIALS_REF,
        kind=SecretReferenceKind.CREDENTIALS,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id=PROVIDER,
    )
    for reference in (certificate, csc, credentials):
        service.bind_secret_reference(
            actor=_tenant_admin(),
            reference=reference,
            correlation_id=f"corr-bind-{reference.kind.value}",
        )
    return certificate, csc, credentials


def _registered_vault(
    certificate: SecretReference,
    csc: SecretReference,
    credentials: SecretReference,
) -> InMemorySyntheticFiscalSecretVault:
    vault = InMemorySyntheticFiscalSecretVault()
    vault.register(
        host_namespace=HOST,
        reference=certificate,
        material=EphemeralCertificateMaterial(
            reference_id=CERT_REF,
            pkcs12_bytes=SYNTHETIC_CERTIFICATE_BYTES,
            password=b"synthetic-only",
        ),
    )
    vault.register(
        host_namespace=HOST,
        reference=csc,
        material=EphemeralCscMaterial(
            reference_id=CSC_REF,
            code=b"SYNTHETIC-CSC",
        ),
        provider_id=PROVIDER,
    )
    vault.register(
        host_namespace=HOST,
        reference=credentials,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=CREDENTIALS_REF,
            credential_bytes=b"SYNTHETIC-PROVIDER-CREDENTIAL",
        ),
        provider_id=PROVIDER,
    )
    return vault


def test_resolves_bound_certificate_through_host_scoped_runtime_vault(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(database)
    vault = _registered_vault(certificate, csc, credentials)
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)

    material = service.resolve(_context())

    assert isinstance(material, EphemeralCertificateMaterial)
    assert material.reference_id == CERT_REF
    assert material.pkcs12_bytes == SYNTHETIC_CERTIFICATE_BYTES


def test_cross_host_resolution_fails_closed(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(database)
    vault = _registered_vault(certificate, csc, credentials)
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)

    with pytest.raises(SecretUnavailableError, match="host/reference"):
        service.resolve(_context(host="fm.iron"))


def test_cross_tenant_and_cross_unit_resolution_fail_closed(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(database)
    vault = _registered_vault(certificate, csc, credentials)
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)

    with pytest.raises(SecretUnavailableError, match="not bound"):
        service.resolve(_context(tenant="tenant-other"))
    with pytest.raises(SecretUnavailableError, match="not bound"):
        service.resolve(_context(unit="unit-other"))


def test_cross_environment_resolution_fails_closed(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(
        database,
        environments=frozenset(
            {FiscalEnvironment.HOMOLOGATION, FiscalEnvironment.PRODUCTION}
        ),
    )
    vault = _registered_vault(certificate, csc, credentials)
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)

    with pytest.raises(SecretUnavailableError, match="not bound"):
        service.resolve(_context(environment=FiscalEnvironment.PRODUCTION))


def test_purpose_and_kind_mismatch_is_rejected_before_resolution() -> None:
    with pytest.raises(FiscalValidationError, match="incompatible"):
        _context(
            purpose=SecretUsagePurpose.DOCUMENT_SIGNING,
            kind=SecretReferenceKind.CSC,
        )


def test_provider_scoped_purposes_require_explicit_provider_identity() -> None:
    with pytest.raises(FiscalValidationError, match="provider_id"):
        _context(
            purpose=SecretUsagePurpose.PROVIDER_AUTHENTICATION,
            kind=SecretReferenceKind.CREDENTIALS,
        )
    with pytest.raises(FiscalValidationError, match="provider_id"):
        _context(
            purpose=SecretUsagePurpose.CSC_AUTHENTICATION,
            kind=SecretReferenceKind.CSC,
        )


def test_provider_scoped_material_uses_distinct_control_plane_references(tmp_path) -> None:
    database = _database(tmp_path)
    _, _, credentials_a = _onboard_and_bind(database)
    credentials_b = SecretReference(
        reference_id="ref:fm-fiscal/tenant-vault/unit-vault/provider-b-credentials",
        kind=SecretReferenceKind.CREDENTIALS,
        tenant_id=TENANT,
        unit_id=UNIT,
        environment=FiscalEnvironment.HOMOLOGATION,
        provider_id="provider-b",
    )
    DurableControlPlaneService(database).bind_secret_reference(
        actor=_tenant_admin(),
        reference=credentials_b,
        correlation_id="corr-bind-provider-b",
    )

    vault = InMemorySyntheticFiscalSecretVault()
    vault.register(
        host_namespace=HOST,
        reference=credentials_a,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=CREDENTIALS_REF,
            credential_bytes=b"PROVIDER-A-SYNTHETIC",
        ),
        provider_id=PROVIDER,
    )
    vault.register(
        host_namespace=HOST,
        reference=credentials_b,
        material=EphemeralProviderCredentialsMaterial(
            reference_id=credentials_b.reference_id,
            credential_bytes=b"PROVIDER-B-SYNTHETIC",
        ),
        provider_id="provider-b",
    )
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)

    material_a = service.resolve(
        _context(
            purpose=SecretUsagePurpose.PROVIDER_AUTHENTICATION,
            kind=SecretReferenceKind.CREDENTIALS,
            provider_id=PROVIDER,
        )
    )
    material_b = service.resolve(
        _context(
            purpose=SecretUsagePurpose.PROVIDER_AUTHENTICATION,
            kind=SecretReferenceKind.CREDENTIALS,
            provider_id="provider-b",
        )
    )

    assert isinstance(material_a, EphemeralProviderCredentialsMaterial)
    assert isinstance(material_b, EphemeralProviderCredentialsMaterial)
    assert material_a.reference_id != material_b.reference_id
    assert material_a.credential_bytes == b"PROVIDER-A-SYNTHETIC"
    assert material_b.credential_bytes == b"PROVIDER-B-SYNTHETIC"


def test_vault_unavailable_and_missing_material_fail_closed(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, _, _ = _onboard_and_bind(database)
    unavailable = InMemorySyntheticFiscalSecretVault(available=False)
    service = SecretResolutionService(unit_of_work_factory=database, vault=unavailable)

    with pytest.raises(SecretUnavailableError, match="unavailable"):
        service.resolve(_context())

    empty = InMemorySyntheticFiscalSecretVault()
    service = SecretResolutionService(unit_of_work_factory=database, vault=empty)
    with pytest.raises(SecretUnavailableError, match="host/reference"):
        service.resolve(_context())

    wrong_material = EphemeralCscMaterial(reference_id=certificate.reference_id, code=b"x")
    with pytest.raises(SecretMaterialTypeError, match="kind"):
        empty.register(
            host_namespace=HOST,
            reference=certificate,
            material=wrong_material,
        )


def test_ephemeral_material_repr_is_redacted() -> None:
    certificate = EphemeralCertificateMaterial(
        reference_id=CERT_REF,
        pkcs12_bytes=SYNTHETIC_CERTIFICATE_BYTES,
        password=b"synthetic-only",
    )
    csc = EphemeralCscMaterial(reference_id=CSC_REF, code=b"SYNTHETIC-CSC")
    credentials = EphemeralProviderCredentialsMaterial(
        reference_id=CREDENTIALS_REF,
        credential_bytes=b"SYNTHETIC-PROVIDER-CREDENTIAL",
    )

    assert "SYNTHETIC" not in repr(certificate)
    assert "synthetic-only" not in repr(certificate)
    assert "SYNTHETIC" not in repr(csc)
    assert "SYNTHETIC" not in repr(credentials)


def test_resolution_is_read_only_and_does_not_add_secret_audit_payload(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(database)
    vault = _registered_vault(certificate, csc, credentials)
    durable = DurableControlPlaneService(database)
    before = durable.list_audit(actor=_tenant_admin(), tenant_id=TENANT)

    material = SecretResolutionService(
        unit_of_work_factory=database,
        vault=vault,
    ).resolve(_context())

    after = durable.list_audit(actor=_tenant_admin(), tenant_id=TENANT)
    assert isinstance(material, EphemeralCertificateMaterial)
    assert after == before
    assert all("SYNTHETIC" not in repr(event) for event in after)


def test_control_plane_schema_remains_reference_only(tmp_path) -> None:
    database = _database(tmp_path)
    _onboard_and_bind(database)

    with sqlite3.connect(database.path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(fm_control_plane_secret_references)"
            ).fetchall()
        }

    assert columns == {
        "reference_id",
        "kind",
        "tenant_id",
        "unit_id",
        "environment",
        "provider_id",
    }
    forbidden = {
        "secret",
        "value",
        "material",
        "password",
        "token",
        "pfx",
        "csc",
        "private_key",
    }
    assert not (columns & forbidden)


def test_restart_preserves_reference_but_never_ephemeral_material(tmp_path) -> None:
    database = _database(tmp_path)
    certificate, csc, credentials = _onboard_and_bind(database)
    vault = _registered_vault(certificate, csc, credentials)
    service = SecretResolutionService(unit_of_work_factory=database, vault=vault)
    assert isinstance(service.resolve(_context()), EphemeralCertificateMaterial)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    empty_runtime_vault = InMemorySyntheticFiscalSecretVault()
    restarted_service = SecretResolutionService(
        unit_of_work_factory=restarted,
        vault=empty_runtime_vault,
    )

    with restarted.unit_of_work() as uow:
        reference = uow.control_plane.get_secret_reference(
            TENANT,
            UNIT,
            FiscalEnvironment.HOMOLOGATION,
            SecretReferenceKind.CERTIFICATE,
        )
    assert reference is not None
    with pytest.raises(SecretUnavailableError, match="host/reference"):
        restarted_service.resolve(_context())
