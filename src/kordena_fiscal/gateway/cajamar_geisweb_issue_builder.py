"""Cajamar GeisWeb20 10.2 EnviaLoteRps serialization from a durable RPS.

The municipality's legacy layout (section 13.1) provides the wire field names.
Live XSD/WSDL validation, XMLDSig and source-of-truth fiscal calculations are
independent injected ports; this module neither reserves numbers nor transmits.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.cajamar_geisweb_homologation import CajamarPreparedNfse
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

_NS = "http://www.geisweb.net.br/xsd/envio_lote_rps.xsd"
_LIMIT = 2_097_152


class CajamarGeiswebIssueError(FiscalValidationError):
    """Invalid municipal issue fields or mismatch with the durable source."""


@dataclass(frozen=True, slots=True)
class CajamarGeiswebIssueData:
    """Tax-engine-reviewed GeisWeb-only fields, never inferred from browser XML.

    The regime, tax rate and launch type have municipal legal significance and
    must be resolved by the existing fiscal policy before this serializer runs.
    """

    municipal_registration: str
    service_code: str
    launch_type: str
    issuer_regime: str
    iss_rate: Decimal
    service_city: str
    recipient_tax_id: str
    recipient_name: str
    recipient_street: str
    recipient_number: str
    recipient_neighborhood: str
    recipient_city: str
    recipient_state: str
    recipient_postal_code: str
    pis: Decimal | None = None
    cofins: Decimal | None = None
    csll: Decimal | None = None
    irrf: Decimal | None = None
    inss: Decimal | None = None


def _field(value: str, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value.strip()) <= limit
        or any(ord(char) < 32 for char in value)
    ):
        raise CajamarGeiswebIssueError(f"Invalid GeisWeb {name}")
    return value.strip()


def _money(value: Decimal, name: str) -> str:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value >= Decimal("1000000000000")
        or value * 100 != (value * 100).to_integral_value()
    ):
        raise CajamarGeiswebIssueError(f"Invalid GeisWeb {name}")
    return format(value, ".2f")


def _add(parent: etree._Element, name: str, value: str) -> None:
    etree.SubElement(parent, f"{{{_NS}}}{name}").text = value


def _node(parent: etree._Element, name: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{_NS}}}{name}")


def _validate_fields(fields: CajamarGeiswebIssueData) -> None:
    if not isinstance(fields, CajamarGeiswebIssueData):
        raise CajamarGeiswebIssueError("Missing municipal issue data")
    registration = _field(fields.municipal_registration, "registration", 16)
    if not registration.isascii() or not registration.isalnum():
        raise CajamarGeiswebIssueError("Invalid municipal registration")
    if (
        not fields.service_code.isascii()
        or not fields.service_code.isdecimal()
        or len(fields.service_code) not in (3, 4)
        or fields.launch_type not in ("N", "T", "P", "R")
        or fields.issuer_regime not in ("1", "2", "4", "6")
    ):
        raise CajamarGeiswebIssueError("Invalid reviewed GeisWeb tax classification")
    exponent = fields.iss_rate.as_tuple().exponent if isinstance(fields.iss_rate, Decimal) else None
    if exponent is not None and not isinstance(exponent, int):
        raise CajamarGeiswebIssueError("Invalid reviewed GeisWeb ISS precision")
    if (
        not isinstance(fields.iss_rate, Decimal)
        or not fields.iss_rate.is_finite()
        or fields.iss_rate < 0
        or fields.iss_rate > 100
        or (isinstance(exponent, int) and exponent < -5)
    ):
        raise CajamarGeiswebIssueError("Invalid reviewed GeisWeb ISS rate")
    _field(fields.service_city, "service city", 100)
    _field(fields.recipient_name, "recipient name", 100)
    for name, limit in (
        ("recipient_street", 60), ("recipient_number", 10),
        ("recipient_neighborhood", 50), ("recipient_city", 40),
        ("recipient_state", 2), ("recipient_postal_code", 11),
    ):
        _field(getattr(fields, name), name, limit)
    if (
        len(fields.recipient_tax_id) not in (11, 14)
        or not fields.recipient_tax_id.isascii()
        or not fields.recipient_tax_id.isdecimal()
        or len(fields.recipient_state) != 2
        or not fields.recipient_state.isascii()
        or not fields.recipient_state.isalpha()
        or not fields.recipient_state.isupper()
    ):
        raise CajamarGeiswebIssueError("Invalid GeisWeb recipient identification")
    for name in ("pis", "cofins", "csll", "irrf", "inss"):
        value = getattr(fields, name)
        if value is not None:
            _money(value, name)


def build_cajamar_issue_xml(
    *, request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    fields: CajamarGeiswebIssueData,
) -> bytes:
    """Serialize one NFS-e RPS against persisted lot/number and canonical amounts."""
    if not isinstance(request, NfseAuthorizationRequest) or not isinstance(
        original, Sp4OriginalRps
    ):
        raise CajamarGeiswebIssueError("Canonical Cajamar document required")
    doc = request.document
    if (
        original.issuer_ibge != "3509205"
        or doc.scope.identity_partition_key != original.scope.identity_partition_key
        or doc.document_id != original.document_id
        or request.request_fingerprint != original.request_fingerprint
        or doc.issuer.cnpj != original.issuer_cnpj
        or doc.competence_date != original.competence_date
        or doc.totals.gross_amount.amount != original.gross_amount
        or len(doc.services) != 1
        or original.municipal_batch_id is None
        or not 1 <= len(original.municipal_batch_id) <= 10
        or not original.rps_number.isascii()
        or not original.rps_number.isdecimal()
        or not 1 <= len(original.rps_number) <= 8
        or int(original.rps_number) < 1
    ):
        raise CajamarGeiswebIssueError("Cajamar emission differs from original RPS")
    _validate_fields(fields)
    service = doc.services[0]
    if service.gross_amount.amount != original.gross_amount:
        raise CajamarGeiswebIssueError("Cajamar service does not match source gross amount")
    gross = _money(original.gross_amount, "gross amount")
    base = _money(service.taxable_amount.amount, "ISS base")
    if service.taxable_amount.amount <= 0:
        raise CajamarGeiswebIssueError("Cajamar ISS base is missing")
    root = etree.Element(f"{{{_NS}}}EnviaLoteRps", nsmap={"geis": _NS})
    _add(root, "CnpjCpf", original.issuer_cnpj.value)
    _add(root, "NumeroLote", original.municipal_batch_id)
    rps = _node(root, "Rps")
    identification = _node(rps, "IdentificacaoRps")
    _add(identification, "NumeroRps", original.rps_number)
    _add(rps, "DataEmissao", doc.issued_at.strftime("%d/%m/%Y"))
    service_node = _node(rps, "Servico")
    values = _node(service_node, "Valores")
    _add(values, "ValorServicos", gross)
    _add(values, "BaseCalculo", base)
    _add(values, "Aliquota", str(fields.iss_rate))
    _add(service_node, "CodigoServico", fields.service_code)
    _add(service_node, "TipoLancamento", fields.launch_type)
    _add(service_node, "Discriminacao", _field(service.description, "description", 1500))
    _add(service_node, "MunicipioPrestacaoServico", fields.service_city)
    issuer = _node(service_node, "PrestadorServico")
    issuer_id = _node(issuer, "IdentificacaoPrestador")
    _add(issuer_id, "CnpjCpf", original.issuer_cnpj.value)
    _add(issuer_id, "InscricaoMunicipal", fields.municipal_registration)
    _add(issuer_id, "Regime", fields.issuer_regime)
    taker = _node(service_node, "TomadorServico")
    taker_id = _node(taker, "IdentificacaoTomador")
    _add(taker_id, "CnpjCpf", fields.recipient_tax_id)
    _add(taker_id, "RazaoSocial", fields.recipient_name)
    address = _node(taker, "Endereco")
    for element, value in (
        ("Rua", fields.recipient_street),
        ("Numero", fields.recipient_number),
        ("Bairro", fields.recipient_neighborhood),
        ("Cidade", fields.recipient_city),
        ("Estado", fields.recipient_state),
        ("Cep", fields.recipient_postal_code),
    ):
        _add(address, element, value)
    agency = _node(service_node, "OrgaoGerador")
    _add(agency, "CodigoMunicipio", "3509205")
    _add(agency, "Uf", "SP")
    taxes = (
        ("Pis", fields.pis), ("Cofins", fields.cofins),
        ("Csll", fields.csll), ("Irrf", fields.irrf), ("Inss", fields.inss),
    )
    if any(amount is not None for _, amount in taxes):
        other = _node(service_node, "OutrosImpostos")
        for name, amount in taxes:
            if amount is not None:
                _add(other, name, _money(amount, name))
    xml = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    if len(xml) > _LIMIT:
        raise CajamarGeiswebIssueError("Cajamar issue XML exceeds maximum size")
    return xml


def prepare_cajamar_signed_issue(
    *, request: NfseAuthorizationRequest, original: Sp4OriginalRps,
    fields: CajamarGeiswebIssueData,
    sign_document: Callable[[bytes], bytes],
    validate_signed_request: Callable[[bytes], None],
) -> CajamarPreparedNfse:
    """Bind issuer/RPS/amount after signing and delegate XSD to the pin validator."""
    if not callable(sign_document) or not callable(validate_signed_request):
        raise CajamarGeiswebIssueError("Cajamar signer and official schema unavailable")
    unsigned = build_cajamar_issue_xml(
        request=request, original=original, fields=fields,
    )
    signed = sign_document(unsigned)
    if not isinstance(signed, bytes) or not 0 < len(signed) <= _LIMIT:
        raise CajamarGeiswebIssueError("Cajamar signed issue XML missing or oversized")
    try:
        root = etree.fromstring(
            signed, parser=etree.XMLParser(
                no_network=True, load_dtd=False,
                resolve_entities=False, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise CajamarGeiswebIssueError("Cajamar signed issue XML malformed") from None
    if root.tag != f"{{{_NS}}}EnviaLoteRps" or bool(
        getattr(root.getroottree().docinfo, "doctype", "")
    ):
        raise CajamarGeiswebIssueError("Cajamar signed issue XML root changed")
    for path, expected in (
        ("CnpjCpf", original.issuer_cnpj.value),
        ("NumeroLote", original.municipal_batch_id),
        ("Rps/IdentificacaoRps/NumeroRps", original.rps_number),
        ("Rps/Servico/Valores/ValorServicos", _money(original.gross_amount, "gross")),
        ("Rps/Servico/PrestadorServico/IdentificacaoPrestador/CnpjCpf",
         original.issuer_cnpj.value),
        ("Rps/Servico/TomadorServico/IdentificacaoTomador/CnpjCpf",
         fields.recipient_tax_id),
    ):
        namespaced = "/".join(f"{{{_NS}}}{part}" for part in path.split("/"))
        matches = root.findall(namespaced)
        if len(matches) != 1 or matches[0].text != expected:
            raise CajamarGeiswebIssueError(
                "Signed Cajamar issue no longer matches original fiscal document"
            )
    # A signature provider must not be allowed to alter service taxation,
    # recipient details or ISS classification while preserving only the RPS
    # number and gross amount. Reconcile every fiscal wire field BEFORE the
    # pinned XSD/XMLDSig port receives the signed document.
    doc = request.document
    fiscal_fields = (
        ("Rps/DataEmissao", doc.issued_at.strftime("%d/%m/%Y")),
        ("Rps/Servico/Valores/BaseCalculo", _money(
            doc.services[0].taxable_amount.amount, "ISS base",
        )),
        ("Rps/Servico/Valores/Aliquota", str(fields.iss_rate)),
        ("Rps/Servico/CodigoServico", fields.service_code),
        ("Rps/Servico/TipoLancamento", fields.launch_type),
        ("Rps/Servico/Discriminacao", _field(
            doc.services[0].description, "description", 1500,
        )),
        ("Rps/Servico/MunicipioPrestacaoServico", fields.service_city),
        ("Rps/Servico/PrestadorServico/IdentificacaoPrestador/InscricaoMunicipal",
         fields.municipal_registration),
        ("Rps/Servico/PrestadorServico/IdentificacaoPrestador/Regime",
         fields.issuer_regime),
        ("Rps/Servico/TomadorServico/IdentificacaoTomador/RazaoSocial",
         fields.recipient_name),
        ("Rps/Servico/TomadorServico/Endereco/Rua", fields.recipient_street),
        ("Rps/Servico/TomadorServico/Endereco/Numero", fields.recipient_number),
        ("Rps/Servico/TomadorServico/Endereco/Bairro",
         fields.recipient_neighborhood),
        ("Rps/Servico/TomadorServico/Endereco/Cidade", fields.recipient_city),
        ("Rps/Servico/TomadorServico/Endereco/Estado", fields.recipient_state),
        ("Rps/Servico/TomadorServico/Endereco/Cep",
         fields.recipient_postal_code),
        ("Rps/Servico/OrgaoGerador/CodigoMunicipio", "3509205"),
        ("Rps/Servico/OrgaoGerador/Uf", "SP"),
    )
    for path, expected in fiscal_fields:
        path_ns = "/".join(f"{{{_NS}}}{part}" for part in path.split("/"))
        elements = root.findall(path_ns)
        if len(elements) != 1 or elements[0].text != expected:
            raise CajamarGeiswebIssueError(
                "Signed Cajamar issue no longer matches original fiscal document"
            )
    taxes = (
        ("Pis", fields.pis), ("Cofins", fields.cofins),
        ("Csll", fields.csll), ("Irrf", fields.irrf), ("Inss", fields.inss),
    )
    other_ns = "/".join(
        f"{{{_NS}}}{part}" for part in ("Rps", "Servico", "OutrosImpostos")
    )
    tax_nodes = root.findall(other_ns)
    if len(tax_nodes) != (1 if any(v is not None for _, v in taxes) else 0):
        raise CajamarGeiswebIssueError(
            "Signed Cajamar issue no longer matches original fiscal document"
        )
    if tax_nodes:
        expected_taxes = {
            f"{{{_NS}}}{name}": _money(amount, name)
            for name, amount in taxes if amount is not None
        }
        received_taxes = {
            node.tag: node.text for node in tax_nodes[0]
        }
        if received_taxes != expected_taxes or len(tax_nodes[0]) != len(expected_taxes):
            raise CajamarGeiswebIssueError(
                "Signed Cajamar issue no longer matches original fiscal document"
            )
    validate_signed_request(signed)
    return CajamarPreparedNfse(
        scope=original.scope,
        issuer_cnpj=original.issuer_cnpj,
        tax_regime=request.document.issuer.tax_regime,
        competence_date=original.competence_date,
        method="EnviaLoteRps",
        signed_request_xml=signed,
    )
