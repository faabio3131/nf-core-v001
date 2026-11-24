"""MG transport tests use synthetic A1 and local exchanges; no official issuance."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from lxml import etree

from kordena_fiscal.domain import Cnpj, ElectronicInvoiceModel, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway.authorization import AuthorizationRequest, AuthorizationStatus
from kordena_fiscal.gateway.nfe_sp_homologation import (
    NFE_NAMESPACE,
    HomologationAuthorizationTarget,
    OfficialNfeTransportError,
    SefazHomologationAuthorizationGateway,
    SefazSpHomologationGateway,
)
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml import AccessKeyInput, build_access_key

NS = NFE_NAMESPACE
CNPJ = "11222333000181"


def _request(uf="31", model=ElectronicInvoiceModel.NFE):
    key = build_access_key(AccessKeyInput(
        state_ibge_code=uf, issued_at=datetime(2026, 11, 5, tzinfo=UTC),
        issuer_cnpj=Cnpj(CNPJ), model=model, series=1, invoice_number=1,
        emission_type=1, numeric_code=12345678,
    ))
    xml = (
        f'<enviNFe xmlns="{NS}" versao="4.00"><idLote>1</idLote><indSinc>1</indSinc>'
        f'<NFe><infNFe Id="NFe{key.value}" versao="4.00"><ide><cUF>{uf}</cUF>'
        f'<mod>{model.value}</mod><tpAmb>2</tpAmb></ide><emit><CNPJ>{CNPJ}</CNPJ>'
        '</emit></infNFe></NFe></enviNFe>'
    ).encode()
    return AuthorizationRequest(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-a", unit_id="mg-unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="mg-test",
        ),
        access_key=key, signed_xml=xml, idempotency_key=IdempotencyKey("b" * 64),
        request_fingerprint="a" * 64,
    )


@pytest.fixture
def material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic MG")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), b"\x0c\x0e" + CNPJ.encode()),
        ]), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False,
        ), critical=True).sign(key, hashes.SHA256())
    )
    return EphemeralCertificateMaterial(
        reference_id="synthetic:mg", password=b"test-only",
        pkcs12_bytes=pkcs12.serialize_key_and_certificates(
            b"synthetic", key, certificate, None,
            serialization.BestAvailableEncryption(b"test-only"),
        ),
    )


def _gateway(resolver, exchange=None, validator=None):
    return SefazHomologationAuthorizationGateway(
        target=HomologationAuthorizationTarget.MG_NFE,
        resolve_certificate=resolver, exchange=exchange,
        validate_schema=validator or Mock(),
    )


@pytest.mark.parametrize("fiscal_request", [
    _request("35"), _request(model=ElectronicInvoiceModel.NFCE),
    replace(_request(), scope=replace(_request().scope, environment=FiscalEnvironment.PRODUCTION)),
    replace(_request(), signed_xml=_request().signed_xml.replace(b"<cUF>31", b"<cUF>35")),
    replace(_request(), signed_xml=_request().signed_xml.replace(b"<tpAmb>2", b"<tpAmb>1")),
    replace(_request(), signed_xml=_request().signed_xml.replace(CNPJ.encode(), b"99999999999999")),
    replace(_request(), signed_xml=b"<invalid/>"),
])
def test_wrong_scope_never_touches_vault_or_transport(fiscal_request):
    resolver, exchange = Mock(), Mock()
    with pytest.raises(OfficialNfeTransportError):
        _gateway(resolver, exchange).authorize(fiscal_request)
    resolver.assert_not_called()
    exchange.assert_not_called()


@pytest.mark.parametrize("wrong", [
    _request("35", ElectronicInvoiceModel.NFCE),
    _request("31", ElectronicInvoiceModel.NFE),
    replace(
        _request("35"),
        signed_xml=_request("35").signed_xml.replace(b"<mod>55", b"<mod>65"),
    ),
    replace(
        _request("35"),
        signed_xml=_request("35").signed_xml.replace(b"<cUF>35", b"<cUF>31"),
    ),
    replace(
        _request("35"),
        signed_xml=_request("35").signed_xml.replace(
            CNPJ.encode(), b"99999999999999",
        ),
    ),
])
def test_sp_model55_authorizer_blocks_wrong_fiscal_model_before_a1(
    wrong: AuthorizationRequest,
) -> None:
    """NF-e SP55 cannot send NFC-e 65 or tampered UF/issuer to its endpoint."""
    certificate = Mock(side_effect=AssertionError("A1 must not be touched"))
    sender = Mock(side_effect=AssertionError("SEFAZ must not be called"))
    gateway = SefazSpHomologationGateway(
        resolve_certificate=certificate, exchange=sender,
    )
    with pytest.raises(OfficialNfeTransportError, match="SEFAZ SP NF-e"):
        gateway.authorize(wrong)
    certificate.assert_not_called()
    sender.assert_not_called()


def test_mg_requires_explicit_target_and_schema_validator():
    with pytest.raises(ValueError, match="XSD"):
        SefazHomologationAuthorizationGateway(
            target=HomologationAuthorizationTarget.MG_NFE, resolve_certificate=Mock(),
        )
    with pytest.raises(ValueError, match="Unknown"):
        SefazHomologationAuthorizationGateway(
            target="mg_nfe", resolve_certificate=Mock(), validate_schema=Mock(),
        )


def test_schema_rejection_precedes_network(material):
    resolver, exchange = Mock(return_value=material), Mock()
    validator = Mock(side_effect=OfficialNfeTransportError("XSD rejected"))
    with pytest.raises(OfficialNfeTransportError, match="XSD"):
        _gateway(resolver, exchange, validator).authorize(_request())
    resolver.assert_called_once()
    exchange.assert_not_called()


def test_shared_mg_flow_signs_and_preserves_matching_protocol(material):
    request = _request()
    response = (
        '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
        f'<retEnviNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF><cStat>104</cStat>'
        f'<protNFe versao="4.00"><infProt><chNFe>{request.access_key.value}</chNFe>'
        '<tpAmb>2</tpAmb><cStat>100</cStat><nProt>131000000000001</nProt>'
        '<digVal>synthetic</digVal></infProt></protNFe></retEnviNFe></Body></Envelope>'
    ).encode()
    def reply(payload, *_args):
        digest = etree.fromstring(payload).findtext(
            ".//{http://www.w3.org/2000/09/xmldsig#}DigestValue"
        )
        return response.replace(b"synthetic", digest.encode())
    exchange = Mock(side_effect=reply)
    resolver = Mock(return_value=material)
    validator = Mock()
    result = _gateway(resolver, exchange, validator).authorize(request)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.provider.provider_name == "sefaz-mg-homologacao-nfe4"
    assert result.scope == request.scope
    assert result.authorized_xml and b"nfeProc" in result.authorized_xml
    assert validator.call_count == 1
    resolver.assert_called_once_with(request.scope, CNPJ)
    envelope = etree.fromstring(exchange.call_args.args[0])
    assert envelope.find(f".//{{{NS}}}enviNFe") is not None
    assert envelope.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
    assert exchange.call_count == 1


def test_transport_selects_fixed_mg_url_and_preserves_sp_compatibility(monkeypatch):
    import ssl

    import kordena_fiscal.gateway.nfe_sp_homologation as transport
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"<reply/>"
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(transport, "build_opener", Mock(return_value=opener))
    mg = _gateway(Mock())
    mg._https_exchange(b"<synthetic/>", ssl.create_default_context(), 2)
    assert opener.open.call_args.args[0].full_url == (
        "https://hnfe.fazenda.mg.gov.br/nfe2/services/NFeAutorizacao4"
    )
    sp = SefazSpHomologationGateway(resolve_certificate=Mock())
    sp._https_exchange(b"<synthetic/>", ssl.create_default_context(), 2)
    assert opener.open.call_args.args[0].full_url == transport.NFE_SP_HOMOLOGATION_AUTHORIZATION_URL


def test_fiscal_redirect_handler_never_follows_location():
    from email.message import Message
    from urllib.request import Request

    from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects
    assert RejectFiscalRedirects().redirect_request(
        Request("https://hnfe.fazenda.mg.gov.br/"), None, 302, "redirect",
        Message(), "https://attacker.example/",
    ) is None


@pytest.mark.parametrize("tamper", ["digest", "signature", "certificate", "reference"])
def test_mg_rejects_tampered_prepared_xml_before_transport(material, tamper):
    from kordena_fiscal.domain import FiscalValidationError
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml

    original = _request()
    signed = sign_nfe_envi_xml(
        original.signed_xml, material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1,
    )
    root = etree.fromstring(signed)
    fields = {
        "digest": "DigestValue", "signature": "SignatureValue",
        "certificate": "X509Certificate", "reference": "Reference",
    }
    node = root.find(".//{http://www.w3.org/2000/09/xmldsig#}" + fields[tamper])
    if tamper == "reference":
        node.set("URI", "#other-document")
    else:
        node.text = "YQ=="
    exchange = Mock()
    with pytest.raises(FiscalValidationError, match="Invalid NF-e signature|Incompatible"):
        _gateway(Mock(return_value=material), exchange).authorize(
            replace(original, signed_xml=etree.tostring(root))
        )
    exchange.assert_not_called()


@pytest.mark.parametrize("corruption", ["state", "environment", "key", "digest", "fault"])
def test_inconsistent_official_reply_never_authorizes(material, corruption):
    original = _request()
    def reply(payload, *_args):
        digest = etree.fromstring(payload).findtext(
            ".//{http://www.w3.org/2000/09/xmldsig#}DigestValue"
        )
        answer = (
            '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
            f'<retEnviNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF><cStat>104</cStat>'
            f'<protNFe><infProt><chNFe>{original.access_key.value}</chNFe><tpAmb>2</tpAmb>'
            f'<cStat>100</cStat><nProt>131000000000001</nProt><digVal>{digest}</digVal>'
            '</infProt></protNFe></retEnviNFe></Body></Envelope>'
        )
        if corruption == "state":
            answer = answer.replace("<cUF>31", "<cUF>35")
        elif corruption == "environment":
            answer = answer.replace("<tpAmb>2", "<tpAmb>1")
        elif corruption == "key":
            answer = answer.replace(original.access_key.value, "1" * 44)
        elif corruption == "digest":
            answer = answer.replace(digest, "forged")
        else:
            answer = (
                '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">'
                '<Body><Fault/></Body></Envelope>'
            )
        return answer.encode()
    exchange = Mock(side_effect=reply)
    with pytest.raises(OfficialNfeTransportError):
        _gateway(Mock(return_value=material), exchange).authorize(original)
    assert exchange.call_count == 1


def test_mg_official_composition_rejects_incomplete_xml_before_transport(material):
    from kordena_fiscal.gateway.nfe_sp_homologation import build_mg_nfe_homologation_gateway
    from kordena_fiscal.xml.schema import XmlSchemaValidationError
    exchange = Mock()
    gateway = build_mg_nfe_homologation_gateway(
        resolve_certificate=Mock(return_value=material), exchange=exchange,
    )
    # Synthetic XML is intentionally incomplete: the real official XSD must reject it.
    with pytest.raises(XmlSchemaValidationError, match="pinned XSD"):
        gateway.authorize(_request())
    exchange.assert_not_called()


def test_mg_signature_profile_satisfies_official_xmldsig_and_crypto(material):
    import base64

    from cryptography.hazmat.primitives.asymmetric import padding

    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml.official_nfe_schema import load_official_nfe_schema
    signed = sign_nfe_envi_xml(
        _request().signed_xml, material,
        profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1,
    )
    root = etree.fromstring(signed)
    signature = root.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
    official = next(
        resource for resource in load_official_nfe_schema().resources
        if resource.name == "xmldsig-core-schema_v1.01.xsd"
    )
    etree.XMLSchema(etree.fromstring(official.content)).assertValid(signature)
    info = signature.find("{http://www.w3.org/2000/09/xmldsig#}SignedInfo")
    value = signature.findtext("{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
    _, certificate, _ = pkcs12.load_key_and_certificates(
        material.pkcs12_bytes, material.password,
    )
    certificate.public_key().verify(
        base64.b64decode(value), etree.tostring(info, method="c14n"),
        padding.PKCS1v15(), hashes.SHA1(),
    )
    digest = signature.findtext(".//{http://www.w3.org/2000/09/xmldsig#}DigestValue")
    assert len(base64.b64decode(digest)) == 20
    signed256 = sign_nfe_envi_xml(_request().signed_xml, material)
    signature256 = etree.fromstring(signed256).find(
        ".//{http://www.w3.org/2000/09/xmldsig#}Signature"
    )
    # The existing default remains distinct and cannot be mislabeled official NFe4.
    assert not etree.XMLSchema(etree.fromstring(official.content)).validate(signature256)


def test_unknown_signature_profile_is_rejected(material):
    from kordena_fiscal.domain import FiscalValidationError
    from kordena_fiscal.signing.nfe_xmldsig import sign_nfe_envi_xml
    with pytest.raises(FiscalValidationError, match="protocol profile"):
        sign_nfe_envi_xml(_request().signed_xml, material, profile="arbitrary")

@pytest.mark.parametrize("batch_code", ["103", "105"])
def test_in_progress_batch_never_authorizes_even_with_embedded_protocol(material, batch_code):
    request = _request()
    response = (
        '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
        f'<retEnviNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<cStat>{batch_code}</cStat><infRec><nRec>310000000000001</nRec></infRec>'
        '<protNFe><infProt><cStat>100</cStat><nProt>131000000000001</nProt></infProt>'
        '</protNFe></retEnviNFe></Body></Envelope>'
    ).encode()
    exchange = Mock(return_value=response)
    result = _gateway(Mock(return_value=material), exchange).authorize(request)
    assert result.status is AuthorizationStatus.PENDING
    assert result.provider_request_id == "310000000000001"
    assert result.protocol_reference is None
    exchange.assert_called_once()
