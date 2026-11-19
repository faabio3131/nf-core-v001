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
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.xml import NfeAccessKey

from .fiscal_runtime import FiscalOperationHandler, PreflightFiscalOperationHandler
from .provider_issuance_handler import PreparedXmlGatewaySelector
from .provider_operation_wiring import build_provider_operation_handlers


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
    ) -> None:
        self._application = application
        self._national = national
        self._extrema = extrema

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
        raise FiscalValidationError("NFS-e issuance has no approved matching provider")

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        provider = self._provider(request)
        if (
            provider != EXTREMA_WEBISS_PROVIDER_ID
            or self._extrema is None
            or request.document.issuer.address.jurisdiction.municipality_ibge_code
            != EXTREMA_IBGE
        ):
            raise FiscalValidationError("Read-only NFS-e provider recovery is unavailable")
        return self._extrema.query(request)


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
        if national_adapter is not None or extrema_adapter is not None:
            router = _GovernedNfseRouter(
                application=application,
                national=national_adapter,
                extrema=extrema_adapter,
            )
            selected_nfse = NfseGatewayClient(router)
            if extrema_adapter is not None:
                # The canonical durable recovery handler performs only the
                # original RPS query, never a second issuance POST.
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
