"""Santana Simpliss signed replacement DPS (National NFS-e official XSD 1.01).

A substitution is a *new* canonical DPS with the old official NFS-e key
inside <subst>. It is NOT a second SOAP endpoint and NOT an ordinary issue.
No user/browser may supply this intent without original-invoice review and
human approval. The caller must durably reserve the replacement DPS through
the existing fiscal application before invoking this stateless serializer.

It reuses the canonical builder/signing, changes only the reviewed substitution
node in an unsigned XML, revalidates against the official hash-pinned XSD and
re-signs with the scoped A1. It never creates or increments fiscal numbers.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.nfse_national_homologation import parse_signed_dps_info
from kordena_fiscal.gateway.santana_simpliss_homologation import SANTANA_IBGE
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

_NS = "http://www.sped.fazenda.gov.br/nfse"
_TAG = "{" + _NS + "}"
_DS = "{http://www.w3.org/2000/09/xmldsig#}"
_REASON_CODES = frozenset({"01", "02", "03", "04", "05", "99"})


@dataclass(frozen=True, slots=True)
class SantanaSubstitutionReview:
    """Immutable owner-reviewed source and administrative justification."""

    original_document_id: str
    original_access_key: str
    reason_code: str
    reason_description: str | None
    human_approval_reference: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.original_document_id, str)
            or not 1 <= len(self.original_document_id.strip()) <= 128
            or not isinstance(self.original_access_key, str)
            or not self.original_access_key.isascii()
            or not self.original_access_key.isdecimal()
            or len(self.original_access_key) != 50
            or not self.original_access_key.startswith("35")
            or not isinstance(self.reason_code, str)
            or self.reason_code not in _REASON_CODES
            or not isinstance(self.human_approval_reference, str)
            or not 8 <= len(self.human_approval_reference.strip()) <= 128
        ):
            raise FiscalValidationError("Santana substitution requires approved original invoice")
        if self.reason_description is not None:
            if (
                not isinstance(self.reason_description, str)
                or not 15 <= len(self.reason_description.strip()) <= 255
                or any(ord(x) < 32 for x in self.reason_description)
            ):
                raise FiscalValidationError("Santana substitution reason is not valid")


def build_santana_signed_replacement_dps(
    request: NfseAuthorizationRequest,
    certificate: EphemeralCertificateMaterial,
    *,
    review: SantanaSubstitutionReview,
    verify_original: Callable[
        [NfseAuthorizationRequest, SantanaSubstitutionReview], None
    ],
) -> bytes:
    """Sign only an authorized municipal substitution with a fresh DPS number."""
    if (
        not isinstance(request, NfseAuthorizationRequest)
        or not isinstance(certificate, EphemeralCertificateMaterial)
        or not isinstance(review, SantanaSubstitutionReview)
        or not callable(verify_original)
        or request.document.issuer.address.jurisdiction.municipality_ibge_code
        != SANTANA_IBGE
        or request.document.dps_number is None
    ):
        raise FiscalValidationError("Santana substitution needs a new numbered DPS")
    # Verify archived original NFS-e and same-tenant, same-issuer approval;
    # caller must reject unapproved, already substituted or cancelled originals.
    verify_original(request, review)

    signed = build_signed_dps(request, certificate)
    info = parse_signed_dps_info(signed)
    root = info.getparent()
    if root is None or root.tag != _TAG + "DPS":
        raise FiscalValidationError("Santana original DPS is not canonical")
    signature = root.find(_DS + "Signature")
    if signature is None or signature.getparent() is not root:
        raise FiscalValidationError("Santana original DPS signature is missing")
    # Remove the prior signature BEFORE changing XML; a replacement must be
    # digitally signed over the final substitution facts, never patched later.
    root.remove(signature)
    city = info.find(_TAG + "cLocEmi")
    if city is None or city.text != SANTANA_IBGE:
        raise FiscalValidationError("Santana substitution issuer municipality differs")
    if info.find(_TAG + "subst") is not None:
        raise FiscalValidationError("Santana replacement source is already populated")
    node = etree.Element(_TAG + "subst")
    etree.SubElement(node, _TAG + "chSubstda").text = review.original_access_key
    etree.SubElement(node, _TAG + "cMotivo").text = review.reason_code
    if review.reason_description is not None:
        etree.SubElement(node, _TAG + "xMotivo").text = review.reason_description.strip()
    info.insert(list(info).index(city) + 1, node)
    xml = etree.tostring(root, encoding="utf-8", xml_declaration=False)
    national_dps_validator("1.01").validate_document(xml)
    finished = sign_nfse_dps_xml(xml, certificate)
    parse_signed_dps_info(finished)
    return finished
