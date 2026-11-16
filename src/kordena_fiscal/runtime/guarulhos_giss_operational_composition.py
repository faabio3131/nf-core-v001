"""Guarulhos GissOnline V2 reuses the *same* canonical GissOnline 2.04 ports.

Source: https://guarulhos.giss.com.br/giss-ajuda/desenvolvedores.html
It publishes current Serviços Prestados V1.8 and RTC XSDs. No transport is
provisioned unless trusted WSDL+XSD signature verification ports are supplied.
The current Guarulhos fiscal channel gate is already in municipal_sp_routing;
no new rule engine, database or authentication is introduced.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissHomologationTransport,
    JundiaiGissWsdlContract,
)
from kordena_fiscal.gateway.municipal_sp_routing import (
    GUARULHOS_GISS_V2_PROVIDER_ID,
    GUARULHOS_IBGE,
)
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .jundiai_operational_composition import JundiaiTrustedRuntimePorts
from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts


@dataclass(frozen=True, slots=True)
class GuarulhosGissTrustedRuntimePorts:
    """Explicit opt-in Guarulhos wrapper over reviewed, shared GissOnline ports."""

    shared_giss: JundiaiTrustedRuntimePorts

    def __post_init__(self) -> None:
        if (
            not isinstance(self.shared_giss, JundiaiTrustedRuntimePorts)
            or self.shared_giss.transport.municipality_ibge != GUARULHOS_IBGE
        ):
            raise FiscalValidationError(
                "Guarulhos needs reviewed GissOnline ports for its own municipality"
            )

    def attach(self, application: FiscalApplicationService) -> Sp4ReviewedMunicipalPorts:
        return self.shared_giss.attach(application)


def build_guarulhos_giss_trusted_transport(
    *,
    application: FiscalApplicationService,
    vault: EncryptedA1Vault,
    contract_for_method: Callable[[str], JundiaiGissWsdlContract],
    validate_signed_xml: Callable[[bytes, str, str], None],
) -> JundiaiGissHomologationTransport:
    """Bind municipal A1, operation and issuer to existing canonical authorities."""
    if (
        not isinstance(application, FiscalApplicationService)
        or not isinstance(vault, EncryptedA1Vault)
        or not callable(contract_for_method)
        or not callable(validate_signed_xml)
    ):
        raise FiscalValidationError("Guarulhos requires audited WSDL/XSD and canonical A1")

    class CanonicalResolver:
        def resolve_provider_id(
            self, *, scope: ExecutionScope,
            document_kind: FiscalDocumentKind,
            jurisdiction: BrazilianJurisdiction, operation: str,
        ) -> str:
            return application.resolve_configured_provider_id(
                scope=scope, document_kind=document_kind,
                jurisdiction=jurisdiction, operation=operation,
            )

    return JundiaiGissHomologationTransport(
        resolver=CanonicalResolver(),
        resolve_certificate=lambda scope, cnpj: vault.resolve(
            scope=scope, issuer_cnpj=cnpj,
        ),
        contract_for_method=contract_for_method,
        validate_signed_xml=validate_signed_xml,
        municipality_ibge=GUARULHOS_IBGE,
        provider_id=GUARULHOS_GISS_V2_PROVIDER_ID,
    )
