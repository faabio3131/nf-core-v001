"""Strict Osasco WCF full-invoice correlation, based on official 2024/2026 manuals.

Prefeitura V10.6 (Sep 2024), pp.18-20 documents ConsultarNotaCompletaResult
and NotaFiscalRelatorioDTO; V2.1 (Apr 2026), p.38 retains the same method.
The *current* WSDL/XSD validator remains a separate mandatory runtime port.
No SOAP 200 / Erro=false alone confers a fiscal invoice.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from lxml import etree

from kordena_fiscal.domain import Cnpj
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.osasco_rtc_homologation import OsascoOperationReceipt
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_SOAP = "{http://schemas.xmlsoap.org/soap/envelope/}"
_WCF = "{http://tempuri.org/}"
_MAX = 2_097_152


class OsascoFullInvoiceError(Sp4CanonicalMunicipalError):
    """Unverified, ambiguous or mismatched complete municipal invoice."""


def _one(parent: etree._Element, name: str) -> etree._Element:
    found = [node for node in parent if etree.QName(node).localname == name]
    if len(found) != 1:
        raise OsascoFullInvoiceError("Osasco official invoice field is missing or ambiguous")
    return found[0]


def _field(parent: etree._Element, name: str, *, maximum: int = 128) -> str:
    node = _one(parent, name)
    text = node.text.strip() if isinstance(node.text, str) else ""
    if not 0 < len(text) <= maximum or any(ord(c) < 32 for c in text):
        raise OsascoFullInvoiceError("Osasco official invoice identifier is invalid")
    return text


def _money(raw: str) -> Decimal:
    if (
        not raw or not raw.isascii()
        or raw.count(",") + raw.count(".") > 1
        or not all(c in "0123456789,." for c in raw)
        or raw.startswith((".", ","))
    ):
        raise OsascoFullInvoiceError("Osasco official invoice amount is malformed")
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        raise OsascoFullInvoiceError("Osasco invoice amount cannot be decoded") from None
    if (
        not value.is_finite() or value < 0
        or value * 100 != (value * 100).to_integral_value()
    ):
        raise OsascoFullInvoiceError("Osasco invoice amount has invalid precision")
    return value


def _parse(xml: bytes) -> etree._Element:
    if not isinstance(xml, bytes) or not 0 < len(xml) <= _MAX:
        raise OsascoFullInvoiceError("Missing bounded Osasco official invoice evidence")
    try:
        root = etree.fromstring(
            xml,
            parser=etree.XMLParser(
                no_network=True, load_dtd=False, resolve_entities=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise OsascoFullInvoiceError("Malformed Osasco official invoice XML") from None
    if bool(getattr(root.getroottree().docinfo, "doctype", "")):
        raise OsascoFullInvoiceError("Osasco municipal XML forbids DTD")
    return root


def decode_osasco_archived_full_invoice(
    raw_soap: bytes, original: Sp4OriginalRps,
) -> Sp4VerifiedInvoice:
    """Extract exactly one invoice matching the immutable original RPS.

    The caller MUST independently validate the full SOAP WSDL/XSD contract
    and the issuer-bound transport. This parser proves data correlation only.
    """
    if not isinstance(original, Sp4OriginalRps) or original.issuer_ibge != "3534401":
        raise OsascoFullInvoiceError("Original Osasco RPS is required")
    root = _parse(raw_soap)
    if root.tag != _SOAP + "Envelope":
        raise OsascoFullInvoiceError("Expected original municipal SOAP envelope")
    body = _one(root, "Body")
    if body.tag != _SOAP + "Body" or len(body) != 1:
        raise OsascoFullInvoiceError("Osasco SOAP body is ambiguous")
    response = _one(body, "ConsultarNotaCompletaResponse")
    if response.tag != _WCF + "ConsultarNotaCompletaResponse" or len(response) != 1:
        raise OsascoFullInvoiceError("Osasco SOAP method does not match query")
    result = _one(response, "ConsultarNotaCompletaResult")
    if result.tag != _WCF + "ConsultarNotaCompletaResult":
        raise OsascoFullInvoiceError("Osasco SOAP result namespace mismatch")
    if _field(result, "Erro", maximum=5).lower() != "false":
        raise OsascoFullInvoiceError("Osasco full-note query did not succeed")
    if _field(result, "QtdeNotas", maximum=5) != "1":
        raise OsascoFullInvoiceError("Osasco result does not contain exactly one note")
    notes = _one(result, "NotasGeradas")
    if len(notes) != 1:
        raise OsascoFullInvoiceError("Osasco note collection is ambiguous")
    note = _one(notes, "NotaFiscalRelatorioDTO")
    number = _field(note, "Numero", maximum=20)
    receipt = _field(note, "NumeroRecibo", maximum=20)
    authenticator = _field(note, "CodigoAutenticidade", maximum=64)
    issuer = _field(_one(note, "Prestador"), "CNPJ", maximum=14)
    amount = _money(_field(note, "Valor", maximum=24))
    if (
        not number.isascii() or not number.isdecimal() or int(number) < 1
        or not receipt.isascii() or not receipt.isdecimal()
        or not original.rps_number.isascii() or not original.rps_number.isdecimal()
        or int(receipt) != int(original.rps_number)
        or not authenticator.isascii() or not authenticator.isalnum()
        or issuer != original.issuer_cnpj.value
        or amount != original.gross_amount
    ):
        raise OsascoFullInvoiceError(
            "Osasco authorized note does not match issuer, receipt or value"
        )
    cancelled = [node for node in note if etree.QName(node).localname == "DataCancelamento"]
    if len(cancelled) > 1 or (
        cancelled and isinstance(cancelled[0].text, str)
        and cancelled[0].text.strip()
    ):
        raise OsascoFullInvoiceError("Cancelled municipal note cannot authorize issuance")
    # Invoice XML is the exact original fiscal SOAP proof. The service period
    # was already bound to the unique original receipt in the canonical UoW.
    return Sp4VerifiedInvoice(
        issuer_cnpj=Cnpj(issuer), issuer_ibge=original.issuer_ibge,
        competence_date=original.competence_date,
        rps_number=original.rps_number, rps_series=original.rps_series,
        gross_amount=amount, invoice_number=number,
        verification_code=authenticator, invoice_reference=number,
        authorized_xml=raw_soap,
    )


def interpret_osasco_full_note_result(
    receipt: OsascoOperationReceipt,
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
) -> Sp4ProviderOutcome:
    """Never accept a municipal receipt as authorized until full XML correlates."""
    if (
        not isinstance(receipt, OsascoOperationReceipt)
        or not isinstance(request, NfseAuthorizationRequest)
        or not isinstance(original, Sp4OriginalRps)
        or receipt.method != "ConsultarNotaCompleta"
        or original.document_id != request.document.document_id
        or original.request_fingerprint != request.request_fingerprint
    ):
        raise OsascoFullInvoiceError("Canonical Osasco query and original RPS required")
    if receipt.fiscal_error or not receipt.status_available or not receipt.response_xml:
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    invoice = decode_osasco_archived_full_invoice(receipt.response_xml, original)
    return Sp4ProviderOutcome(
        status=AuthorizationStatus.AUTHORIZED, official_invoice=invoice,
    )
