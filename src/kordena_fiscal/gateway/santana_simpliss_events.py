"""Santana Simpliss event 101101: reviewed, signed, correlated municipal POST.

This bridge does not generate a fiscal event from a browser request. The
canonical fiscal application must authorize/claim the original cancellation
durably, obtain the signed official-event document, and supply XSD/XMLDSig
validation. A timeout leaves the event unresolved: never resend automatically.
"""
from __future__ import annotations

import base64
import gzip
import json
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from kordena_fiscal.domain import (
    FiscalDocumentKind,
    FiscalValidationError,
)
from kordena_fiscal.gateway.fiscal_tls import build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationIntent,
    NationalNfseCancellationReceipt,
    _validated_response,
)
from kordena_fiscal.gateway.nfse_national_query import _verify_nfse_receipt_signature
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_IBGE,
    SANTANA_PROVIDER_ID,
    SantanaSimplissEndpoint,
    SantanaSimplissError,
    _https_exchange,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer
from kordena_fiscal.xml.santana_simpliss_schema import santana_official_validator


class SantanaSimplissEventTransport:
    """Adapt published Simpliss cancel/event route without claiming a national binding."""

    def __init__(
        self, *, endpoint: SantanaSimplissEndpoint,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[..., EphemeralCertificateMaterial],
        approve_cancellation: Callable[[NationalNfseCancellationIntent], None],
        validate_signed_event: Callable[[bytes], None],
        validate_official_event: Callable[[bytes], None],
        exchange: Callable[
            [str, str, bytes | None, ssl.SSLContext, float], bytes
        ] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if (
            not isinstance(endpoint, SantanaSimplissEndpoint)
            or not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not callable(approve_cancellation)
            or not callable(validate_signed_event)
            or not callable(validate_official_event)
            or not 0 < timeout_seconds <= 30.0
        ):
            raise SantanaSimplissError("Santana event requires complete reviewed authority")
        self._endpoint = endpoint
        self._resolver = provider_resolver
        self._certificate = resolve_certificate
        self._approve = approve_cancellation
        self._validate_signed_event = validate_signed_event
        self._validate_official_event = validate_official_event
        self._exchange = exchange or _https_exchange
        self._timeout = timeout_seconds

    def cancel(
        self, intent: NationalNfseCancellationIntent,
    ) -> NationalNfseCancellationReceipt:
        if not isinstance(intent, NationalNfseCancellationIntent):
            raise SantanaSimplissError("Santana cancellation needs signed canonical intent")
        city = intent.issuer_jurisdiction
        if (
            city.state_code != "SP" or city.municipality_ibge_code != SANTANA_IBGE
            or not intent.scope.host_namespace
        ):
            raise SantanaSimplissError("Santana event has different fiscal municipality")
        provider = self._resolver.resolve_provider_id(
            scope=intent.scope,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=city,
            operation="cancel",
        )
        if provider != SANTANA_PROVIDER_ID:
            raise SantanaSimplissError("Santana event provider binding mismatch")
        self._approve(intent)
        # Caller must validate official event XSD and cryptographic signature.
        self._validate_signed_event(intent.signed_event_xml)
        material = self._certificate(intent.scope, intent.issuer.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=intent.issuer, at=datetime.now(UTC),
        )
        body = json.dumps({
            "pedidoRegistroEventoXmlGZipB64": base64.b64encode(
                gzip.compress(intent.signed_event_xml, mtime=0),
            ).decode("ascii"),
        }, separators=(",", ":")).encode("ascii")
        response = self._exchange(
            "POST", self._endpoint.events_url(intent.invoice_reference), body,
            build_fiscal_tls_context(material), self._timeout,
        )
        try:
            official = _validated_response(response, intent)
            self._validate_official_event(official)
        except FiscalValidationError:
            raise SantanaSimplissError(
                "Santana event receipt was not officially validated"
            ) from None
        return NationalNfseCancellationReceipt(
            invoice_reference=intent.invoice_reference,
            event_xml=official,
        )


_NS = "http://www.sped.fazenda.gov.br/nfse"
_TAG = "{" + _NS + "}"
_APP_VERSION = "NFCORE1"


def validate_santana_event_xml(xml: bytes, *, kind: str) -> None:
    """Prove national 1.01 schema, signed reference and cryptographic integrity."""
    if kind not in ("request", "response"):
        raise SantanaSimplissError("Unsupported official event contract")
    santana_official_validator(kind).validate_document(xml)
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
    )
    root = etree.fromstring(xml, parser)
    if getattr(root.getroottree().docinfo, "doctype", None):
        raise SantanaSimplissError("Santana event DTD is forbidden")
    expected = _TAG + ("pedRegEvento" if kind == "request" else "evento")
    identifier = "infPedReg" if kind == "request" else "infEvento"
    info = root.find(_TAG + identifier)
    if root.tag != expected or info is None or info.get("Id") is None:
        raise SantanaSimplissError("Santana signed event structure is invalid")
    assert info.get("Id") is not None
    _verify_nfse_receipt_signature(root, info, info.get("Id", ""))


def build_signed_santana_cancellation(
    *, request: NfseAuthorizationRequest, key: str,
    reason_code: str, reason_description: str,
    approval_reference: str, occurred_at: datetime,
    material: EphemeralCertificateMaterial,
) -> NationalNfseCancellationIntent:
    """Create canonical, signed cancellation event without browser-owned XML."""
    document = request.document
    if (
        document.scope.environment.value != "homologation"
        or document.issuer.address.jurisdiction.municipality_ibge_code != SANTANA_IBGE
        or document.issuer.address.jurisdiction.state_code != "SP"
        or not isinstance(key, str) or len(key) != 50
        or not key.isascii() or not key.isdecimal() or not key.startswith("35")
        or reason_code not in ("1", "2", "9")
        or not isinstance(reason_description, str)
        or not 15 <= len(reason_description.strip()) <= 255
        or any(ord(char) < 32 for char in reason_description)
        or not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
    ):
        raise SantanaSimplissError("Invalid approved Santana event 101101")
    validate_a1_for_issuer(
        material.pkcs12_bytes, material.password,
        issuer_cnpj=document.issuer.cnpj, at=datetime.now(UTC),
    )
    private, certificate, _ = pkcs12.load_key_and_certificates(
        material.pkcs12_bytes, material.password,
    )
    if not isinstance(private, rsa.RSAPrivateKey) or certificate is None:
        raise SantanaSimplissError("Santana signing identity is not a valid A1 RSA")
    root = etree.Element(_TAG + "pedRegEvento", nsmap={None: _NS})  # type: ignore[dict-item]
    root.set("versao", "1.01")
    inf = etree.SubElement(root, _TAG + "infPedReg")
    inf.set("Id", "PRE" + key + "101101")
    etree.SubElement(inf, _TAG + "tpAmb").text = "2"
    etree.SubElement(inf, _TAG + "verAplic").text = _APP_VERSION
    etree.SubElement(inf, _TAG + "dhEvento").text = occurred_at.astimezone(
        ZoneInfo("America/Sao_Paulo")
    ).isoformat(timespec="seconds")
    etree.SubElement(inf, _TAG + "CNPJAutor").text = document.issuer.cnpj.value
    etree.SubElement(inf, _TAG + "chNFSe").text = key
    # Official Santana 2025-12-10 TCInfPedReg requires nPedRegEvento
    # BEFORE e101101, unlike the generic reference mirror schema.
    etree.SubElement(inf, _TAG + "nPedRegEvento").text = "1"
    cancel = etree.SubElement(inf, _TAG + "e101101")
    etree.SubElement(cancel, _TAG + "xDesc").text = "Cancelamento de NFS-e"
    etree.SubElement(cancel, _TAG + "cMotivo").text = reason_code
    etree.SubElement(cancel, _TAG + "xMotivo").text = reason_description.strip()
    append_nfse_signature(root, inf, private, certificate, legacy_abrasf=False)
    signed = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    validate_santana_event_xml(signed, kind="request")
    return NationalNfseCancellationIntent(
        scope=document.scope, issuer=document.issuer.cnpj,
        issuer_jurisdiction=document.issuer.address.jurisdiction,
        invoice_reference=key,
        human_approval_reference=approval_reference,
        signed_event_xml=signed,
    )
