"""Osasco WCF v2.1: construct immutable source-linked full-note consultation.

Official Osasco Web Service v2.1, April/2026, section 'Método
ConsultarNotaCompleta' (pages 36-38). Only required ChaveAutenticacao and
exact persisted NumeroReciboUnico are sent, in alphabetical field order.

The actual 36-character taxpayer-specific key is deliberately inserted by
OsascoRtcHomologationTransport, never serialized by this request builder.
The key/driver is a runtime configuration, not a placeholder database value.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoPreparedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps

_METHOD_NS = "http://tempuri.org/"
_DTO = "http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem"


class OsascoWcfBuilderError(FiscalValidationError):
    """Invalid original receipt or taxpayer scope for official Osasco query."""


def build_osasco_original_note_query(
    *, original: Sp4OriginalRps, regime: TaxRegimeCode,
) -> OsascoPreparedOperation:
    """One read-only municipal consultation; no new fiscal RPS allocation."""
    if (
        not isinstance(original, Sp4OriginalRps)
        or original.issuer_ibge != "3534401"
        or not isinstance(regime, TaxRegimeCode)
        or not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or not 1 <= len(original.rps_number) <= 20
        or int(original.rps_number) < 1
    ):
        raise OsascoWcfBuilderError("Original Osasco receipt identity unavailable")
    root = etree.Element(
        f"{{{_METHOD_NS}}}ConsultarNotaCompleta",
        nsmap={"tem": _METHOD_NS, "eis": _DTO},
    )
    fields = etree.SubElement(root, f"{{{_METHOD_NS}}}request")
    # Key placeholder is required by the SOAP assembler; its real value
    # is resolved from the tenant/unit credential after the provider binding.
    etree.SubElement(fields, f"{{{_DTO}}}ChaveAutenticacao")
    etree.SubElement(fields, f"{{{_DTO}}}NumeroReciboUnico").text = (
        original.rps_number
    )
    return OsascoPreparedOperation(
        scope=original.scope, issuer_cnpj=original.issuer_cnpj,
        tax_regime=regime, competence_date=original.competence_date,
        method="ConsultarNotaCompleta",
        request_xml=etree.tostring(root, encoding="utf-8", xml_declaration=True),
    )
