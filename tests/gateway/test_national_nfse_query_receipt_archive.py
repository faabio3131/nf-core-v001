"""NFS-e National query returns official XML to the canonical archive boundary."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.nfse_national_homologation import OfficialNfseTransportError
from kordena_fiscal.gateway.nfse_national_query import _validate_official_nfse as _query_validate
from kordena_fiscal.gateway.nfse_national_receipt import NationalReceiptIdentity
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationResult
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.xml.nfse_national_profiles import NT009_RESTRICTED_PROFILE

_receipt_spec = importlib.util.spec_from_file_location(
    "national_receipt_fixture", Path(__file__).parents[1] / "support/national_receipt_fixture.py",
)
assert _receipt_spec and _receipt_spec.loader
_receipt_fixture = importlib.util.module_from_spec(_receipt_spec)
_receipt_spec.loader.exec_module(_receipt_fixture)

_KEY = "3550308" + "22" + "12345678000195" + "3" * 27
_NS = "http://www.sped.fazenda.gov.br/nfse"


def _validate_official_nfse(raw, key, **context):
    # Negative signature tests must fail for malformed XML, not absent context.
    context.setdefault(
        'expected', NationalReceiptIdentity.from_request(_receipt_fixture.sample()[0]),
    )
    context.setdefault('schema_profile', NT009_RESTRICTED_PROFILE)
    return _query_validate(raw, key, **context)


def _response(xml: bytes) -> bytes:
    return json.dumps(
        {"nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii")}
    ).encode()


def _receipt(key: str = _KEY) -> bytes:
    return _receipt_fixture.sample_receipt(key)[2]


def test_query_preserves_original_authorized_receipt_bytes() -> None:
    receipt = _receipt()
    assert _validate_official_nfse(
        _response(receipt), _KEY,
        expected=NationalReceiptIdentity.from_request(_receipt_fixture.sample()[0]),
        schema_profile=NT009_RESTRICTED_PROFILE,
    ) == receipt


def test_query_does_not_accept_an_unrelated_document_or_a_bare_key() -> None:
    with pytest.raises(OfficialNfseTransportError, match="different access key"):
        _validate_official_nfse(
            _response(_receipt("3550308" + "22" + "12345678000195" + "4" * 27)), _KEY,
        )
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



def test_query_rejects_resigned_receipt_with_same_identity_but_changed_fiscal_facts():
    from dataclasses import replace
    from decimal import Decimal

    from kordena_fiscal.domain import Money
    from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
    from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps

    request, material = _receipt_fixture.sample()
    original_dps = build_sefin_signed_dps(request, material)
    original_xml = _receipt_fixture.complete_receipt(original_dps, material, key=_KEY)
    expected = NationalReceiptIdentity.from_request(request)
    assert _validate_official_nfse(_response(original_xml), _KEY, expected=expected) == original_xml

    for changed in (
        replace(request.document.services[0], description="Outro servico sintetico"),
        replace(request.document.services[0], gross_amount=Money(Decimal("200.00"))),
    ):
        other = NfseAuthorizationRequest.build(replace(request.document, services=(changed,)))
        other_dps = build_sefin_signed_dps(other, material)
        other_xml = _receipt_fixture.complete_receipt(other_dps, material, key=_KEY)
        # Both signatures and XSD are valid, same CNPJ/series/number/key, but
        # this is not the canonical fiscal document prepared by the customer.
        with pytest.raises(OfficialNfseTransportError, match="differs from canonical DPS"):
            _validate_official_nfse(_response(other_xml), _KEY, expected=expected)

        from kordena_fiscal.gateway.nfse_national_homologation import (
            OfficialNfseTransportError as PostError,
        )
        from kordena_fiscal.gateway.nfse_national_homologation import (
            parse_nfse_homologation_response,
        )

        payload = json.loads(_response(other_xml))
        payload["chaveAcesso"] = _KEY
        with pytest.raises(PostError, match="XML retornado"):
            parse_nfse_homologation_response(
                json.dumps(payload).encode(), expected=expected,
                schema_profile=NT009_RESTRICTED_PROFILE,
            )
