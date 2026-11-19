"""Offline envelope and cryptographic tests; no fiscal endpoint is contacted."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.nfse_national_homologation import (
    OfficialNfseTransportError,
    build_nfse_dps_request,
    parse_nfse_homologation_response,
)
from kordena_fiscal.signing.nfse_xmldsig import sign_nfse_dps_xml
from kordena_fiscal.vault import EphemeralCertificateMaterial

_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _unsigned_dps(environment: str = "2") -> bytes:
    root = etree.Element(f"{{{_NS}}}DPS", nsmap={None: _NS})
    info = etree.SubElement(root, f"{{{_NS}}}infDPS", Id="DPS1234567890")
    etree.SubElement(info, f"{{{_NS}}}tpAmb").text = environment
    return etree.tostring(root, encoding="utf-8")


def _ephemeral_certificate() -> tuple[EphemeralCertificateMaterial, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NFCore Offline Test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    blob = pkcs12.serialize_key_and_certificates(
        b"nfcore-test", key, cert, None, BestAvailableEncryption(b"unit-test")
    )
    return EphemeralCertificateMaterial(
        reference_id="ref:nfcore-offline", pkcs12_bytes=blob, password=b"unit-test"
    ), key


def test_dps_signature_is_verifiable_and_envelope_is_gzipped() -> None:
    identity, key = _ephemeral_certificate()
    signed = sign_nfse_dps_xml(_unsigned_dps(), identity)
    root = etree.fromstring(signed)
    info = root.xpath("./*[local-name()='infDPS']")[0]
    signature = root.find(f"{{{_DS}}}Signature")
    assert signature is not None
    signed_info = signature.find(f"{{{_DS}}}SignedInfo")
    assert signed_info is not None
    signature_value = signature.findtext(f"{{{_DS}}}SignatureValue")
    assert signature_value
    key.public_key().verify(
        base64.b64decode(signature_value),
        etree.tostring(signed_info, method="c14n", exclusive=False, with_comments=False),
        padding.PKCS1v15(), hashes.SHA1(),  # noqa: S303 -- pinned National DPS XSD fixes RSA-SHA1
    )
    signature_method = signed_info.find(f".//{{{_DS}}}SignatureMethod")
    digest_method = signature.find(f".//{{{_DS}}}DigestMethod")
    assert signature_method is not None and signature_method.get("Algorithm") == f"{_DS}rsa-sha1"
    assert digest_method is not None and digest_method.get("Algorithm") == f"{_DS}sha1"
    digest = signature.findtext(f".//{{{_DS}}}DigestValue")
    assert digest == base64.b64encode(
        hashlib.sha1(  # noqa: S324 -- pinned National DPS XSD fixes SHA-1 digests
            etree.tostring(info, method="c14n", exclusive=False, with_comments=False)
        ).digest()
    ).decode("ascii")
    payload = json.loads(build_nfse_dps_request(signed))
    assert gzip.decompress(base64.b64decode(payload["dpsXmlGZipB64"])) == signed


def test_nfse_rejects_production_dps_before_signing() -> None:
    identity, _ = _ephemeral_certificate()
    with pytest.raises(FiscalValidationError, match="tpAmb=2"):
        sign_nfse_dps_xml(_unsigned_dps("1"), identity)


def test_nfse_rejects_missing_xml_signature() -> None:
    with pytest.raises(OfficialNfseTransportError, match="XMLDSig"):
        build_nfse_dps_request(_unsigned_dps())


def test_nfse_parses_offline_authorization_receipt() -> None:
    key = "31" + "0" * 48
    xml = (
        f'<NFSe xmlns="{_NS}"><infNFSe Id="NFS{key}"/></NFSe>'
    ).encode()
    response = json.dumps({
        "chaveAcesso": key,
        "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii"),
    }).encode("utf-8")
    parsed = parse_nfse_homologation_response(response)
    assert parsed["status"] == "authorized"
    assert parsed["xml"] == xml.decode()


@pytest.mark.parametrize(
    ("key", "id_suffix"),
    [
        ("31" + "0" * 48, "31" + "1" * 48),
        ("31" + "0" * 42, "31" + "0" * 42),
        ("AB" + "0" * 48, "AB" + "0" * 48),
    ],
)
def test_nfse_reply_requires_exact_fifty_digit_signed_document_identity(
    key: str, id_suffix: str,
) -> None:
    xml = f'<NFSe xmlns="{_NS}"><infNFSe Id="NFS{id_suffix}"/></NFSe>'.encode()
    response = json.dumps({
        "chaveAcesso": key,
        "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode(),
    }).encode()
    with pytest.raises(OfficialNfseTransportError, match="XML retornado"):
        parse_nfse_homologation_response(response)


def test_nfse_rejects_invalid_response_without_secret_echo() -> None:
    with pytest.raises(OfficialNfseTransportError):
        parse_nfse_homologation_response(b'{"secret":"never echo"}')


@pytest.mark.parametrize(
    "payload",
    [
        b"<root/>",
        b'<NFSe xmlns="https://untrusted.example/"/>',
        b'<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/"/>',
        (
            b'<!DOCTYPE NFSe [<!ENTITY x "untrusted">]>'
            b'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"/>'
        ),
    ],
)
def test_nfse_receipt_refuses_unrelated_root_or_dtd(payload: bytes) -> None:
    """Official authorization requires a NFS-e namespace/root, not arbitrary XML."""
    response = json.dumps({
        "chaveAcesso": "35" + "0" * 42,
        "nfseXmlGZipB64": base64.b64encode(gzip.compress(payload)).decode("ascii"),
    }).encode()
    with pytest.raises(OfficialNfseTransportError, match="XML retornado"):
        parse_nfse_homologation_response(response)

@pytest.mark.parametrize("canonical", [False, True])
def test_nfse_mtls_exchange_refuses_redirect(monkeypatch, canonical):
    import ssl
    from email.message import Message
    from unittest.mock import Mock
    from urllib.error import HTTPError
    from urllib.request import Request

    from kordena_fiscal.gateway import nfse_nacional_homologation, nfse_national_homologation
    from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects

    module = nfse_nacional_homologation if canonical else nfse_national_homologation
    exchange = (
        nfse_nacional_homologation._exchange_http
        if canonical else
        nfse_national_homologation.NfseNationalHomologationTransport._https_exchange
    )
    opener = Mock()
    opener.open.side_effect = HTTPError("https://sefin.example", 302, "redirect", Message(), None)
    build = Mock(return_value=opener)
    monkeypatch.setattr(module, "build_opener", build)
    with pytest.raises(FiscalValidationError):
        exchange(b"{}", ssl.create_default_context(), 1)
    opener.open.assert_called_once()
    guard = next(arg for arg in build.call_args.args if isinstance(arg, RejectFiscalRedirects))
    request = opener.open.call_args.args[0]
    assert request.full_url.startswith("https://sefin.producaorestrita.nfse.gov.br/")
    assert guard.redirect_request(
        Request(request.full_url), None, 302, "redirect", Message(), "https://external.example/",
    ) is None

@pytest.mark.parametrize("version", ["1.00", "1.01"])
def test_national_schema_rejects_minimal_dps_at_scoped_dispatch(version):
    from kordena_fiscal.gateway.nfse_nacional_homologation import encode_signed_dps
    from kordena_fiscal.xml.schema import XmlSchemaValidationError

    material, _ = _ephemeral_certificate()
    root = etree.fromstring(_unsigned_dps())
    root.set("versao", version)
    provider = etree.SubElement(root[0], f"{{{_NS}}}prest")
    etree.SubElement(provider, f"{{{_NS}}}CNPJ").text = "11222333000181"
    signed = sign_nfse_dps_xml(etree.tostring(root), material)
    with pytest.raises(FiscalValidationError, match="scoped A1"):
        encode_signed_dps(signed, issuer_cnpj="00944029000100")
    with pytest.raises(XmlSchemaValidationError):
        encode_signed_dps(signed, issuer_cnpj="11222333000181")


def test_national_envelope_refuses_an_abrasf_root():
    with pytest.raises(FiscalValidationError, match="official DPS root"):
        build_nfse_dps_request(
            b'<GerarNfseEnvio xmlns="http://www.abrasf.org.br/nfse.xsd"/>',
        )


@pytest.mark.parametrize("issuer_ibge", ["3550308", "3106200", "3304557", "4106902", "5103403"])
def test_scoped_dps_checks_issuer_municipality_before_envelope(issuer_ibge):
    from kordena_fiscal.gateway.nfse_nacional_homologation import encode_signed_dps

    material, _ = _ephemeral_certificate()
    root = etree.fromstring(_unsigned_dps())
    etree.SubElement(root[0], f"{{{_NS}}}cLocEmi").text = "5002704"
    signed = sign_nfse_dps_xml(etree.tostring(root), material)
    with pytest.raises(FiscalValidationError, match="issuer municipality"):
        encode_signed_dps(
            signed, issuer_cnpj="11222333000181", issuer_municipality_ibge=issuer_ibge,
        )
