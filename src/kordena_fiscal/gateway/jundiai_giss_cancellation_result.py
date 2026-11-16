"""GissOnline 2.04 municipal cancellation proof over the original NFS-e.

Only the official CancelarNfseResposta checked against the pinned XSD,
municipal signature and the immutable fiscal invoice may finalize the event.
A timeout or ambiguous XML remains pending; never blindly resend the POST.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiGissReceipt
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_RESPONSE = "{http://www.giss.com.br/cancelar-nfse-resposta-v2_04.xsd}CancelarNfseResposta"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"
_LIMIT = 2_097_152


class JundiaiGissCancelResultError(FiscalValidationError):
    """Sanitized municipal cancellation proof error."""


@dataclass(frozen=True, slots=True)
class JundiaiGissCancellationDecision:
    """Municipal cancellation state; None requires read-only recovery."""

    confirmed: bool | None
    response_xml: bytes = field(repr=False)
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if (
            self.confirmed not in (True, False, None)
            or not isinstance(self.response_xml, bytes)
            or not 0 < len(self.response_xml) <= _LIMIT
            or (
                self.rejection_code is not None and (
                    not 0 < len(self.rejection_code) <= 64
                    or not self.rejection_code.isascii()
                )
            )
            or (self.confirmed is False) != (self.rejection_code is not None)
        ):
            raise JundiaiGissCancelResultError("Unverified GissOnline cancellation result")


def _sole_descendant(
    root: etree._Element, local_name: str, *, required: bool = True,
) -> etree._Element | None:
    nodes = [
        node for node in root.iter()
        if isinstance(node.tag, str) and etree.QName(node).localname == local_name
    ]
    if len(nodes) > 1 or (required and len(nodes) != 1):
        raise JundiaiGissCancelResultError("Ambiguous official Giss " + local_name)
    return nodes[0] if nodes else None


def verify_jundiai_cancel_reply(
    *, receipt: JundiaiGissReceipt, source: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice, code: str,
    validate_official_response: Callable[[bytes], None],
) -> JundiaiGissCancellationDecision:
    """Correlate verified XML with original CNPJ, city, note and reason code."""
    if (
        not isinstance(receipt, JundiaiGissReceipt)
        or receipt.method != "CancelarNfse"
        or not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or not callable(validate_official_response)
        or source.issuer_ibge not in {"3525904", "3518800"}
        or issued.issuer_ibge != source.issuer_ibge
        or issued.issuer_cnpj != source.issuer_cnpj
        or issued.invoice_number != issued.invoice_reference
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or code not in ("1", "2", "4")
    ):
        raise JundiaiGissCancelResultError("Giss cancellation taxpayer or scope mismatch")
    raw = receipt.official_response_xml
    if not raw:
        return JundiaiGissCancellationDecision(
            confirmed=None, response_xml=receipt.response_xml,
        )
    validate_official_response(raw)
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            huge_tree=False,
        ))
    except etree.XMLSyntaxError:
        raise JundiaiGissCancelResultError("Malformed official Giss cancellation") from None
    if (
        root.tag != _RESPONSE
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise JundiaiGissCancelResultError("Wrong official Giss cancellation XML")
    confirmed = _sole_descendant(root, "NfseCancelamento", required=False)
    errors = _sole_descendant(root, "ListaMensagemRetorno", required=False)
    if confirmed is not None and errors is not None:
        raise JundiaiGissCancelResultError("Contradictory Giss cancellation result")
    if confirmed is not None:
        if etree.QName(confirmed).namespace != _TYPES:
            raise JundiaiGissCancelResultError("Unexpected Giss cancellation namespace")
        confirmation = _sole_descendant(confirmed, "Confirmacao")
        assert confirmation is not None
        if _sole_descendant(confirmation, "DataHora") is None:
            raise JundiaiGissCancelResultError("Giss cancellation time missing")
        values: dict[str, str] = {}
        for field_name in ("Numero", "Cnpj", "CodigoMunicipio", "CodigoCancelamento"):
            node = _sole_descendant(confirmation, field_name)
            if node is None or node.text is None:
                raise JundiaiGissCancelResultError("Giss fiscal cancellation source missing")
            values[field_name] = node.text.strip()
        if values != {
            "Numero": issued.invoice_number, "Cnpj": source.issuer_cnpj.value,
            "CodigoMunicipio": source.issuer_ibge, "CodigoCancelamento": code,
        }:
            raise JundiaiGissCancelResultError(
                "Giss cancellation confirmation differs from original invoice"
            )
        return JundiaiGissCancellationDecision(
            confirmed=True, response_xml=raw,
        )
    if errors is not None:
        error = _sole_descendant(errors, "MensagemRetorno")
        if error is None:
            raise JundiaiGissCancelResultError("Giss rejection details missing")
        number = _sole_descendant(error, "Codigo")
        if number is None or not number.text or not number.text.strip():
            raise JundiaiGissCancelResultError("Giss rejection code missing")
        return JundiaiGissCancellationDecision(
            confirmed=False, response_xml=raw,
            rejection_code=number.text.strip(),
        )
    return JundiaiGissCancellationDecision(
        confirmed=None, response_xml=raw,
    )

def verify_jundiai_cancel_query(
    *, receipt: JundiaiGissReceipt, source: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice,
    validate_official_query: Callable[[bytes], None],
    verify_cancelled_note: Callable[[bytes], None],
) -> JundiaiGissCancellationDecision:
    """Read-only original RPS query can finalize a prior uncertain cancellation.

    The provider may return an active invoice while a cancellation is still
    pending. An active invoice is NOT proof of rejection and never enables a
    retry. A signed, source-correlated NfseCancelamento is confirmation.
    """
    if (
        not isinstance(receipt, JundiaiGissReceipt)
        or receipt.method != "ConsultarNfsePorRps"
        or not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or source.issuer_ibge not in {"3525904", "3518800"}
        or issued.issuer_ibge != source.issuer_ibge
        or issued.issuer_cnpj != source.issuer_cnpj
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or not callable(validate_official_query)
        or not callable(verify_cancelled_note)
    ):
        raise JundiaiGissCancelResultError("Untrusted Jundiai cancellation recovery")
    raw = receipt.official_response_xml
    if not raw:
        return JundiaiGissCancellationDecision(
            confirmed=None, response_xml=receipt.response_xml,
        )
    validate_official_query(raw)
    try:
        root = etree.fromstring(
            raw, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False,
                no_network=True, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissCancelResultError(
            "Invalid Giss original RPS cancellation consultation"
        ) from None
    if (
        root.tag != "{http://www.giss.com.br/consultar-nfse-rps-resposta-v2_04.xsd}"
        "ConsultarNfseRpsResposta"
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise JundiaiGissCancelResultError("Wrong original Giss RPS status XML")
    note = _sole_descendant(root, "CompNfse", required=False)
    if note is None:
        return JundiaiGissCancellationDecision(
            confirmed=None, response_xml=raw,
        )
    cancellation = _sole_descendant(note, "NfseCancelamento", required=False)
    if cancellation is None:
        return JundiaiGissCancellationDecision(
            confirmed=None, response_xml=raw,
        )
    if etree.QName(cancellation).namespace != _TYPES:
        raise JundiaiGissCancelResultError("Wrong official cancellation namespace")
    # The reviewer verifies the municipality's signature, pinned XSD and
    # taxpayer identity independently of the transport's SOAP 200.
    verify_cancelled_note(etree.tostring(cancellation, encoding="utf-8"))
    confirmation = _sole_descendant(cancellation, "Confirmacao")
    assert confirmation is not None
    _sole_descendant(confirmation, "DataHora")
    checks = {
        "Numero": issued.invoice_number,
        "Cnpj": source.issuer_cnpj.value,
        "CodigoMunicipio": source.issuer_ibge,
    }
    for field_name, expected in checks.items():
        node = _sole_descendant(confirmation, field_name)
        if node is None or node.text is None or node.text.strip() != expected:
            raise JundiaiGissCancelResultError(
                "Giss cancellation query differs from original authorized invoice"
            )
    return JundiaiGissCancellationDecision(
        confirmed=True, response_xml=raw,
    )
