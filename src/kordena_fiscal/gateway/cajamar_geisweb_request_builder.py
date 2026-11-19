"""Cajamar GeisWeb lot-recovery XML from the *persisted* original RPS.

The layout corresponds to GeisWeb 10.2, section 13.3 (ConsultaLoteRps),
which identifies the originating taxpayer, the service provider and the
original lot. The online WSDL/XSD pin is a separate environment-specific
port, not recreated from this historical reference.

This builder does not assign fiscal numbers or mutate a document. Its output
is signed by the existing A1 signer port if the current municipal schema
requires it, then checked against the pinned XSD before SOAP transmission.
"""
from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarPreparedNfse
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps

_MAX = 2_097_152


class CajamarGeiswebBuilderError(FiscalValidationError):
    """Sanitized Cajamar original-RPS recovery preparation error."""


def build_cajamar_lot_query_xml(
    *, issuer_cnpj: Cnpj, original_lot: str,
) -> bytes:
    """Construct GeisWeb's canonical, numbered ConsultaLoteRps payload."""
    if (
        not isinstance(issuer_cnpj, Cnpj)
        or not isinstance(original_lot, str)
        or not 1 <= len(original_lot) <= 10
        or not original_lot.isascii()
        or not original_lot.isdecimal()
        or int(original_lot) <= 0
    ):
        raise CajamarGeiswebBuilderError("Original GeisWeb lot identity unavailable")
    root = etree.Element("ConsultaLoteRps")
    etree.SubElement(root, "CnpjCpf").text = issuer_cnpj.value
    query = etree.SubElement(root, "Consulta")
    etree.SubElement(query, "CnpjCpfPrestador").text = issuer_cnpj.value
    etree.SubElement(query, "NumeroLote").text = original_lot
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def prepare_cajamar_original_lot_query(
    *,
    source: Sp4OriginalRps,
    tax_regime: object,
    sign_document: Callable[[bytes], bytes],
    validate_signed_request: Callable[[bytes], None],
) -> CajamarPreparedNfse:
    """Prepare a non-mutating signed request using the current XSD port.

    The signer must use existing A1 material and the active municipal XMLDSig
    contract. Its result is NOT assumed to be valid merely because it's XML.
    """
    from kordena_fiscal.domain import TaxRegimeCode

    if (
        not isinstance(source, Sp4OriginalRps)
        or source.issuer_ibge != "3509205"
        or not isinstance(tax_regime, TaxRegimeCode)
        or not callable(sign_document)
        or not callable(validate_signed_request)
        or source.municipal_batch_id is None
    ):
        raise CajamarGeiswebBuilderError("Invalid Cajamar municipal query source")
    raw = build_cajamar_lot_query_xml(
        issuer_cnpj=source.issuer_cnpj,
        original_lot=source.municipal_batch_id,
    )
    signed = sign_document(raw)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _MAX:
        raise CajamarGeiswebBuilderError("Cajamar signed XML missing or oversized")
    try:
        root = etree.fromstring(
            signed, parser=etree.XMLParser(
                no_network=True, load_dtd=False, resolve_entities=False, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise CajamarGeiswebBuilderError("Cajamar signed XML is invalid") from None
    if root.tag != "ConsultaLoteRps" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise CajamarGeiswebBuilderError("Cajamar signed XML root mismatch")
    nodes = {
        name: [
            n for n in root.iter()
            if etree.QName(n).localname == name
        ] for name in ("CnpjCpf", "CnpjCpfPrestador", "NumeroLote")
    }
    if any(len(nodes[name]) != 1 for name in nodes) or (
        (nodes["CnpjCpf"][0].text or "").strip() != source.issuer_cnpj.value
        or (nodes["CnpjCpfPrestador"][0].text or "").strip()
        != source.issuer_cnpj.value
        or (nodes["NumeroLote"][0].text or "").strip() != source.municipal_batch_id
    ):
        raise CajamarGeiswebBuilderError(
            "Signed GeisWeb query no longer matches persisted source RPS"
        )
    validate_signed_request(signed)
    return CajamarPreparedNfse(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        tax_regime=tax_regime, competence_date=source.competence_date,
        method="ConsultaLoteRps", signed_request_xml=signed,
    )
