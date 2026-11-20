"""Cajamar GeisWeb 10.2 §13.4: issuer-scoped municipal cancellation XML.

A prepared cancellation is not a fiscal confirmation. The municipal
response must be interpreted separately by the existing fiscal operation
orchestrator. This builder accepts the original RPS and its previously
verified note and delegates XMLDSig/XSD to reviewed runtime ports.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebResult,
    CajamarPreparedNfse,
)
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


_SOAP = "{http://schemas.xmlsoap.org/soap/envelope/}"


@dataclass(frozen=True, slots=True)
class CajamarCancellationDecision:
    """Reviewed municipal cancellation, not an HTTP/SOAP success assumption."""

    confirmed: bool
    response_xml: bytes = field(repr=False)
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.confirmed, bool) or not isinstance(self.response_xml, bytes):
            raise CajamarGeiswebCancellationError("Invalid municipal cancel decision")
        if not 0 < len(self.response_xml) <= _LIMIT:
            raise CajamarGeiswebCancellationError("Missing municipal cancellation evidence")
        if self.confirmed == (self.rejection_code is not None):
            raise CajamarGeiswebCancellationError("Contradictory municipal cancel decision")


def interpret_cajamar_cancel_response(
    *, receipt: CajamarGeiswebResult,
    source: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice,
    verify_official_response: Callable[[bytes], None],
) -> CajamarCancellationDecision:
    """Correlate the exact original invoice with confirmed GeisWeb cancellation.

    GeisWeb's CancelaNfseResposta contains Nfse/IdentificacaoNfse with
    NumeroRps, NumeroNfse and CodigoVerificacao. A generic 200/OK or Msg
    cannot prove that a specific authorized fiscal note was cancelled.
    """
    build_cajamar_cancel_xml(source=source, issued=issued)
    if (
        not isinstance(receipt, CajamarGeiswebResult)
        or receipt.method != "CancelaNfse"
        or not callable(verify_official_response)
        or not isinstance(receipt.response_xml, bytes)
        or not 0 < len(receipt.response_xml) <= _LIMIT
    ):
        raise CajamarGeiswebCancellationError("Official GeisWeb cancellation proof required")
    try:
        parser = etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False, huge_tree=False,
        )
        soap = etree.fromstring(receipt.response_xml, parser=parser)
        if soap.tag != _SOAP + "Envelope" or bool(
            getattr(soap.getroottree().docinfo, "doctype", "")
        ):
            raise CajamarGeiswebCancellationError("Unexpected cancellation SOAP envelope")
        body = soap.find(_SOAP + "Body")
        if body is None or body.find(_SOAP + "Fault") is not None or len(body) != 1:
            raise CajamarGeiswebCancellationError("GeisWeb cancellation SOAP fault")
        wrappers = [
            elem for elem in body
            if etree.QName(elem).localname == "CancelaNfseResponse"
        ]
        if len(wrappers) != 1:
            raise CajamarGeiswebCancellationError("Ambiguous GeisWeb cancellation method")
        payloads = [
            elem for elem in wrappers[0]
            if etree.QName(elem).localname == "CancelaNfseResult"
        ]
        if len(payloads) != 1:
            raise CajamarGeiswebCancellationError("GeisWeb cancellation result unavailable")
        result = payloads[0]
        payload_text = result.text
        if len(result) == 1 and not (payload_text or "").strip():
            inner = etree.tostring(result[0], encoding="utf-8")
        elif not len(result) and isinstance(payload_text, str) and payload_text.strip():
            inner = payload_text.strip().encode("utf-8")
        else:
            raise CajamarGeiswebCancellationError("Ambiguous GeisWeb cancellation XML")
        if len(inner) > _LIMIT:
            raise CajamarGeiswebCancellationError("Oversized cancellation XML")
        root = etree.fromstring(inner, parser=parser)
    except etree.XMLSyntaxError:
        raise CajamarGeiswebCancellationError("Malformed GeisWeb cancellation XML") from None
    if root.tag != "CancelaNfseResposta" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise CajamarGeiswebCancellationError("Invalid official cancellation response")
    verify_official_response(inner)
    errors = root.findall("Msg")
    notes = root.findall("Nfse")
    if errors:
        if len(errors) != 1 or notes:
            raise CajamarGeiswebCancellationError("Contradictory municipal cancellation result")
        error_code = errors[0].findtext("Erro")
        if (
            not isinstance(error_code, str)
            or not error_code.isascii() or not error_code.isdecimal()
            or not 0 < int(error_code) <= 999
        ):
            raise CajamarGeiswebCancellationError("Unverified municipal cancellation rejection")
        return CajamarCancellationDecision(
            confirmed=False, response_xml=inner, rejection_code=error_code,
        )
    if len(notes) != 1:
        raise CajamarGeiswebCancellationError("No correlated cancelled fiscal note")
    identities = notes[0].findall("IdentificacaoNfse")
    if len(identities) != 1:
        raise CajamarGeiswebCancellationError("Ambiguous cancelled NFS-e identity")
    ident = identities[0]
    required = {
        "NumeroRps": source.rps_number,
        "NumeroNfse": issued.invoice_number,
        "CodigoVerificacao": issued.verification_code,
    }
    for key, expected in required.items():
        found = ident.findall(key)
        observed = found[0].text if len(found) == 1 else None
        if not isinstance(observed, str) or observed.strip() != expected:
            raise CajamarGeiswebCancellationError(
                "Cancellation response is not linked to original fiscal invoice"
            )
    return CajamarCancellationDecision(confirmed=True, response_xml=inner)
