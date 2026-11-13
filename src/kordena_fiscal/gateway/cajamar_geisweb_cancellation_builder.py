"""Cajamar GeisWeb 10.2 §13.4: issuer-scoped municipal cancellation XML.

A prepared cancellation is not a fiscal confirmation. The municipal
response must be interpreted separately by the existing fiscal operation
orchestrator. This builder accepts the original RPS and its previously
verified note and delegates XMLDSig/XSD to reviewed runtime ports.
"""
from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarPreparedNfse
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_LIMIT = 2_097_152


class CajamarGeiswebCancellationError(FiscalValidationError):
    """Cajamar fiscal cancellation request has invalid source identity."""


def build_cajamar_cancel_xml(
    *, source: Sp4OriginalRps, issued: Sp4VerifiedInvoice,
) -> bytes:
    """Build GeisWeb CancelaNfse with no second RPS or invented identifier."""
    if (
        not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or source.issuer_ibge != "3509205"
        or issued.issuer_ibge != source.issuer_ibge
        or issued.issuer_cnpj != source.issuer_cnpj
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or issued.competence_date != source.competence_date
        or issued.gross_amount != source.gross_amount
        or not issued.invoice_number.isascii()
        or not issued.invoice_number.isdecimal()
        or not 1 <= len(issued.invoice_number) <= 10
        or int(issued.invoice_number) <= 0
    ):
        raise CajamarGeiswebCancellationError(
            "Original GeisWeb fiscal invoice and RPS mismatch"
        )
    root = etree.Element("CancelaNfse")
    etree.SubElement(root, "CnpjCpf").text = source.issuer_cnpj.value
    cancel = etree.SubElement(root, "Cancela")
    etree.SubElement(cancel, "CnpjCpfPrestador").text = source.issuer_cnpj.value
    etree.SubElement(cancel, "NumeroNfse").text = issued.invoice_number
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def prepare_cajamar_cancel(
    *, source: Sp4OriginalRps, issued: Sp4VerifiedInvoice,
    regime: TaxRegimeCode, human_approved: bool,
    sign_document: Callable[[bytes], bytes],
    validate_signed_request: Callable[[bytes], None],
) -> CajamarPreparedNfse:
    """Prepare for the existing city transport; return is not authorization."""
    if (
        not isinstance(regime, TaxRegimeCode)
        or human_approved is not True
        or not callable(sign_document)
        or not callable(validate_signed_request)
    ):
        raise CajamarGeiswebCancellationError(
            "Incomplete Cajamar cancellation approval or signing ports"
        )
    raw = build_cajamar_cancel_xml(source=source, issued=issued)
    signed = sign_document(raw)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _LIMIT:
        raise CajamarGeiswebCancellationError("Signed GeisWeb cancellation XML unavailable")
    try:
        root = etree.fromstring(
            signed, parser=etree.XMLParser(
                no_network=True, load_dtd=False, resolve_entities=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise CajamarGeiswebCancellationError("Invalid signed GeisWeb cancellation") from None
    if root.tag != "CancelaNfse" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise CajamarGeiswebCancellationError("GeisWeb cancellation root changed")
    fields = (
        ("CnpjCpf", source.issuer_cnpj.value),
        ("Cancela/CnpjCpfPrestador", source.issuer_cnpj.value),
        ("Cancela/NumeroNfse", issued.invoice_number),
    )
    for path, value in fields:
        found = root.findall(path)
        if len(found) != 1 or found[0].text != value:
            raise CajamarGeiswebCancellationError(
                "Signed cancellation no longer matches original fiscal note"
            )
    validate_signed_request(signed)
    return CajamarPreparedNfse(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        tax_regime=regime, competence_date=source.competence_date,
        method="CancelaNfse", signed_request_xml=signed,
        human_approved=True,
    )
