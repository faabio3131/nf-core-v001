"""Model-55/65 XML from canonical reviewed facts and canonical calculated taxes.

This builder does not select tax rates, reserve numbers, sign or transmit. It
rejects unsupported fiscal families rather than silently omitting their groups.
"""

from dataclasses import dataclass
from decimal import Decimal

from lxml import etree

from kordena_fiscal.documents import CanonicalFiscalDocument, PaymentMethodKind
from kordena_fiscal.domain import Cnpj, FiscalAddress, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.tax.nfe_calculation import NfeCalculatedTaxes, calculate_nfe_line
from kordena_fiscal.tax.rtc_group_indicators import (
    require_representable_classification,
    rtc_cst_requires_gibscbs,
)
from kordena_fiscal.xml import NfeAccessKey

NS = "http://www.portalfiscal.inf.br/nfe"


@dataclass(frozen=True, slots=True)
class NfeSaleOptions:
    nature: str
    presence: int
    freight_mode: int
    intermediary_indicator: int | None = None
    intermediary_cnpj: str | None = None
    intermediary_registration: str | None = None
    card_integration_type: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.nature, str) or not 1 <= len(self.nature.strip()) <= 60:
            raise FiscalValidationError("operation nature is required")
        if type(self.presence) is not int or self.presence not in {0, 1, 2, 3, 4, 5, 9}:
            raise FiscalValidationError("presence indicator is required")
        if type(self.freight_mode) is not int or self.freight_mode not in {0, 1, 2, 3, 4, 9}:
            raise FiscalValidationError("freight modality is required")
        if self.intermediary_indicator is not None and (
            type(self.intermediary_indicator) is not int
            or self.intermediary_indicator not in {0, 1}
        ):
            raise FiscalValidationError("intermediary indicator must be explicit: 0 or 1")
        if self.presence in {2, 3, 4, 9} and self.intermediary_indicator is None:
            raise FiscalValidationError("remote sale requires an intermediary indicator")
        if self.intermediary_indicator == 1:
            if self.intermediary_cnpj is None or not self.intermediary_registration:
                raise FiscalValidationError(
                    "intermediary identity and merchant registration required"
                )
            Cnpj(self.intermediary_cnpj)
            if not 2 <= len(self.intermediary_registration) <= 60:
                raise FiscalValidationError("intermediary merchant registration has invalid length")
        elif self.intermediary_cnpj is not None or self.intermediary_registration is not None:
            raise FiscalValidationError("intermediary facts conflict with absence of intermediary")
        if self.card_integration_type is not None and (
            type(self.card_integration_type) is not int or self.card_integration_type not in {1, 2}
        ):
            raise FiscalValidationError("invalid card integration type")


def _element(parent: etree._Element, name: str, value: object = None) -> etree._Element:
    result = etree.SubElement(parent, "{" + NS + "}" + name)
    if value is not None:
        result.text = str(value)
    return result


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _address(parent: etree._Element, name: str, address: FiscalAddress) -> None:
    if not address.jurisdiction.municipality_ibge_code:
        raise FiscalValidationError("municipality IBGE code is required")
    target = _element(parent, name)
    for key, value in (
        ("xLgr", address.street),
        ("nro", address.number),
        ("xCpl", address.complement),
        ("xBairro", address.district),
        ("cMun", address.jurisdiction.municipality_ibge_code),
        ("xMun", address.municipality_name),
        ("UF", address.jurisdiction.state_code),
        ("CEP", address.postal_code),
    ):
        if value is not None:
            _element(target, key, value)
    _element(target, "cPais", "1058")
    _element(target, "xPais", "BRASIL")


def build_nfe_sale(
    document: CanonicalFiscalDocument,
    access_key: NfeAccessKey,
    options: NfeSaleOptions,
) -> bytes:
    issuer, recipient = document.issuer, document.recipient
    nfce = document.document_kind.value == "nfce"
    model = "65" if nfce else "55"
    if document.document_kind.value not in {"nfe", "nfce"} or access_key.value[20:22] != model:
        raise FiscalValidationError("sale builder requires matching NF-e/NFC-e model")
    if nfce and (
        issuer.address.jurisdiction.state_code not in {"MG", "SP"}
        or options.presence not in {1, 4}
        or (
            recipient is not None
            and (
                not recipient.final_consumer
                or recipient.ie_indicator != 9
                or recipient.address.jurisdiction.state_code
                != issuer.address.jurisdiction.state_code
            )
        )
        or (options.presence == 4 and recipient is None)
    ):
        raise FiscalValidationError(
            "NFC-e requires same-UF final consumer and reviewed online sale"
        )
    if document.scope.environment is not FiscalEnvironment.HOMOLOGATION:
        raise FiscalValidationError("production fiscal preparation is not activated")
    if (recipient is None and not nfce) or (
        recipient is not None and recipient.address.jurisdiction.country_code != "BR"
    ):
        raise FiscalValidationError("complete Brazilian recipient snapshot is required")
    if access_key.issuer_identifier != issuer.cnpj.value or access_key.value[34] != "1":
        raise FiscalValidationError("access key differs from issuer or normal emission")
    municipality = issuer.address.jurisdiction.municipality_ibge_code
    if not municipality or access_key.value[:2] != municipality[:2]:
        raise FiscalValidationError("access key differs from issuer jurisdiction")
    if access_key.value[2:6] != document.issued_at.strftime("%y%m"):
        raise FiscalValidationError("access key differs from document month")
    if document.change_amount.amount and not nfce:
        raise FiscalValidationError("sale builder requires payments reconciled without change")
    if document.issued_at.year != 2026 and any(
        line.tax_decision.outcome.ibs_cbs_cst_code is not None for line in document.items
    ):
        raise FiscalValidationError("RTC informational-2026 rule cannot be used outside 2026")
    interstate_final_consumer = (
        recipient is not None
        and issuer.address.jurisdiction.state_code != recipient.address.jurisdiction.state_code
        and recipient.final_consumer
        and recipient.ie_indicator == 9
    )
    taxes = [
        calculate_nfe_line(
            line.tax_decision,
            net_amount=line.net_amount.amount,
            regime=issuer.tax_regime,
            interstate_final_consumer=interstate_final_consumer,
            taxable_quantity=line.taxable_quantity or line.quantity,
        )
        for line in document.items
    ]
    invoice_total = document.totals.net_amount.amount + sum(
        (
            tax.ipi_amount + tax.st_amount + tax.fcp_st_amount - tax.icms_deson_deduction
            for tax in taxes
        ), Decimal(0)
    )
    if (
        not document.payments
        or document.totals.payment_amount.amount - document.change_amount.amount != invoice_total
    ):
        raise FiscalValidationError("explicit reconciled payment snapshots are required")
    cash = sum(
        (p.amount.amount for p in document.payments if p.method is PaymentMethodKind.CASH),
        Decimal(0),
    )
    if document.change_amount.amount > cash:
        raise FiscalValidationError("change must be covered by cash payments")
    root = etree.Element("{" + NS + "}enviNFe", nsmap={"nfe": NS}, versao="4.00")
    _element(root, "idLote", str(int(access_key.value[25:34])))
    _element(root, "indSinc", "1")
    invoice = _element(root, "NFe")
    info = _element(invoice, "infNFe")
    info.set("Id", "NFe" + access_key.value)
    info.set("versao", "4.00")
    ide = _element(info, "ide")
    destination = (
        "1"
        if recipient is None
        or issuer.address.jurisdiction.state_code == recipient.address.jurisdiction.state_code
        else "2"
    )
    if (
        destination == "2"
        and recipient is not None
        and recipient.final_consumer
        and not interstate_final_consumer
    ):
        raise FiscalValidationError("interstate final consumer requires reviewed IE indicator")
    if destination == "2" and any(
        line.tax_decision.outcome.nfe_rates is not None
        and line.tax_decision.outcome.nfe_rates.fcp_rate is not None
        for line in document.items
    ):
        raise FiscalValidationError("interstate FCP requires destination-specific calculation")
    for key, value in (
        ("cUF", access_key.value[:2]),
        ("cNF", access_key.value[35:43]),
        ("natOp", options.nature.strip()),
        ("mod", model),
        ("serie", str(int(access_key.value[22:25]))),
        ("nNF", str(int(access_key.value[25:34]))),
        ("dhEmi", document.issued_at.isoformat(timespec="seconds")),
        ("tpNF", "1"),
        ("idDest", destination),
        ("cMunFG", municipality),
        ("tpImp", "4" if nfce else "1"),
        ("tpEmis", "1"),
        ("cDV", access_key.value[-1]),
        ("tpAmb", "2"),
        ("finNFe", "1"),
        ("indFinal", "1" if nfce or (recipient is not None and recipient.final_consumer) else "0"),
        ("indPres", options.presence),
        ("procEmi", "0"),
        ("verProc", "NFCore-1"),
    ):
        if key == "procEmi" and options.intermediary_indicator is not None:
            _element(ide, "indIntermed", options.intermediary_indicator)
        _element(ide, key, value)
    emit = _element(info, "emit")
    _element(emit, "CNPJ", issuer.cnpj.value)
    _element(emit, "xNome", issuer.legal_name)
    _address(emit, "enderEmit", issuer.address)
    if issuer.state_registration.exempt or not issuer.state_registration.number:
        raise FiscalValidationError("model-55 issuer requires explicit state registration")
    _element(emit, "IE", issuer.state_registration.number)
    _element(emit, "CRT", int(issuer.tax_regime))
    if recipient is not None:
        dest = _element(info, "dest")
        _element(
            dest,
            "CNPJ" if isinstance(recipient.document, Cnpj) else "CPF",
            recipient.document.value,
        )
        _element(dest, "xNome", "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL")
        _address(dest, "enderDest", recipient.address)
        _element(dest, "indIEDest", recipient.ie_indicator)
        if recipient.state_registration is not None and recipient.state_registration.number:
            _element(dest, "IE", recipient.state_registration.number)
    for line, tax in zip(document.items, taxes, strict=True):
        product = line.product
        rates = line.tax_decision.outcome.nfe_rates
        benefit = rates.icms_benefit if rates is not None else None
        if benefit is not None and (
            nfce or not benefit.code.startswith(issuer.address.jurisdiction.state_code)
        ):
            raise FiscalValidationError("ICMS benefit differs from reviewed model or UF")
        if (
            (
                product.hints.fiscal_benefit_code is not None
                and (benefit is None or product.hints.fiscal_benefit_code != benefit.code)
            )
            or product.hints.ibs_cbs_classification_code is not None
            or line.restaurant_decision is not None
        ):
            raise FiscalValidationError(
                "special fiscal metadata requires its authoritative builder"
            )
        if any(
            value.amount != value.amount.quantize(Decimal("0.01"))
            for value in (
                line.gross_amount,
                line.discount_amount,
                line.surcharge_amount,
                line.freight_amount,
            )
        ) or line.gross_amount.amount != (line.quantity * line.unit_price.amount).quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        ):
            raise FiscalValidationError("line monetary snapshots do not reconcile")
        if line.quantity != line.quantity.quantize(Decimal("0.0001")) or (
            line.unit_price.amount != line.unit_price.amount.quantize(Decimal("0.0000000001"))
        ):
            raise FiscalValidationError("line precision exceeds supported XML precision")
        if product.gtin is None:
            raise FiscalValidationError("GTIN must be explicit")
        taxable_quantity = line.taxable_quantity
        taxable_price = line.taxable_unit_price
        if taxable_quantity is None or taxable_price is None:
            if product.commercial_unit != product.taxable_unit:
                raise FiscalValidationError("taxable unit conversion must be explicit")
            taxable_quantity, taxable_price = line.quantity, line.unit_price.amount
        if (
            taxable_quantity != taxable_quantity.quantize(Decimal("0.0001"))
            or taxable_price != taxable_price.quantize(Decimal("0.0000000001"))
            or (taxable_quantity * taxable_price).quantize(
                Decimal("0.01"), rounding="ROUND_HALF_UP"
            )
            != line.gross_amount.amount
        ):
            raise FiscalValidationError("taxable unit conversion does not reconcile")
        if line.tax_decision.outcome.cfop[0] != ("5" if destination == "1" else "6"):
            raise FiscalValidationError("CFOP differs from destination jurisdiction")
        det = _element(info, "det")
        det.set("nItem", str(line.line_number))
        prod = _element(det, "prod")
        for key, value in (
            ("cProd", product.commercial_code),
            ("cEAN", product.gtin.value),
            (
                "xProd",
                "NOTA FISCAL EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
                if nfce and line.line_number == 1
                else product.description,
            ),
            ("NCM", product.ncm.value),
        ):
            _element(prod, key, value)
        if product.cest is not None:
            _element(prod, "CEST", product.cest.value)
        if benefit is not None:
            _element(prod, "cBenef", benefit.code)
        for key, value in (
            ("CFOP", line.tax_decision.outcome.cfop),
            ("uCom", product.commercial_unit.value),
            ("qCom", format(line.quantity, ".4f")),
            ("vUnCom", format(line.unit_price.amount, ".10f")),
            ("vProd", _money(line.gross_amount.amount)),
            ("cEANTrib", product.gtin.value),
            ("uTrib", product.taxable_unit.value),
            ("qTrib", format(taxable_quantity, ".4f")),
            ("vUnTrib", format(taxable_price, ".10f")),
            ("vFrete", _money(line.freight_amount.amount)),
            ("vDesc", _money(line.discount_amount.amount)),
            ("vOutro", _money(line.surcharge_amount.amount - line.freight_amount.amount)),
            ("indTot", "1"),
        ):
            if key not in {"vFrete", "vDesc", "vOutro"} or value != "0.00":
                _element(prod, key, value)
        _taxes(_element(det, "imposto"), line.tax_decision.outcome, int(product.origin), tax)
    total_node = _element(info, "total")
    totals = _element(total_node, "ICMSTot")
    freight = sum((line.freight_amount.amount for line in document.items), Decimal(0))
    values = {
        "vBC": sum((t.icms_base for t in taxes), Decimal(0)),
        "vICMS": sum((t.icms_amount for t in taxes), Decimal(0)),
        "vICMSDeson": sum((t.icms_deson_amount for t in taxes), Decimal(0)),
        "vFCP": sum((t.fcp_amount for t in taxes), Decimal(0)),
        "vFCPUFDest": sum((t.fcp_destination_amount for t in taxes), Decimal(0)),
        "vICMSUFDest": sum((t.difal_amount for t in taxes), Decimal(0)),
        "vBCST": sum((t.st_base for t in taxes), Decimal(0)),
        "vST": sum((t.st_amount for t in taxes), Decimal(0)),
        "vFCPST": sum((t.fcp_st_amount for t in taxes), Decimal(0)),
        "vIPI": sum((t.ipi_amount for t in taxes), Decimal(0)),
        "vProd": document.totals.gross_amount.amount,
        "vFrete": freight,
        "vDesc": document.totals.discount_amount.amount,
        "vPIS": sum((t.pis_amount for t in taxes), Decimal(0)),
        "vCOFINS": sum((t.cofins_amount for t in taxes), Decimal(0)),
        "vOutro": document.totals.surcharge_amount.amount - freight,
        "vNF": invoice_total,
    }
    for key in (
        "vBC",
        "vICMS",
        "vICMSDeson",
        "vFCPUFDest",
        "vICMSUFDest",
        "vICMSUFRemet",
        "vFCP",
        "vBCST",
        "vST",
        "vFCPST",
        "vFCPSTRet",
        "vProd",
        "vFrete",
        "vSeg",
        "vDesc",
        "vII",
        "vIPI",
        "vIPIDevol",
        "vPIS",
        "vCOFINS",
        "vOutro",
        "vNF",
    ):
        _element(totals, key, _money(values.get(key, Decimal(0))))
    classified = [line.tax_decision.outcome.ibs_cbs_cst_code is not None for line in document.items]
    if any(classified):
        if not all(classified):
            raise FiscalValidationError("RTC requires coherent classification on all lines")
        rtc_total = _element(total_node, "IBSCBSTot")
        _element(rtc_total, "vBCIBSCBS", _money(sum((t.rtc_base for t in taxes), Decimal(0))))
        ibs_total = _element(rtc_total, "gIBS")
        for name, field in (
            ("gIBSUF", "rtc_ibs_uf_amount"),
            ("gIBSMun", "rtc_ibs_municipal_amount"),
        ):
            group_total = _element(ibs_total, name)
            _element(group_total, "vDif", "0.00")
            _element(group_total, "vDevTrib", "0.00")
            _element(
                group_total,
                "vIBSUF" if name == "gIBSUF" else "vIBSMun",
                _money(sum((getattr(t, field) for t in taxes), Decimal(0))),
            )
        _element(
            ibs_total,
            "vIBS",
            _money(
                sum((t.rtc_ibs_uf_amount + t.rtc_ibs_municipal_amount for t in taxes), Decimal(0))
            ),
        )
        _element(ibs_total, "vCredPres", "0.00")
        _element(ibs_total, "vCredPresCondSus", "0.00")
        cbs_total = _element(rtc_total, "gCBS")
        _element(cbs_total, "vDif", "0.00")
        _element(cbs_total, "vDevTrib", "0.00")
        _element(cbs_total, "vCBS", _money(sum((t.rtc_cbs_amount for t in taxes), Decimal(0))))
        _element(cbs_total, "vCredPres", "0.00")
        _element(cbs_total, "vCredPresCondSus", "0.00")
        _element(
            total_node,
            "vNFTot",
            _money(
                invoice_total
                + sum(
                    (
                        t.rtc_ibs_uf_amount + t.rtc_ibs_municipal_amount + t.rtc_cbs_amount
                        for t in taxes
                    ),
                    Decimal(0),
                )
            ),
        )
    if options.freight_mode == 9 and freight:
        raise FiscalValidationError("freight amount conflicts with no-transport modality")
    _element(_element(info, "transp"), "modFrete", options.freight_mode)
    pag = _element(info, "pag")
    methods = {
        PaymentMethodKind.CASH: "01",
        PaymentMethodKind.PIX: "17",
        PaymentMethodKind.BOLETO: "15",
        PaymentMethodKind.VOUCHER: "10",
        PaymentMethodKind.CREDIT_CARD: "03",
        PaymentMethodKind.DEBIT_CARD: "04",
    }
    for payment in document.payments:
        if payment.method not in methods:
            raise FiscalValidationError("payment requires its own reviewed integration metadata")
        det_pag = _element(pag, "detPag")
        _element(det_pag, "tPag", methods[payment.method])
        _element(det_pag, "vPag", _money(payment.amount.amount))
        if payment.amount.amount != payment.amount.amount.quantize(Decimal("0.01")):
            raise FiscalValidationError("payment precision exceeds cents")
        if payment.method in {PaymentMethodKind.CREDIT_CARD, PaymentMethodKind.DEBIT_CARD}:
            if options.card_integration_type not in {1, 2}:
                raise FiscalValidationError("card payment requires reviewed integration facts")
            card = _element(det_pag, "card")
            _element(card, "tpIntegra", options.card_integration_type)
            if options.card_integration_type == 1:
                if not all(
                    (payment.card_acquirer_cnpj, payment.card_brand, payment.card_authorization)
                ):
                    raise FiscalValidationError("integrated card requires per-transaction facts")
                _element(card, "CNPJ", payment.card_acquirer_cnpj)
                _element(card, "tBand", payment.card_brand)
                _element(card, "cAut", payment.card_authorization)
            elif payment.card_acquirer_cnpj is not None:
                raise FiscalValidationError("card facts conflict with non-integrated payment")
    if document.change_amount.amount:
        _element(pag, "vTroco", _money(document.change_amount.amount))
    if options.intermediary_indicator == 1:
        intermediary = _element(info, "infIntermed")
        _element(intermediary, "CNPJ", Cnpj(str(options.intermediary_cnpj)).value)
        _element(intermediary, "idCadIntTran", options.intermediary_registration)
    if nfce:
        supplement = _element(invoice, "infNFeSupl")
        # NFC-e QR v3 ONLINE, NT 2025.001: chave|3|tpAmb (CSC-free).
        # Keep URL authority per UF; offline contingency needs signed QR,
        # and is not synthesized by this preparation path.
        base_qr, consultation = {
            "MG": (
                "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml?p=",
                "https://hportalsped.fazenda.mg.gov.br/portalnfce",
            ),
            "SP": (
                "https://www.homologacao.nfce.fazenda.sp.gov.br/qrcode?p=",
                "https://www.homologacao.nfce.fazenda.sp.gov.br/consulta",
            ),
        }[issuer.address.jurisdiction.state_code]
        _element(supplement, "qrCode", base_qr + access_key.value + "|3|2")
        _element(supplement, "urlChave", consultation)
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def _taxes(parent: etree._Element, outcome: object, origin: int, tax: NfeCalculatedTaxes) -> None:
    from kordena_fiscal.tax import TaxRuleOutcome

    assert isinstance(outcome, TaxRuleOutcome) and outcome.nfe_rates is not None
    rates = outcome.nfe_rates
    code = outcome.icms_code
    group = (
        "ICMS" + code
        if code in {"00", "10", "20", "30", "51", "70"}
        else "ICMSSN102"
        if len(code) == 3
        else "ICMS40"
    )
    icms = _element(_element(parent, "ICMS"), group)
    _element(icms, "orig", origin)
    _element(icms, "CSOSN" if len(code) == 3 else "CST", code)
    if code in {"00", "10", "20", "70"}:
        for key, value in (
            ("modBC", "3"),
            *(
                (("pRedBC", format(rates.icms_reduction_rate, ".4f")),)
                if rates.icms_reduction_rate is not None
                else ()
            ),
            ("vBC", _money(tax.icms_base)),
            ("pICMS", format(rates.icms_rate, ".4f")),
            ("vICMS", _money(tax.icms_amount)),
        ):
            _element(icms, key, value)
        if rates.fcp_rate is not None:
            if code in {"10", "20", "70"}:
                _element(icms, "vBCFCP", _money(tax.icms_base))
            _element(icms, "pFCP", format(rates.fcp_rate, ".4f"))
            _element(icms, "vFCP", _money(tax.fcp_amount))
    benefit = rates.icms_benefit
    if code == "51":
        assert benefit is not None and benefit.deferral_rate is not None
        for key, value in (
            ("modBC", "3"),
            ("vBC", _money(tax.icms_base)),
            ("pICMS", format(rates.icms_rate, ".4f")),
            ("vICMSOp", _money(tax.icms_operation_amount)),
            ("pDif", format(benefit.deferral_rate, ".4f")),
            ("vICMSDif", _money(tax.icms_deferred_amount)),
            ("vICMS", _money(tax.icms_amount)),
        ):
            _element(icms, key, value)
    if benefit is not None and benefit.deson_reason is not None:
        _element(icms, "vICMSDeson", _money(tax.icms_deson_amount))
        _element(icms, "motDesICMS", benefit.deson_reason)
        _element(icms, "indDeduzDeson", "1" if benefit.deduct_deson else "0")
    if code in {"10", "30", "70"}:
        assert rates.st_mva_rate is not None and rates.st_rate is not None
        for key, value in (
            ("modBCST", "4"),
            ("pMVAST", format(rates.st_mva_rate, ".4f")),
            ("vBCST", _money(tax.st_base)),
            ("pICMSST", format(rates.st_rate, ".4f")),
            ("vICMSST", _money(tax.st_amount)),
        ):
            _element(icms, key, value)
        if rates.fcp_st_rate is not None:
            _element(icms, "vBCFCPST", _money(tax.st_base))
            _element(icms, "pFCPST", format(rates.fcp_st_rate, ".4f"))
            _element(icms, "vFCPST", _money(tax.fcp_st_amount))
    if rates.ipi_enquiry_code is not None:
        ipi = _element(parent, "IPI")
        _element(ipi, "cEnq", rates.ipi_enquiry_code)
        taxable = rates.ipi_rate is not None or rates.ipi_unit_amount is not None
        group_ipi = _element(ipi, "IPITrib" if taxable else "IPINT")
        _element(group_ipi, "CST", (rates.ipi_cst or "50") if taxable else rates.ipi_cst)
        if rates.ipi_rate is not None:
            _element(group_ipi, "vBC", _money(tax.ipi_base))
            _element(group_ipi, "pIPI", format(rates.ipi_rate, ".4f"))
        elif rates.ipi_unit_amount is not None:
            _element(group_ipi, "qUnid", format(tax.ipi_taxable_quantity, ".4f"))
            _element(group_ipi, "vUnid", format(rates.ipi_unit_amount, ".4f"))
        if taxable:
            _element(group_ipi, "vIPI", _money(tax.ipi_amount))
    for name, code, rate, base, amount in (
        ("PIS", outcome.pis_cst, rates.pis_rate, tax.pis_base, tax.pis_amount),
        ("COFINS", outcome.cofins_cst, rates.cofins_rate, tax.cofins_base, tax.cofins_amount),
    ):
        other_mode = rates.pis_other_mode if name == "PIS" else rates.cofins_other_mode
        other = code in {"49", "99"}
        taxed = code in {"01", "02"} or (other and other_mode == "percentage")
        per_unit = code == "03" or (other and other_mode == "per_unit")
        group_el = _element(
            _element(parent, name),
            name + ("Outr" if other else "Aliq" if taxed else "Qtde" if per_unit else "NT"),
        )
        _element(group_el, "CST", code)
        if taxed:
            _element(group_el, "vBC", _money(base))
            _element(group_el, "p" + name, format(rate, ".4f"))
            _element(group_el, "v" + name, _money(amount))
        elif per_unit or other:
            unit_amount = rates.pis_unit_amount if name == "PIS" else rates.cofins_unit_amount
            quantity = tax.contribution_taxable_quantity if per_unit else Decimal("0.0000")
            amount_per_unit = unit_amount if per_unit else Decimal("0.0000")
            assert amount_per_unit is not None
            _element(group_el, "qBCProd", format(quantity, ".4f"))
            _element(group_el, "vAliqProd", format(amount_per_unit, ".4f"))
            _element(group_el, "v" + name, _money(amount))
    if rates.difal_destination_rate is not None:
        assert rates.difal_interstate_rate is not None
        assert rates.difal_destination_share is not None
        uf = _element(parent, "ICMSUFDest")
        _element(uf, "vBCUFDest", _money(tax.difal_base))
        if rates.fcp_destination_rate is not None:
            _element(uf, "vBCFCPUFDest", _money(tax.difal_base))
            _element(uf, "pFCPUFDest", format(rates.fcp_destination_rate, ".4f"))
        _element(uf, "pICMSUFDest", format(rates.difal_destination_rate, ".4f"))
        _element(uf, "pICMSInter", format(rates.difal_interstate_rate, ".2f"))
        _element(uf, "pICMSInterPart", format(rates.difal_destination_share, ".4f"))
        if rates.fcp_destination_rate is not None:
            _element(uf, "vFCPUFDest", _money(tax.fcp_destination_amount))
        _element(uf, "vICMSUFDest", _money(tax.difal_amount))
        _element(uf, "vICMSUFRemet", "0.00")
    if outcome.ibs_cbs_cst_code is not None:
        with_group = rtc_cst_requires_gibscbs(outcome.ibs_cbs_cst_code)
        if outcome.ibs_cbs_classification_code is not None:
            require_representable_classification(outcome.ibs_cbs_classification_code)
        rtc = _element(parent, "IBSCBS")
        _element(rtc, "CST", outcome.ibs_cbs_cst_code)
        _element(rtc, "cClassTrib", outcome.ibs_cbs_classification_code)
        if not with_group:
            return  # CST 400/410: SITUACAO_TRIBUTARIA forbids gIBSCBS.
        rtc_group = _element(rtc, "gIBSCBS")
        _element(rtc_group, "vBC", _money(tax.rtc_base))
        for name, rtc_rate, rtc_value, reduction, rate_tag, value_tag in (
            (
                "gIBSUF",
                rates.rtc_uf_rate,
                tax.rtc_ibs_uf_amount,
                rates.rtc_uf_reduction_rate,
                "pIBSUF",
                "vIBSUF",
            ),
            (
                "gIBSMun",
                rates.rtc_municipal_rate,
                tax.rtc_ibs_municipal_amount,
                rates.rtc_municipal_reduction_rate,
                "pIBSMun",
                "vIBSMun",
            ),
        ):
            assert rtc_rate is not None
            part = _element(rtc_group, name)
            _element(part, rate_tag, format(rtc_rate, ".4f"))
            if reduction is not None:
                reduction_node = _element(part, "gRed")
                _element(reduction_node, "pRedAliq", format(reduction, ".4f"))
                _element(
                    reduction_node,
                    "pAliqEfet",
                    format(
                        (rtc_rate * (100 - reduction) / 100).quantize(
                            Decimal("0.0001"), rounding="ROUND_HALF_UP"
                        ),
                        ".4f",
                    ),
                )
            _element(part, value_tag, _money(rtc_value))
        _element(rtc_group, "vIBS", _money(tax.rtc_ibs_uf_amount + tax.rtc_ibs_municipal_amount))
        cbs = _element(rtc_group, "gCBS")
        assert rates.rtc_cbs_rate is not None
        _element(cbs, "pCBS", format(rates.rtc_cbs_rate, ".4f"))
        if rates.rtc_cbs_reduction_rate is not None:
            reduction_node = _element(cbs, "gRed")
            _element(reduction_node, "pRedAliq", format(rates.rtc_cbs_reduction_rate, ".4f"))
            _element(
                reduction_node,
                "pAliqEfet",
                format(
                    (rates.rtc_cbs_rate * (100 - rates.rtc_cbs_reduction_rate) / 100).quantize(
                        Decimal("0.0001"), rounding="ROUND_HALF_UP"
                    ),
                    ".4f",
                ),
            )
        _element(cbs, "vCBS", _money(tax.rtc_cbs_amount))
