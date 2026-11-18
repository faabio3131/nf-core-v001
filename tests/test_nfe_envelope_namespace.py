"""SOAP and archive wrappers must preserve the signed namespace context."""
# ruff: noqa: F811 -- imported pytest fixtures are requested by name.
from types import SimpleNamespace

import pytest
from lxml import etree
from test_bling_canonical import NOW, mapping, sale_document, signing_material  # noqa: F401

from kordena_fiscal.domain import ElectronicInvoiceModel
from kordena_fiscal.gateway.nfe_sp_homologation import _authorized_nfe_proc, _soap_envelope
from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
from kordena_fiscal.signing.nfe_xmldsig import (
    NfeSignatureProfile,
    sign_nfe_envi_xml,
    verify_official_nfe4_signature,
)
from kordena_fiscal.xml import AccessKeyInput, build_access_key


@pytest.mark.parametrize("namespace_mode", ["prefixed", "default", "custom_unused"])
def test_wrappers_preserve_signature_context_and_do_not_mutate(
    mapping, signing_material, namespace_mode,
):
    document = sale_document(mapping)
    key = build_access_key(AccessKeyInput(
        "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678))
    unsigned = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    if namespace_mode == "default":
        unsigned = unsigned.replace(b"xmlns:nfe=", b"xmlns=")
        unsigned = unsigned.replace(b"<nfe:", b"<").replace(b"</nfe:", b"</")
    elif namespace_mode == "custom_unused":
        unsigned = unsigned.replace(b"nfe:", b"inv:").replace(b"xmlns:nfe", b"xmlns:inv")
        unsigned = unsigned.replace(b"<inv:enviNFe ",
            b'<inv:enviNFe xmlns:unused="urn:unrelated:test" ')
    signed = sign_nfe_envi_xml(unsigned, signing_material,
        profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1)
    batch = etree.fromstring(signed)
    original = etree.tostring(batch)
    soap = etree.fromstring(_soap_envelope(batch))
    ns = "http://www.portalfiscal.inf.br/nfe"
    verify_official_nfe4_signature(soap.find(f".//{{{ns}}}enviNFe"), signing_material)
    assert etree.tostring(batch) == original
    digest = batch.findtext(".//{http://www.w3.org/2000/09/xmldsig#}DigestValue")
    reply = etree.fromstring((
        f'<retEnviNFe xmlns="{ns}"><protNFe versao="4.00"><infProt>'
        f'<chNFe>{key.value}</chNFe><tpAmb>2</tpAmb><cStat>100</cStat>'
        f'<nProt>135000000000001</nProt><digVal>{digest}</digVal>'
        '</infProt></protNFe></retEnviNFe>'
    ).encode())
    archived = _authorized_nfe_proc(batch, reply, SimpleNamespace(access_key=key))
    verify_official_nfe4_signature(etree.fromstring(archived), signing_material)
    assert etree.tostring(batch) == original
