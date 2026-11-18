"""Osasco 2026 WCF per-invoice cancel/substitute request construction.

Official Prefeitura de Osasco WebService 2.1 (April/2026), page 32-33:
Cancelar fields ChaveAutenticacao, Homologacao, Motivo, NumeroNota,
TipoCancelamento. Normal cancellation ('N') and substitution ('S') are
distinct fiscal actions. This module builds the official request, not a
new receipt or alternative tax engine; core cancellation orchestration,
audit and human approval remain separate concerns.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoOperationReceipt,
    OsascoPreparedOperation,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4VerifiedInvoice,
)

_WCF = "http://tempuri.org/"
_DTO = "http://schemas.datacontract.org/2004/07/Eissnfe.Negocio.WebServices.Mensagem"


class OsascoCancelBuilderError(FiscalValidationError):
    """Invalid human-approved cancel/substitute command or municipal invoice."""


def build_osasco_cancel_request(
    *, source: Sp4OriginalRps, issued: Sp4VerifiedInvoice,
    regime: TaxRegimeCode, cancel_type: str, reason: str | None,
    human_approved: bool,
) -> OsascoPreparedOperation:
    """Build an official WCF cancellation with issuer-scoped original note."""
    if (
        not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or not isinstance(regime, TaxRegimeCode)
        or source.issuer_ibge != "3534401"
        or issued.issuer_ibge != source.issuer_ibge
        or issued.issuer_cnpj != source.issuer_cnpj
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or issued.competence_date != source.competence_date
        or issued.gross_amount != source.gross_amount
        or cancel_type not in ("N", "S")
        or human_approved is not True
    ):
        raise OsascoCancelBuilderError("Osasco cancelled note identity or approval invalid")
    if (
        not issued.invoice_number.isascii()
        or not issued.invoice_number.isdecimal()
        or int(issued.invoice_number) < 1
        or len(issued.invoice_number) > 20
        or (
            reason is not None and (
                not isinstance(reason, str) or not 1 <= len(reason) <= 500
                or any(ord(c) < 32 for c in reason)
            )
        )
    ):
        raise OsascoCancelBuilderError("Osasco cancellation number or reason invalid")
    root = etree.Element(
        f"{{{_WCF}}}Cancelar",
        nsmap={"tem": _WCF, "eis": _DTO},
    )
    fields = etree.SubElement(root, f"{{{_WCF}}}request")
    etree.SubElement(fields, f"{{{_DTO}}}ChaveAutenticacao")
    etree.SubElement(fields, f"{{{_DTO}}}Homologacao").text = "true"
    if reason is not None:
        etree.SubElement(fields, f"{{{_DTO}}}Motivo").text = reason
    etree.SubElement(fields, f"{{{_DTO}}}NumeroNota").text = issued.invoice_number
    etree.SubElement(fields, f"{{{_DTO}}}TipoCancelamento").text = cancel_type
    return OsascoPreparedOperation(
        scope=source.scope, issuer_cnpj=source.issuer_cnpj,
        tax_regime=regime, competence_date=source.competence_date,
        method="Cancelar",
        request_xml=etree.tostring(root, encoding="utf-8", xml_declaration=True),
    )


@dataclass(frozen=True, slots=True)
class OsascoCancellationDecision:
    """Only a separately verified municipal reply may advance cancellation state.

    None means ambiguous/unknown: preserve CANCEL_REQUESTED and investigate
    using read-only consultation, never resend a cancellation POST automatically.
    """

    confirmed: bool | None
    response_xml: bytes = field(repr=False)
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if (
            self.confirmed not in (True, False, None)
            or type(self.response_xml) is not bytes
            or not 0 < len(self.response_xml) <= 2_097_152
            or (
                self.rejection_code is not None and (
                    not isinstance(self.rejection_code, str)
                    or not 1 <= len(self.rejection_code) <= 64
                )
            )
            or (self.confirmed is False) != (self.rejection_code is not None)
        ):
            raise OsascoCancelBuilderError("Osasco cancellation decision is unverified")


def verify_osasco_cancel_reply(
    *,
    receipt: OsascoOperationReceipt,
    source: Sp4OriginalRps,
    issued: Sp4VerifiedInvoice,
    verify_official_response: Callable[
        [bytes, Sp4OriginalRps, Sp4VerifiedInvoice], bool | None
    ],
) -> OsascoCancellationDecision:
    """Only a reviewed external validator interprets cancellation confirmation.

    The WCF result is not proof of a cancellation by itself; the supplied
    verifier must correlate the municipal response/consultation to the original
    invoice, taxpayer, number, scope and legal cancellation requirements.
    """
    if (
        not isinstance(receipt, OsascoOperationReceipt)
        or receipt.method != "Cancelar"
        or not isinstance(source, Sp4OriginalRps)
        or not isinstance(issued, Sp4VerifiedInvoice)
        or not callable(verify_official_response)
        or source.issuer_ibge != "3534401"
        or source.issuer_cnpj != issued.issuer_cnpj
        or issued.issuer_ibge != source.issuer_ibge
        or issued.rps_number != source.rps_number
        or issued.rps_series != source.rps_series
        or issued.competence_date != source.competence_date
        or issued.gross_amount != source.gross_amount
        or not receipt.response_xml
    ):
        raise OsascoCancelBuilderError("Unreviewed Osasco cancellation response")
    proof = verify_official_response(receipt.response_xml, source, issued)
    if type(proof) is not bool and proof is not None:
        raise OsascoCancelBuilderError("Municipal cancellation proof must be tri-state")
    if receipt.fiscal_error and proof is True:
        raise OsascoCancelBuilderError("Contradictory Osasco cancellation response")
    if proof is False:
        return OsascoCancellationDecision(
            confirmed=False, response_xml=receipt.response_xml,
            rejection_code="OSASCO_CANCEL_REJECTED",
        )
    return OsascoCancellationDecision(
        confirmed=proof, response_xml=receipt.response_xml,
    )
