from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from kordena_fiscal.control_plane import (
    AdminPrincipal,
    CommercialConfigurationService,
    ConfiguredFiscalOperation,
    ControlPlaneNotFoundError,
    ControlPlanePermission,
    DurableControlPlaneService,
    DurableProviderBindingResolver,
    FiscalUnitRegistration,
    ProviderBinding,
    ProviderRuntimePolicyConfig,
    SecretReference,
    SecretReferenceKind,
    UnitModuleBinding,
    WebhookDestinationConfig,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalProductProfile,
    FiscalUnitCode,
    FiscalValidationError,
    NcmCode,
    ProductOrigin,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase

HML = FiscalEnvironment.HOMOLOGATION
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Customer:
    tenant_id: str
    unit_id: str
    host_namespace: str
    provider_id: str
    jurisdiction: BrazilianJurisdiction
    documents: tuple[FiscalDocumentKind, ...]
    module_id: str
    product_id: str


CUSTOMERS = (
    _Customer(
        tenant_id="restaurant-sp",
        unit_id="matriz-sp",
        host_namespace="fm.kordena",
        provider_id="provider-a",
        jurisdiction=BrazilianJurisdiction("SP"),
        documents=(FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE),
        module_id="restaurant",
        product_id="SKU-SP-001",
    ),
    _Customer(
        tenant_id="academia-sp",
        unit_id="servicos-sp",
        host_namespace="fm.iron",
        provider_id="provider-b",
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        documents=(FiscalDocumentKind.NFSE,),
        module_id="standard",
        product_id="SERVICE-SP-001",
    ),
    _Customer(
        tenant_id="varejo-mg",
        unit_id="loja-mg",
        host_namespace="fm.sales",
        provider_id="provider-c",
        jurisdiction=BrazilianJurisdiction("MG"),
        documents=(FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE),
        module_id="standard",
        product_id="SKU-MG-001",
    ),
)


def _admin() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="commercial-config-admin",
        permissions=frozenset(
            {
                ControlPlanePermission.ORGANIZATION_WRITE,
                ControlPlanePermission.UNIT_WRITE,
                ControlPlanePermission.SECRET_REFERENCE_WRITE,
                ControlPlanePermission.COMMERCIAL_CONFIG_WRITE,
                ControlPlanePermission.AUDIT_READ,
            }
        ),
        global_scope=True,
    )


def _scope(customer: _Customer) -> ExecutionScope:
    return ExecutionScope(
        host_namespace=customer.host_namespace,
        tenant_id=customer.tenant_id,
        unit_id=customer.unit_id,
        environment=HML,
        correlation_id=f"onboarding-{customer.tenant_id}",
    )


def _profile(customer: _Customer) -> FiscalProductProfile:
    return FiscalProductProfile(
        profile_id=f"product-profile-{customer.tenant_id}",
        product_id=customer.product_id,
        scope=_scope(customer),
        commercial_code=customer.product_id,
        description=f"Synthetic fiscal item for {customer.tenant_id}",
        ncm=NcmCode("21069090"),
        commercial_unit=FiscalUnitCode("UN"),
        taxable_unit=FiscalUnitCode("UN"),
        origin=ProductOrigin.NATIONAL,
        effective_from=NOW,
    )


def _bind_secrets(
    control_plane: DurableControlPlaneService,
    actor: AdminPrincipal,
    customer: _Customer,
) -> None:
    references = [
        SecretReference(
            reference_id=(
                f"ref:commercial/{customer.tenant_id}/{customer.unit_id}/certificate"
            ),
            kind=SecretReferenceKind.CERTIFICATE,
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            environment=HML,
        ),
        SecretReference(
            reference_id=(
                f"ref:commercial/{customer.tenant_id}/{customer.unit_id}/"
                f"{customer.provider_id}/credentials"
            ),
            kind=SecretReferenceKind.CREDENTIALS,
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            environment=HML,
            provider_id=customer.provider_id,
        ),
    ]
    if FiscalDocumentKind.NFCE in customer.documents:
        references.append(
            SecretReference(
                reference_id=(
                    f"ref:commercial/{customer.tenant_id}/{customer.unit_id}/"
                    f"{customer.provider_id}/csc"
                ),
                kind=SecretReferenceKind.CSC,
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
                provider_id=customer.provider_id,
            )
        )
    for reference in references:
        control_plane.bind_secret_reference(
            actor=actor,
            reference=reference,
            correlation_id=f"bind-{customer.tenant_id}-{reference.kind.value}",
        )


def _configure_customer(
    database: SqliteFiscalDatabase,
    actor: AdminPrincipal,
    customer: _Customer,
) -> None:
    control_plane = DurableControlPlaneService(database)
    commercial = CommercialConfigurationService(database)
    control_plane.onboard_organization(
        actor=actor,
        tenant_id=customer.tenant_id,
        legal_name=f"Synthetic {customer.tenant_id}",
        correlation_id=f"org-{customer.tenant_id}",
    )
    control_plane.onboard_unit(
        actor=actor,
        registration=FiscalUnitRegistration(
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            display_name=f"Synthetic {customer.unit_id}",
            enabled_environments=frozenset({HML}),
        ),
        correlation_id=f"unit-{customer.tenant_id}",
    )
    _bind_secrets(control_plane, actor, customer)
    commercial.add_product_profile(actor=actor, profile=_profile(customer))
    commercial.set_module_binding(
        actor=actor,
        binding=UnitModuleBinding(
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            environment=HML,
            module_id=customer.module_id,
        ),
    )
    commercial.set_webhook_destination(
        actor=actor,
        destination=WebhookDestinationConfig(
            destination_id=f"events-{customer.provider_id}",
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            environment=HML,
            url=f"https://{customer.tenant_id}.example.invalid/fiscal-events",
        ),
    )
    commercial.set_runtime_policy(
        actor=actor,
        policy=ProviderRuntimePolicyConfig(
            policy_id=f"runtime-{customer.provider_id}",
            tenant_id=customer.tenant_id,
            unit_id=customer.unit_id,
            environment=HML,
            provider_id=customer.provider_id,
            connect_timeout_seconds=3,
            read_timeout_seconds=12,
            max_attempts=3,
            base_delay_seconds=0.25,
            max_delay_seconds=3,
            jitter_ratio=0.15,
            circuit_failure_threshold=3,
            circuit_recovery_seconds=30,
        ),
    )
    for document_kind in customer.documents:
        commercial.set_provider_binding(
            actor=actor,
            binding=ProviderBinding(
                binding_id=(
                    f"binding-{customer.tenant_id}-{document_kind.value}-authorize"
                ),
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
                document_kind=document_kind,
                jurisdiction=customer.jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE,
                provider_id=customer.provider_id,
            ),
        )


def test_three_distinct_customers_survive_restart_with_same_source(tmp_path) -> None:
    database = SqliteFiscalDatabase(tmp_path / "zero-code-onboarding.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    actor = _admin()

    for customer in CUSTOMERS:
        _configure_customer(database, actor, customer)

    restarted = SqliteFiscalDatabase(database.path)
    assert restarted.initialize() == ()
    resolver = DurableProviderBindingResolver(restarted)

    for customer in CUSTOMERS:
        scope = _scope(customer)
        for document_kind in customer.documents:
            provider_id = resolver.resolve_provider_id(
                scope=scope,
                document_kind=document_kind,
                jurisdiction=customer.jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE.value,
            )
            assert provider_id == customer.provider_id

        with restarted.unit_of_work() as uow:
            product = uow.commercial.resolve_product_profile(
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
                product_id=customer.product_id,
                instant=NOW,
            )
            modules = uow.commercial.list_module_bindings(
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
            )
            webhooks = uow.commercial.list_webhook_destinations(
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
            )
            policy = uow.commercial.get_runtime_policy(
                tenant_id=customer.tenant_id,
                unit_id=customer.unit_id,
                environment=HML,
                provider_id=customer.provider_id,
            )
            credentials = uow.control_plane.get_secret_reference(
                customer.tenant_id,
                customer.unit_id,
                HML,
                SecretReferenceKind.CREDENTIALS,
                provider_id=customer.provider_id,
            )

        assert product is not None and product.product_id == customer.product_id
        assert [binding.module_id for binding in modules if binding.enabled] == [
            customer.module_id
        ]
        assert len(webhooks) == 1 and webhooks[0].enabled
        assert policy is not None and policy.provider_id == customer.provider_id
        assert credentials is not None
        assert credentials.provider_id == customer.provider_id


def test_customer_configuration_is_exact_and_cross_partition_lookup_fails_closed(
    tmp_path,
) -> None:
    database = SqliteFiscalDatabase(tmp_path / "zero-code-isolation.sqlite3")
    assert database.initialize() == (1, 2, 3, 4, 5, 13, 14, 17, 18, 19)
    actor = _admin()
    restaurant = CUSTOMERS[0]
    retail = CUSTOMERS[2]
    _configure_customer(database, actor, restaurant)
    _configure_customer(database, actor, retail)
    resolver = DurableProviderBindingResolver(database)

    with pytest.raises(ControlPlaneNotFoundError, match="provider binding"):
        resolver.resolve_provider_id(
            scope=ExecutionScope(
                host_namespace=restaurant.host_namespace,
                tenant_id=restaurant.tenant_id,
                unit_id=retail.unit_id,
                environment=HML,
                correlation_id="cross-unit",
            ),
            document_kind=FiscalDocumentKind.NFE,
            jurisdiction=restaurant.jurisdiction,
            operation=ConfiguredFiscalOperation.AUTHORIZE.value,
        )

    with database.unit_of_work() as uow:
        assert (
            uow.control_plane.get_secret_reference(
                restaurant.tenant_id,
                restaurant.unit_id,
                HML,
                SecretReferenceKind.CREDENTIALS,
                provider_id=retail.provider_id,
            )
            is None
        )
        assert (
            uow.commercial.resolve_product_profile(
                tenant_id=restaurant.tenant_id,
                unit_id=restaurant.unit_id,
                environment=HML,
                product_id=retail.product_id,
                instant=NOW,
            )
            is None
        )


def test_nfse_provider_binding_is_municipality_specific() -> None:
    with pytest.raises(FiscalValidationError, match="municipality"):
        ProviderBinding(
            binding_id="nfse-without-municipality",
            tenant_id="academia-sp",
            unit_id="servicos-sp",
            environment=HML,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP"),
            operation=ConfiguredFiscalOperation.AUTHORIZE,
            provider_id="provider-b",
        )
