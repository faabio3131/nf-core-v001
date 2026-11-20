"""Render DANFCe model 65 only from a scoped, archived and authorized NFC-e XML.

This adapter never issues a note, retrieves a CSC or signs payloads. Its sole input
is the already authorized nfeProc persisted by the canonical fiscal archive.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError

_NFE = "http://www.portalfiscal.inf.br/nfe"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_MAX_XML_BYTES = 2_097_152
_MAX_PDF_BYTES = 8_388_608


def validate_authorized_nfce_danfce(xml_bytes: bytes) -> None:
    """Validate NFC-e authorization, access-key binding and QR presence before PDF."""
    if not isinstance(xml_bytes, bytes) or not 0 < len(xml_bytes) <= _MAX_XML_BYTES:
        raise FiscalValidationError("XML NFC-e ausente ou excede limite")
    try:
        root = etree.fromstring(
            xml_bytes, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False,
                no_network=True, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("XML NFC-e inválido") from None
    if (
        root.tag != f"{{{_NFE}}}nfeProc"
        or root.get("versao") != "4.00"
        or getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise FiscalValidationError("DANFCe exige nfeProc 4.00 autorizado sem DTD")

    invoices = root.findall(f"{{{_NFE}}}NFe/{{{_NFE}}}infNFe")
    protocols = root.findall(f"{{{_NFE}}}protNFe/{{{_NFE}}}infProt")
    signatures = root.findall(f"{{{_NFE}}}NFe/{{{_DS}}}Signature")
    qr_nodes = root.findall(f"{{{_NFE}}}NFe/{{{_NFE}}}infNFeSupl/{{{_NFE}}}qrCode")
    if len(invoices) != 1 or len(protocols) != 1 or len(signatures) != 1 or len(qr_nodes) != 1:
        raise FiscalValidationError("NFC-e deve ter nota, protocolo, XMLDSig e QR únicos")

    invoice, protocol = invoices[0], protocols[0]
    model = invoice.findtext(f"{{{_NFE}}}ide/{{{_NFE}}}mod")
    invoice_environment = invoice.findtext(f"{{{_NFE}}}ide/{{{_NFE}}}tpAmb")
    protocol_environment = protocol.findtext(f"{{{_NFE}}}tpAmb")
    access_key = invoice.get("Id", "")
    number = access_key[3:] if access_key.startswith("NFe") else ""
    if (
        model != "65"
        or len(number) != 44
        or not number.isascii()
        or not number.isdecimal()
        or protocol.findtext(f"{{{_NFE}}}chNFe") != number
        or invoice_environment != "2"
        or protocol_environment != invoice_environment
        or protocol.findtext(f"{{{_NFE}}}cStat") != "100"
        or not protocol.findtext(f"{{{_NFE}}}nProt")
    ):
        raise FiscalValidationError("DANFCe exige NFC-e 65 protocolada em homologação")

    qr_code = (qr_nodes[0].text or "").strip()
    try:
        url = urlsplit(qr_code)
        if (
            url.scheme.lower() != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
            or len(qr_code) > 4096
        ):
            raise ValueError
    except ValueError:
        raise FiscalValidationError("NFC-e autorizada exige URL HTTPS de QR Code válida") from None


def render_authorized_nfce_danfce(xml_bytes: bytes) -> bytes:
    """Generate locally with the existing pinned fiscal PDF library."""
    validate_authorized_nfce_danfce(xml_bytes)
    try:
        from brazilfiscalreport.danfce import Danfce  # type: ignore[import-untyped]

        document = Danfce(xml=xml_bytes.decode("utf-8"))
        rendered = document.output(dest="S")
        pdf = bytes(rendered) if isinstance(rendered, (bytes, bytearray)) else b""
    except Exception as exc:
        raise FiscalValidationError("Falha na geração segura do DANFCe") from exc
    if not pdf.startswith(b"%PDF-") or len(pdf) > _MAX_PDF_BYTES:
        raise FiscalValidationError("Gerador DANFCe não produziu um PDF válido")
    return pdf
