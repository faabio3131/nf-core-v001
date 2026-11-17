"""FIS-03 live signer-pin gate: synthetic certificates are never operational trust."""

from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12

from kordena_fiscal.gateway.nfse_national_receipt import (
    NationalReceiptIdentity,
    NfseReceiptVerificationError,
    require_national_receipt_signer_pins,
    validate_official_nfse_receipt,
)
from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps
from kordena_fiscal.xml.nfse_national_profiles import NT009_RESTRICTED_PROFILE

_spec = importlib.util.spec_from_file_location(
    "nfse_receipt_synthetic_fixture", Path(__file__).parents[1] / "support/national_receipt_fixture.py",
)
assert _spec and _spec.loader
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
_ENV = "NFCORE_NFSE_RECEIPT_SIGNER_SHA256"


@pytest.fixture(scope="module")
def receipt() -> tuple[object, object, bytes, bytes, str, str]:
    request, material = _fixture.sample()
    dps = build_sefin_signed_dps(request, material)
    xml = _fixture.complete_receipt(dps, material)
    _, cert, _ = pkcs12.load_key_and_certificates(
        material.pkcs12_bytes, material.password,
    )
    assert cert is not None
    pin = cert.fingerprint(hashes.SHA256()).hex()
    return request, material, dps, xml, _fixture.key_for(dps), pin


def _envelope(xml: bytes) -> bytes:
    return json.dumps({
        "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii"),
    }).encode("utf-8")


def test_configured_exact_leaf_pin_accepts_crypto_valid_synthetic_fixture(
    receipt: tuple[object, object, bytes, bytes, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _, _, xml, key, pin = receipt
    monkeypatch.setenv(_ENV, pin.upper())
    assert require_national_receipt_signer_pins() == frozenset({pin})
    assert validate_official_nfse_receipt(
        _envelope(xml), key, expected=NationalReceiptIdentity.from_request(request),
        schema_profile=NT009_RESTRICTED_PROFILE,
    ) == xml


def test_other_valid_xml_certificate_fails_when_not_in_operator_pins(
    receipt: tuple[object, object, bytes, bytes, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _, _, xml, key, _ = receipt
    monkeypatch.setenv(_ENV, "0" * 64)
    with pytest.raises(NfseReceiptVerificationError, match="Untrusted.*signer"):
        validate_official_nfse_receipt(
            _envelope(xml), key, expected=NationalReceiptIdentity.from_request(request),
            schema_profile=NT009_RESTRICTED_PROFILE,
        )


@pytest.mark.parametrize("value", [
    "", "0" * 63, "g" * 64, "0" * 64 + ",", "0" * 64 + "," + "0" * 64,
    "0" * 64 + ", " + "1" * 64, "0" * 64 + "," + "1" * 64 + ",",
])
def test_malformed_operator_pins_fail_closed(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, value)
    with pytest.raises(NfseReceiptVerificationError, match="signer trust pins"):
        require_national_receipt_signer_pins()


def test_live_low_level_post_refuses_without_pins_before_tls(
    receipt: tuple[object, object, bytes, bytes, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kordena_fiscal.gateway import nfse_national_homologation as transport

    _, material, dps, _, _, _ = receipt
    monkeypatch.delenv(_ENV, raising=False)
    tls = Mock()
    monkeypatch.setattr(transport, "build_fiscal_tls_context", tls)
    gateway = transport.NfseNationalHomologationTransport(certificate=material)
    with pytest.raises(NfseReceiptVerificationError, match="signer trust pins unavailable"):
        gateway.submit_signed_dps(dps)
    tls.assert_not_called()


def test_live_canonical_post_refuses_without_pins_before_tls(
    receipt: tuple[object, object, bytes, bytes, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kordena_fiscal.gateway import nfse_nacional_homologation as transport

    request, material, dps, _, _, _ = receipt
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.setattr(transport, "validate_a1_for_issuer", Mock())
    monkeypatch.setattr(transport, "require_mg_national_channel_eligibility", Mock())
    tls = Mock()
    monkeypatch.setattr(transport, "build_fiscal_tls_context", tls)
    gateway = transport.NfseNacionalHomologationGateway(
        resolve_certificate=lambda *_: material,
        build_signed_dps=lambda *_: dps,
    )
    with pytest.raises(NfseReceiptVerificationError, match="signer trust pins unavailable"):
        gateway.authorize(request)
    tls.assert_not_called()


def test_live_canonical_get_refuses_without_pins_before_a1(
    receipt: tuple[object, object, bytes, bytes, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kordena_fiscal.gateway import nfse_national_query as query
    from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

    request, material, _, _, _, _ = receipt
    scope = replace(request.document.scope, host_namespace="synthetic-pins-host")
    request = NfseAuthorizationRequest.build(replace(
        request.document, scope=scope,
        issuer=replace(request.document.issuer, scope=scope),
    ))
    monkeypatch.delenv(_ENV, raising=False)
    resolver = Mock()
    resolver.resolve_provider_id.return_value = "nfse-nacional-producao-restrita"
    resolve_cert = Mock(return_value=material)
    gateway = query.NfseNationalHomologationQueryGateway(
        provider_resolver=resolver,
        resolve_certificate=resolve_cert,
    )
    with pytest.raises(NfseReceiptVerificationError, match="signer trust pins unavailable"):
        gateway.query(request)
    resolve_cert.assert_not_called()
