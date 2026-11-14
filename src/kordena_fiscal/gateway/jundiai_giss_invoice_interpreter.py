"""GissOnline 2.04: reconcile provider-issued CompNfse to one durable RPS.

The municipal transport's SOAP receipt is not an invoice. Only its isolated
official service XML, under Giss-specific namespaces, can yield a candidate
invoice. An independent official XSD/XMLDSig verifier MUST approve the bytes
before the canonical gateway promotes AUTHORIZED. For a missing/unknown RPS,
the answer stays PENDING: a prior POST may still be processing.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from kordena_fiscal.domain import Cnpj
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiGissReceipt
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_RESPONSE = "{http://www.giss.com.br/consultar-nfse-rps-resposta-v2_04.xsd}"
_TYPES = "{http://www.giss.com.br/tipos-v2_04.xsd}"
_LIMIT = 2_097_152


def _required(parent: etree._Element, path: str, name: str) -> str:
    nodes = parent.findall(path)
    if len(nodes) != 1 or not nodes[0].text or not nodes[0].text.strip():
        raise Sp4CanonicalMunicipalError(f"GissOnline official {name} is ambiguous or missing")
    value = nodes[0].text.strip()
    if len(value) > 128 or any(ord(c) < 32 for c in value):
        raise Sp4CanonicalMunicipalError(f"GissOnline official {name} is invalid")
    return value


def _candidate_from_giss(
    official_xml: bytes, original: Sp4OriginalRps,
) -> Sp4VerifiedInvoice | None:
    if not isinstance(official_xml, bytes) or not 0 < len(official_xml) <= _LIMIT:
        raise Sp4CanonicalMunicipalError("GissOnline official response length invalid")
    try:
        root = etree.fromstring(
            official_xml, parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise Sp4CanonicalMunicipalError("GissOnline official XML malformed") from None
    if (
        root.tag != _RESPONSE + "ConsultarNfseRpsResposta"
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise Sp4CanonicalMunicipalError("GissOnline official response schema root mismatch")
    notes = root.findall(".//" + _TYPES + "CompNfse")
    if not notes:
        return None
    if len(notes) != 1:
        raise Sp4CanonicalMunicipalError("GissOnline returned multiple invoice candidates")
    info = notes[0].find(_TYPES + "Nfse/" + _TYPES + "InfNfse")
    if info is None:
        raise Sp4CanonicalMunicipalError("GissOnline invoice has no fiscal InfNfse")
    source = info.find(
        _TYPES + "DeclaracaoPrestacaoServico/"
        + _TYPES + "InfDeclaracaoPrestacaoServico"
    )
    if source is None:
        raise Sp4CanonicalMunicipalError("GissOnline invoice lacks original RPS declaration")
    number = _required(info, _TYPES + "Numero", "NFS-e number")
    verification = _required(
        info, _TYPES + "CodigoVerificacao", "verification code",
    )
    municipality = _required(
        info, _TYPES + "OrgaoGerador/" + _TYPES + "CodigoMunicipio",
        "emitting municipality",
    )
    issuer = _required(
        source, _TYPES + "Prestador/" + _TYPES + "CpfCnpj/" + _TYPES + "Cnpj",
        "original issuer CNPJ",
    )
    invoice_issuer = _required(
        info,
        _TYPES + "PrestadorServico/" + _TYPES + "IdentificacaoPrestador/"
        + _TYPES + "CpfCnpj/" + _TYPES + "Cnpj",
        "official invoice issuer CNPJ",
    )
    rps_number = _required(
        source,
        _TYPES + "Rps/" + _TYPES + "IdentificacaoRps/" + _TYPES + "Numero",
        "original RPS number",
    )
    rps_series = _required(
        source,
        _TYPES + "Rps/" + _TYPES + "IdentificacaoRps/" + _TYPES + "Serie",
        "original RPS series",
    )
    competence = _required(source, _TYPES + "Competencia", "competence")
    value = _required(
        source, _TYPES + "Servico/" + _TYPES + "Valores/"
        + _TYPES + "ValorServicos", "gross service amount",
    )
    try:
        competence_date = date.fromisoformat(competence)
        gross_amount = Decimal(value)
        parsed_cnpj = Cnpj(issuer)
    except (ValueError, InvalidOperation):
        raise Sp4CanonicalMunicipalError("GissOnline invoice fiscal fields invalid") from None
    if (
        not number.isascii() or not number.isdecimal()
        or parsed_cnpj.value != invoice_issuer
        or parsed_cnpj != original.issuer_cnpj
        or municipality != original.issuer_ibge
        or competence_date != original.competence_date
        or rps_number != original.rps_number
        or rps_series != original.rps_series
        or not gross_amount.is_finite()
        or gross_amount != original.gross_amount
    ):
        raise Sp4CanonicalMunicipalError(
            "GissOnline official invoice differs from original taxpayer RPS"
        )
    # Municipal NFS-e number is the official issuer-scoped reference.
    # Never invent a 50-digit National key or pretend XMLDSig was verified.
    return Sp4VerifiedInvoice(
        issuer_cnpj=parsed_cnpj,
        issuer_ibge=municipality,
        competence_date=competence_date,
        rps_number=rps_number,
        rps_series=rps_series,
        gross_amount=gross_amount,
        invoice_number=number,
        verification_code=verification,
        invoice_reference=number,
        authorized_xml=official_xml,
    )


def interpret_jundiai_giss_result(
    receipt: JundiaiGissReceipt,
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
) -> Sp4ProviderOutcome:
    """Only read-only RPS lookup can confirm a specific invoice."""
    if not isinstance(receipt, JundiaiGissReceipt) or not isinstance(
        original, Sp4OriginalRps
    ) or not isinstance(request, NfseAuthorizationRequest):
        raise Sp4CanonicalMunicipalError("GissOnline requires a canonical fiscal receipt")
    if receipt.method == "RecepcionarLoteRps":
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.PENDING,
            provider_request_id=receipt.batch_protocol,
        )
    if receipt.method != "ConsultarNfsePorRps":
        raise Sp4CanonicalMunicipalError("GissOnline invoice proof must come from RPS lookup")
    if not receipt.official_response_xml:
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    candidate = _candidate_from_giss(receipt.official_response_xml, original)
    if candidate is None:
        return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
    # Caller’s canonical verify_official_invoice_xml port validates this same
    # official result against pinned Giss 2.04 XSD and authoritative signature.
    return Sp4ProviderOutcome(
        status=AuthorizationStatus.AUTHORIZED,
        official_invoice=candidate,
    )
