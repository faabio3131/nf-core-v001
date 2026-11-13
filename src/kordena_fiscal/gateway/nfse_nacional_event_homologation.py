"""National NFS-e cancellation event: signed, audited, single POST (tpAmb=2).

Official SEFIN Nacional contract: POST /nfse/{chaveAcesso}/eventos receives
pedidoRegistroEventoXmlGZipB64 and returns eventoXmlGZipB64. This transport
never builds a fiscal event from browser input and never treats HTTP 201 alone
as an accepted cancellation. The caller must already hold the confirmed
original NFS-e, a durable human authorization and official event XSD/XMLDSig
validation. No retries after ambiguous timeout: reconcile with a separate GET.

Official source: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
"""
from __future__ import annotations

import base64
import binascii
import gzip
import io
import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.nfse_national_homologation import (
    SEFIN_HOMOLOGATION_NFSE_URL,
)
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_CANCEL_TYPE = "101101"
_MAX_XML = 2_097_152
_URL = SEFIN_HOMOLOGATION_NFSE_URL
_NS_TAG = "{" + _NS + "}"


class NationalNfseEventError(FiscalValidationError):
    """No secrets, full XML, certificates or upstream body in error messages."""


def _secure_parse(xml: bytes) -> etree._Element:
    if not isinstance(xml, bytes) or not 0 < len(xml) <= _MAX_XML:
        raise NationalNfseEventError("Invalid national event XML size")
    try:
        root: etree._Element = etree.fromstring(
            xml,
            parser=etree.XMLParser(
                resolve_entities=False, no_network=True, load_dtd=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise NationalNfseEventError("Malformed national event XML") from None
    if bool(getattr(root.getroottree().docinfo, "doctype", "")):
        raise NationalNfseEventError("National event DTD is forbidden")
    return root


def _key(value: str) -> str:
    if (
        type(value) is not str
        or len(value) != 50
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise NationalNfseEventError("NFS-e key must contain exactly 50 digits")
    return value


@dataclass(frozen=True, slots=True)
class NationalNfseCancellationIntent:
    """Original invoice and signed event bound to a single approved issuer."""

    scope: ExecutionScope
    issuer: Cnpj
    issuer_jurisdiction: BrazilianJurisdiction
    invoice_reference: str
    human_approval_reference: str
    signed_event_xml: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, ExecutionScope)
            or self.scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not self.scope.host_namespace
            or not isinstance(self.issuer, Cnpj)
            or not isinstance(self.issuer_jurisdiction, BrazilianJurisdiction)
            or self.issuer_jurisdiction.municipality_ibge_code is None
            or not isinstance(self.human_approval_reference, str)
            or not 8 <= len(self.human_approval_reference) <= 128
            or not self.human_approval_reference.isascii()
        ):
            raise NationalNfseEventError(
                "National cancellation requires governed issuer scope and human approval"
            )
        _key(self.invoice_reference)
        root = _secure_parse(self.signed_event_xml)
        if root.tag != f"{_NS_TAG}pedRegEvento":
            raise NationalNfseEventError("Cancellation requires pedRegEvento root")
        info = root.findall(f"{_NS_TAG}infPedReg")
        signature = root.findall(f"{{{_DS}}}Signature")
        if (
            len(info) != 1 or len(signature) != 1
            or signature[0].getparent() is not root
            or info[0].get("Id") != "PRE" + self.invoice_reference + _CANCEL_TYPE
            or sum(x.get("Id") == info[0].get("Id") for x in root.iter()) != 1
            or info[0].findtext(f"{_NS_TAG}tpAmb") != "2"
            or info[0].findtext(f"{_NS_TAG}CNPJAutor") != self.issuer.value
            or info[0].findtext(f"{_NS_TAG}chNFSe") != self.invoice_reference
            or info[0].find(f"{_NS_TAG}e{_CANCEL_TYPE}") is None
        ):
            raise NationalNfseEventError(
                "Signed cancellation event does not match original fiscal issuer"
            )
        references = signature[0].findall(
            f"{{{_DS}}}SignedInfo/{{{_DS}}}Reference"
        )
        if (
            len(references) != 1
            or references[0].get("URI") != "#" + info[0].get("Id", "")
        ):
            raise NationalNfseEventError("Cancellation XMLDSig reference differs from event")


@dataclass(frozen=True, slots=True)
class NationalNfseCancellationReceipt:
    """Provider-issued event XML, never a locally synthesized tax authority."""

    invoice_reference: str
    event_xml: bytes = field(repr=False)
    confirmed: bool = True

    def __post_init__(self) -> None:
        _key(self.invoice_reference)
        if self.confirmed is not True or not isinstance(self.event_xml, bytes):
            raise NationalNfseEventError("Only verified official cancellation can be confirmed")


def _validated_response(payload: bytes, intent: NationalNfseCancellationIntent) -> bytes:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= _MAX_XML:
        raise NationalNfseEventError("Invalid SEFIN event reply")
    try:
        response = json.loads(payload)
        if not isinstance(response, dict) or response.get("tipoAmbiente") != 2:
            raise ValueError
        encoded = response.get("eventoXmlGZipB64")
        if not isinstance(encoded, str) or len(encoded) > _MAX_XML * 2:
            raise ValueError
        compressed = base64.b64decode(encoded, validate=True)
        if len(compressed) > _MAX_XML:
            raise ValueError
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            xml = stream.read(_MAX_XML + 1)
    except (ValueError, binascii.Error, UnicodeDecodeError, OSError):
        raise NationalNfseEventError("SEFIN returned invalid event envelope") from None
    event = _secure_parse(xml)
    if event.tag != f"{_NS_TAG}evento":
        raise NationalNfseEventError("SEFIN event must use official root")
    nodes = event.findall(f"{_NS_TAG}infEvento")
    if len(nodes) != 1:
        raise NationalNfseEventError("SEFIN event identity is ambiguous")
    request = nodes[0].find(f"{_NS_TAG}pedRegEvento/{_NS_TAG}infPedReg")
    if (
        request is None
        or request.findtext(f"{_NS_TAG}chNFSe") != intent.invoice_reference
        or request.findtext(f"{_NS_TAG}CNPJAutor") != intent.issuer.value
        or request.find(f"{_NS_TAG}e{_CANCEL_TYPE}") is None
        or request.findtext(f"{_NS_TAG}tpAmb") != "2"
    ):
        raise NationalNfseEventError(
            "SEFIN cancellation receipt does not confirm the original invoice"
        )
    return xml


def _exchange(
    key: str, body: bytes, tls: ssl.SSLContext, timeout: float,
) -> bytes:
    req = Request(
        _URL + "/" + _key(key) + "/eventos",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with build_opener(HTTPSHandler(context=tls), RejectFiscalRedirects()).open(
            req, timeout=timeout,
        ) as result:
            raw = result.read(_MAX_XML + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError):
        raise NationalNfseEventError(
            "SEFIN event status unknown; query before any new attempt"
        ) from None
    if len(raw) > _MAX_XML:
        raise NationalNfseEventError("SEFIN event response exceeds limit")
    return bytes(raw)


class NationalNfseCancellationHomologationTransport:
    """A1 + human-approved signed XML + fiscal binding, no automatic retry."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        validate_signed_event: Callable[[bytes], None],
        approve_cancellation: Callable[[NationalNfseCancellationIntent], None],
        validate_official_event: Callable[[bytes], None],
        exchange: Callable[[str, bytes, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if (
            not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not callable(validate_signed_event)
            or not callable(approve_cancellation)
            or not callable(validate_official_event)
            or not 0 < timeout_seconds <= 30
        ):
            raise NationalNfseEventError("Incomplete national cancellation authority")
        self._resolver = provider_resolver
        self._certificate = resolve_certificate
        self._validate = validate_signed_event
        self._approve = approve_cancellation
        self._validate_response = validate_official_event
        self._exchange = exchange or _exchange
        self._timeout = timeout_seconds

    def cancel(
        self, intent: NationalNfseCancellationIntent,
    ) -> NationalNfseCancellationReceipt:
        if not isinstance(intent, NationalNfseCancellationIntent):
            raise NationalNfseEventError("Canonical national cancellation intent required")
        provider = self._resolver.resolve_provider_id(
            scope=intent.scope,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=intent.issuer_jurisdiction,
            operation="cancel",
        )
        if provider != NACIONAL_HOMOLOGATION_PROVIDER_ID:
            raise NationalNfseEventError("National cancellation provider binding mismatch")
        self._approve(intent)
        # Must verify official XSD AND XMLDSig against issuer and signed bytes.
        self._validate(intent.signed_event_xml)
        material = self._certificate(intent.scope, intent.issuer.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password, issuer_cnpj=intent.issuer,
            at=datetime.now(UTC),
        )
        payload = json.dumps(
            {
                "pedidoRegistroEventoXmlGZipB64": base64.b64encode(
                    gzip.compress(intent.signed_event_xml, mtime=0)
                ).decode("ascii"),
            }, separators=(",", ":"),
        ).encode("ascii")
        reply = self._exchange(
            intent.invoice_reference,
            payload,
            build_fiscal_tls_context(material),
            self._timeout,
        )
        event_xml = _validated_response(reply, intent)
        # A structurally correlated XML is not proof it was signed by SEFIN.
        # Require separately pinned official event schema and signature checks.
        self._validate_response(event_xml)
        return NationalNfseCancellationReceipt(
            invoice_reference=intent.invoice_reference,
            event_xml=event_xml,
        )
