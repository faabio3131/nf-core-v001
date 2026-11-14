"""Read-only SEFIN Nacional DPS recovery, reusing the canonical fiscal authority.

GET /dps/{id} -> access key; GET /nfse/{key} -> authoritative XML.
This transport never POSTs DPS, cannot reassign numbers and cannot infer
authorization from a naked 50-digit key. Before field use it requires
official version-specific XSD/XMLDSig and receipt archival certification.
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
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_national_homologation import (
    SEFIN_HOMOLOGATION_NFSE_URL,
    OfficialNfseTransportError,
)
from kordena_fiscal.gateway.nfse_national_receipt import (
    NfseReceiptVerificationError,
    validate_official_nfse_receipt,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

_PROVIDER_ID = "nfse-nacional-producao-restrita"
_PROVIDER = GatewayProviderMetadata(_PROVIDER_ID, "1.0")
_URL_BASE = SEFIN_HOMOLOGATION_NFSE_URL.rsplit("/nfse", 1)[0]
_MAX_RESPONSE = 4_194_304


def _dps_id(request: NfseAuthorizationRequest) -> str:
    document = request.document
    cnpj = document.issuer.cnpj.value
    municipality = document.issuer.address.jurisdiction.municipality_ibge_code
    number = document.dps_number
    series = document.dps_series
    if (
        municipality is None or len(municipality) != 7
        or not municipality.isascii() or not municipality.isdecimal()
        or not cnpj.isascii() or not cnpj.isdecimal() or len(cnpj) != 14
        or number is None
        or not isinstance(number, int) or isinstance(number, bool)
        or not 1 <= number <= 999_999_999_999_999
        or not 1 <= series <= 99_999
    ):
        raise OfficialNfseTransportError(
            "Official DPS query requires a durably reserved legal issuer serial"
        )
    return f"DPS{municipality}1{cnpj}{series:05d}{number:015d}"


def _parse_key(raw: bytes, municipality: str) -> str:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise OfficialNfseTransportError("Invalid national DPS query response length")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise OfficialNfseTransportError("Invalid national DPS query JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("chaveAcesso"), str):
        raise OfficialNfseTransportError("National DPS query has no confirmed access key")
    key: str = payload["chaveAcesso"]
    if not key.isascii() or not key.isdecimal() or len(key) != 50:
        raise OfficialNfseTransportError("Invalid official NFS-e access key")
    if not key.startswith(municipality[:2]):
        raise OfficialNfseTransportError("Official NFS-e key does not match issuer UF")
    return key



def _validate_official_nfse(raw: bytes, key: str) -> bytes:
    """Compatibility entrypoint for national GET and replay callers."""
    try:
        return validate_official_nfse_receipt(raw, key)
    except NfseReceiptVerificationError as exc:
        raise OfficialNfseTransportError(str(exc)) from None


def _read_only_get(path: str, context: ssl.SSLContext, timeout: float) -> bytes:
    if not path.startswith(_URL_BASE + "/"):
        raise OfficialNfseTransportError("National API request path invalid")
    request = Request(
        path, method="GET", headers={"Accept": "application/json"},
    )
    try:
        opener = build_opener(HTTPSHandler(context=context), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as response:
            result = response.read(_MAX_RESPONSE + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise OfficialNfseTransportError(
            "Ambiguous national NFS-e query; reconcile without retransmitting DPS"
        ) from None
    if len(result) > _MAX_RESPONSE:
        raise OfficialNfseTransportError("National query response exceeds limit")
    return bytes(result)


class NfseNationalHomologationQueryGateway:
    """Retrieve an existing DPS only; binding and A1 must match exact issuer unit."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        exchange_get: Callable[[str, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if (
            not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("SEFIN query requires canonical binding, A1 and timeout")
        self._provider_resolver = provider_resolver
        self._resolve_certificate = resolve_certificate
        self._get = exchange_get or _read_only_get
        self._timeout = timeout_seconds

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise FiscalValidationError("NFS-e query requires canonical prepared request")
        document = request.document
        scope = document.scope
        jurisdiction = document.issuer.address.jurisdiction
        if (
            scope.host_namespace is None
            or scope.environment is not FiscalEnvironment.HOMOLOGATION
            or jurisdiction.municipality_ibge_code is None
        ):
            raise OfficialNfseTransportError("National NFS-e query requires trusted scope")
        dps_id = _dps_id(request)
        bound = self._provider_resolver.resolve_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=jurisdiction, operation="query",
        )
        if bound != _PROVIDER_ID:
            raise OfficialNfseTransportError("National NFS-e query provider is not bound")
        issuer_cnpj = document.issuer.cnpj.value
        material = self._resolve_certificate(scope, issuer_cnpj)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=Cnpj(issuer_cnpj), at=datetime.now(UTC),
        )
        tls = build_fiscal_tls_context(material)
        key = _parse_key(
            self._get(f"{_URL_BASE}/dps/{dps_id}", tls, self._timeout),
            jurisdiction.municipality_ibge_code,
        )
        authorized_xml = _validate_official_nfse(
            self._get(f"{_URL_BASE}/nfse/{key}", tls, self._timeout), key,
        )
        return NfseAuthorizationResult(
            status=AuthorizationStatus.AUTHORIZED,
            scope=scope, document_id=document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_PROVIDER,
            provider_request_id=dps_id,
            invoice_reference=key,
            authorized_xml=authorized_xml,
        )
