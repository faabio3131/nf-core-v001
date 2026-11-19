"""Municipal WebISS 2.02 RTC schema authority for MG, deliberately fail-closed.

ABRASF 2.03 is NOT a WebISS 2.02/IBSCBS compatibility schema. The official
municipal WebISS RTC package must be captured verbatim, SHA-256 pinned in this
repository, code-reviewed and tested before municipal XML can be transmitted.
Never download or trust tenant-supplied XSDs on the fiscal execution path.

Authoritative municipal announcement:
https://extremamg.webiss.com.br/ (Manuais -> Nota Fiscal de Servicos Eletronica)
Independent implementation evidence:
https://documentacao.senior.com.br/documentoseletronicos/notasdaversao/5-8-16/
"""
from __future__ import annotations

import gzip
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.xml.schema import (
    SchemaResource,
    SchemaSet,
    XmlSchemaValidationError,
    XmlSchemaValidator,
)

_EXTREMA_RTC_DESTINATION_ORDER_SOURCE = (
    "https://documentacao.senior.com.br/documentoseletronicos/notasdaversao/5-8-16/"
)
WEBISS_RTC_LAYOUT_VERSION = "2.02"
WEBISS_MG_IBGE = frozenset({"3125101", "3170107"})

# Extrema: supplier-published RTC XSD linked by the municipal WebISS portal,
# together with its XMLDSig import from the public WebService support archive.
# Uberaba deliberately remains unpinned; never reuse this city-specific pin.
PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS: Mapping[str, str] = {
    "3125101": "8e0f2a9174cbfafa5a601a7003c5f3d4408ceadd01de1e87b9be12c09cc762ee",
}


class WebissMunicipalSchemaUnverified(FiscalValidationError):
    """Municipal 2026 schema not certified; network access must be denied."""


@dataclass(frozen=True, slots=True)
class Webiss2026SchemaEvidence:
    municipality_ibge: str
    schema_package_sha256: str
    schema_version: str = WEBISS_RTC_LAYOUT_VERSION

    def __post_init__(self) -> None:
        if self.municipality_ibge not in WEBISS_MG_IBGE:
            raise WebissMunicipalSchemaUnverified("Unsupported WebISS MG municipality")
        if self.schema_version != WEBISS_RTC_LAYOUT_VERSION:
            raise WebissMunicipalSchemaUnverified(
                "WebISS MG requires the municipal RTC 2.02 schema, not ABRASF 2.03"
            )
        digest = PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS.get(self.municipality_ibge)
        if digest is None or self.schema_package_sha256 != digest:
            raise WebissMunicipalSchemaUnverified(
                "Official WebISS RTC 2026 XSD package is not pinned and certified"
            )


def validate_webiss_official_xml(
    *,
    evidence: Webiss2026SchemaEvidence,
    validator: XmlSchemaValidator,
    xml: bytes,
) -> None:
    """Enforce the exact municipality-reviewed XSD over each SOAP inner payload."""
    if not isinstance(evidence, Webiss2026SchemaEvidence):
        raise WebissMunicipalSchemaUnverified("Missing official municipal schema evidence")
    if not isinstance(validator, XmlSchemaValidator):
        raise WebissMunicipalSchemaUnverified("Missing pinned municipal XSD validator")
    try:
        checked = validator.validate_document(xml)
    except XmlSchemaValidationError as exc:
        raise WebissMunicipalSchemaUnverified(
            "WebISS 2026 XML is incompatible with the pinned municipal schema"
        ) from exc
    if checked.schema_package_sha256 != evidence.schema_package_sha256:
        raise WebissMunicipalSchemaUnverified(
            "WebISS municipal schema package hash mismatch"
        )

def build_pinned_webiss_municipal_schema(
    *,
    municipality_ibge: str,
    root_schema: str,
    resources: tuple[SchemaResource, ...],
    source_uri: str,
) -> tuple[Webiss2026SchemaEvidence, XmlSchemaValidator]:
    """Load a reviewed WebISS RTC package, offline and matched by SHA-256.

    The XSD/manifest must be reviewed and version-controlled before runtime.
    No host/network, tenant upload or dynamic fetch is permitted here. An
    unknown or unpinned municipal package always fails closed.
    """
    if municipality_ibge not in WEBISS_MG_IBGE:
        raise WebissMunicipalSchemaUnverified("Unknown municipal schema jurisdiction")
    official_hosts = {
        "3125101": "https://extremamg.webiss.com.br/",
        "3170107": "https://uberabamg.webiss.com.br/",
    }
    if source_uri != official_hosts[municipality_ibge]:
        raise WebissMunicipalSchemaUnverified(
            "WebISS XSD provenance must match its municipal official portal"
        )
    expected_digest = PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS.get(municipality_ibge)
    if expected_digest is None:
        raise WebissMunicipalSchemaUnverified(
            "Official WebISS RTC 2026 XSD package is not yet verified"
        )
    schema_set = SchemaSet(
        version=WEBISS_RTC_LAYOUT_VERSION,
        root_schema=root_schema,
        resources=resources,
        source_uri=source_uri,
    )
    if schema_set.package_sha256 != expected_digest:
        raise WebissMunicipalSchemaUnverified(
            "Municipal schema package differs from reviewed SHA-256"
        )
    validator = XmlSchemaValidator(schema_set)
    return (
        Webiss2026SchemaEvidence(municipality_ibge, expected_digest),
        validator,
    )


def require_extrema_rtc_destination_order(xml: bytes) -> None:
    """Reject the 2026 Extrema E160 <dest> ordering regression before dispatch.

    The municipality's actual pinned XSD is still the schema authority; this
    targeted safeguard only enforces the independently documented rule:
    the recipient's identifier is the FIRST element in the IBS/CBS
    destination group, rather than email/address/name preceding it.
    No elements are repaired/reordered after signing, which would invalidate
    XMLDSig and could change the recipient's legal identity.

    Source: Senior eDocs 5.8.16, Extrema WebISS 2.02 + RTC E160 notice.
    """
    if not isinstance(xml, bytes) or not 0 < len(xml) <= 2_097_152:
        raise WebissMunicipalSchemaUnverified(
            "Invalid municipal XML before RTC destination preflight"
        )
    if b"<!DOCTYPE" in xml.upper():
        raise WebissMunicipalSchemaUnverified("DTD is forbidden in WebISS RTC XML")
    try:
        root = etree.fromstring(
            xml, parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        raise WebissMunicipalSchemaUnverified("Invalid municipal RTC XML") from None
    namespace = "http://www.abrasf.org.br/nfse.xsd"
    for ibscbs in root.iter(f"{{{namespace}}}IBSCBS"):
        indicator = ibscbs.findtext(f"{{{namespace}}}indDest")
        recipient = ibscbs.find(f"{{{namespace}}}dest")
        # Cross-field condition in the published WebISS 2.02 RTC schema:
        # indDest=0 means the acquirer is the recipient (no separate <dest>);
        # indDest=1 means a distinct recipient must be identified.
        # This check complements the official XSD without computing tax.
        if (indicator == "0" and recipient is not None) or (
            indicator == "1" and recipient is None
        ):
            raise WebissMunicipalSchemaUnverified(
                "Extrema WebISS RTC recipient group conflicts with indDest"
            )
    for destination in root.iter(f"{{{namespace}}}dest"):
        if not any(
            ancestor.tag == f"{{{namespace}}}IBSCBS"
            for ancestor in destination.iterancestors()
        ):
            continue
        children = list(destination)
        if not children:
            raise WebissMunicipalSchemaUnverified(
                "Extrema IBS/CBS destination requires an identifier"
            )
        first = children[0]
        if first.tag not in (
            f"{{{namespace}}}CNPJ",
            f"{{{namespace}}}CPF",
            f"{{{namespace}}}NIF",
            f"{{{namespace}}}cNaoNIF",
        ):
            raise WebissMunicipalSchemaUnverified(
                "Extrema WebISS RTC E160: recipient identification must precede"
                " the other destination fields"
            )
        # The official XSD remains responsible for enforcing type, required
        # fields, alternate identities and the order of subsequent elements.


_EXTREMA_RTC_ROOT = "nfse_v2_02-IBSCBS.xsd"
_EXTREMA_RTC_ROOT_SHA256 = "4caeadd9b4993b7741d7a83aa80601ac5743524d5af7bdd14f862fed053c7003"
_EXTREMA_RTC_XMLDSIG = "xmldsig-core-schema20020212.xsd"
_EXTREMA_RTC_XMLDSIG_SHA256 = "13f29857c337bef574e59ea1023caaa9b407bcae0dea013c5c295385688708d4"
_EXTREMA_RTC_COMPRESSED_SIGNATURE_SHA256 = (
    "64ea007670853de7f77136fcdd81fbae91ec377f383e435550c3c8e5e6647088"
)
_EXTREMA_RTC_SOURCE = "https://extremamg.webiss.com.br/"


@lru_cache(maxsize=1)
def load_pinned_extrema_webiss_rtc_schema() -> tuple[Webiss2026SchemaEvidence, XmlSchemaValidator]:
    """Load the exact reviewed municipality-linked RTC schema set, entirely offline.

    The original XMLDSig import is stored as deterministic gzip bytes to avoid
    introducing an unreviewed, substitute signature grammar. Both decompressed
    resources and the compressed artifact are independently hash-checked.
    A missing wheel resource or changed byte fails before provider dispatch.
    """
    directory = files("kordena_fiscal.xml").joinpath(
        "official", "WEBISS_EXTREMA_RTC_2026",
    )
    try:
        rtc_bytes = directory.joinpath(_EXTREMA_RTC_ROOT).read_bytes()
        compressed = directory.joinpath(_EXTREMA_RTC_XMLDSIG + ".gz").read_bytes()
    except (FileNotFoundError, OSError):
        raise WebissMunicipalSchemaUnverified(
            "Pinned Extrema RTC schema missing from the installed distribution"
        ) from None
    if hashlib.sha256(compressed).hexdigest() != _EXTREMA_RTC_COMPRESSED_SIGNATURE_SHA256:
        raise WebissMunicipalSchemaUnverified("Extrema XMLDSig source archive integrity mismatch")
    try:
        xmlsig_bytes = gzip.decompress(compressed)
    except (EOFError, OSError):
        raise WebissMunicipalSchemaUnverified(
            "Invalid Extrema XMLDSig compressed resource"
        ) from None
    if len(rtc_bytes) != 105916 or len(xmlsig_bytes) != 10467:
        raise WebissMunicipalSchemaUnverified("Unexpected Extrema schema resource size")
    if hashlib.sha256(rtc_bytes).hexdigest() != _EXTREMA_RTC_ROOT_SHA256:
        raise WebissMunicipalSchemaUnverified("Extrema RTC schema content hash mismatch")
    if hashlib.sha256(xmlsig_bytes).hexdigest() != _EXTREMA_RTC_XMLDSIG_SHA256:
        raise WebissMunicipalSchemaUnverified("Extrema XMLDSig schema content hash mismatch")
    resources = (
        SchemaResource.from_bytes(_EXTREMA_RTC_ROOT, rtc_bytes),
        SchemaResource.from_bytes(_EXTREMA_RTC_XMLDSIG, xmlsig_bytes),
    )
    return build_pinned_webiss_municipal_schema(
        municipality_ibge="3125101",
        root_schema=_EXTREMA_RTC_ROOT,
        resources=resources,
        source_uri=_EXTREMA_RTC_SOURCE,
    )
