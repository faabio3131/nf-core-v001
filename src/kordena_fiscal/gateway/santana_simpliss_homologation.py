"""Santana de Parnaíba: reviewed Simpliss municipal JSON/GZIP/XMLDSig API.

Reuses the canonical national DPS signer, durable numbering, A1, fiscal UoW
and signed receipt verifier. The actual /nfse URL is operator reviewed:
the public Swagger currently denies unattended retrieval. Never repeat a
fiscal POST after an ambiguous response or invent a DPS lookup endpoint.
"""
from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import (
    AuthorizationStatus,
    GatewayProviderMetadata,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.municipal_sp_routing import (
    require_sp_municipal_nfse_issuance_permitted,
)
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationReceipt,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import encode_signed_dps
from kordena_fiscal.gateway.nfse_national_receipt import validate_nfse_receipt_integrity
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
    NfseRejectionDetail,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.xml.santana_simpliss_schema import santana_official_validator
from kordena_fiscal.xml.schema import XmlSchemaValidationError

if TYPE_CHECKING:
    from kordena_fiscal.gateway.santana_simpliss_events import SantanaVerifiedEvent
    from kordena_fiscal.gateway.santana_simpliss_substitution import (
        SantanaSubstitutionReview,
    )

SANTANA_PROVIDER_ID = "santana-simpliss-v1-homologation"
SANTANA_IBGE = "3547304"
_HOMOLOGATION_HOST = "producaorestrita.simplissweb.com.br"
_PROVIDER = GatewayProviderMetadata(SANTANA_PROVIDER_ID, "1.00")
_MAX_RESPONSE = 4_194_304


class SantanaSimplissError(FiscalValidationError):
    """Non-secret municipal integration error."""


def _valid_key(key: object) -> bool:
    return (
        type(key) is str and len(key) == 50
        and key.isascii() and key.isdecimal() and key.startswith("35")
    )


@dataclass(frozen=True, slots=True)
class SantanaSimplissEndpoint:
    """Exact POST /nfse URL; an operator must verify the prefix in official Swagger."""

    issue_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.issue_url, str):
            raise SantanaSimplissError("Reviewed Santana API URL is mandatory")
        parsed = urlsplit(self.issue_url)
        try:
            valid_port = parsed.port in (None, 443)
        except ValueError:
            valid_port = False
        if (
            parsed.scheme != "https"
            or parsed.hostname != _HOMOLOGATION_HOST
            or not valid_port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query or parsed.fragment
            or not parsed.path.endswith("/nfse")
            or parsed.path.startswith("//")
            or "%" in parsed.path
            or any(p in ("", ".", "..") for p in parsed.path.split("/")[1:])
        ):
            raise SantanaSimplissError("Santana requires pinned restricted HTTPS /nfse URL")

    def invoice_url(self, access_key: str) -> str:
        if not _valid_key(access_key):
            raise SantanaSimplissError("Invalid scoped Santana NFS-e access key")
        return self.issue_url + "/" + access_key

    def events_url(self, access_key: str) -> str:
        return self.invoice_url(access_key) + "/eventos"


def _response(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise SantanaSimplissError("Invalid Santana response size")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise SantanaSimplissError("Invalid Santana response JSON") from None
    if not isinstance(data, dict):
        raise SantanaSimplissError("Invalid Santana response envelope")
    ambient = data.get("tipoAmbiente")
    if ambient is not None and ambient not in (2, "2"):
        raise SantanaSimplissError("Santana response environment mismatch")
    return data


def _rejections(data: dict[str, object]) -> tuple[NfseRejectionDetail, ...]:
    raw = data.get("erros")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not 1 <= len(raw) <= 32:
        raise SantanaSimplissError("Invalid Santana rejection list")
    results: list[NfseRejectionDetail] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SantanaSimplissError("Invalid Santana rejection entry")
        code = item.get("Codigo", item.get("codigo"))
        message = item.get("Descricao", item.get("descricao"))
        if (
            not isinstance(code, (str, int)) or isinstance(code, bool)
            or not isinstance(message, str)
        ):
            raise SantanaSimplissError("Invalid Santana rejection fields")
        results.append(NfseRejectionDetail(
            code=str(code), origin="SIMPLISS_SANTANA", raw_message=message,
        ))
    return tuple(results)


def _https_exchange(
    method: str, url: str, body: bytes | None, tls: ssl.SSLContext, timeout: float,
) -> bytes:
    if method not in {"POST", "GET"}:
        raise SantanaSimplissError("Unsupported Santana method")
    request = Request(
        url, data=body, method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with build_opener(HTTPSHandler(context=tls), RejectFiscalRedirects()).open(
            request, timeout=timeout,
        ) as response:
            raw = response.read(_MAX_RESPONSE + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise SantanaSimplissError(
            "Santana fiscal response uncertain; query before another transmission"
        ) from None
    if len(raw) > _MAX_RESPONSE:
        raise SantanaSimplissError("Santana response exceeds the allowed size")
    return bytes(raw)


class SantanaSimplissHomologationGateway:
    """Separate municipal provider, shared canonical document/A1/numbering."""

    def __init__(
        self, *, endpoint: SantanaSimplissEndpoint,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        build_signed_dps: Callable[
            [NfseAuthorizationRequest, EphemeralCertificateMaterial], bytes
        ],
        preaudit: Callable[[NfseAuthorizationRequest], None],
        resolve_known_key: Callable[[NfseAuthorizationRequest], str | None] | None = None,
        exchange: Callable[[str, str, bytes | None, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
        submit_event: Callable[[
            NfseAuthorizationRequest, str, str, str, str, datetime,
        ], NationalNfseCancellationReceipt] | None = None,
        validate_official_invoice: Callable[[bytes], None] | None = None,
    ) -> None:
        if (
            not isinstance(endpoint, SantanaSimplissEndpoint)
            or not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not callable(build_signed_dps)
            or not callable(preaudit)
            or (resolve_known_key is not None and not callable(resolve_known_key))
            or (submit_event is not None and not callable(submit_event))
            or (validate_official_invoice is not None and not callable(validate_official_invoice))
            or not 0 < timeout_seconds <= 30
        ):
            raise SantanaSimplissError("Incomplete reviewed Santana fiscal authority")
        self._endpoint = endpoint
        self._resolver = provider_resolver
        self._certificate = resolve_certificate
        self._builder = build_signed_dps
        self._preaudit = preaudit
        self._known_key = resolve_known_key
        self._exchange = exchange or _https_exchange
        self._timeout = timeout_seconds
        self._submit_event = submit_event
        self._validate_official_invoice = validate_official_invoice

    def _review(
        self, request: NfseAuthorizationRequest, operation: str,
    ) -> tuple[EphemeralCertificateMaterial, str]:
        if not isinstance(request, NfseAuthorizationRequest):
            raise SantanaSimplissError("Prepared NFS-e must be canonical")
        document = request.document
        scope = document.scope
        jurisdiction = document.issuer.address.jurisdiction
        if (
            scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not scope.host_namespace or jurisdiction.state_code != "SP"
            or jurisdiction.municipality_ibge_code != SANTANA_IBGE
            or document.dps_number is None
        ):
            raise SantanaSimplissError("Santana requires a scoped, durably numbered DPS")
        if operation == "authorize":
            # New issuance/replacement cannot evade national competence rules
            # through direct gateway calls. Historical query/cancel stays valid.
            try:
                require_sp_municipal_nfse_issuance_permitted(
                    issuer_jurisdiction=jurisdiction,
                    tax_regime=document.issuer.tax_regime,
                    competence_date=document.competence_date,
                )
            except FiscalValidationError as exc:
                raise SantanaSimplissError(str(exc)) from None
        actual = self._resolver.resolve_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=jurisdiction, operation=operation,
        )
        if actual != SANTANA_PROVIDER_ID:
            raise SantanaSimplissError("Santana fiscal binding mismatch")
        self._preaudit(request)
        cnpj = document.issuer.cnpj.value
        material = self._certificate(scope, cnpj)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=Cnpj(cnpj), at=datetime.now(UTC),
        )
        return material, cnpj

    def _result(self, request: NfseAuthorizationRequest, raw: bytes) -> NfseAuthorizationResult:
        data = _response(raw)
        key = data.get("chaveAcesso")
        status = AuthorizationStatus.PENDING
        invoice_xml: bytes | None = None
        rejections: tuple[NfseRejectionDetail, ...] = ()
        if key is not None:
            if not _valid_key(key):
                raise SantanaSimplissError("Invalid Santana NFS-e access key")
            assert isinstance(key, str)
            try:
                invoice_xml = validate_nfse_receipt_integrity(raw, key)
                if self._validate_official_invoice is not None:
                    self._validate_official_invoice(invoice_xml)
            except (FiscalValidationError, XmlSchemaValidationError):
                raise SantanaSimplissError(
                    "Santana response lacks cryptographically verified NFS-e"
                ) from None
            status = AuthorizationStatus.AUTHORIZED
        else:
            rejections = _rejections(data)
            if rejections:
                status = AuthorizationStatus.REJECTED
        dps_id = data.get("idDps")
        return NfseAuthorizationResult(
            status=status,
            scope=request.document.scope,
            document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint,
            provider=_PROVIDER,
            provider_request_id=dps_id[:512] if isinstance(dps_id, str) else None,
            invoice_reference=key if status is AuthorizationStatus.AUTHORIZED else None,
            authorized_xml=invoice_xml,
            rejection_code=rejections[0].code if rejections else None,
            rejection_message=rejections[0].raw_message if rejections else None,
            rejections=rejections,
        )

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        material, cnpj = self._review(request, "authorize")
        signed_dps = self._builder(request, material)
        payload = encode_signed_dps(
            signed_dps, issuer_cnpj=cnpj, issuer_municipality_ibge=SANTANA_IBGE,
        )
        raw = self._exchange(
            "POST", self._endpoint.issue_url, payload,
            build_fiscal_tls_context(material), self._timeout,
        )
        return self._result(request, raw)

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        """GET by persisted official key; the public manual has no GET /dps method."""
        if self._known_key is None:
            raise SantanaSimplissError(
                "Santana query needs the original confirmed official access key"
            )
        material, _ = self._review(request, "query")
        key = self._known_key(request)
        if not _valid_key(key):
            raise SantanaSimplissError("Unverified Santana access key")
        assert isinstance(key, str)
        raw = self._exchange(
            "GET", self._endpoint.invoice_url(key), None,
            build_fiscal_tls_context(material), self._timeout,
        )
        result = self._result(request, raw)
        if (
            result.status is not AuthorizationStatus.AUTHORIZED
            or result.invoice_reference != key
        ):
            raise SantanaSimplissError("Santana query did not confirm the original invoice")
        return result

    @property
    def supports_events(self) -> bool:
        return self._submit_event is not None

    def submit_cancellation(
        self, request: NfseAuthorizationRequest, key: str,
        reason_code: str, reason_description: str,
        approval_reference: str, occurred_at: datetime,
    ) -> NationalNfseCancellationReceipt:
        if self._submit_event is None:
            raise SantanaSimplissError("Santana reviewed event authority missing")
        return self._submit_event(
            request, key, reason_code, reason_description,
            approval_reference, occurred_at,
        )

    def prepare_substitution(
        self, request: NfseAuthorizationRequest, *,
        review: SantanaSubstitutionReview,
        verify_original: Callable[
            [NfseAuthorizationRequest, SantanaSubstitutionReview], None
        ],
    ) -> bytes:
        """Build official replacement DPS before any durable transmission claim."""
        material, cnpj = self._review(request, "authorize")
        from kordena_fiscal.gateway.santana_simpliss_substitution import (
            build_santana_signed_replacement_dps,
        )

        signed = build_santana_signed_replacement_dps(
            request, material, review=review, verify_original=verify_original,
        )
        # Signature and official municipal 1.01 shape must both match.
        santana_official_validator("dps").validate_document(signed)
        return encode_signed_dps(
            signed, issuer_cnpj=cnpj,
            issuer_municipality_ibge=SANTANA_IBGE,
        )

    def submit_substitution(
        self, request: NfseAuthorizationRequest, prepared_envelope: bytes,
    ) -> NfseAuthorizationResult:
        """Send only a previously signed/reviewed substitution once."""
        if (
            not isinstance(prepared_envelope, bytes)
            or not 0 < len(prepared_envelope) <= _MAX_RESPONSE
        ):
            raise SantanaSimplissError("Santana prepared replacement envelope invalid")
        material, _ = self._review(request, "authorize")
        raw = self._exchange(
            "POST", self._endpoint.issue_url, prepared_envelope,
            build_fiscal_tls_context(material), self._timeout,
        )
        return self._result(request, raw)

    def query_verified_event(
        self, request: NfseAuthorizationRequest, *,
        original_key: str, event_code: str,
    ) -> SantanaVerifiedEvent | None:
        """Read GET /nfse/{key}/eventos; never resend an uncertain POST."""
        if event_code not in ("101101", "105102") or not _valid_key(original_key):
            raise SantanaSimplissError("Unsupported Santana event recovery")
        material, issuer = self._review(request, "cancel")
        assert isinstance(original_key, str)
        response = self._exchange(
            "GET", self._endpoint.events_url(original_key), None,
            build_fiscal_tls_context(material), self._timeout,
        )
        from kordena_fiscal.gateway.santana_simpliss_events import (
            read_santana_official_events,
        )

        matches = [
            result for result in read_santana_official_events(
                response, original_key=original_key, issuer_cnpj=issuer,
            )
            if result.event_code == event_code
        ]
        if len(matches) > 1:
            raise SantanaSimplissError("Ambiguous Santana cancellation event")
        return matches[0] if matches else None

    def query_substitution_invoice(
        self, request: NfseAuthorizationRequest, *,
        replacement_key: str, original_key: str,
    ) -> NfseAuthorizationResult:
        """Verify GET replacement NFS-e is the exact reserved new DPS.

        A signed event that happens to reference a different substitute cannot
        authorize this document. The returned NFS-e must contain its actual
        signed DPS with the same canonical Id and substituted original key.
        """
        if not _valid_key(replacement_key) or not _valid_key(original_key):
            raise SantanaSimplissError("Invalid signed Santana replacement reference")
        material, issuer = self._review(request, "query")
        assert isinstance(replacement_key, str)
        raw = self._exchange(
            "GET", self._endpoint.invoice_url(replacement_key), None,
            build_fiscal_tls_context(material), self._timeout,
        )
        result = self._result(request, raw)
        if (
            result.status is not AuthorizationStatus.AUTHORIZED
            or result.invoice_reference != replacement_key
            or result.authorized_xml is None
        ):
            raise SantanaSimplissError("Read-only Santana replacement is unconfirmed")
        from lxml import etree

        from kordena_fiscal.gateway.nfse_national_query import _dps_id

        parser = etree.XMLParser(
            resolve_entities=False, no_network=True,
            load_dtd=False, huge_tree=False,
        )
        root = etree.fromstring(result.authorized_xml, parser)
        namespace = "{http://www.sped.fazenda.gov.br/nfse}"
        info = root.find(namespace + "infNFSe")
        dps = (
            info.find(namespace + "DPS/" + namespace + "infDPS")
            if info is not None else None
        )
        if (
            root.tag != namespace + "NFSe"
            or dps is None or dps.get("Id") != _dps_id(request)
            or dps.findtext(
                namespace + "subst/" + namespace + "chSubstda"
            ) != original_key
            or dps.findtext(
                namespace + "prest/" + namespace + "CNPJ"
            ) != issuer
            or dps.findtext(namespace + "cLocEmi") != SANTANA_IBGE
        ):
            raise SantanaSimplissError(
                "Signed official substitute does not match reserved canonical DPS"
            )
        return result
