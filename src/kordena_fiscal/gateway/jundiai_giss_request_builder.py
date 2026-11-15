"""Jundiaí GissOnline ABRASF 2.04: source-linked read-only RPS lookup.

The municipality's current *Serviços Prestados* technical manual V1.8,
section 7.1.5, requires IdentificacaoRps and Prestador on every query.
Signer and XSD version are injected from existing government-aware runtime
ports. This module never reserves a second RPS or builds a fake receipt.
"""
from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiSignedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps

_ROOT = "http://www.giss.com.br/consultar-nfse-rps-envio-v2_04.xsd"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"
_LIMIT = 2_097_152


class JundiaiGissBuilderError(FiscalValidationError):
    """Invalid Giss source RPS identity / current XSD preparation."""


def build_jundiai_original_rps_query_xml(
    *, original: Sp4OriginalRps, municipal_registration: str,
    rps_type: str = "1",
) -> bytes:
    """Giss 2.04 ConsultarNfseRpsEnvio; builder never requests a mutation."""
    if not isinstance(original, Sp4OriginalRps) or original.issuer_ibge != "3525904":
        raise JundiaiGissBuilderError("Jundiai original service RPS is unavailable")
    if (
        not isinstance(municipal_registration, str)
        or not 1 <= len(municipal_registration) <= 20
        or not municipal_registration.isascii()
        or not municipal_registration.isdecimal()
        or int(municipal_registration) < 1
        or not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or int(original.rps_number) < 1
        or rps_type not in ("1", "2", "3")
    ):
        raise JundiaiGissBuilderError("Untrusted Giss original receipt metadata")
    namespaces: dict[str, str] = {"giss": _ROOT, "tipos": _TYPES}
    root = etree.Element(
        f"{{{_ROOT}}}ConsultarNfseRpsEnvio",
        nsmap=namespaces,
    )
    rps = etree.SubElement(root, f"{{{_ROOT}}}IdentificacaoRps")
    etree.SubElement(rps, f"{{{_TYPES}}}Numero").text = original.rps_number
    etree.SubElement(rps, f"{{{_TYPES}}}Serie").text = original.rps_series
    etree.SubElement(rps, f"{{{_TYPES}}}Tipo").text = rps_type
    issuer = etree.SubElement(root, f"{{{_ROOT}}}Prestador")
    identity = etree.SubElement(issuer, f"{{{_TYPES}}}CpfCnpj")
    etree.SubElement(identity, f"{{{_TYPES}}}Cnpj").text = original.issuer_cnpj.value
    etree.SubElement(issuer, f"{{{_TYPES}}}InscricaoMunicipal").text = (
        municipal_registration
    )
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def prepare_jundiai_original_rps_query(
    *, original: Sp4OriginalRps, regime: TaxRegimeCode,
    municipal_registration: str, sign_document: Callable[[bytes], bytes],
    validate_signed_request: Callable[[bytes], None],
) -> JundiaiSignedOperation:
    """Delegate A1 XMLDSig and pinned XSD validation to runtime ports."""
    if (
        not isinstance(regime, TaxRegimeCode)
        or not callable(sign_document) or not callable(validate_signed_request)
    ):
        raise JundiaiGissBuilderError("Jundiai signer/schema components unavailable")
    raw = build_jundiai_original_rps_query_xml(
        original=original, municipal_registration=municipal_registration,
    )
    signed = sign_document(raw)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _LIMIT:
        raise JundiaiGissBuilderError("Jundiai signed RPS query invalid")
    try:
        root = etree.fromstring(
            signed,
            parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissBuilderError("Jundiai signed request XML malformed") from None
    if (
        root.tag != f"{{{_ROOT}}}ConsultarNfseRpsEnvio"
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise JundiaiGissBuilderError("Jundiai signed query schema root mismatch")
    source_numbers = root.findall(
        f".//{{{_ROOT}}}IdentificacaoRps/{{{_TYPES}}}Numero"
    )
    series = root.findall(f".//{{{_ROOT}}}IdentificacaoRps/{{{_TYPES}}}Serie")
    issuers = root.findall(
        f".//{{{_ROOT}}}Prestador/{{{_TYPES}}}CpfCnpj/{{{_TYPES}}}Cnpj"
    )
    registrations = root.findall(f".//{{{_ROOT}}}Prestador/{{{_TYPES}}}InscricaoMunicipal")
    if (
        len(source_numbers) != 1 or len(series) != 1
        or len(issuers) != 1 or len(registrations) != 1
        or source_numbers[0].text != original.rps_number
        or series[0].text != original.rps_series
        or issuers[0].text != original.issuer_cnpj.value
        or registrations[0].text != municipal_registration
    ):
        raise JundiaiGissBuilderError(
            "Jundiai signed query differs from original issuer RPS"
        )
    validate_signed_request(signed)
    return JundiaiSignedOperation(
        scope=original.scope, issuer_cnpj=original.issuer_cnpj,
        tax_regime=regime, competence_date=original.competence_date,
        method="ConsultarNfsePorRps", signed_xml=signed,
    )
