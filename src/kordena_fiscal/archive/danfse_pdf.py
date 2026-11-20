"""Render a National DANFSe strictly from the official archived NFS-e XML.

No signing, authorization, gateway transmission or third-party PDF service.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError

_NS = "http://www.sped.fazenda.gov.br/nfse"
_MAX_XML = 2_097_152
_MAX_PDF = 8_388_608


def render_authorized_national_danfse(xml_bytes: bytes) -> bytes:
    """Reject unsupported XMLs and require a National 50-digit invoice identity."""
    if not isinstance(xml_bytes, bytes) or not 0 < len(xml_bytes) <= _MAX_XML:
        raise FiscalValidationError("XML NFS-e ausente ou excede limite")
    try:
        root = etree.fromstring(
            xml_bytes, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("XML nacional inválido para DANFSe") from None
    if root.tag != f"{{{_NS}}}NFSe" or getattr(root.getroottree().docinfo, "doctype", ""):
        raise FiscalValidationError("DANFSe exige XML NFS-e Nacional, sem DTD")
    infos = root.findall(f"{{{_NS}}}infNFSe")
    if len(infos) != 1:
        raise FiscalValidationError("DANFSe exige uma NFS-e identificada")
    xml_id = infos[0].get("Id", "")
    if (
        not xml_id.startswith("NFS") or len(xml_id) != 53
        or not xml_id[3:].isascii() or not xml_id[3:].isdecimal()
    ):
        raise FiscalValidationError("DANFSe exige chave nacional de 50 dígitos")
    try:
        from brazilfiscalreport.danfse import Danfse  # type: ignore[import-untyped]

        rendered = Danfse(xml=xml_bytes.decode("utf-8")).output(dest="S")
        pdf = bytes(rendered) if isinstance(rendered, (bytes, bytearray)) else b""
    except Exception as exc:
        raise FiscalValidationError("Falha na geração local da DANFSe") from exc
    if not pdf.startswith(b"%PDF-") or len(pdf) > _MAX_PDF:
        raise FiscalValidationError("Gerador DANFSe não produziu PDF válido")
    return pdf
