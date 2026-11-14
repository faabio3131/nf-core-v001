"""NFS-e National query returns official XML to the canonical archive boundary."""
from __future__ import annotations

import base64
import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.nfse_national_homologation import OfficialNfseTransportError
from kordena_fiscal.gateway.nfse_national_query import _validate_official_nfse
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationResult
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature

_KEY = "35" + "0" * 48
_NS = "http://www.sped.fazenda.gov.br/nfse"


def _response(xml: bytes) -> bytes:
    return json.dumps(
        {"nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii")}
    ).encode()


def _receipt(key: str = _KEY) -> bytes:
    """Synthetic cryptographic receipt, not an official SEFIN or ICP proof."""
    signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic issuer only")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(signer.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .sign(signer, hashes.SHA256())
    )
    root = etree.Element(f"{{{_NS}}}NFSe", nsmap={None: _NS}, versao="1.01")
    info = etree.SubElement(root, f"{{{_NS}}}infNFSe")
    info.set("Id", "NFS" + key)
    append_nfse_signature(root, info, signer, cert, legacy_abrasf=False)
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def test_query_preserves_original_authorized_receipt_bytes() -> None:
    receipt = _receipt()
    assert _validate_official_nfse(_response(receipt), _KEY) == receipt


def test_query_does_not_accept_an_unrelated_document_or_a_bare_key() -> None:
    with pytest.raises(OfficialNfseTransportError, match="different access key"):
        _validate_official_nfse(_response(_receipt("99" + "0" * 48)), _KEY)
    with pytest.raises(OfficialNfseTransportError):
        _validate_official_nfse(json.dumps({"chaveAcesso": _KEY}).encode(), _KEY)


def _result(
    status: AuthorizationStatus,
    xml: bytes | None,
) -> NfseAuthorizationResult:
    return NfseAuthorizationResult(
        status=status,
        scope=ExecutionScope(
            tenant_id="test-tenant", unit_id="test-unit",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="test-nfse-receipt", host_namespace="test-host",
        ),
        document_id="test-document",
        idempotency_key=IdempotencyKey("c" * 64),
        request_fingerprint="d" * 64,
        provider=GatewayProviderMetadata("synthetic-nfse", "1"),
        invoice_reference=_KEY if status is AuthorizationStatus.AUTHORIZED else None,
        authorized_xml=xml,
        rejection_code="REJECTED" if status is AuthorizationStatus.REJECTED else None,
        rejection_message="synthetic rejection" if status is AuthorizationStatus.REJECTED else None,
    )


def test_authorization_contract_carries_bounded_official_xml_only_when_authorized() -> None:
    payload = _receipt()
    assert _result(AuthorizationStatus.AUTHORIZED, payload).authorized_xml == payload
    with pytest.raises(FiscalValidationError, match="cannot contain invoice metadata"):
        _result(AuthorizationStatus.PENDING, payload)
    with pytest.raises(FiscalValidationError, match="cannot contain invoice metadata"):
        _result(AuthorizationStatus.REJECTED, payload)
    with pytest.raises(FiscalValidationError, match="Invalid authorized NFS-e XML evidence"):
        _result(AuthorizationStatus.AUTHORIZED, b"x" * (2 * 1024 * 1024 + 1))


def test_query_rejects_unsigned_receipt_even_when_access_key_matches() -> None:
    bare = f'<NFSe xmlns="{_NS}" versao="1.01"><infNFSe Id="NFS{_KEY}"/></NFSe>'
    with pytest.raises(OfficialNfseTransportError, match="signature placement"):
        _validate_official_nfse(_response(bare.encode()), _KEY)


@pytest.mark.parametrize("mutation", ["payload", "reference", "signature", "version"])
def test_query_rejects_tampered_national_receipt(mutation: str) -> None:
    root = etree.fromstring(_receipt())
    ds = "http://www.w3.org/2000/09/xmldsig#"
    if mutation == "payload":
        root.find(f"{{{_NS}}}infNFSe").set("modified", "yes")
    elif mutation == "reference":
        root.find(f".//{{{ds}}}Reference").set("URI", "#NFS" + "0" * 50)
    elif mutation == "signature":
        signature = root.find(f".//{{{ds}}}SignatureValue")
        signature.text = "AA==" + (signature.text or "")
    else:
        root.set("versao", "1.00")
    with pytest.raises(OfficialNfseTransportError):
        _validate_official_nfse(_response(etree.tostring(root)), _KEY)


def test_query_rejects_duplicated_signed_info_id() -> None:
    root = etree.fromstring(_receipt())
    info = root.find(f"{{{_NS}}}infNFSe")
    extra = etree.SubElement(info, f"{{{_NS}}}untrusted", Id="NFS" + _KEY)
    extra.text = "duplicate-reference"
    with pytest.raises(OfficialNfseTransportError, match="signature placement"):
        _validate_official_nfse(_response(etree.tostring(root)), _KEY)
