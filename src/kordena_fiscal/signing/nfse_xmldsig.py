"""Enveloped XMLDSig for pinned National NFS-e DPS 1.00 and 1.01.

The taxpayer-bound A1 comes from the existing Vault, never from browser JSON.
DPS 1.00 XSD fixes RSA-SHA1; DPS 1.01's official XMLDSig schema permits
RSA-SHA256, used here to avoid downgrading the updated format. Legacy ABRASF
contracts keep their separate version-governed signature algorithm.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.vault import EphemeralCertificateMaterial

_DS = "http://www.w3.org/2000/09/xmldsig#"
_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


def sign_nfse_dps_xml(
    unsigned_xml: bytes, certificate_material: EphemeralCertificateMaterial
) -> bytes:
    """Sign the unique infDPS/Id reference and embed one Signature in DPS."""
    if not unsigned_xml or len(unsigned_xml) > 2_097_152:
        raise FiscalValidationError("DPS inválida ou excede limite de assinatura")
    try:
        root = etree.fromstring(
            unsigned_xml,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("XML DPS inválido") from None
    if root.tag != "{http://www.sped.fazenda.gov.br/nfse}DPS":
        raise FiscalValidationError("Assinatura NFS-e requer DPS")
    info_nodes = [
        child for child in root if child.tag == "{http://www.sped.fazenda.gov.br/nfse}infDPS"
    ]
    if len(info_nodes) != 1:
        raise FiscalValidationError("Assinatura requer uma infDPS")
    info = info_nodes[0]
    identifier = info.get("Id", "")
    if not identifier.startswith("DPS") or len(identifier) > 100:
        raise FiscalValidationError("Id de DPS inválido")
    environments = [
        child for child in root.iter() if etree.QName(child).localname == "tpAmb"
    ]
    if len(environments) != 1 or environments[0].text != "2":
        raise FiscalValidationError("Assinatura DPS permitida somente em tpAmb=2")
    if root.find(f".//{{{_DS}}}Signature") is not None:
        raise FiscalValidationError("DPS já está assinada")
    key, cert, _ = pkcs12.load_key_and_certificates(
        certificate_material.pkcs12_bytes, certificate_material.password
    )
    if not isinstance(key, rsa.RSAPrivateKey) or cert is None:
        raise FiscalValidationError("Assinatura DPS exige identidade A1 RSA")

    # The original DPS 1.00 XSD fixes RSA-SHA1; the official National
    # 1.01 XMLDSig schema permits SHA-256. Select per signed schema version,
    # never silently downgrade an unknown/modern DPS to SHA-1.
    version = root.get("versao")
    if version not in ("1.00", "1.01"):
        raise FiscalValidationError("DPS signature schema version is unsupported")
    append_nfse_signature(root, info, key, cert, legacy_abrasf=version == "1.00")
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def append_nfse_signature(
    parent: etree._Element,
    info: etree._Element,
    key: rsa.RSAPrivateKey,
    cert: x509.Certificate,
    *,
    legacy_abrasf: bool,
    whole_document: bool = False,
) -> None:
    """Insert XMLDSig over an Id target or over the entire request document."""
    identifier = info.get("Id")
    if not identifier and not whole_document:
        raise FiscalValidationError("Missing NFS-e signature reference Id")
    canonical_info = etree.tostring(info, method="c14n", exclusive=False, with_comments=False)
    algorithm = hashes.SHA1() if legacy_abrasf else hashes.SHA256()
    digest = (
        hashlib.sha1(canonical_info).digest()
        if legacy_abrasf else hashlib.sha256(canonical_info).digest()
    )
    signature_method = _DS + "rsa-sha1" if legacy_abrasf else _RSA_SHA256
    digest_method = _DS + "sha1" if legacy_abrasf else _SHA256
    signature = etree.Element(f"{{{_DS}}}Signature", nsmap={"ds": _DS})
    signed_info = etree.SubElement(signature, f"{{{_DS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{_DS}}}CanonicalizationMethod", Algorithm=_C14N)
    etree.SubElement(signed_info, f"{{{_DS}}}SignatureMethod", Algorithm=signature_method)
    uri = "" if whole_document else f"#{identifier}"
    reference = etree.SubElement(signed_info, f"{{{_DS}}}Reference", URI=uri)
    transforms = etree.SubElement(reference, f"{{{_DS}}}Transforms")
    etree.SubElement(transforms, f"{{{_DS}}}Transform", Algorithm=_ENVELOPED)
    etree.SubElement(transforms, f"{{{_DS}}}Transform", Algorithm=_C14N)
    etree.SubElement(reference, f"{{{_DS}}}DigestMethod", Algorithm=digest_method)
    etree.SubElement(reference, f"{{{_DS}}}DigestValue").text = base64.b64encode(
        digest
    ).decode("ascii")
    parent.append(signature)
    canonical_signed_info = etree.tostring(
        signed_info, method="c14n", exclusive=False, with_comments=False
    )
    etree.SubElement(signature, f"{{{_DS}}}SignatureValue").text = base64.b64encode(
        key.sign(canonical_signed_info, padding.PKCS1v15(), algorithm)
    ).decode("ascii")
    key_info = etree.SubElement(signature, f"{{{_DS}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{_DS}}}X509Data")
    etree.SubElement(x509_data, f"{{{_DS}}}X509Certificate").text = base64.b64encode(
        cert.public_bytes(Encoding.DER)
    ).decode("ascii")
