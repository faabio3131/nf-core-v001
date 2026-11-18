"""Build Osasco's actual read-only ConsultaNotaCompleta WCF request.

The city's April/2026 WebService 2.1 manual, pp. 36–38, defines the
alphabetical Mensagem fields and the NumeroReciboUnico filter. This builder
uses the original, persisted receipt number, leaving taxpayer auth blank so
the approved Osasco WCF transport injects the active secret independently.

This is functional request construction, usable with simulated or authorized
credentials, not a claimed real Prefeitura authorization.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoPreparedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)

_WCF = "http://tempuri.org/"
_MSG = "http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem"

# Exact order from Osasco's original public method contract (APR/2026).
_FIELDS = (
    "CNPJTomador",
    "CPFTomador",
    "ChaveAutenticacao",
    "DataFinal",
    "DataInicial",
    "NumeroNotaFinal",
    "NumeroNotaInicial",
    "NumeroReciboFinal",
    "NumeroReciboInicial",
    "NumeroReciboUnico",
)


def build_osasco_full_note_query(
    original: Sp4OriginalRps, tax_regime: TaxRegimeCode,
) -> OsascoPreparedOperation:
    """Return a prepared, source-bound query with NO credential in the XML."""
    if not isinstance(original, Sp4OriginalRps) or original.issuer_ibge != "3534401":
        raise Sp4CanonicalMunicipalError("Original Osasco receipt not supplied")
    if not isinstance(tax_regime, TaxRegimeCode):
        raise Sp4CanonicalMunicipalError("Original taxpayer regime must be known")
    if (
        not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or int(original.rps_number) < 1
    ):
        raise Sp4CanonicalMunicipalError("Original Osasco receipt invalid")
    root = etree.Element(
        f"{{{_WCF}}}ConsultarNotaCompleta",
        nsmap={"tem": _WCF, "eis": _MSG},
    )
    wrapper = etree.SubElement(root, f"{{{_WCF}}}request")
    for name in _FIELDS:
        value = etree.SubElement(wrapper, f"{{{_MSG}}}{name}")
        if name == "NumeroReciboUnico":
            value.text = original.rps_number
    return OsascoPreparedOperation(
        scope=original.scope,
        issuer_cnpj=original.issuer_cnpj,
        tax_regime=tax_regime,
        competence_date=original.competence_date,
        method="ConsultarNotaCompleta",
        request_xml=etree.tostring(root, encoding="utf-8", xml_declaration=True),
    )
