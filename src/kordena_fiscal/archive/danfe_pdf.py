"""Render NF-e DANFE from *already authorized* nfeProc XML.

No issuance, signature or provider business rule lives in the renderer. Output
is generated locally; no customer XML is sent to third-party web services.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError

_NFE = "http://www.portalfiscal.inf.br/nfe"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_MAX_XML_BYTES = 2_097_152
_MAX_PDF_BYTES = 8_388_608


def render_authorized_nfe_danfe(xml_bytes: bytes) -> bytes:
    """Render a printable DANFE only from an authorized, consistent NF-e 4.00."""
    if not isinstance(xml_bytes, bytes) or not 0 < len(xml_bytes) <= _MAX_XML_BYTES:
        raise FiscalValidationError("XML autorizado ausente ou excede limite")
    try:
        root = etree.fromstring(
            xml_bytes, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("XML NF-e inválido") from None
    if getattr(root.getroottree().docinfo, "doctype", "") or root.tag != f"{{{_NFE}}}nfeProc":
        raise FiscalValidationError("DANFE requer nfeProc autorizado, sem DTD")
    if root.get("versao") != "4.00":
        raise FiscalValidationError("DANFE exige leiaute NF-e 4.00")
    invoices = root.findall(f"{{{_NFE}}}NFe/{{{_NFE}}}infNFe")
    protocols = root.findall(f"{{{_NFE}}}protNFe/{{{_NFE}}}infProt")
    if len(invoices) != 1 or len(protocols) != 1:
        raise FiscalValidationError("NF-e protocolada exige nota e protocolo únicos")
    signature = root.findall(f"{{{_NFE}}}NFe/{{{_DS}}}Signature")
    model = invoices[0].findtext(f"{{{_NFE}}}ide/{{{_NFE}}}mod")
    if len(signature) != 1 or model != "55":
        raise FiscalValidationError("DANFE exige NF-e modelo 55 com XMLDSig")
    access_key = invoices[0].get("Id", "")
    protocol_key = protocols[0].findtext(f"{{{_NFE}}}chNFe")
    status = protocols[0].findtext(f"{{{_NFE}}}cStat")
    environment = protocols[0].findtext(f"{{{_NFE}}}tpAmb")
    if (
        len(access_key) != 47
        or not access_key.startswith("NFe")
        or protocol_key != access_key[3:]
        or status != "100"
        or environment != "2"
        or not protocols[0].findtext(f"{{{_NFE}}}nProt")
    ):
        raise FiscalValidationError("DANFE bloqueado: protocolo NF-e não autorizado")
    try:
        from brazilfiscalreport.danfe import Danfe  # type: ignore[import-untyped]

        document = Danfe(xml=xml_bytes.decode("utf-8"))
        rendered = document.output()
        pdf = bytes(rendered) if isinstance(rendered, (bytes, bytearray)) else b""
    except Exception as exc:  # Fiscal PDF adapter: never leak renderer errors or XML\n
        raise FiscalValidationError("Falha na geração segura do DANFE") from exc
    if not pdf.startswith(b"%PDF-") or len(pdf) > _MAX_PDF_BYTES:
        raise FiscalValidationError("Gerador DANFE não produziu um PDF válido")
    return pdf
