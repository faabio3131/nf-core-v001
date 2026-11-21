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
    NationalReceiptIdentity,
    NfseReceiptVerificationError,
    current_national_receipt_profile,
    require_national_receipt_signer_pins,
    validate_official_nfse_receipt,
)
from kordena_fiscal.gateway.nfse_national_receipt import (
    _verify_nfse_receipt_signature as _verify_nfse_receipt_signature,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.issuance.nfse_dps_identity import national_dps_id
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
    try:
        document = request.document
        municipality = document.issuer.address.jurisdiction.municipality_ibge_code
        if municipality is None or document.dps_number is None:
            raise FiscalValidationError("DPS serial unavailable")
        return national_dps_id(
            municipality, document.issuer.cnpj.value,
            document.dps_series, document.dps_number,
        )
    except FiscalValidationError:
        raise OfficialNfseTransportError(
            "Official DPS query requires a durably reserved legal issuer serial"
        ) from None


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



def _validate_official_nfse(
    raw: bytes, key: str, *, expected: NationalReceiptIdentity | None = None,
    schema_profile: str | None = None,
) -> bytes:
    """Compatibility entrypoint for national GET and replay callers."""
    try:
        return validate_official_nfse_receipt(
            raw, key, expected=expected, schema_profile=schema_profile,
        )
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


_LIVE_GET = _read_only_get


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
        # A read-only recovery must not trust an arbitrary XMLDSig leaf either.
        if self._get is _LIVE_GET:
            require_national_receipt_signer_pins()
            from kordena_fiscal.gateway.nfse_receipt_pki import (
                require_national_receipt_pki_ready,
            )
            require_national_receipt_pki_ready()
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
        profile = current_national_receipt_profile()
        authorized_xml = _validate_official_nfse(
            self._get(f"{_URL_BASE}/nfse/{key}", tls, self._timeout), key,
            expected=NationalReceiptIdentity.from_request(request, schema_profile=profile),
            schema_profile=profile,
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
