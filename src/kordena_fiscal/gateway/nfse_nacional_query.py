"""Read-only SEFIN Nacional recovery by immutable DPS identity (homologation).

Never POSTs, allocates fiscal numbering, changes an issuer or retries issuance.
Production-restricted GET /dps/{id} -> GET /nfse/{chaveAcesso} is documented
in the official 2025 taxpayer API manual and checked with the 2026 schema.
https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-em-homologacao/manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e.pdf

The owning canonical Control Plane must still bind QUERY to this exact provider,
scope, issuer municipality and tenant/unit before invoking this adapter.
"""
from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    OfficialNfseTransportError,
    require_nfse_national_issuer_eligibility,
)
from kordena_fiscal.gateway.nfse_national_homologation import (
    SEFIN_HOMOLOGATION_NFSE_URL,
    parse_nfse_homologation_response,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest, NfseAuthorizationResult
from kordena_fiscal.issuance.nfse_dps_builder import derive_national_dps_id
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

_BASE = SEFIN_HOMOLOGATION_NFSE_URL.removesuffix("/nfse")
_LIMIT = 2_097_152
_PROVIDER = GatewayProviderMetadata(NACIONAL_HOMOLOGATION_PROVIDER_ID, "1.0")


class NfseNationalLookupMissing(OfficialNfseTransportError):
    """The provider returned HTTP 404; no successful issuance is implied."""


def _get(path: str, tls: ssl.SSLContext, timeout: float) -> bytes:
    """Strict provider-owned GET boundary, without URL discovery or redirects."""
    if not (
        path.startswith("/dps/DPS") or path.startswith("/nfse/")
    ) or any(ch not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz/"
             for ch in path):
        raise OfficialNfseTransportError("Invalid national fiscal lookup path")
    url = _BASE + path
    try:
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        opener = build_opener(HTTPSHandler(context=tls), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as stream:
            raw = stream.read(_LIMIT + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise NfseNationalLookupMissing("NFS-e ainda nao localizada na SEFIN") from None
        raise OfficialNfseTransportError("Consulta SEFIN Nacional indisponivel") from None
    except (URLError, TimeoutError, OSError, ssl.SSLError):
        raise OfficialNfseTransportError("Consulta SEFIN Nacional indisponivel") from None
    if not isinstance(raw, bytes) or len(raw) > _LIMIT:
        raise OfficialNfseTransportError("Resposta nacional de consulta excede limite")
    return raw


def _payload(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise OfficialNfseTransportError("Consulta nacional sem resposta valida")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise OfficialNfseTransportError("Consulta nacional retornou JSON invalido") from None
    if not isinstance(value, dict):
        raise OfficialNfseTransportError("Consulta nacional retornou objeto invalido")
    return value


class NfseNacionalHomologationQueryGateway:
    """Reconcile original DPS once, without ever submitting it a second time."""

    def __init__(
        self,
        *,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        exchange_get: Callable[[str, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if not callable(resolve_certificate) or not 0 < timeout_seconds <= 60:
            raise ValueError("National query requires scoped A1 and bounded timeout")
        self._resolve_certificate = resolve_certificate
        self._exchange = exchange_get or _get
        self._timeout = timeout_seconds

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise OfficialNfseTransportError("Invalid canonical NFS-e recovery request")
        doc = request.document
        if doc.scope.environment is not FiscalEnvironment.HOMOLOGATION:
            raise OfficialNfseTransportError("National recovery limited to homologation")
        issuer = doc.issuer
        try:
            require_nfse_national_issuer_eligibility(
                jurisdiction=issuer.address.jurisdiction,
                tax_regime=issuer.tax_regime,
                competence_date=doc.competence_date,
            )
        except FiscalValidationError:
            raise OfficialNfseTransportError(
                "National issuer regime/competence unavailable"
            ) from None
        dps_id = derive_national_dps_id(request)
        a1 = self._resolve_certificate(doc.scope, issuer.cnpj.value)
        validate_a1_for_issuer(
            a1.pkcs12_bytes, a1.password, issuer_cnpj=Cnpj(issuer.cnpj.value),
            at=datetime.now(UTC),
        )
        tls = build_fiscal_tls_context(a1)
        try:
            first = _payload(self._exchange("/dps/" + dps_id, tls, self._timeout))
        except NfseNationalLookupMissing:
            return self._result(request, AuthorizationStatus.PENDING)
        key = first.get("chaveAcesso")
        if not isinstance(key, str) or len(key) != 50 or not key.isascii() or not key.isdecimal():
            raise OfficialNfseTransportError("DPS nao retornou uma chave fiscal valida")
        response = self._exchange("/nfse/" + key, tls, self._timeout)
        parsed = parse_nfse_homologation_response(response)
        if parsed["chaveAcesso"] != key:
            raise OfficialNfseTransportError("Chave divergente na consulta da NFS-e")
        return self._result(
            request, AuthorizationStatus.AUTHORIZED,
            invoice_reference=key,
            authorized_xml=parsed["xml"].encode("utf-8"),
        )

    @staticmethod
    def _result(
        request: NfseAuthorizationRequest,
        status: AuthorizationStatus,
        *,
        invoice_reference: str | None = None,
        authorized_xml: bytes | None = None,
    ) -> NfseAuthorizationResult:
        return NfseAuthorizationResult(
            status=status,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_PROVIDER,
            invoice_reference=invoice_reference,
            authorized_xml=authorized_xml,
        )
