"""Official NFS-e Nacional SEFIN production-restrita (tpAmb=2) REST transport.

Receives schema-valid, already XMLDSig-signed DPS from the canonical document
preparation authority. Never builds a DPS from untrusted browser JSON.
"""
from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import (
    AuthorizationStatus,
    GatewayProviderMetadata,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.mg_nfse_channel_guard import require_mg_national_channel_eligibility
from kordena_fiscal.gateway.nfse_national_homologation import (
    SEFIN_HOMOLOGATION_NFSE_URL,
    build_nfse_dps_request,
    parse_nfse_homologation_response,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

NACIONAL_HOMOLOGATION_NFSE_URL = SEFIN_HOMOLOGATION_NFSE_URL
_MAX_RESPONSE = 2_097_152
NACIONAL_HOMOLOGATION_PROVIDER_ID = "nfse-nacional-producao-restrita"
_PROVIDER = GatewayProviderMetadata(NACIONAL_HOMOLOGATION_PROVIDER_ID, "1.0")


class OfficialNfseTransportError(FiscalValidationError):
    """Transport failure with secrets and upstream response stripped."""


def encode_signed_dps(
    signed_dps: bytes, *, issuer_cnpj: str | None = None,
    issuer_municipality_ibge: str | None = None,
) -> bytes:
    """Strict DPS envelope for national NFS-e POST /nfse."""
    try:
        return build_nfse_dps_request(
            signed_dps, issuer_cnpj=issuer_cnpj,
            issuer_municipality_ibge=issuer_municipality_ibge,
        )
    except FiscalValidationError as exc:
        raise OfficialNfseTransportError(str(exc)) from None


def _exchange_http(payload: bytes, context: ssl.SSLContext, timeout: float) -> bytes:
    req = Request(
        NACIONAL_HOMOLOGATION_NFSE_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
        with opener.open(req, timeout=timeout) as response:
            data = response.read(_MAX_RESPONSE + 1)
        if len(data) > _MAX_RESPONSE:
            raise OfficialNfseTransportError("Resposta nacional excede limite")
        return bytes(data)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise OfficialNfseTransportError(
            "Comunicação com SEFIN Nacional indisponível; consulte antes de retransmitir"
        ) from None


class NfseNacionalHomologationGateway:
    """Real REST/mTLS transport with trusted prepared signed-DPS dependency."""

    def __init__(
        self,
        *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        build_signed_dps: Callable[[NfseAuthorizationRequest, EphemeralCertificateMaterial], bytes],
        exchange: Callable[[bytes, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if not callable(resolve_certificate) or not callable(build_signed_dps):
            raise ValueError("NFS-e requires trusted certificate and DPS preparation ports")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Invalid NFS-e timeout")
        self._resolve_certificate = resolve_certificate
        self._build_signed_dps = build_signed_dps
        self._exchange = exchange or _exchange_http
        self._timeout = timeout_seconds

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise OfficialNfseTransportError("Solicitação NFS-e inválida")
        document = request.document
        if document.scope.environment is not FiscalEnvironment.HOMOLOGATION:
            raise OfficialNfseTransportError("NFS-e disponível apenas com tpAmb=2")
        issuer_cnpj = document.issuer.cnpj.value
        issuer_municipality = document.issuer.address.jurisdiction.municipality_ibge_code
        if issuer_municipality is None:
            raise OfficialNfseTransportError("DPS requires an issuer municipality")
        try:
            require_mg_national_channel_eligibility(
                jurisdiction=document.issuer.address.jurisdiction,
                tax_regime=document.issuer.tax_regime,
                competence_date=document.competence_date,
            )
        except FiscalValidationError:
            # Never open the A1 vault or contact SEFIN for a wrong issuer.
            municipality_label = (
                "Contagem/MG" if issuer_municipality == "3118601"
                else f"IBGE {issuer_municipality}/MG"
            )
            raise OfficialNfseTransportError(
                f"{municipality_label}: contrato do Emissor Nacional nao autorizado "
                "para regime e competencia informados"
            ) from None
        material = self._resolve_certificate(document.scope, issuer_cnpj)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password, issuer_cnpj=Cnpj(issuer_cnpj),
            at=datetime.now(UTC),
        )
        signed_dps = self._build_signed_dps(request, material)
        payload = encode_signed_dps(
            signed_dps, issuer_cnpj=issuer_cnpj, issuer_municipality_ibge=issuer_municipality,
        )
        response = self._exchange(payload, build_fiscal_tls_context(material), self._timeout)
        if not isinstance(response, bytes) or len(response) > _MAX_RESPONSE:
            raise OfficialNfseTransportError("Resposta SEFIN inválida")
        try:
            result = json.loads(response)
            if not isinstance(result, dict) or result.get("tipoAmbiente") != 2:
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            raise OfficialNfseTransportError("Resposta SEFIN sem homologação válida") from None

        key = result.get("chaveAcesso")
        if isinstance(key, str) and key:
            # The access key alone is not proof of an authorized invoice.
            # The SEFIN must provide the corresponding decompressible XML.
            # The shared parser bounds gzip size and validates its XML.
            parsed = parse_nfse_homologation_response(response)
            if parsed.get("chaveAcesso") != key:
                raise OfficialNfseTransportError("NFS-e autorizada com chave divergente")
            status = AuthorizationStatus.AUTHORIZED
            kwargs = {"invoice_reference": key[:512]}
        else:
            errors = result.get("erros")
            if isinstance(errors, list) and errors:
                first = errors[0] if isinstance(errors[0], dict) else {}
                status = AuthorizationStatus.REJECTED
                kwargs = {
                    "rejection_code": str(
                        first.get("Codigo", first.get("codigo", "NFSE_REJECTED"))
                    )[:512],
                    "rejection_message": str(
                        first.get("Descricao", first.get("descricao", "DPS rejeitada"))
                    )[:512],
                }
            else:
                status = AuthorizationStatus.PENDING
                kwargs = {}
        return NfseAuthorizationResult(
            status=status, scope=document.scope, document_id=document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_PROVIDER,
            provider_request_id=str(result["idDps"])[:512]
            if isinstance(result.get("idDps"), str) else None,
            invoice_reference=kwargs.get("invoice_reference"),
            rejection_code=kwargs.get("rejection_code"),
            rejection_message=kwargs.get("rejection_message"),
        )
