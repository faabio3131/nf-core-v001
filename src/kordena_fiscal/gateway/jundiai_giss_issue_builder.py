"""Jundiaí GissOnline v2.04: deterministic one-RPS invoice request serializer.

Uses the current city's GissOnline V2 schema family, the source RPS and
pre-reviewed taxpayer data. Never assigns an RPS/lot, signs with a new crypto
implementation, estimates municipal ISS or calls a prefeitura by itself.

Authority for fields: Jundiaí GissOnline technical manual v1.8 (2026), and
the municipal 2026 taxpayer guidance. Live WSDL/XSD and XMLDSig are pinned
and verified by injected canonical runtime ports.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiSignedOperation
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_ISSUE = "http://www.giss.com.br/enviar-lote-rps-envio-v2_04.xsd"
_TYPES = "http://www.giss.com.br/tipos-v2_04.xsd"
_LIMIT = 2_097_152


class JundiaiGissIssueError(FiscalValidationError):
    """Municipal ABRASF request mismatches original taxpayer/RPS facts."""


@dataclass(frozen=True, slots=True)
class JundiaiGissRecipient:
    tax_id: str
    name: str
    street: str
    street_number: str
    district: str
    city_ibge: str
    state: str
    postal_code: str
    phone: str | None = None
    email: str | None = None
    municipal_registration: str | None = None


@dataclass(frozen=True, slots=True)
class JundiaiGissTaxFields:
    """Reviewed local ISS data. The 2026 NBS/RTC fields are OPTIONAL by city guide.

    Their source and interpretation must remain with the shared fiscal core.
    The serializer does not assume that a non-national municipal invoice
    includes a tax calculation for IBS/CBS.
    """

    municipal_registration: str
    item_lista_servico: str
    municipal_taxation_code: str
    iss_exigibility: str
    incidence_ibge: str
    iss_rate: Decimal
    issuer_special_regime: str
    optante_simples: str
    fiscal_incentive: str
    recipient: JundiaiGissRecipient
    national_service_code: str | None = None
    rps_type: str = "1"
    pis: Decimal = Decimal("0.00")
    cofins: Decimal = Decimal("0.00")
    inss: Decimal = Decimal("0.00")
    income_tax: Decimal = Decimal("0.00")
    csll: Decimal = Decimal("0.00")
    other_retention: Decimal = Decimal("0.00")
    operation_indicator: str | None = None
    rtc_cst: str | None = None
    rtc_classification: str | None = None
    rtc_fin_nfse: str | None = None
    rtc_ind_dest: str | None = None
    rtc_incidence_ibge: str | None = None
    rtc_taxable_base: Decimal | None = None
    rtc_ind_final: str | None = None


def _label(value: str, name: str, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value.strip()) <= limit
        or any(ord(c) < 32 for c in value)
    ):
        raise JundiaiGissIssueError(f"Invalid GissOnline {name}")
    return value.strip()


def _decimal(value: Decimal, name: str, digits: int = 2) -> str:
    factor = 10**digits
    if (
        not isinstance(value, Decimal) or not value.is_finite()
        or value < 0 or value >= Decimal("1000000000000")
        or value * factor != (value * factor).to_integral_value()
    ):
        raise JundiaiGissIssueError(f"Invalid GissOnline {name}")
    return format(value, f".{digits}f")


def _digits(value: str, name: str, max_digits: int) -> str:
    text = _label(value, name, max_digits)
    if not text.isascii() or not text.isdecimal():
        raise JundiaiGissIssueError(f"Invalid GissOnline numeric {name}")
    return text


def _tag(parent: etree._Element, name: str, value: str) -> etree._Element:
    node = etree.SubElement(parent, f"{{{_TYPES}}}{name}")
    node.text = value
    return node


def _part(parent: etree._Element, name: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{_TYPES}}}{name}")


def _tax_fields(fields: JundiaiGissTaxFields) -> None:
    if not isinstance(fields, JundiaiGissTaxFields):
        raise JundiaiGissIssueError("GissOnline reviewed municipal fields unavailable")
    _digits(fields.municipal_registration, "IM", 20)
    _label(fields.item_lista_servico, "LC116 service code", 5)
    _digits(fields.municipal_taxation_code, "municipal taxation", 20)
    if fields.rps_type not in ("1", "2", "3"):
        raise JundiaiGissIssueError("GissOnline RPS type invalid")
    if fields.iss_exigibility not in ("1", "2", "3", "4", "5", "6", "7"):
        raise JundiaiGissIssueError("GissOnline ISS exigibility invalid")
    if fields.issuer_special_regime not in ("1", "2", "3", "4", "5", "6"):
        raise JundiaiGissIssueError("GissOnline issuer special regime invalid")
    if fields.optante_simples not in ("1", "2") or fields.fiscal_incentive not in ("1", "2"):
        raise JundiaiGissIssueError("GissOnline issuer fiscal classification invalid")
    if len(_digits(fields.incidence_ibge, "ISS incidence IBGE", 7)) != 7:
        raise JundiaiGissIssueError("GissOnline ISS municipality required")
    _decimal(fields.iss_rate, "ISS rate", 4)
    for name in ("pis", "cofins", "inss", "income_tax", "csll", "other_retention"):
        _decimal(getattr(fields, name), name)
    receiver = fields.recipient
    if not isinstance(receiver, JundiaiGissRecipient):
        raise JundiaiGissIssueError("GissOnline service recipient missing")
    if (
        len(_digits(receiver.tax_id, "recipient taxpayer", 14)) not in (11, 14)
        or len(_digits(receiver.city_ibge, "recipient city", 7)) != 7
        or len(_digits(receiver.postal_code, "recipient CEP", 8)) != 8
        or len(_label(receiver.state, "recipient state", 2)) != 2
    ):
        raise JundiaiGissIssueError("GissOnline recipient address incomplete")
    for name, max_len in (
        ("name", 115), ("street", 125), ("street_number", 20), ("district", 60),
    ):
        _label(getattr(receiver, name), "recipient " + name, max_len)
    if receiver.phone is not None:
        _digits(receiver.phone, "recipient phone", 20)
    if receiver.email is not None:
        _label(receiver.email, "recipient email", 120)
    if receiver.municipal_registration is not None:
        _label(receiver.municipal_registration, "recipient IM", 20)
    if fields.national_service_code is not None and len(
        _digits(fields.national_service_code, "NBS", 9)
    ) != 9:
        raise JundiaiGissIssueError("GissOnline NBS must have nine digits")
    # For 2026 GissOnline allows the RTC identifiers to be unprovided. When
    # taxpayers supply them, require all correlated identifiers together.
    indicators = (
        fields.operation_indicator, fields.rtc_cst, fields.rtc_classification,
        fields.rtc_fin_nfse, fields.rtc_ind_dest,
        fields.rtc_incidence_ibge, fields.rtc_taxable_base, fields.rtc_ind_final,
    )
    if any(x is not None for x in indicators):
        if fields.national_service_code is None:
            raise JundiaiGissIssueError("GissOnline RTC requires NBS correlation")
        if any(x is None for x in indicators):
            raise JundiaiGissIssueError("Partial GissOnline 2026 RTC classification")
        assert fields.operation_indicator is not None
        assert fields.rtc_cst is not None
        assert fields.rtc_classification is not None
        assert fields.rtc_fin_nfse is not None
        assert fields.rtc_ind_dest is not None
        assert fields.rtc_incidence_ibge is not None
        assert fields.rtc_taxable_base is not None
        if fields.rtc_fin_nfse not in ("0", "1") or fields.rtc_ind_dest not in ("0", "1"):
            raise JundiaiGissIssueError("Invalid GissOnline 2026 RTC operation type")
        if fields.rtc_ind_final is not None and fields.rtc_ind_final not in ("0", "1"):
            raise JundiaiGissIssueError("Invalid GissOnline final-use flag")
        if len(_digits(fields.rtc_incidence_ibge, "IBS locality", 7)) != 7:
            raise JundiaiGissIssueError("GissOnline IBSCBS incidence locality missing")
        _decimal(fields.rtc_taxable_base, "IBS/CBS taxable base")
        _digits(fields.operation_indicator, "INDOP", 12)
        _digits(fields.rtc_cst, "IBS/CBS CST", 3)
        _digits(fields.rtc_classification, "IBS/CBS class", 6)
        if (
            len(fields.rtc_cst) != 3
            or len(fields.rtc_classification) != 6
            or not fields.rtc_classification.startswith(fields.rtc_cst)
        ):
            raise JundiaiGissIssueError("GissOnline tax classification mismatch")


def build_jundiai_giss_issue_xml(
    *, request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    fields: JundiaiGissTaxFields,
) -> bytes:
    """Build a one-RPS ABRASF 2.04 lot, preserving original immutable source."""
    if not isinstance(request, NfseAuthorizationRequest) or not isinstance(
        original, Sp4OriginalRps
    ):
        raise JundiaiGissIssueError("GissOnline canonical source required")
    doc = request.document
    if (
        original.issuer_ibge != "3525904"
        or original.scope.identity_partition_key != doc.scope.identity_partition_key
        or original.document_id != doc.document_id
        or original.request_fingerprint != request.request_fingerprint
        or original.issuer_cnpj != doc.issuer.cnpj
        or original.competence_date != doc.competence_date
        or original.gross_amount != doc.totals.gross_amount.amount
        or len(doc.services) != 1
        or doc.services[0].gross_amount.amount != original.gross_amount
        or original.municipal_batch_id is None
        or len(original.municipal_batch_id) > 15
        or not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or int(original.rps_number) < 1
    ):
        raise JundiaiGissIssueError("GissOnline source RPS and fiscal document differ")
    _tax_fields(fields)
    if (
        doc.service_jurisdiction.municipality_ibge_code is None
        or len(doc.service_jurisdiction.municipality_ibge_code) != 7
        or doc.service_jurisdiction.state_code != "SP"
    ):
        raise JundiaiGissIssueError("GissOnline municipality of service unavailable")
    root = etree.Element(f"{{{_ISSUE}}}EnviarLoteRpsEnvio",
                         nsmap={"env": _ISSUE, "tipos": _TYPES})
    lot = etree.SubElement(root, f"{{{_ISSUE}}}LoteRps", Id="LoteRps"+original.municipal_batch_id,
                           versao="2.04")
    _tag(lot, "NumeroLote", original.municipal_batch_id)
    issuer = _part(lot, "Prestador")
    idn = _part(issuer, "CpfCnpj")
    _tag(idn, "Cnpj", original.issuer_cnpj.value)
    _tag(issuer, "InscricaoMunicipal", fields.municipal_registration)
    _tag(lot, "QuantidadeRps", "1")
    listed = _part(lot, "ListaRps")
    rps = _part(listed, "Rps")
    service_info = _part(rps, "InfDeclaracaoPrestacaoServico")
    service_info.set("Id", "ID"+original.municipal_batch_id+"_"+original.rps_number)
    fiscal_rps = _part(service_info, "Rps")
    fiscal_rps.set("Id", "RPS"+original.rps_number)
    identification = _part(fiscal_rps, "IdentificacaoRps")
    _tag(identification, "Numero", original.rps_number)
    _tag(identification, "Serie", original.rps_series)
    _tag(identification, "Tipo", fields.rps_type)
    _tag(fiscal_rps, "DataEmissao", doc.issued_at.date().isoformat())
    _tag(fiscal_rps, "Status", "1")
    _tag(service_info, "Competencia", original.competence_date.isoformat())

    service = doc.services[0]
    srv = _part(service_info, "Servico")
    amounts = _part(srv, "Valores")
    for name, amount in (
        ("ValorServicos", service.gross_amount.amount),
        ("ValorDeducoes", service.deduction_amount.amount),
        ("ValorPis", fields.pis), ("ValorCofins", fields.cofins),
        ("ValorInss", fields.inss), ("ValorIr", fields.income_tax),
        ("ValorCsll", fields.csll), ("OutrasRetencoes", fields.other_retention),
        ("ValorIss", service.iss_amount.amount),
    ):
        _tag(amounts, name, _decimal(amount, name))
    _tag(amounts, "Aliquota", _decimal(fields.iss_rate, "ISS rate", 4))
    if fields.rtc_cst is not None:
        # Official manual v1.8 tcIBSCBS + the municipal 2.04 Valores group.
        # The shared tax engine must pass the reviewed amounts and location.
        assert fields.rtc_fin_nfse is not None
        assert fields.rtc_ind_dest is not None
        assert fields.operation_indicator is not None
        assert fields.rtc_classification is not None
        assert fields.rtc_incidence_ibge is not None
        assert fields.rtc_taxable_base is not None
        ibscbs = _part(amounts, "IBSCBS")
        _tag(ibscbs, "finNFSe", fields.rtc_fin_nfse)
        if fields.rtc_ind_final is not None:
            _tag(ibscbs, "indFinal", fields.rtc_ind_final)
        _tag(ibscbs, "cIndOp", fields.operation_indicator)
        _tag(ibscbs, "indDest", fields.rtc_ind_dest)
        rtc_values = _part(ibscbs, "valores")
        rtc_trib = _part(rtc_values, "trib")
        g = _part(rtc_trib, "gIBSCBS")
        _tag(g, "CST", fields.rtc_cst)
        _tag(g, "cClassTrib", fields.rtc_classification)
        _tag(rtc_values, "cLocalidadeIncid", fields.rtc_incidence_ibge)
        _tag(rtc_values, "vBC", _decimal(fields.rtc_taxable_base, "IBS/CBS taxable base"))
    _tag(srv, "IssRetido", "1" if service.iss_withheld else "2")
    _tag(srv, "ItemListaServico", fields.item_lista_servico)
    _tag(srv, "CodigoTributacaoMunicipio", fields.municipal_taxation_code)
    if fields.national_service_code is not None:
        _tag(srv, "CodigoNbs", fields.national_service_code)
    _tag(srv, "Discriminacao", _label(service.description, "description", 2000))
    _tag(srv, "CodigoMunicipio", doc.service_jurisdiction.municipality_ibge_code)
    _tag(srv, "ExigibilidadeISS", fields.iss_exigibility)
    _tag(srv, "MunicipioIncidencia", fields.incidence_ibge)

    issuer_rps = _part(service_info, "Prestador")
    issuer_id = _part(issuer_rps, "CpfCnpj")
    _tag(issuer_id, "Cnpj", original.issuer_cnpj.value)
    _tag(issuer_rps, "InscricaoMunicipal", fields.municipal_registration)
    taker = _part(service_info, "TomadorServico")
    taker_id = _part(taker, "IdentificacaoTomador")
    tax_id = _part(taker_id, "CpfCnpj")
    _tag(tax_id, "Cnpj" if len(fields.recipient.tax_id) == 14 else "Cpf",
         fields.recipient.tax_id)
    if fields.recipient.municipal_registration is not None:
        _tag(taker_id, "InscricaoMunicipal", fields.recipient.municipal_registration)
    _tag(taker, "RazaoSocial", fields.recipient.name)
    address = _part(taker, "Endereco")
    for name, value in (
        ("Endereco", fields.recipient.street),
        ("Numero", fields.recipient.street_number),
        ("Bairro", fields.recipient.district),
        ("CodigoMunicipio", fields.recipient.city_ibge),
        ("Uf", fields.recipient.state),
        ("Cep", fields.recipient.postal_code),
    ):
        _tag(address, name, value)
    if fields.recipient.phone is not None or fields.recipient.email is not None:
        contact = _part(taker, "Contato")
        if fields.recipient.phone is not None:
            _tag(contact, "Telefone", fields.recipient.phone)
        if fields.recipient.email is not None:
            _tag(contact, "Email", fields.recipient.email)
    _tag(service_info, "RegimeEspecialTributacao", fields.issuer_special_regime)
    _tag(service_info, "OptanteSimplesNacional", fields.optante_simples)
    _tag(service_info, "IncentivoFiscal", fields.fiscal_incentive)
    # GissOnline 2026 RTC optional values are deliberately left to official
    # XSD-aware tax-extension port: no invented tag placement for IBS/CBS.
    data = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    if len(data) > _LIMIT:
        raise JundiaiGissIssueError("GissOnline batch payload oversized")
    return data


_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"


def _source_preserving_tree(node: etree._Element) -> tuple[object, ...]:
    """Compare all original fields while allowing only XMLDSig additions.

    The signer is not entitled to modify issuer, recipient, RPS, ISS, RTC,
    service codes or amounts. Namespace prefixes and formatting whitespace
    are non-fiscal; element namespaces, values, order and attributes are.
    A separate signed XSD/XMLDSig verifier remains mandatory for authenticity.
    """
    if not isinstance(node.tag, str):
        raise JundiaiGissIssueError("Signed GissOnline issue contains foreign markup")
    if node.tag == f"{{{_XMLDSIG}}}Signature":
        return ()
    if node.tag.startswith(f"{{{_XMLDSIG}}}"):
        raise JundiaiGissIssueError("Unexpected detached XMLDSig element")
    text = node.text or ""
    tail = node.tail or ""
    return (
        node.tag, tuple(sorted(node.attrib.items())),
        text if text.strip() else "",
        tail if tail.strip() else "",
        tuple(
            _source_preserving_tree(child)
            for child in node
            if child.tag != f"{{{_XMLDSIG}}}Signature"
        ),
    )


def prepare_jundiai_giss_signed_issue(
    *, request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    fields: JundiaiGissTaxFields,
    sign_xml: Callable[[bytes], bytes],
    validate_signed_xml: Callable[[bytes], None],
) -> JundiaiSignedOperation:
    """Invoke reviewed two-node XMLDSig port and official pinned XSD validator."""
    if not callable(sign_xml) or not callable(validate_signed_xml):
        raise JundiaiGissIssueError("GissOnline XMLDSig and XSD ports required")
    source = build_jundiai_giss_issue_xml(
        request=request, original=original, fields=fields,
    )
    signed = sign_xml(source)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _LIMIT:
        raise JundiaiGissIssueError("GissOnline signed batch missing or oversized")
    try:
        root = etree.fromstring(
            signed, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise JundiaiGissIssueError("GissOnline signed issue XML malformed") from None
    if root.tag != f"{{{_ISSUE}}}EnviarLoteRpsEnvio" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise JundiaiGissIssueError("GissOnline signed issue root changed")
    for path, expected in (
        (f"{{{_ISSUE}}}LoteRps/{{{_TYPES}}}NumeroLote",
         original.municipal_batch_id),
        (f".//{{{_TYPES}}}IdentificacaoRps/{{{_TYPES}}}Numero",
         original.rps_number),
        (f".//{{{_TYPES}}}IdentificacaoRps/{{{_TYPES}}}Serie",
         original.rps_series),
        (f".//{{{_TYPES}}}Valores/{{{_TYPES}}}ValorServicos",
         _decimal(original.gross_amount, "original amount")),
    ):
        nodes = root.findall(path)
        if len(nodes) != 1 or nodes[0].text != expected:
            raise JundiaiGissIssueError(
                "Signed GissOnline issue does not match persisted original RPS"
            )
    # Verify the complete generated document after signing, not just four
    # identity fields. An XML signer must never rewrite RTC/ISS, recipient,
    # or service metadata while preserving original number and gross amount.
    unsigned_root = etree.fromstring(
        source,
        parser=etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            huge_tree=False,
        ),
    )
    if _source_preserving_tree(root) != _source_preserving_tree(unsigned_root):
        raise JundiaiGissIssueError(
            "Signed GissOnline issue does not match persisted original RPS"
        )
    validate_signed_xml(signed)
    return JundiaiSignedOperation(
        scope=original.scope, issuer_cnpj=original.issuer_cnpj,
        tax_regime=request.document.issuer.tax_regime,
        competence_date=original.competence_date,
        method="RecepcionarLoteRps", signed_xml=signed,
    )
