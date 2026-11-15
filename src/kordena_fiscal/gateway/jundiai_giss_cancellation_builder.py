"""Jundiaí GissOnline ABRASF 2.04 cancellation request preparation.

Official GissOnline Serviços Prestados V1.8, §7.1.1 and tcPedidoCancelamento:
CancelarNfseEnvio/Pedido/InfPedidoCancelamento contains original
IdentificacaoNfse (Numero, CpfCnpj/Cnpj, optional IM, CodigoMunicipio),
CodigoCancelamento and source-linked XML signature Id. Valid municipal
reason codes 1 (emission error), 2 (service not provided), 4 (duplicate);
codes 3 and 5 are restricted to the tax authority, per ABRASF 2.04.
The existing issuer signer and pinned XSD validator produce final payloads.
"""
from __future__ import annotations

from collections.abc import Callable

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiSignedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_ROOT = "http://www.giss.com.br/cancelar-nfse-envio-v2_04.xsd"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"
_LIMIT = 2_097_152


class JundiaiGissCancelError(FiscalValidationError):
    """Municipal cancellation request is not matched to original invoice."""


def build_jundiai_cancel_xml(
    *,
    source: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice,
    cancel_code: str,
    signature_reference_id: str,
    municipal_registration: str | None,
) -> bytes:
    """Prepare a provider-compatible fiscal request; no synthetic confirmation."""
    if (
        not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or source.issuer_ibge != "3525904"
        or issued.issuer_ibge != source.issuer_ibge
        or issued.issuer_cnpj != source.issuer_cnpj
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or issued.competence_date != source.competence_date
        or issued.gross_amount != source.gross_amount
        or not issued.invoice_number.isascii()
        or not issued.invoice_number.isdecimal()
        or int(issued.invoice_number) < 1
        or len(issued.invoice_number) > 15
        or cancel_code not in ("1", "2", "4")
        or not isinstance(signature_reference_id, str)
        or not 1 <= len(signature_reference_id) <= 64
        or not signature_reference_id.isascii()
        or not signature_reference_id[0].isalpha()
        or not all(ch.isalnum() or ch in "._-" for ch in signature_reference_id)
        or (
            municipal_registration is not None
            and (
                not isinstance(municipal_registration, str)
                or not 1 <= len(municipal_registration) <= 15
                or not municipal_registration.isascii()
                or not municipal_registration.isdecimal()
            )
        )
    ):
        raise JundiaiGissCancelError("Invalid original Giss NFS-e cancellation identity")
    root = etree.Element(
        f"{{{_ROOT}}}CancelarNfseEnvio",
        nsmap={"giss": _ROOT, "tipos": _TYPES},
    )
    pedido = etree.SubElement(root, f"{{{_ROOT}}}Pedido")
    info = etree.SubElement(
        pedido, f"{{{_TYPES}}}InfPedidoCancelamento",
        Id=signature_reference_id,
    )
    ident = etree.SubElement(info, f"{{{_TYPES}}}IdentificacaoNfse")
    etree.SubElement(ident, f"{{{_TYPES}}}Numero").text = issued.invoice_number
    cn = etree.SubElement(ident, f"{{{_TYPES}}}CpfCnpj")
    etree.SubElement(cn, f"{{{_TYPES}}}Cnpj").text = source.issuer_cnpj.value
    if municipal_registration is not None:
        etree.SubElement(ident, f"{{{_TYPES}}}InscricaoMunicipal").text = (
            municipal_registration
        )
    etree.SubElement(ident, f"{{{_TYPES}}}CodigoMunicipio").text = source.issuer_ibge
    etree.SubElement(info, f"{{{_TYPES}}}CodigoCancelamento").text = cancel_code
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def prepare_jundiai_cancel(
    *, source: Sp4OriginalRps, issued: Sp4VerifiedInvoice,
    regime: TaxRegimeCode, cancel_code: str,
    signature_reference_id: str, municipal_registration: str | None,
    human_approved: bool,
    sign_document: Callable[[bytes], bytes],
    validate_signed_request: Callable[[bytes], None],
) -> JundiaiSignedOperation:
    """Reuse source issuer A1 and pinned 2.04 XSD/signature ports."""
    if (
        not isinstance(regime, TaxRegimeCode)
        or human_approved is not True
        or not callable(sign_document)
        or not callable(validate_signed_request)
    ):
        raise JundiaiGissCancelError("Giss cancellation approval/signature unavailable")
    raw = build_jundiai_cancel_xml(
        source=source, issued=issued, cancel_code=cancel_code,
        signature_reference_id=signature_reference_id,
        municipal_registration=municipal_registration,
    )
    signed = sign_document(raw)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _LIMIT:
        raise JundiaiGissCancelError("Signed Giss cancellation XML missing")
    try:
        root = etree.fromstring(
            signed, parser=etree.XMLParser(
                no_network=True, load_dtd=False, resolve_entities=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissCancelError("Signed Giss cancellation XML malformed") from None
    types = f"{{{_TYPES}}}"
    info = root.findall(f"{{{_ROOT}}}Pedido/{types}InfPedidoCancelamento")
    if (
        root.tag != f"{{{_ROOT}}}CancelarNfseEnvio"
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
        or len(info) != 1
        or info[0].get("Id") != signature_reference_id
        or len(root.findall(f".//{types}IdentificacaoNfse/{types}Numero")) != 1
        or root.findtext(f".//{types}IdentificacaoNfse/{types}Numero")
        != issued.invoice_number
        or root.findtext(f".//{types}CpfCnpj/{types}Cnpj")
        != source.issuer_cnpj.value
        or root.findtext(f".//{types}CodigoCancelamento") != cancel_code
        or root.findtext(f".//{types}CodigoMunicipio") != source.issuer_ibge
    ):
        raise JundiaiGissCancelError("Signed Giss cancellation altered original note")
    validate_signed_request(signed)
    return JundiaiSignedOperation(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        tax_regime=regime, competence_date=source.competence_date,
        method="CancelarNfse", signed_xml=signed, human_approved=True,
    )
