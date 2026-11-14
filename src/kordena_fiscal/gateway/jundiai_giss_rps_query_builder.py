"""Build a real Jundiaí GissOnline V2 ABRASF 2.04 query-by-RPS request.

The provider accepts ConsultarNfsePorRps with ConsultarNfseRpsEnvio.
The wire contract and official XSD/WS-Security are reviewed by the existing
JundiaiGissHomologationTransport, so no taxpayer certificate is embedded here.
This builder can be exercised with synthetic taxpayers during construction.
"""
from __future__ import annotations

from lxml import etree

from kordena_fiscal.domain import TaxRegimeCode
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiSignedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)

_DOCUMENT = "http://www.giss.com.br/consultar-nfse-rps-envio-v2_04.xsd"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"


def build_jundiai_rps_query(
    original: Sp4OriginalRps,
    tax_regime: TaxRegimeCode,
    *,
    municipal_registration: str,
    rps_type: int = 1,
) -> JundiaiSignedOperation:
    """Use the originally issued RPS number, series, issuer and IM.

    This request retrieves a note without a second POST of the RPS batch.
    """
    if not isinstance(original, Sp4OriginalRps) or original.issuer_ibge != "3525904":
        raise Sp4CanonicalMunicipalError("Original Jundiai RPS not supplied")
    if not isinstance(tax_regime, TaxRegimeCode):
        raise Sp4CanonicalMunicipalError("Jundiai fiscal regime missing")
    if (
        not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or int(original.rps_number) < 1
        or not municipal_registration.isascii()
        or not municipal_registration.isdecimal()
        or not 1 <= len(municipal_registration) <= 20
        or rps_type not in (1, 2, 3)
    ):
        raise Sp4CanonicalMunicipalError("Invalid Jundiai RPS or municipal registration")
    root = etree.Element(
        f"{{{_DOCUMENT}}}ConsultarNfseRpsEnvio",
        nsmap={"g": _DOCUMENT, "t": _TYPES},
    )
    identification = etree.SubElement(root, f"{{{_TYPES}}}IdentificacaoRps")
    for tag, value in (
        ("Numero", original.rps_number),
        ("Serie", original.rps_series),
        ("Tipo", str(rps_type)),
    ):
        etree.SubElement(identification, f"{{{_TYPES}}}{tag}").text = value
    issuer = etree.SubElement(root, f"{{{_TYPES}}}Prestador")
    cnpj = etree.SubElement(issuer, f"{{{_TYPES}}}CpfCnpj")
    etree.SubElement(cnpj, f"{{{_TYPES}}}Cnpj").text = original.issuer_cnpj.value
    etree.SubElement(issuer, f"{{{_TYPES}}}InscricaoMunicipal").text = (
        municipal_registration
    )
    return JundiaiSignedOperation(
        scope=original.scope,
        issuer_cnpj=original.issuer_cnpj,
        tax_regime=tax_regime,
        competence_date=original.competence_date,
        method="ConsultarNfsePorRps",
        signed_xml=etree.tostring(root, encoding="utf-8", xml_declaration=True),
    )
