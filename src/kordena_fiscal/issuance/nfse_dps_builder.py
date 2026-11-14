"""Builds the official National NFS-e DPS XML from the canonical domain model.

Constructs the ``<DPS>`` document defined by the real, hash-pinned schema
shipped under ``xml/official/NFSE_NACIONAL_1.0x`` directly from an
``NfseAuthorizationRequest`` -- no field is invented beyond what the
canonical issuer/document already carries. The unsigned XML is validated
against the pinned XSD (``national_dps_validator``) before being handed to
the existing XMLDSig signer (``sign_nfse_dps_xml``); this module performs no
cryptography of its own and never reads or writes the A1 vault.

DPS series and serial MUST be reserved by the canonical durable fiscal
Unit of Work before calling this builder. Neither hashes nor MAX+1 can
allocate fiscal numbers. Special ISS regimes and Simples sublimit assessment
require an effective-dated reviewed treatment, never a provisional fallback.
"""
from __future__ import annotations

from datetime import UTC
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

from kordena_fiscal.domain import Cnpj, Cpf, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest, NfseForeignAddress
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

_NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
_SCHEMA_VERSION = "1.01"
_VER_APLIC = "nfcore-dps-v1"  # TSVerAplic: TSString, maxLength 20
_FEDERAL_INSCRIPTION_TYPE_CNPJ = "1"
_CENT = Decimal("0.01")

# National DPS "opSimpNac" is a distinct official code table from our domain's
# TaxRegimeCode (CRT); the two enumerations are NOT numerically compatible
# and must be translated explicitly rather than passed through.
_OP_SIMP_NAC: dict[TaxRegimeCode, str] = {
    TaxRegimeCode.NORMAL: "1",  # Nao optante
    TaxRegimeCode.MEI: "2",  # Optante - MEI
    TaxRegimeCode.SIMPLES_NACIONAL: "3",  # Optante - ME/EPP
    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT: "3",  # Optante - ME/EPP (sublimite excedido)
}


def _child(parent: etree._Element, tag: str, text: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{_NFSE_NS}}}{tag}")
    element.text = text
    return element


def _money(value: Decimal) -> str:
    # TSDec15V2 accepts "0", "0.NN" or "[1-9]...[.NN]"; two fixed decimals
    # satisfy every branch of that pattern.
    return f"{value:.2f}"


def _require_durable_dps_numbering(request: NfseAuthorizationRequest) -> tuple[str, str]:
    """Use only a UoW-assigned, fingerprint-bound DPS series and serial.

    An unnumbered request is safe for read-only preaudit/recovery but must not
    be signed or transmitted, even to a production-restrita endpoint.
    """
    document = request.document
    if document.dps_number is None:
        raise FiscalValidationError(
            "DPS number not reserved by durable fiscal Unit of Work"
        )
    return str(document.dps_series), str(document.dps_number)

def build_signed_dps(
    request: NfseAuthorizationRequest, certificate: EphemeralCertificateMaterial
) -> bytes:
    """Build, schema-validate and sign the national DPS for ``request``.

    Fail-closed: any field this builder cannot populate confidently from
    verified document data raises ``FiscalValidationError`` rather than
    guessing or silently omitting a required XSD element.
    """
    if not isinstance(request, NfseAuthorizationRequest):
        raise FiscalValidationError("build_signed_dps requires an NfseAuthorizationRequest")
    document = request.document
    issuer = document.issuer

    if len(document.services) != 1:
        raise FiscalValidationError(
            "National DPS schema models exactly one service per DPS; split "
            "multi-line NFS-e documents into one DPS submission per line"
        )
    service = document.services[0]

    if service.national_taxation_code is None or not (
        len(service.national_taxation_code) == 6 and service.national_taxation_code.isdigit()
    ):
        raise FiscalValidationError(
            "NFS-e service line requires a 6-digit numeric national_taxation_code (cTribNac)"
        )

    cnpj = issuer.cnpj.value
    if not cnpj.isdigit():
        raise FiscalValidationError(
            "DPS Id/CNPJ elements require a purely numeric CNPJ; this issuer "
            "carries an alphanumeric CNPJ not yet supported by the pinned schema"
        )

    issuer_municipality = issuer.address.jurisdiction.municipality_ibge_code
    if issuer_municipality is None or not issuer_municipality.isdigit():
        raise FiscalValidationError("DPS requires a numeric issuer municipality IBGE code")
    issuer_municipality = issuer_municipality.zfill(7)
    if len(issuer_municipality) != 7:
        raise FiscalValidationError("issuer municipality IBGE code must have 7 digits")

    service_municipality = document.service_jurisdiction.municipality_ibge_code
    if service_municipality is None or not service_municipality.isdigit():
        raise FiscalValidationError("DPS requires a numeric service jurisdiction IBGE code")
    service_municipality = service_municipality.zfill(7)

    op_simp_nac = _OP_SIMP_NAC.get(issuer.tax_regime)
    if op_simp_nac is None:
        raise FiscalValidationError(
            f"unsupported tax regime for NFS-e Nacional: {issuer.tax_regime!r}"
        )

    serie, n_dps = _require_durable_dps_numbering(request)
    dps_id = (
        "DPS"
        + issuer_municipality
        + _FEDERAL_INSCRIPTION_TYPE_CNPJ
        + cnpj
        + serie.zfill(5)
        + n_dps.zfill(15)
    )

    root = etree.Element(f"{{{_NFSE_NS}}}DPS", nsmap={None: _NFSE_NS})  # type: ignore[dict-item]
    root.set("versao", _SCHEMA_VERSION)
    info = etree.SubElement(root, f"{{{_NFSE_NS}}}infDPS", Id=dps_id)

    _child(info, "tpAmb", "2")  # governed gateway only authorizes FiscalEnvironment.HOMOLOGATION
    _child(
        info,
        "dhEmi",
        document.issued_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00",
    )
    _child(info, "verAplic", _VER_APLIC)
    _child(info, "serie", serie)
    _child(info, "nDPS", n_dps)
    _child(info, "dCompet", document.competence_date.strftime("%Y-%m-%d"))
    _child(info, "tpEmit", "1")  # Prestador -- this flow always submits on the issuer's own behalf
    _child(info, "cLocEmi", issuer_municipality)

    prest = etree.SubElement(info, f"{{{_NFSE_NS}}}prest")
    _child(prest, "CNPJ", cnpj)
    if issuer.municipal_registration is not None:
        im = issuer.municipal_registration.number
        if len(im) > 15:
            raise FiscalValidationError("municipal registration exceeds the 15-character IM limit")
        _child(prest, "IM", im)
    _child(prest, "xNome", issuer.legal_name.strip())
    end = etree.SubElement(prest, f"{{{_NFSE_NS}}}end")
    # Official National DPS 1.01 TCEndereco requires endNac/endExt before
    # xLgr. This issuer carries a Brazilian CNPJ/IBGE and must use endNac.
    end_nac = etree.SubElement(end, f"{{{_NFSE_NS}}}endNac")
    _child(end_nac, "cMun", issuer_municipality)
    _child(end_nac, "CEP", issuer.address.postal_code)
    _child(end, "xLgr", issuer.address.street.strip())
    _child(end, "nro", issuer.address.number.strip())
    if issuer.address.complement:
        _child(end, "xCpl", issuer.address.complement.strip())
    _child(end, "xBairro", issuer.address.district.strip())
    reg_trib = etree.SubElement(prest, f"{{{_NFSE_NS}}}regTrib")
    _child(reg_trib, "opSimpNac", op_simp_nac)
    treatment = document.national_tax_treatment
    if issuer.tax_regime is TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT and (
        treatment is None or treatment.simples_assessment_code is None
    ):
        raise FiscalValidationError(
            "Simples excess sublimit requires a reviewed regApTribSN decision"
        )
    if treatment is not None and treatment.simples_assessment_code is not None:
        _child(reg_trib, "regApTribSN", treatment.simples_assessment_code)
    # For an ordinary profile without a special fiscal decision, '0' is
    # the explicit official "Nenhum" regime. Nonzero regimes can only come
    # from the reviewed document decision, versioned with competence.
    _child(reg_trib, "regEspTrib", (
        treatment.special_regime_code if treatment is not None else "0"
    ))

    # Toma is placed after prest and before serv under the official 1.01 XSD.
    # The source reference is NOT a tax identity and is never substituted here.
    if document.service_taker is not None:
        taker = document.service_taker
        toma = etree.SubElement(info, f"{{{_NFSE_NS}}}toma")
        if isinstance(taker.tax_id, Cnpj):
            _child(toma, "CNPJ", taker.tax_id.value)
        elif isinstance(taker.tax_id, Cpf):
            _child(toma, "CPF", taker.tax_id.value)
        elif taker.nif is not None:
            _child(toma, "NIF", taker.nif)
        elif taker.no_nif_reason is not None:
            _child(toma, "cNaoNIF", taker.no_nif_reason)
        else:
            raise FiscalValidationError("Canonical taker tax identity is missing")
        if taker.municipal_registration is not None:
            _child(toma, "IM", taker.municipal_registration)
        _child(toma, "xNome", taker.legal_name)
        if taker.address is not None:
            address = taker.address
            end_taker = etree.SubElement(toma, f"{{{_NFSE_NS}}}end")
            if isinstance(address, NfseForeignAddress):
                ext = etree.SubElement(end_taker, f"{{{_NFSE_NS}}}endExt")
                _child(ext, "cPais", address.country_code)
                _child(ext, "cEndPost", address.postal_code)
                _child(ext, "xCidade", address.city)
                _child(ext, "xEstProvReg", address.region)
            else:
                national = etree.SubElement(end_taker, f"{{{_NFSE_NS}}}endNac")
                _child(national, "cMun", address.jurisdiction.municipality_ibge_code or "")
                _child(national, "CEP", address.postal_code)
            _child(end_taker, "xLgr", address.street)
            _child(end_taker, "nro", address.number)
            if address.complement is not None:
                _child(end_taker, "xCpl", address.complement)
            _child(end_taker, "xBairro", address.district)

    serv = etree.SubElement(info, f"{{{_NFSE_NS}}}serv")
    loc_prest = etree.SubElement(serv, f"{{{_NFSE_NS}}}locPrest")
    _child(loc_prest, "cLocPrestacao", service_municipality)
    c_serv = etree.SubElement(serv, f"{{{_NFSE_NS}}}cServ")
    _child(c_serv, "cTribNac", service.national_taxation_code)
    _child(c_serv, "xDescServ", service.description.strip())

    valores = etree.SubElement(info, f"{{{_NFSE_NS}}}valores")
    v_serv_prest = etree.SubElement(valores, f"{{{_NFSE_NS}}}vServPrest")
    _child(v_serv_prest, "vServ", _money(service.gross_amount.amount))
    if service.deduction_amount.amount > 0:
        ded_red = etree.SubElement(valores, f"{{{_NFSE_NS}}}vDedRed")
        _child(ded_red, "vDR", _money(service.deduction_amount.amount))
    trib = etree.SubElement(valores, f"{{{_NFSE_NS}}}trib")
    trib_mun = etree.SubElement(trib, f"{{{_NFSE_NS}}}tribMun")
    iss_taxation = treatment.iss_taxation_code if treatment is not None else "1"
    _child(trib_mun, "tribISSQN", iss_taxation)
    if treatment is not None and iss_taxation == "3":
        if treatment.result_country_code is None:
            raise FiscalValidationError("Exported ISS service requires country")
        _child(trib_mun, "cPaisResult", treatment.result_country_code)
    if treatment is not None and iss_taxation == "2":
        if treatment.immunity_type_code is None:
            raise FiscalValidationError("Immune ISS service requires immunity type")
        _child(trib_mun, "tpImunidade", treatment.immunity_type_code)
    taxable = service.taxable_amount.amount
    iss_amount = service.iss_amount.amount
    # XSD 1.01 changed TCTribMunicipal field order: tpRetISSQN before pAliq.
    _child(trib_mun, "tpRetISSQN", "2" if service.iss_withheld else "1")
    if taxable > 0 and iss_amount > 0:
        rate = (iss_amount / taxable * 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        _child(trib_mun, "pAliq", _money(rate))
    tot_trib = etree.SubElement(trib, f"{{{_NFSE_NS}}}totTrib")
    _child(tot_trib, "indTotTrib", "0")  # Decreto 8.264/2014: no tax-total estimate declared

    unsigned_xml = etree.tostring(root, encoding="utf-8", xml_declaration=False)
    national_dps_validator(_SCHEMA_VERSION).validate_document(unsigned_xml)
    return sign_nfse_dps_xml(unsigned_xml, certificate)
