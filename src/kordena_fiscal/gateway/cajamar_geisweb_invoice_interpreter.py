"""Cajamar GeisWeb: source-correlated result of ConsultaLoteRps.

Legacy GeisWeb manual 10.2, section 13.3 (ConsultaLoteRpsResposta)
specifies Rps/IdentificacaoNfse, NumeroRps, NumeroNfse,
CodigoVerificacao, Competencia, Servico/Valores/ValorServicos and
PrestadorServico/IdentificacaoPrestador/CnpjCpf. Status-only / Msg
responses do not authorize fiscal documents.

The independent official schema/signature verifier of the canonical adapter
MUST approve these exact bytes before the lifecycle can become AUTHORIZED.
The historical 2020 manual alone is not activation evidence for Cajamar 2026.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from kordena_fiscal.domain import Cnpj
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarGeiswebResult
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_SOAP = "{http://schemas.xmlsoap.org/soap/envelope/}"
_LIMIT = 2_097_152


def _parse(xml: bytes) -> etree._Element:
    if not isinstance(xml, bytes) or not 0 < len(xml) <= _LIMIT:
        raise Sp4CanonicalMunicipalError("GeisWeb official XML response is missing or oversized")
    try:
        root = etree.fromstring(
            xml, parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise Sp4CanonicalMunicipalError("GeisWeb returned malformed XML") from None
    if bool(getattr(root.getroottree().docinfo, "doctype", "")):
        raise Sp4CanonicalMunicipalError("GeisWeb official response forbids DTD")
    return root


def _service_result(response_xml: bytes) -> bytes:
    root = _parse(response_xml)
    if root.tag != _SOAP + "Envelope":
        raise Sp4CanonicalMunicipalError("GeisWeb response requires SOAP envelope")
    body = root.find(_SOAP + "Body")
    if body is None or body.find(_SOAP + "Fault") is not None:
        raise Sp4CanonicalMunicipalError("GeisWeb fiscal SOAP fault or missing body")
    responses = [
        node for node in body
        if etree.QName(node).localname == "ConsultaLoteRpsResponse"
    ]
    if len(responses) != 1:
        raise Sp4CanonicalMunicipalError("GeisWeb response method is ambiguous")
    results = [
        node for node in responses[0]
        if etree.QName(node).localname == "ConsultaLoteRpsResult"
    ]
    if len(results) != 1:
        raise Sp4CanonicalMunicipalError("GeisWeb returned no official consultation result")
    result = results[0]
    if len(result):
        if len(result) != 1:
            raise Sp4CanonicalMunicipalError("GeisWeb returned multiple XML documents")
        candidate = etree.tostring(result[0], encoding="utf-8")
    elif result.text and result.text.strip():
        candidate = result.text.strip().encode("utf-8")
    else:
        raise Sp4CanonicalMunicipalError("GeisWeb returned empty consultation")
    if len(candidate) > _LIMIT:
        raise Sp4CanonicalMunicipalError("GeisWeb inner XML exceeds bound")
    return candidate


def _one(parent: etree._Element, path: str, field: str, *, limit: int = 128) -> str:
    values = parent.findall(path)
    if len(values) != 1 or not values[0].text:
        raise Sp4CanonicalMunicipalError(f"GeisWeb {field} is missing or ambiguous")
    value = values[0].text.strip()
    if not 0 < len(value) <= limit or any(ord(c) < 32 for c in value):
        raise Sp4CanonicalMunicipalError(f"GeisWeb {field} is invalid")
    return value


def _amount(value: str) -> Decimal:
    # GeisWeb uses Brazilian decimals (12,2); fail closed on ambiguous
    # separators or scientific notation, with up to two fraction digits.
    normalized = value.replace(",", ".")
    if (
        value.count(",") > 1 or "." in value
        or not all(ch in "0123456789.," for ch in value)
        or normalized.count(".") > 1
    ):
        raise Sp4CanonicalMunicipalError("GeisWeb official service amount is malformed")
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        raise Sp4CanonicalMunicipalError("GeisWeb official amount is invalid") from None
    if (
        not amount.is_finite() or amount < 0
        or amount * 100 != (amount * 100).to_integral_value()
    ):
        raise Sp4CanonicalMunicipalError("GeisWeb service amount precision is invalid")
    return amount


def interpret_cajamar_geisweb_result(
    receipt: CajamarGeiswebResult,
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
) -> Sp4ProviderOutcome:
    """Read-only lot recovery confirms at most ONE matching official NFS-e.

    The EnviaLoteRps response is not promoted here. Even a synchronous
    transport acknowledgement may precede the official original-RPS proof.
    """
    if (
        not isinstance(receipt, CajamarGeiswebResult)
        or not isinstance(request, NfseAuthorizationRequest)
        or not isinstance(original, Sp4OriginalRps)
    ):
        raise Sp4CanonicalMunicipalError("GeisWeb requires canonical request and RPS")
    if receipt.method == "EnviaLoteRps":
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    if receipt.method != "ConsultaLoteRps":
        raise Sp4CanonicalMunicipalError("GeisWeb recovery must use original RPS lot")
    if not receipt.response_xml:
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    official_xml = _service_result(receipt.response_xml)
    root = _parse(official_xml)
    if root.tag != "ConsultaLoteRpsResposta":
        raise Sp4CanonicalMunicipalError("GeisWeb lot XML root mismatch")
    if root.findall("Msg"):
        if root.findall("Rps"):
            raise Sp4CanonicalMunicipalError("Contradictory GeisWeb lot error and invoice")
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    invoices = root.findall("Rps")
    if not invoices:
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    if len(invoices) != 1:
        raise Sp4CanonicalMunicipalError("GeisWeb returned multiple RPS invoices")
    rps = invoices[0]
    ident = rps.find("IdentificacaoNfse")
    if ident is None:
        raise Sp4CanonicalMunicipalError("GeisWeb invoice identification missing")
    original_number = _one(ident, "NumeroRps", "original RPS number", limit=8)
    note_number = _one(ident, "NumeroNfse", "NFS-e number", limit=8)
    verifier = _one(ident, "CodigoVerificacao", "verification code", limit=10)
    competence = _one(rps, "Competencia", "competence", limit=7)
    issuer = _one(
        rps,
        "Servico/PrestadorServico/IdentificacaoPrestador/CnpjCpf",
        "issuer CNPJ", limit=14,
    )
    billed = _amount(_one(rps, "Servico/Valores/ValorServicos", "gross amount", limit=18))
    try:
        issuer_id = Cnpj(issuer)
        competence_month = date.fromisoformat(competence + "-01")
    except ValueError:
        raise Sp4CanonicalMunicipalError("GeisWeb official fiscal identity malformed") from None
    if (
        not original_number.isascii() or not original_number.isdecimal()
        or not note_number.isascii() or not note_number.isdecimal()
        or int(original_number) != int(original.rps_number)
        or not original.rps_number.isascii() or not original.rps_number.isdecimal()
        or issuer_id != original.issuer_cnpj
        or competence_month.year != original.competence_date.year
        or competence_month.month != original.competence_date.month
        or billed != original.gross_amount
    ):
        raise Sp4CanonicalMunicipalError(
            "GeisWeb invoice differs from persisted original taxpayer RPS"
        )
    # The municipal layout does not expose an RPS series in this reply:
    # the series is taken from the exact immutable original RPS and must
    # be separately validated against the submitted signed RPS identity.
    invoice = Sp4VerifiedInvoice(
        issuer_cnpj=issuer_id,
        issuer_ibge=original.issuer_ibge,
        competence_date=original.competence_date,
        rps_number=original.rps_number,
        rps_series=original.rps_series,
        gross_amount=billed,
        invoice_number=note_number,
        verification_code=verifier,
        invoice_reference=note_number,
        authorized_xml=official_xml,
    )
    return Sp4ProviderOutcome(
        status=AuthorizationStatus.AUTHORIZED, official_invoice=invoice,
    )
