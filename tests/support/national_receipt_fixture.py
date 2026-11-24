"""Complete synthetic NT009 NFSe fixtures; no SEFIN or ICP trust claim."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_nfse_receipt_validator
from kordena_fiscal.xml.nfse_national_profiles import NT009_RESTRICTED_PROFILE

NS = 'http://www.sped.fazenda.gov.br/nfse'
TAG = '{' + NS + '}'


def sample():
    spec = importlib.util.spec_from_file_location(
        'receipt_builder_fixture', Path(__file__).parents[1] / 'issuance/test_nfse_dps_builder.py',
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic receipt only')])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True).sign(key, hashes.SHA256()))
    blob = pkcs12.serialize_key_and_certificates(
        b'synthetic', key, cert, None, BestAvailableEncryption(b'unit-test'),
    )
    return module._request(), EphemeralCertificateMaterial(
        reference_id='synthetic-receipt', pkcs12_bytes=blob, password=b'unit-test',
    )


def key_for(dps: bytes, digit: str = '3') -> str:
    info = etree.fromstring(dps).find(TAG + 'infDPS')
    assert info is not None
    return (info.findtext(TAG + 'cLocEmi') + '22'
            + info.findtext(TAG + 'prest/' + TAG + 'CNPJ') + digit * 27)


def complete_receipt(
    dps: bytes, material, *, key: str | None = None, issued_at=None,
    schema_profile: str = NT009_RESTRICTED_PROFILE,
) -> bytes:
    """Include the actual submitted DPS, with its reserved serial and signed bytes."""
    dps_root = etree.fromstring(dps)
    dps_info = dps_root.find(TAG + 'infDPS')
    assert dps_info is not None
    city = dps_info.findtext(TAG + 'cLocEmi')
    cnpj = dps_info.findtext(TAG + 'prest/' + TAG + 'CNPJ')
    assert city and cnpj
    private, cert, _ = pkcs12.load_key_and_certificates(material.pkcs12_bytes, material.password)
    assert isinstance(private, rsa.RSAPrivateKey) and cert is not None
    root = etree.Element(TAG + 'NFSe', nsmap={None: NS}, versao='1.01')
    info = etree.SubElement(root, TAG + 'infNFSe', Id='NFS' + (key or key_for(dps)))

    def child(parent, name, value):
        etree.SubElement(parent, TAG + name).text = value

    for name, value in [
        ('xLocEmi', 'Cidade Sintetica'), ('xLocPrestacao', 'Cidade Sintetica'),
        ('nNFSe', '1'), ('xTribNac', 'Servico sintetico'), ('verAplic', 'nfcore-synthetic'),
        ('ambGer', '2'), ('tpEmis', '1'), ('cStat', '100'),
        ('dhProc', (issued_at or datetime.now(UTC)).isoformat(timespec='seconds')), ('nDFSe', '1'),
    ]:
        child(info, name, value)
    emit = etree.SubElement(info, TAG + 'emit')
    child(emit, 'CNPJ', cnpj)
    child(emit, 'xNome', 'Empresa Sintetica')
    address = etree.SubElement(emit, TAG + 'enderNac')
    for name, value in [
        ('xLgr', 'Rua Sintetica'), ('nro', '1'), ('xBairro', 'Centro'),
        ('cMun', city), ('UF', {'31': 'MG', '35': 'SP'}.get(city[:2], 'SP')), ('CEP', '01001000'),
    ]:
        child(address, name, value)
    child(etree.SubElement(info, TAG + 'valores'), 'vLiq', '100.00')
    info.append(dps_root)
    append_nfse_signature(root, info, private, cert, legacy_abrasf=False)
    xml = etree.tostring(root, encoding='utf-8', xml_declaration=True)
    national_nfse_receipt_validator(profile=schema_profile).validate_document(xml)
    return xml


def sample_receipt(key: str | None = None):
    request, material = sample()
    dps = build_sefin_signed_dps(request, material)
    return request, material, complete_receipt(dps, material, key=key)
