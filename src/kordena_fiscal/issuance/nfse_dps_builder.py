"""Builds the official National NFS-e DPS XML from the canonical domain model.

Constructs the ``<DPS>`` document defined by the real, hash-pinned schema
shipped under ``xml/official/NFSE_NACIONAL_1.0x`` directly from an
``NfseAuthorizationRequest`` -- no field is invented beyond what the
canonical issuer/document already carries. The unsigned XML is validated
against the pinned XSD (``national_dps_validator``) before being handed to
the existing XMLDSig signer (``sign_nfse_dps_xml``); this module performs no
cryptography of its own and never reads or writes the A1 vault.

Two provisional, owner-reviewable decisions are documented inline where they
are made: the ``nDPS``/``serie`` numbering strategy (no sequential-number
field exists yet on ``NfseCanonicalDocument``; Rule #5 forbids an unsafe
MAX+1 strategy, so the number is derived deterministically from the
already-governed request fingerprint instead) and the ``regApTribSN``
default used when a Simples Nacional sublimit has been exceeded.
"""
from __future__ import annotations

import hashlib
from datetime import UTC
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError, TaxRegimeCode
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

_NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
_SCHEMA_VERSION = "1.00"
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


def _derive_dps_numbering(request: NfseAuthorizationRequest) -> tuple[str, str]:
    """Deterministic nDPS (15 numeric digits, no unsafe MAX+1 counter).

    PROVISIONAL: ``NfseCanonicalDocument`` carries no sequential fiscal
    numbering field today. Deriving ``nDPS`` from the hash of the document's
    own, already-governed ``request_fingerprint`` keeps this gateway
    fail-closed and deterministic (same document -> same number, no shared
    mutable counter to race), but it is not a numbering *authority* in the
    sense other fiscal flows use. Replace with a dedicated numbering
    authority before this builder is relied on for anything beyond
    homologation testing.
    """
    seed = f"{request.request_fingerprint}:{request.document.document_id}".encode()
    digest = int(hashlib.sha256(seed).hexdigest(), 16)
    n_dps = str(10**14 + digest % (9 * 10**14))
    if len(n_dps) != 15:  # pragma: no cover - defensive, arithmetic guarantees this
        raise FiscalValidationError("nDPS derivation did not produce 15 digits")
    return "1", n_dps


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

    serie, n_dps = _derive_dps_numbering(request)
    dps_id = (
        "DPS"
        + issuer_municipality
        + _FEDERAL_INSCRIPTION_TYPE_CNPJ
        + cnpj
        + serie.zfill(5)
        + n_dps
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
    _child(end, "xLgr", issuer.address.street.strip())
    _child(end, "nro", issuer.address.number.strip())
    if issuer.address.complement:
        _child(end, "xCpl", issuer.address.complement.strip())
    _child(end, "xBairro", issuer.address.district.strip())
    reg_trib = etree.SubElement(prest, f"{{{_NFSE_NS}}}regTrib")
    _child(reg_trib, "opSimpNac", op_simp_nac)
    if issuer.tax_regime is TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT:
        # PROVISIONAL default: once a Simples Nacional sublimit is exceeded,
        # apportion both federal and municipal taxes outside SN per each
        # tax's own legislation (regApTribSN=3). FiscalProfile does not yet
        # carry an explicit regApTribSN signal to pick 1/2/3 with certainty;
        # revisit with the owner before relying on this for real submission.
        _child(reg_trib, "regApTribSN", "3")
    _child(reg_trib, "regEspTrib", "0")  # Nenhum; FiscalProfile models no special regime today

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
    _child(trib_mun, "tribISSQN", "1")  # Operacao tributavel; domain models no exemption flag yet
    taxable = service.taxable_amount.amount
    iss_amount = service.iss_amount.amount
    if taxable > 0 and iss_amount > 0:
        rate = (iss_amount / taxable * 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        _child(trib_mun, "pAliq", _money(rate))
    _child(trib_mun, "tpRetISSQN", "2" if service.iss_withheld else "1")
    tot_trib = etree.SubElement(trib, f"{{{_NFSE_NS}}}totTrib")
    _child(tot_trib, "indTotTrib", "0")  # Decreto 8.264/2014: no tax-total estimate declared

    unsigned_xml = etree.tostring(root, encoding="utf-8", xml_declaration=False)
    national_dps_validator(_SCHEMA_VERSION).validate_document(unsigned_xml)
    return sign_nfse_dps_xml(unsigned_xml, certificate)
