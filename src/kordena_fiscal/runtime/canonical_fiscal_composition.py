"""Canonical runtime composition with explicit fail-closed fiscal provider boundaries.

The handlers are always registered. Provider credentials and official transports
must be provisioned independently; this module never simulates authorization.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.compliance.nfse_preaudit import (
    extrema_cancellation_preaudit,
    extrema_nfse_preaudit,
)
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
from kordena_fiscal.control_plane.service import ControlPlaneNotFoundError
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway import AuthorizationRequest, FiscalGatewayClient
from kordena_fiscal.gateway.cajamar_geisweb_cancellation_builder import (
    CajamarCancellationDecision,
)
from kordena_fiscal.gateway.mg_webiss_soap import (
    EXTREMA_IBGE,
    EXTREMA_WEBISS_PROVIDER_ID,
    WebissExtremaHomologationTransport,
)
from kordena_fiscal.gateway.nfe_sp_homologation import (
    MG_NFCE_HOMOLOGATION_PROVIDER_ID,
    MG_NFE_HOMOLOGATION_PROVIDER_ID,
    HomologationAuthorizationTarget,
    SefazSpHomologationGateway,
    build_mg_nfce_homologation_gateway,
    build_mg_nfe_homologation_gateway,
)
from kordena_fiscal.gateway.nfe_sp_operations_homologation import (
    SefazHomologationOperationsGateway,
    SefazSpHomologationOperationsGateway,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import AbrasfServiceFacts
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    NfseNacionalHomologationGateway,
)
from kordena_fiscal.gateway.nfse_national_query import (
    NfseNationalHomologationQueryGateway,
)
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_PROVIDER_ID,
    SantanaSimplissHomologationGateway,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.gateway.webiss_2026_schema import (
    load_pinned_extrema_webiss_rtc_schema,
)
from kordena_fiscal.gateway.webiss_extrema_canonical import (
    WebissExtremaCanonicalNfseGateway,
)
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseGatewayClient,
    NfseQueryClient,
)
from kordena_fiscal.operations import (
    CancellationRequest,
    CancellationResult,
    FiscalOperationsClient,
    FiscalOperationsGateway,
    FiscalQueryRequest,
    FiscalQueryResult,
    InutilizationRequest,
    InutilizationResult,
)
from kordena_fiscal.runtime.national_event_handlers import build_national_event_handlers
from kordena_fiscal.runtime.santana_event_handlers import build_santana_event_handlers
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.xml import NfeAccessKey

from .barueri_cancel_handlers import build_barueri_event_handlers
from .barueri_operational_composition import BarueriTrustedRuntimePorts
from .cajamar_operational_composition import CajamarTrustedRuntimePorts
from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler
from .jundiai_cancel_handlers import build_jundiai_event_handlers
from .guarulhos_giss_operational_composition import GuarulhosGissTrustedRuntimePorts
from .jundiai_operational_composition import JundiaiTrustedRuntimePorts
from .osasco_cancel_handlers import (
    build_osasco_cancel_handler,
    build_osasco_substitution_handler,
)
from .osasco_operational_composition import OsascoTrustedRuntimePorts
from .provider_issuance_handler import PreparedXmlGatewaySelector
from .provider_operation_wiring import build_provider_operation_handlers
from .sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
    build_sp4_canonical_clients,
)


def fiscal_external_dependency_snapshot(
    *, certificate_vault: EncryptedA1Vault | None,
    trusted_signed_dps_builder: Callable[
        [NfseAuthorizationRequest, EphemeralCertificateMaterial], bytes
    ] | None = None,
    nfse_preaudit: Callable[[NfseAuthorizationRequest], None] | None = None,
) -> dict[str, bool]:
    """Configuration status only; never assert taxpayer-specific issuance readiness.

    A configured Vault is not proof that a tenant has uploaded a valid certificate.
    Both SP NF-e and National NFS-e require a trustworthy signed-document
    preparation boundary; until that is provisioned, external execution is NOT ready.
    """
    vault_ready = isinstance(certificate_vault, EncryptedA1Vault)
    nfe_transport_ready = vault_ready
    nfse_transport_ready = (
        vault_ready and callable(trusted_signed_dps_builder) and callable(nfse_preaudit)
    )
    # Python signer and A1 mTLS are imported at composition time, but a signing
    # capability is only configured when an A1 Vault exists.
    signer_ready = vault_ready
    return {
        "fiscal_provider_transport_real_configured": nfe_transport_ready,
        "fiscal_external_secret_client_configured": vault_ready,
        "fiscal_signer_configured": signer_ready,
        "fiscal_runtime_external_execution_ready": (
            nfe_transport_ready and nfse_transport_ready and signer_ready
        ),
    }


class UnprovisionedFiscalGateway:
    """Concrete deny-by-default boundary until a tenant-scoped official adapter is bound."""

    @staticmethod
    def _unavailable() -> None:
        raise FiscalValidationError(
            "Certificado A1 não cadastrado para o CNPJ emitente ou provedor fiscal "
            "de homologação não configurado"
        )

    def authorize(self, request: Any) -> Any:
        self._unavailable()

    def query(self, request: Any) -> Any:
        self._unavailable()

    def cancel(self, request: Any) -> Any:
        self._unavailable()

    def inutilize(self, request: Any) -> Any:
        self._unavailable()


def _require_mg_binding(
    application: FiscalApplicationService, scope: ExecutionScope,
    access_key: NfeAccessKey, operation: ConfiguredFiscalOperation,
) -> None:
    label = {
        ConfiguredFiscalOperation.QUERY: "consulta MG",
        ConfiguredFiscalOperation.CANCEL: "cancelamento MG",
    }.get(operation, "autorização MG")
    if scope.environment is not FiscalEnvironment.HOMOLOGATION:
        raise FiscalValidationError(f"Operação de {label} disponível apenas em homologação")
    if scope.host_namespace is None or access_key.value[:2] != "31":
        raise FiscalValidationError(f"Operação de {label} exige escopo e chave UF MG")
    if access_key.model.value == 55:
        kind = FiscalDocumentKind.NFE
        expected_provider = MG_NFE_HOMOLOGATION_PROVIDER_ID
    elif access_key.model.value == 65:
        kind = FiscalDocumentKind.NFCE
        expected_provider = MG_NFCE_HOMOLOGATION_PROVIDER_ID
    else:
        raise FiscalValidationError(f"Operação de {label} com modelo não suportado")
    try:
        provider_id = application.resolve_configured_provider_id(
            scope=scope,
            document_kind=kind,
            jurisdiction=BrazilianJurisdiction("MG"),
            operation=operation.value,
        )
    except ControlPlaneNotFoundError as exc:
        raise FiscalValidationError(f"Vínculo fiscal de {label} indisponível") from exc
    if provider_id != expected_provider:
        raise FiscalValidationError(f"Provedor do vínculo de {label} incompatível")


class _GovernedNationalNfseGateway:
    """Enforce a durable unit binding and fiscal audit before accessing A1."""

    def __init__(
        self,
        *,
        application: FiscalApplicationService,
        preaudit: Callable[[NfseAuthorizationRequest], None],
        gateway: NfseNacionalHomologationGateway,
    ) -> None:
        self._application = application
        self._preaudit = preaudit
        self._gateway = gateway

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        document = request.document
        scope = document.scope
        jurisdiction = document.issuer.address.jurisdiction
        if (
            scope.environment is not FiscalEnvironment.HOMOLOGATION
            or scope.host_namespace is None
            or jurisdiction.municipality_ibge_code is None
        ):
            raise FiscalValidationError("NFS-e Nacional exige escopo de homologacao e municipio")
        try:
            provider_id = self._application.resolve_configured_provider_id(
                scope=scope,
                document_kind=FiscalDocumentKind.NFSE,
                jurisdiction=jurisdiction,
                operation=ConfiguredFiscalOperation.AUTHORIZE.value,
            )
        except ControlPlaneNotFoundError as exc:
            raise FiscalValidationError("Vinculo fiscal NFS-e Nacional indisponivel") from exc
        if provider_id != NACIONAL_HOMOLOGATION_PROVIDER_ID:
            raise FiscalValidationError("Provedor do vinculo NFS-e Nacional incompativel")
        self._preaudit(request)
        return self._gateway.authorize(request)


class _CanonicalWebissProviderResolver:
    """Pass only the durable control-plane binding into municipal transport."""

    def __init__(self, application: FiscalApplicationService) -> None:
        self._application = application

    def resolve_provider_id(
        self, *, scope: ExecutionScope, document_kind: FiscalDocumentKind,
        jurisdiction: BrazilianJurisdiction, operation: str,
    ) -> str:
        return self._application.resolve_configured_provider_id(
            scope=scope, document_kind=document_kind,
            jurisdiction=jurisdiction, operation=operation,
        )


class _GovernedNfseRouter:
    """Route national/Extrema issuances solely from exact persisted provider bindings."""

    def __init__(
        self, *, application: FiscalApplicationService,
        national: _GovernedNationalNfseGateway | None,
        extrema: WebissExtremaCanonicalNfseGateway | None,
        national_query: NfseNationalHomologationQueryGateway | None = None,
        municipal_issuance: Mapping[str, NfseGatewayClient] | None = None,
        municipal_recovery: Mapping[str, NfseQueryClient] | None = None,
    ) -> None:
        self._application = application
        self._national = national
        self._national_query = national_query
        self._extrema = extrema
        self._municipal_issuance = municipal_issuance or {}
        self._municipal_recovery = municipal_recovery or {}

    def _provider(self, request: NfseAuthorizationRequest) -> str:
        scope = request.document.scope
        if (
            scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not scope.host_namespace
        ):
            raise FiscalValidationError("NFS-e requires governed homologation scope")
        return self._application.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=request.document.issuer.address.jurisdiction,
            operation=ConfiguredFiscalOperation.AUTHORIZE.value,
        )

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        provider = self._provider(request)
        if provider == EXTREMA_WEBISS_PROVIDER_ID:
            if (
                self._extrema is None
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != EXTREMA_IBGE
            ):
                raise FiscalValidationError("Municipal Extrema gateway is not configured")
            return self._extrema.authorize(request)
        if provider == NACIONAL_HOMOLOGATION_PROVIDER_ID and self._national is not None:
            return self._national.authorize(request)
        municipal = self._municipal_issuance.get(provider)
        if municipal is not None:
            return municipal.authorize(request)
        raise FiscalValidationError("NFS-e issuance has no approved matching provider")

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        provider = self._provider(request)
        if provider == NACIONAL_HOMOLOGATION_PROVIDER_ID:
            if self._national_query is None:
                raise FiscalValidationError("Read-only NFS-e provider recovery is unavailable")
            # The query transport independently requires an exact QUERY binding.
            return self._national_query.query(request)
        if provider == EXTREMA_WEBISS_PROVIDER_ID:
            if (
                self._extrema is None
                or request.document.issuer.address.jurisdiction.municipality_ibge_code
                != EXTREMA_IBGE
            ):
                raise FiscalValidationError("Read-only NFS-e provider recovery is unavailable")
            return self._extrema.query(request)
        municipal = self._municipal_recovery.get(provider)
        if municipal is not None:
            # Canonical municipal loader reads the archived original RPS.
            # Query is read-only and never repeats the fiscal POST.
            return municipal.query(request)
        raise FiscalValidationError("Read-only NFS-e provider recovery is unavailable")


class _GovernedMgQueryGateway:
    def __init__(
        self,
        *,
        legacy: FiscalOperationsGateway,
        mg: FiscalOperationsGateway,
        application: FiscalApplicationService,
        mg_nfce: FiscalOperationsGateway | None = None,
    ) -> None:
        self._legacy = legacy
        self._mg = mg
        self._mg_nfce = mg_nfce
        self._application = application

    def _mg_for_model(self, access_key: NfeAccessKey) -> FiscalOperationsGateway:
        if access_key.model.value == 55:
            return self._mg
        if access_key.model.value == 65 and self._mg_nfce is not None:
            return self._mg_nfce
        raise FiscalValidationError("Gateway MG para modelo fiscal indisponível")

    def query(self, request: FiscalQueryRequest) -> FiscalQueryResult:
        if request.access_key.value[:2] != "31":
            return self._legacy.query(request)
        _require_mg_binding(
            self._application, request.scope, request.access_key, ConfiguredFiscalOperation.QUERY
        )
        return self._mg_for_model(request.access_key).query(request)

    def cancel(self, request: CancellationRequest) -> CancellationResult:
        if request.access_key.value[:2] != "31":
            return self._legacy.cancel(request)
        _require_mg_binding(
            self._application,
            scope=request.scope,
            access_key=request.access_key,
            operation=ConfiguredFiscalOperation.CANCEL,
        )
        return self._mg_for_model(request.access_key).cancel(request)

    def inutilize(self, request: InutilizationRequest) -> InutilizationResult:
        # Inutilization has no issuer/state on the command. Do not infer MG
        # from tenant or unit, or silently route all clients through MG.
        # A trusted fiscal profile/state resolver is required before cutover.
        return self._legacy.inutilize(request)


def build_runtime_fiscal_handler_factory(
    *,
    operations_gateway: Any | None = None,
    authorization_gateway: Any | None = None,
    certificate_vault: EncryptedA1Vault | None = None,
    nfse_gateway: NfseGatewayClient | None = None,
    trusted_signed_dps_builder: Callable[
        [NfseAuthorizationRequest, EphemeralCertificateMaterial], bytes
    ] | None = None,
    nfse_preaudit: Callable[[NfseAuthorizationRequest], None] | None = None,
    webiss_extrema_exchange: Callable[
        [bytes, str, ssl.SSLContext, float], bytes
    ] | None = None,
    webiss_service_preaudit: Callable[
        [tuple[AbrasfServiceFacts, ...]], None
    ] | None = None,
    sp4_reviewed_municipalities: Mapping[
        str, Sp4ReviewedMunicipalPorts
    ] | None = None,
    cajamar_verified_cancel: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, Sp4VerifiedInvoice],
        CajamarCancellationDecision,
    ] | None = None,
    cajamar_runtime_ports: CajamarTrustedRuntimePorts | None = None,
    cajamar_port_builder: Callable[
        [FiscalApplicationService], CajamarTrustedRuntimePorts
    ] | None = None,
    osasco_runtime_ports: OsascoTrustedRuntimePorts | None = None,
    osasco_port_builder: Callable[
        [FiscalApplicationService], OsascoTrustedRuntimePorts
    ] | None = None,
    barueri_runtime_ports: BarueriTrustedRuntimePorts | None = None,
    barueri_port_builder: Callable[
        [FiscalApplicationService], BarueriTrustedRuntimePorts
    ] | None = None,
    jundiai_runtime_ports: JundiaiTrustedRuntimePorts | None = None,
    jundiai_port_builder: Callable[
        [FiscalApplicationService], JundiaiTrustedRuntimePorts
    ] | None = None,
    guarulhos_runtime_ports: GuarulhosGissTrustedRuntimePorts | None = None,
    guarulhos_port_builder: Callable[
        [FiscalApplicationService], GuarulhosGissTrustedRuntimePorts
    ] | None = None,
    santana_port_builder: Callable[
        [FiscalApplicationService], SantanaSimplissHomologationGateway
    ] | None = None,
) -> Any:
    """Register all four canonical operations without granting fiscal readiness.

    Real official adapters can be supplied by the deployment composition.
    The default boundary is intentionally non-transmitting.
    """
    selected_operations = operations_gateway
    if selected_operations is None and certificate_vault is not None:
        selected_operations = SefazSpHomologationOperationsGateway(
            resolve_certificate=lambda scope, cnpj: certificate_vault.resolve(
                scope=scope, issuer_cnpj=cnpj
            )
        )
    selected_authorization = authorization_gateway
    if selected_authorization is None and certificate_vault is not None:
        selected_authorization = SefazSpHomologationGateway(
            resolve_certificate=lambda scope, cnpj: certificate_vault.resolve(
                scope=scope, issuer_cnpj=cnpj
            )
        )
    authorization = FiscalGatewayClient(
        selected_authorization or UnprovisionedFiscalGateway()
    )
    # National NFS-e requires an approved, trusted DPS preparation and XMLDSig
    # port; never derive its contents from browser payloads or send unsigned XML.
    if nfse_gateway is not None and trusted_signed_dps_builder is not None:
        raise ValueError("configure either an NFS-e gateway or a trusted DPS builder")
    if trusted_signed_dps_builder is not None and not callable(nfse_preaudit):
        raise ValueError("NFS-e signed DPS composition requires fiscal pre-audit")
    if sp4_reviewed_municipalities is not None and nfse_gateway is not None:
        raise ValueError("Municipal reviewed ports cannot coexist with an opaque gateway")
    if cajamar_runtime_ports is not None and (
        not isinstance(cajamar_runtime_ports, CajamarTrustedRuntimePorts)
        or sp4_reviewed_municipalities is not None
        or cajamar_verified_cancel is not None
        or nfse_gateway is not None
        or cajamar_port_builder is not None
    ):
        raise ValueError("Conflicting trusted Cajamar fiscal authorities")
    if cajamar_port_builder is not None and (
        not callable(cajamar_port_builder)
        or cajamar_verified_cancel is not None
        or sp4_reviewed_municipalities is not None
        or nfse_gateway is not None
    ):
        raise ValueError("Conflicting trusted Cajamar fiscal authorities")
    if cajamar_verified_cancel is not None and (
        not callable(cajamar_verified_cancel)
        or sp4_reviewed_municipalities is None
        or "cajamar-geisweb-homologation" not in sp4_reviewed_municipalities
    ):
        raise ValueError("Cajamar cancellation needs the existing reviewed municipal binding")
    if (
        osasco_runtime_ports is not None
        and (
            not isinstance(osasco_runtime_ports, OsascoTrustedRuntimePorts)
            or osasco_port_builder is not None
            or nfse_gateway is not None
        )
    ) or (
        osasco_port_builder is not None
        and (not callable(osasco_port_builder) or nfse_gateway is not None)
    ):
        raise ValueError("Conflicting reviewed Osasco municipal fiscal authorities")
    if (
        barueri_runtime_ports is not None
        and (not isinstance(barueri_runtime_ports, BarueriTrustedRuntimePorts)
             or barueri_port_builder is not None
             or nfse_gateway is not None)
    ) or (
        barueri_port_builder is not None
        and (not callable(barueri_port_builder) or nfse_gateway is not None)
    ):
        raise ValueError("Conflicting reviewed Barueri municipal fiscal authorities")
    if (
        jundiai_runtime_ports is not None
        and (not isinstance(jundiai_runtime_ports, JundiaiTrustedRuntimePorts)
             or jundiai_port_builder is not None or nfse_gateway is not None)
    ) or (
        jundiai_port_builder is not None
        and (not callable(jundiai_port_builder) or nfse_gateway is not None)
    ):
        raise ValueError("Conflicting reviewed Jundiai municipal fiscal authorities")
    if santana_port_builder is not None and (
        not callable(santana_port_builder) or nfse_gateway is not None
    ):
        raise ValueError("Conflicting reviewed Santana municipal fiscal authorities")
    if webiss_extrema_exchange is not None or webiss_service_preaudit is not None:
        if (
            nfse_gateway is not None
            or certificate_vault is None
            or not callable(nfse_preaudit)
            or not callable(webiss_service_preaudit)
            or not callable(webiss_extrema_exchange)
        ):
            raise ValueError(
                "WebISS requires A1 vault, canonical audit, service audit and approved exchange"
            )
    national_nfse = None
    if certificate_vault is not None and trusted_signed_dps_builder is not None:
        national_nfse = NfseNacionalHomologationGateway(
            resolve_certificate=lambda scope, cnpj: certificate_vault.resolve(
                scope=scope, issuer_cnpj=cnpj
            ),
            build_signed_dps=trusted_signed_dps_builder,
        )
    retention = RetentionPolicyMetadata(
        policy_id="nfcore-fiscal-archive", policy_version=1
    )

    def factory(
        application: FiscalApplicationService,
    ) -> Mapping[str, FiscalOperationHandler]:
        # The municipal ports are scoped to the same canonical application.
        # No secondary persistence, fiscal router, auth or signing identity.
        active_municipalities = sp4_reviewed_municipalities
        active_cajamar_cancel = cajamar_verified_cancel
        selected_cajamar_ports = (
            cajamar_port_builder(application)
            if cajamar_port_builder is not None else cajamar_runtime_ports
        )
        if selected_cajamar_ports is not None:
            if not isinstance(selected_cajamar_ports, CajamarTrustedRuntimePorts):
                raise ValueError("Cajamar operator provisioning returned invalid ports")
            reviewed_ports, reviewed_cancel = selected_cajamar_ports.attach(application)
            active_municipalities = {
                "cajamar-geisweb-homologation": reviewed_ports,
            }
            active_cajamar_cancel = reviewed_cancel
        selected_osasco_ports = (
            osasco_port_builder(application)
            if osasco_port_builder is not None else osasco_runtime_ports
        )
        active_osasco_cancel = None
        active_osasco_substitute = None
        if selected_osasco_ports is not None:
            if not isinstance(selected_osasco_ports, OsascoTrustedRuntimePorts):
                raise ValueError("Osasco operator provisioning returned invalid ports")
            if active_municipalities and "osasco-rtc-homologation" in active_municipalities:
                raise ValueError("Duplicate Osasco provider authority")
            active_municipalities = {
                **(active_municipalities or {}),
                "osasco-rtc-homologation": selected_osasco_ports.attach(application),
            }
            active_osasco_cancel = selected_osasco_ports.attach_verified_cancellation(
                application,
            )
            active_osasco_substitute = selected_osasco_ports.attach_verified_cancellation(
                application, cancel_type="S",
            )
        selected_barueri_ports = (
            barueri_port_builder(application)
            if barueri_port_builder is not None else barueri_runtime_ports
        )
        if selected_barueri_ports is not None:
            if not isinstance(selected_barueri_ports, BarueriTrustedRuntimePorts):
                raise ValueError("Barueri operator provisioning returned invalid ports")
            if active_municipalities and "barueri-pmb004-homologation" in active_municipalities:
                raise ValueError("Duplicate Barueri provider authority")
            active_municipalities = {
                **(active_municipalities or {}),
                "barueri-pmb004-homologation": selected_barueri_ports.attach(application),
            }
        selected_jundiai_ports = (
            jundiai_port_builder(application)
            if jundiai_port_builder is not None else jundiai_runtime_ports
        )
        if selected_jundiai_ports is not None:
            if not isinstance(selected_jundiai_ports, JundiaiTrustedRuntimePorts):
                raise ValueError("Jundiai operator provisioning returned invalid ports")
            if active_municipalities and "jundiai-giss-v2-homologation" in active_municipalities:
                raise ValueError("Duplicate Jundiai provider authority")
            active_municipalities = {
                **(active_municipalities or {}),
                "jundiai-giss-v2-homologation": selected_jundiai_ports.attach(application),
            }
        selected_guarulhos_ports = (
            guarulhos_port_builder(application)
            if guarulhos_port_builder is not None else guarulhos_runtime_ports
        )
        if selected_guarulhos_ports is not None:
            if not isinstance(selected_guarulhos_ports, GuarulhosGissTrustedRuntimePorts):
                raise ValueError("Guarulhos operator provisioning returned invalid ports")
            if active_municipalities and (
                "guarulhos-giss-v2-homologation" in active_municipalities
            ):
                raise ValueError("Duplicate Guarulhos provider authority")
            active_municipalities = {
                **(active_municipalities or {}),
                "guarulhos-giss-v2-homologation":
                    selected_guarulhos_ports.attach(application),
            }
        gateway = selected_operations or UnprovisionedFiscalGateway()
        if operations_gateway is None and certificate_vault is not None:
            vault = certificate_vault

            def resolve_mg_certificate(
                scope: ExecutionScope, cnpj: str,
            ) -> EphemeralCertificateMaterial:
                return vault.resolve(scope=scope, issuer_cnpj=cnpj)

            gateway = _GovernedMgQueryGateway(
                legacy=gateway,
                mg=SefazHomologationOperationsGateway(
                    resolve_certificate=resolve_mg_certificate,
                    target=HomologationAuthorizationTarget.MG_NFE,
                ),
                mg_nfce=SefazHomologationOperationsGateway(
                    resolve_certificate=resolve_mg_certificate,
                    target=HomologationAuthorizationTarget.MG_NFCE,
                ),
                application=application,
            )
        selector: PreparedXmlGatewaySelector | None = None
        if authorization_gateway is None and certificate_vault is not None:
            authorization_vault = certificate_vault

            def resolve_authorization_certificate(
                scope: ExecutionScope, cnpj: str,
            ) -> EphemeralCertificateMaterial:
                return authorization_vault.resolve(scope=scope, issuer_cnpj=cnpj)

            mg_authorization = FiscalGatewayClient(build_mg_nfe_homologation_gateway(
                resolve_certificate=resolve_authorization_certificate,
            ))
            mg_nfce_authorization = FiscalGatewayClient(build_mg_nfce_homologation_gateway(
                resolve_certificate=resolve_authorization_certificate,
            ))

            def select_xml_gateway(request: AuthorizationRequest) -> FiscalGatewayClient:
                if request.access_key.value[:2] != "31":
                    return authorization
                _require_mg_binding(
                    application, request.scope, request.access_key,
                    ConfiguredFiscalOperation.AUTHORIZE,
                )
                if request.access_key.model.value == 65:
                    return mg_nfce_authorization
                return mg_authorization

            selector = select_xml_gateway
        selected_nfse = nfse_gateway
        nfse_query_client: NfseQueryClient | None = None
        national_adapter = (
            _GovernedNationalNfseGateway(
                application=application, preaudit=nfse_preaudit,
                gateway=national_nfse,
            )
            if national_nfse is not None and nfse_preaudit is not None else None
        )
        extrema_adapter: WebissExtremaCanonicalNfseGateway | None = None
        if (
            webiss_extrema_exchange is not None
            and webiss_service_preaudit is not None
            and nfse_preaudit is not None
            and certificate_vault is not None
        ):
            evidence, validator = load_pinned_extrema_webiss_rtc_schema()
            current_vault = certificate_vault

            def resolve_extrema_a1(
                scope: ExecutionScope, cnpj: str,
            ) -> EphemeralCertificateMaterial:
                return current_vault.resolve(scope=scope, issuer_cnpj=cnpj)

            transport = WebissExtremaHomologationTransport(
                provider_resolver=_CanonicalWebissProviderResolver(application),
                resolve_certificate=resolve_extrema_a1,
                municipal_schema_evidence=evidence,
                municipal_schema_validator=validator,
                exchange=webiss_extrema_exchange,
            )
            extrema_adapter = WebissExtremaCanonicalNfseGateway(
                transport=transport,
                load_intent=application.load_extrema_rps_intent,
                resolve_certificate=resolve_extrema_a1,
                canonical_preaudit=extrema_nfse_preaudit,
                service_preaudit=webiss_service_preaudit,
                cancellation_preaudit=extrema_cancellation_preaudit,
                municipal_validator=validator,
            )
        municipal_issue: Mapping[str, NfseGatewayClient] = {}
        municipal_query: Mapping[str, NfseQueryClient] = {}
        if active_municipalities is not None:
            municipal_issue, municipal_query = build_sp4_canonical_clients(
                canonical_resolver=_CanonicalWebissProviderResolver(application),
                configured_municipalities=active_municipalities,
                canonical_rps_loader=application.load_sp4_original_rps,
            )
        reviewed_santana: SantanaSimplissHomologationGateway | None = None
        if santana_port_builder is not None:
            reviewed_santana = santana_port_builder(application)
            if not isinstance(reviewed_santana, SantanaSimplissHomologationGateway):
                raise ValueError("Santana reviewed gateway composition is incomplete")
            if SANTANA_PROVIDER_ID in municipal_issue:
                raise ValueError("Duplicate Santana municipal provider authority")
            municipal_issue = {
                **municipal_issue,
                SANTANA_PROVIDER_ID: NfseGatewayClient(reviewed_santana),
            }
            municipal_query = {
                **municipal_query,
                SANTANA_PROVIDER_ID: NfseQueryClient(reviewed_santana),
            }
        national_query = None
        if national_adapter is not None and certificate_vault is not None:
            national_query = NfseNationalHomologationQueryGateway(
                provider_resolver=_CanonicalWebissProviderResolver(application),
                resolve_certificate=lambda scope, cnpj: certificate_vault.resolve(
                    scope=scope, issuer_cnpj=cnpj,
                ),
            )
        if national_adapter is not None or extrema_adapter is not None or municipal_issue:
            router = _GovernedNfseRouter(
                application=application,
                national=national_adapter,
                extrema=extrema_adapter,
                national_query=national_query,
                municipal_issuance=municipal_issue,
                municipal_recovery=municipal_query,
            )
            selected_nfse = NfseGatewayClient(router)
            if extrema_adapter is not None or municipal_query or national_query is not None:
                # Never re-submit a national DPS or municipal RPS on an uncertain return.
                nfse_query_client = NfseQueryClient(router)
        handlers = build_provider_operation_handlers(
            FiscalOperationsClient(gateway),
            application=application,
            prepared_xml_gateway=authorization,
            select_xml_gateway=selector,
            prepared_nfse_gateway=selected_nfse,
            prepared_nfse_query_client=nfse_query_client,
            archive_retention=retention,
        )
        if national_adapter is not None and certificate_vault is not None:
            national_handlers = build_national_event_handlers(
                application=application,
                certificate_vault=certificate_vault,
                provider_resolver=_CanonicalWebissProviderResolver(application),
                retention=retention,
            )
            for operation, handler in national_handlers.items():
                if operation in handlers:
                    raise ValueError("Duplicate national fiscal event handler authority")
                handlers[operation] = handler
        if reviewed_santana is not None and reviewed_santana.supports_events:
            for operation, handler in build_santana_event_handlers(
                application=application, gateway=reviewed_santana,
                retention=retention,
            ).items():
                if operation in handlers:
                    raise ValueError("Duplicate Santana fiscal event handler authority")
                handlers[operation] = handler
        if (
            selected_barueri_ports is not None
            and selected_barueri_ports.supports_events
        ):
            for operation, handler in build_barueri_event_handlers(
                application=application, reviewed=selected_barueri_ports,
                retention=retention,
            ).items():
                if operation in handlers:
                    raise ValueError("Duplicate Barueri event handler authority")
                handlers[operation] = handler
        if (
            selected_jundiai_ports is not None
            and selected_jundiai_ports.supports_events
        ):
            for operation, handler in build_jundiai_event_handlers(
                application=application, reviewed=selected_jundiai_ports,
                retention=retention,
            ).items():
                if operation in handlers:
                    raise ValueError("Duplicate Jundiai fiscal event authority")
                handlers[operation] = handler
        if active_osasco_cancel is not None:
            handlers["cancelOsascoNfse"] = build_osasco_cancel_handler(
                application=application, verified_cancel=active_osasco_cancel,
                retention=retention,
            )
        if active_osasco_substitute is not None:
            handlers["substituteOsascoNfse"] = build_osasco_substitution_handler(
                application=application,
                verified_substitute_cancel=active_osasco_substitute,
                retention=retention,
            )
        if active_cajamar_cancel is not None:
            reviewed_cancel = active_cajamar_cancel

            def validate_cajamar_cancel(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> None:
                if (
                    not isinstance(key, str) or not key.strip() or len(key) > 256
                    or set(payload) != {
                        "unit_id", "environment", "document_id", "human_approval",
                        "cancellation_reason",
                    }
                    or payload.get("unit_id") != scope.unit_id
                    or payload.get("environment") != scope.environment.value
                    or payload.get("human_approval") is not True
                    or not isinstance(payload.get("document_id"), str)
                    or not str(payload["document_id"]).strip()
                    or not isinstance(payload.get("cancellation_reason"), str)
                ):
                    raise FiscalValidationError("Human-reviewed Cajamar cancellation required")
                application.preflight_cajamar_nfse_cancellation(
                    scope=scope, document_id=str(payload["document_id"]),
                    cancellation_reason=str(payload["cancellation_reason"]),
                )

            def execute_cajamar_cancel(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> Mapping[str, Any]:
                validate_cajamar_cancel(scope, payload, key)
                result = application.cancel_prepared_cajamar_nfse(
                    scope=scope, document_id=str(payload["document_id"]),
                    submit_verified_cancel=reviewed_cancel,
                    cancellation_reason=str(payload["cancellation_reason"]),
                    occurred_at=datetime.now(UTC), retention=retention,
                )
                return {
                    "document_id": str(payload["document_id"]),
                    "entry_id": result.archive_reference,
                    "status": result.lifecycle.state.value,
                    "official_fiscal_confirmation": result.decision.confirmed,
                    "rejection_code": result.decision.rejection_code,
                    "municipality_ibge": "3509205",
                }

            handlers["cancelCajamarNfse"] = PreflightFiscalOperationHandler(
                execute_cajamar_cancel, validate_cajamar_cancel,
            )
        if extrema_adapter is not None:
            cancellation_gateway = extrema_adapter

            def validate_extrema_cancel(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> None:
                fields = {
                    "unit_id", "environment", "document_id",
                    "cancellation_code", "human_approval",
                }
                if (
                    not key or not key.strip() or len(key) > 256
                    or set(payload) != fields
                    or payload.get("unit_id") != scope.unit_id
                    or payload.get("environment") != scope.environment.value
                    or payload.get("human_approval") is not True
                    or scope.environment is not FiscalEnvironment.HOMOLOGATION
                    or not isinstance(payload.get("document_id"), str)
                    or not isinstance(payload.get("cancellation_code"), str)
                    or payload["cancellation_code"] not in {"1", "2", "3", "4", "5"}
                ):
                    raise FiscalValidationError("Invalid approved Extrema cancellation intent")
                original = application.load_prepared_nfse_authorization(
                    scope, str(payload["document_id"]),
                )
                city = original.document.issuer.address.jurisdiction
                provider = application.resolve_configured_provider_id(
                    scope=scope, document_kind=FiscalDocumentKind.NFSE,
                    jurisdiction=city,
                    operation=ConfiguredFiscalOperation.CANCEL.value,
                )
                if (
                    city.municipality_ibge_code != EXTREMA_IBGE
                    or provider != EXTREMA_WEBISS_PROVIDER_ID
                ):
                    raise FiscalValidationError("Approved municipal cancellation binding missing")
                application.preflight_extrema_nfse_cancellation(
                    scope=scope, document_id=str(payload["document_id"]),
                )

            def execute_extrema_cancel(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> Mapping[str, Any]:
                validate_extrema_cancel(scope, payload, key)
                outcome = application.cancel_prepared_extrema_nfse(
                    scope=scope,
                    document_id=str(payload["document_id"]),
                    cancellation_code=str(payload["cancellation_code"]),
                    gateway=cancellation_gateway,
                    occurred_at=datetime.now(UTC),
                    retention=retention,
                )
                return {
                    "entry_id": outcome.archive_reference,
                    "document_id": str(payload["document_id"]),
                    "status": outcome.lifecycle.state.value,
                    "municipality_ibge": EXTREMA_IBGE,
                    "official_fiscal_confirmation": outcome.result.confirmed,
                    "rejection_code": outcome.result.rejection_code,
                }

            handlers["cancelExtremaNfse"] = PreflightFiscalOperationHandler(
                execute_extrema_cancel, validate_extrema_cancel,
            )
        if extrema_adapter is not None:
            replacement_gateway = extrema_adapter

            def validate_extrema_substitution(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> None:
                required_fields = {
                    "unit_id", "environment", "original_id", "replacement_id",
                    "cancellation_code", "human_approval",
                }
                if (
                    not key or not key.strip() or len(key) > 256
                    or set(payload) != required_fields
                    or payload.get("unit_id") != scope.unit_id
                    or payload.get("environment") != scope.environment.value
                    or payload.get("human_approval") is not True
                    or scope.environment is not FiscalEnvironment.HOMOLOGATION
                    or not isinstance(payload.get("original_id"), str)
                    or not isinstance(payload.get("replacement_id"), str)
                    or not isinstance(payload.get("cancellation_code"), str)
                    or payload["cancellation_code"] not in {"1", "2", "3", "4", "5"}
                ):
                    raise FiscalValidationError("Invalid human-reviewed municipal substitution")
                original = application.load_prepared_nfse_authorization(
                    scope, str(payload["original_id"]),
                )
                city = original.document.issuer.address.jurisdiction
                for operation in (
                    ConfiguredFiscalOperation.CANCEL,
                    ConfiguredFiscalOperation.AUTHORIZE,
                ):
                    provider = application.resolve_configured_provider_id(
                        scope=scope, document_kind=FiscalDocumentKind.NFSE,
                        jurisdiction=city, operation=operation.value,
                    )
                    if (
                        city.municipality_ibge_code != EXTREMA_IBGE
                        or provider != EXTREMA_WEBISS_PROVIDER_ID
                    ):
                        raise FiscalValidationError(
                            "Substitution requires both municipal provider bindings"
                        )
                application.preflight_extrema_nfse_substitution(
                    scope=scope, original_id=str(payload["original_id"]),
                    replacement_id=str(payload["replacement_id"]),
                )

            def execute_extrema_substitution(
                scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
            ) -> Mapping[str, Any]:
                validate_extrema_substitution(scope, payload, key)
                result = application.substitute_prepared_extrema_nfse(
                    scope=scope, original_id=str(payload["original_id"]),
                    replacement_id=str(payload["replacement_id"]),
                    cancellation_code=str(payload["cancellation_code"]),
                    gateway=replacement_gateway,
                    occurred_at=datetime.now(UTC),
                    retention=retention,
                )
                return {
                    "entry_id": result.archive_reference,
                    "original_id": str(payload["original_id"]),
                    "replacement_id": str(payload["replacement_id"]),
                    "original_status": result.original_lifecycle.state.value,
                    "replacement_status": result.replacement_lifecycle.state.value,
                    "official_fiscal_confirmation": result.result.confirmed,
                    "rejection_code": result.result.rejection_code,
                    "municipality_ibge": EXTREMA_IBGE,
                }

            handlers["substituteExtremaNfse"] = PreflightFiscalOperationHandler(
                execute_extrema_substitution, validate_extrema_substitution,
            )
        # Cajamar's official Decree 7.311/2024 provides municipal portal
        # substitution, not a reviewed GeisWeb SOAP operation. This handler
        # validates an original+candidate without altering either lifecycle.
        # It is available for human review even when municipal SOAP ports are
        # not provisioned; the fiscal documents must already exist.
        def validate_cajamar_substitution_review(
            scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
        ) -> None:
            if (
                set(payload) != {
                    "unit_id", "environment", "original_id",
                    "replacement_id", "human_approval",
                }
                or payload.get("unit_id") != scope.unit_id
                or payload.get("environment") != scope.environment.value
                or scope.environment is not FiscalEnvironment.HOMOLOGATION
                or payload.get("human_approval") is not True
                or not isinstance(payload.get("original_id"), str)
                or not isinstance(payload.get("replacement_id"), str)
                or not str(payload["original_id"]).strip()
                or not str(payload["replacement_id"]).strip()
            ):
                raise FiscalValidationError(
                    "Cajamar substitution review needs two approved document references"
                )
            application.review_prepared_cajamar_substitution(
                scope=scope,
                original_id=str(payload["original_id"]),
                replacement_id=str(payload["replacement_id"]),
                reviewed_at=datetime.now(UTC),
            )

        def execute_cajamar_substitution_review(
            scope: ExecutionScope, payload: Mapping[str, Any], key: str | None,
        ) -> Mapping[str, Any]:
            review = application.review_prepared_cajamar_substitution(
                scope=scope,
                original_id=str(payload["original_id"]),
                replacement_id=str(payload["replacement_id"]),
                reviewed_at=datetime.now(UTC),
            )
            return {
                "original_id": review.original_id,
                "replacement_id": review.replacement_id,
                "deadline": review.deadline.isoformat(),
                "status": review.municipal_action,
                "official_fiscal_confirmation": False,
                "municipal_portal_url": review.portal_url,
                "regulatory_evidence_url": review.decree_url,
                "municipality_ibge": "3509205",
            }

        handlers["reviewCajamarSubstitution"] = PreflightFiscalOperationHandler(
            execute_cajamar_substitution_review,
            validate_cajamar_substitution_review,
        )
        required = {
            "issueFiscalDocument",
            "queryFiscalDocument",
            "cancelFiscalDocument",
            "reconcileFiscalOperation",
        }
        if not required.issubset(handlers):
            raise RuntimeError("canonical fiscal operation composition is incomplete")
        return handlers

    return factory
