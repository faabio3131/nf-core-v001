"""Cajamar GeisWeb20 v10.2 concrete ConsultaLoteRps request serializer.

Manual de integração GeisWeb20 §13.3, page 27, enumerates CnpjCpf,
Consulta/CnpjCpfPrestador/NumeroLote. This is separate from the GeisWeb
SOAP wrapper, mTLS, XML signature and provider authorization.

All values originate in the previously prepared RPS and may be synthesized
in unit tests without a real taxpayer account.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarPreparedNfse
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)


def build_cajamar_lot_query(
    original: Sp4OriginalRps, tax_regime: TaxRegimeCode,
) -> CajamarPreparedNfse:
    """Render the current immutable lot for read-only GeisWeb consultation."""
    if not isinstance(original, Sp4OriginalRps) or original.issuer_ibge != "3509205":
        raise Sp4CanonicalMunicipalError("Original Cajamar RPS not supplied")
    if not isinstance(tax_regime, TaxRegimeCode):
        raise Sp4CanonicalMunicipalError("Original Cajamar regime missing")
    if (
        original.municipal_batch_id is None
        or not 1 <= len(original.municipal_batch_id) <= 10
    ):
        raise Sp4CanonicalMunicipalError("Persisted GeisWeb lot ID required")
    root = etree.Element("ConsultaLoteRps")
    etree.SubElement(root, "CnpjCpf").text = original.issuer_cnpj.value
    consultation = etree.SubElement(root, "Consulta")
    etree.SubElement(consultation, "CnpjCpfPrestador").text = (
        original.issuer_cnpj.value
    )
    etree.SubElement(consultation, "NumeroLote").text = original.municipal_batch_id
    return CajamarPreparedNfse(
        scope=original.scope,
        issuer_cnpj=original.issuer_cnpj,
        tax_regime=tax_regime,
        competence_date=original.competence_date,
        method="ConsultaLoteRps",
        signed_request_xml=etree.tostring(root, encoding="utf-8", xml_declaration=True),
    )
