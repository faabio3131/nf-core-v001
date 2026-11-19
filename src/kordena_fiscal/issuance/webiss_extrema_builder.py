"""Provider-specific WebISS Extrema RPS construction from governed fiscal inputs.

Never infer RPS sequence numbers, IBS/CBS taxation, NBS, tax incidence or
recipient identities from an LLM, user-supplied XML or a provider response.
The canonical issuer/amounts are immutable; the additional municipality
facts and reservation must be explicitly approved and durably archived.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from lxml import etree

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    InternalFiscalSequenceStream,
)
from kordena_fiscal.xml.schema import XmlSchemaValidator

_NS = "http://www.abrasf.org.br/nfse.xsd"
_MUNICIPALITY = "3125101"
_CENT = Decimal("0.01")
_MEDIA_TYPE = "application/vnd.nfcore.webiss-extrema-rps-intent.v1+json"


@dataclass(frozen=True, slots=True)
class ExtremaServiceTaker:
    """Trusted recipient snapshot, separate from the canonical opaque reference."""

    reference: str
    cnpj: Cnpj
    legal_name: str

    def __post_init__(self) -> None:
        if not self.reference or not self.reference.strip():
            raise FiscalValidationError("WebISS taker needs a canonical reference")
        if not isinstance(self.cnpj, Cnpj) or not self.legal_name.strip():
            raise FiscalValidationError("WebISS taker identity is incomplete")
        if not 1 <= len(self.legal_name.strip()) <= 150:
            raise FiscalValidationError("WebISS taker legal name is out of bounds")


@dataclass(frozen=True, slots=True)
class ExtremaRpsIntent:
    """Immutable issuance evidence, including a dedicated atomic RPS reservation.

    RTC values are sourced from an approved and versioned tax rule. Their
    correctness is NEVER guessed from an unrelated national tax code.
    """

    request_fingerprint: str
    issuer_cnpj: Cnpj
    reservation: FiscalNumberReservation
    rule_reference: str
    exigibilidade_iss: str
    incidence_municipality_ibge: str
    iss_rate_fraction: Decimal
    incentive_fiscal: bool
    nbs_code: str
    rtc_operation_indicator: str
    rtc_cst: str
    rtc_tax_class: str
    taker: ExtremaServiceTaker

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint):
            raise FiscalValidationError("Invalid WebISS immutable request fingerprint")
        if not isinstance(self.issuer_cnpj, Cnpj):
            raise FiscalValidationError("Invalid WebISS issuer")
        if not isinstance(self.reservation, FiscalNumberReservation):
            raise FiscalValidationError("An atomic RPS reservation is required")
        if self.reservation.key.model is not InternalFiscalSequenceStream.NFSE_RPS:
            raise FiscalValidationError("NFS-e RPS cannot share NF-e/NFC-e numbering")
        if not 1 <= self.reservation.number <= 999_999_999_999_999:
            raise FiscalValidationError("Reserved RPS number exceeds official layout")
        if not 0 <= self.reservation.key.series <= 99_999:
            raise FiscalValidationError("RPS series exceeds official 5-character field")
        if not self.rule_reference.strip() or len(self.rule_reference) > 512:
            raise FiscalValidationError("Approved RTC tax rule reference is required")
        if self.exigibilidade_iss not in {"1", "2", "3", "4", "5", "6", "7"}:
            raise FiscalValidationError("Invalid ISS exigibility classification")
        if (
            not re.fullmatch(r"[0-9]{7}", self.incidence_municipality_ibge)
            or not re.fullmatch(r"[0-9]{9}", self.nbs_code)
            or not re.fullmatch(r"[0-9]{6}", self.rtc_operation_indicator)
            or not re.fullmatch(r"[0-9]{3}", self.rtc_cst)
            or not re.fullmatch(r"[0-9]{6}", self.rtc_tax_class)
        ):
            raise FiscalValidationError("Invalid WebISS RTC classification fields")
        precision = self.iss_rate_fraction.as_tuple().exponent if isinstance(
            self.iss_rate_fraction, Decimal
        ) else None
        if (
            not isinstance(self.iss_rate_fraction, Decimal)
            or not self.iss_rate_fraction.is_finite()
            or not Decimal("0") <= self.iss_rate_fraction <= Decimal("1")
            or not isinstance(precision, int)
            or precision < -4
        ):
            raise FiscalValidationError("ISS rate must be a 0..1 fraction with <=4 places")
        if not isinstance(self.incentive_fiscal, bool):
            raise FiscalValidationError("Fiscal incentive must be expressly determined")
        if not isinstance(self.taker, ExtremaServiceTaker):
            raise FiscalValidationError("Trusted municipal taker is required")


def validate_extrema_intent(
    request: NfseAuthorizationRequest, intent: ExtremaRpsIntent,
) -> None:
    if not isinstance(request, NfseAuthorizationRequest) or not isinstance(
        intent, ExtremaRpsIntent
    ):
        raise FiscalValidationError("Prepared WebISS requires request and approved intent")
    document = request.document
    scope = document.scope
    jurisdiction = document.issuer.address.jurisdiction
    reservation = intent.reservation
    if (
        scope.environment is not FiscalEnvironment.HOMOLOGATION
        or not scope.host_namespace
        or jurisdiction.state_code != "MG"
        or jurisdiction.municipality_ibge_code != _MUNICIPALITY
        or document.service_jurisdiction.municipality_ibge_code != _MUNICIPALITY
        or intent.request_fingerprint != request.request_fingerprint
        or intent.issuer_cnpj != document.issuer.cnpj
        or reservation.key != FiscalSequenceKey.from_scope(
            scope, model=InternalFiscalSequenceStream.NFSE_RPS,
            series=reservation.key.series,
        )
        or request.document.service_taker_reference != intent.taker.reference
        or len(document.services) != 1
        or document.issuer.tax_regime is TaxRegimeCode.MEI
        or (
            document.issuer.tax_regime in {
                TaxRegimeCode.SIMPLES_NACIONAL,
                TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            }
            and document.competence_date.isoformat() >= "2026-11-01"
        )
    ):
        raise FiscalValidationError("WebISS RPS intent disagrees with immutable fiscal scope")
    line = document.services[0]
    expected_iss = (line.taxable_amount.amount * intent.iss_rate_fraction).quantize(
        _CENT, rounding=ROUND_HALF_UP,
    )
    if (
        line.iss_amount.amount != expected_iss
        or line.taxable_amount.amount <= 0
        or line.gross_amount.amount <= 0
        or line.iss_withheld not in (True, False)
    ):
        raise FiscalValidationError("ISS calculation disagrees with approved RPS tax intent")


def _child(parent: etree._Element, name: str, value: str) -> etree._Element:
    node = etree.SubElement(parent, f"{{{_NS}}}{name}")
    node.text = value
    return node


def build_extrema_rps_xml(
    request: NfseAuthorizationRequest, intent: ExtremaRpsIntent,
    *, validator: XmlSchemaValidator,
) -> bytes:
    """Construct a complete *unsigned* 2.02 RTC RPS, validated before A1 access.

    The existing governed ABRASF signer performs the real XMLDSig and its
    separate fiscal rule preaudit; this builder never signs or transmits.
    """
    validate_extrema_intent(request, intent)
    if not isinstance(validator, XmlSchemaValidator):
        raise FiscalValidationError("Official municipal XSD validator is required")
    document = request.document
    issuer = document.issuer
    line = document.services[0]
    root = etree.Element(
        f"{{{_NS}}}GerarNfseEnvio", nsmap=cast(dict[str, str], {None: _NS}),
    )
    rps = etree.SubElement(root, f"{{{_NS}}}Rps")
    information = etree.SubElement(
        rps, f"{{{_NS}}}InfDeclaracaoPrestacaoServico",
        Id="RPS" + hashlib.sha256(request.request_fingerprint.encode()).hexdigest()[:30],
    )
    rps_info = etree.SubElement(information, f"{{{_NS}}}Rps")
    identification = etree.SubElement(rps_info, f"{{{_NS}}}IdentificacaoRps")
    _child(identification, "Numero", str(intent.reservation.number))
    _child(identification, "Serie", str(intent.reservation.key.series))
    _child(identification, "Tipo", "1")
    _child(rps_info, "DataEmissao", document.issued_at.date().isoformat())
    _child(rps_info, "Status", "1")
    _child(information, "Competencia", document.competence_date.isoformat())
    service = etree.SubElement(information, f"{{{_NS}}}Servico")
    values = etree.SubElement(service, f"{{{_NS}}}Valores")
    _child(values, "ValorServicos", f"{line.gross_amount.amount:.2f}")
    if line.deduction_amount.amount > 0:
        _child(values, "ValorDeducoes", f"{line.deduction_amount.amount:.2f}")
    _child(values, "ValorIss", f"{line.iss_amount.amount:.2f}")
    _child(values, "Aliquota", f"{intent.iss_rate_fraction * 100:.4f}")
    _child(service, "IssRetido", "1" if line.iss_withheld else "2")
    _child(service, "ItemListaServico", line.municipal_service_code)
    if issuer.primary_cnae is not None:
        _child(service, "CodigoCnae", issuer.primary_cnae.value)
    _child(service, "CodigoNbs", intent.nbs_code)
    _child(service, "Discriminacao", line.description)
    _child(service, "CodigoMunicipio", _MUNICIPALITY)
    _child(service, "ExigibilidadeISS", intent.exigibilidade_iss)
    _child(service, "MunicipioIncidencia", intent.incidence_municipality_ibge)
    prestador = etree.SubElement(information, f"{{{_NS}}}Prestador")
    cpf_cnpj = etree.SubElement(prestador, f"{{{_NS}}}CpfCnpj")
    _child(cpf_cnpj, "Cnpj", issuer.cnpj.value)
    if issuer.municipal_registration is not None:
        _child(prestador, "InscricaoMunicipal", issuer.municipal_registration.number)
    if issuer.state_registration.number:
        _child(prestador, "InscricaoEstadual", issuer.state_registration.number)
    tomador = etree.SubElement(information, f"{{{_NS}}}Tomador")
    identificacao = etree.SubElement(tomador, f"{{{_NS}}}IdentificacaoTomador")
    tomador_cpf_cnpj = etree.SubElement(identificacao, f"{{{_NS}}}CpfCnpj")
    _child(tomador_cpf_cnpj, "Cnpj", intent.taker.cnpj.value)
    _child(tomador, "RazaoSocial", intent.taker.legal_name)
    _child(
        information, "OptanteSimplesNacional",
        "2" if issuer.tax_regime is TaxRegimeCode.NORMAL else "1",
    )
    _child(information, "IncentivoFiscal", "1" if intent.incentive_fiscal else "2")
    rtc = etree.SubElement(information, f"{{{_NS}}}IBSCBS")
    _child(rtc, "finNFSe", "0")
    _child(rtc, "cIndOp", intent.rtc_operation_indicator)
    _child(rtc, "indDest", "0")
    rtc_values = etree.SubElement(rtc, f"{{{_NS}}}valores")
    trib = etree.SubElement(rtc_values, f"{{{_NS}}}trib")
    ibs_cbs = etree.SubElement(trib, f"{{{_NS}}}gIBSCBS")
    _child(ibs_cbs, "CST", intent.rtc_cst)
    _child(ibs_cbs, "cClassTrib", intent.rtc_tax_class)
    xml = etree.tostring(root, encoding="utf-8")
    validator.validate_document(xml)
    return xml


def encode_extrema_intent(intent: ExtremaRpsIntent) -> bytes:
    if not isinstance(intent, ExtremaRpsIntent):
        raise FiscalValidationError("Invalid WebISS archival intent")
    payload = {
        "version": 1,
        "request_fingerprint": intent.request_fingerprint,
        "issuer_cnpj": intent.issuer_cnpj.value,
        "reservation": {
            "number": intent.reservation.number,
            "series": intent.reservation.key.series,
            "token": intent.reservation.reservation_token,
        },
        "rule_reference": intent.rule_reference,
        "exigibilidade_iss": intent.exigibilidade_iss,
        "incidence_municipality_ibge": intent.incidence_municipality_ibge,
        "iss_rate_fraction": str(intent.iss_rate_fraction),
        "incentive_fiscal": intent.incentive_fiscal,
        "nbs_code": intent.nbs_code,
        "rtc_operation_indicator": intent.rtc_operation_indicator,
        "rtc_cst": intent.rtc_cst,
        "rtc_tax_class": intent.rtc_tax_class,
        "taker": {
            "reference": intent.taker.reference,
            "cnpj": intent.taker.cnpj.value,
            "legal_name": intent.taker.legal_name,
        },
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def decode_extrema_intent(
    raw: bytes, *, scope: ExecutionScope, request: NfseAuthorizationRequest,
) -> ExtremaRpsIntent:
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        info = data["reservation"]
        taker = data["taker"]
        key = FiscalSequenceKey.from_scope(
            scope, model=InternalFiscalSequenceStream.NFSE_RPS, series=info["series"],
        )
        reservation = FiscalNumberReservation(
            key=key, number=info["number"], reservation_token=info["token"],
        )
        expected_token = hashlib.sha256(
            f"{key.canonical_material}|{reservation.number}".encode(),
        ).hexdigest()
        if reservation.reservation_token != expected_token:
            raise ValueError
        intent = ExtremaRpsIntent(
            request_fingerprint=data["request_fingerprint"],
            issuer_cnpj=Cnpj(data["issuer_cnpj"]),
            reservation=reservation,
            rule_reference=data["rule_reference"],
            exigibilidade_iss=data["exigibilidade_iss"],
            incidence_municipality_ibge=data["incidence_municipality_ibge"],
            iss_rate_fraction=Decimal(data["iss_rate_fraction"]),
            incentive_fiscal=data["incentive_fiscal"],
            nbs_code=data["nbs_code"],
            rtc_operation_indicator=data["rtc_operation_indicator"],
            rtc_cst=data["rtc_cst"],
            rtc_tax_class=data["rtc_tax_class"],
            taker=ExtremaServiceTaker(
                reference=taker["reference"], cnpj=Cnpj(taker["cnpj"]),
                legal_name=taker["legal_name"],
            ),
        )
        validate_extrema_intent(request, intent)
    except (KeyError, TypeError, ValueError, FiscalValidationError, ArithmeticError):
        raise FiscalValidationError("WebISS archived fiscal intent is invalid or mutated") from None
    return intent


EXTREMA_INTENT_MEDIA_TYPE = _MEDIA_TYPE
