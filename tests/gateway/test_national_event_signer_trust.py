"""FIS-03: never accept SEFIN event signer solely for valid XMLDSig.

Fixtures are synthetic. No SEFIN request or ICP credential is used.
"""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from lxml import etree

from kordena_fiscal.gateway import nfse_nacional_event_homologation as event_gateway
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseEventError,
    _enforce_national_event_signer,
    require_national_event_signer_pins,
)

_ENV = "NFCORE_NFSE_EVENT_SIGNER_SHA256"
_DS = "http://www.w3.org/2000/09/xmldsig#"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_signer() -> tuple[etree._Element, str]:
    fixture = _module(
        Path(__file__).parents[1] / "support/national_receipt_fixture.py",
        "fis03_receipt_fixture",
    )
    _, material = fixture.sample()
    _, certificate, _ = pkcs12.load_key_and_certificates(
        material.pkcs12_bytes, material.password,
    )
    assert isinstance(certificate, x509.Certificate)
    root = etree.Element("{http://www.sped.fazenda.gov.br/nfse}evento")
    signature = etree.SubElement(root, f"{{{_DS}}}Signature")
    key = etree.SubElement(signature, f"{{{_DS}}}KeyInfo")
    data = etree.SubElement(key, f"{{{_DS}}}X509Data")
    etree.SubElement(data, f"{{{_DS}}}X509Certificate").text = (
        base64.b64encode(certificate.public_bytes(Encoding.DER)).decode("ascii")
    )
    return root, certificate.fingerprint(hashes.SHA256()).hex()


def test_live_event_pin_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(NationalNfseEventError, match="signer pins unavailable"):
        require_national_event_signer_pins()
    for invalid in ("", "f" * 63, "g" * 64, "a" * 64 + ",", "b" * 64 + "," + "B" * 64):
        monkeypatch.setenv(_ENV, invalid)
        with pytest.raises(NationalNfseEventError):
            require_national_event_signer_pins()
    monkeypatch.setenv(_ENV, "A" * 64)
    assert require_national_event_signer_pins() == frozenset({"a" * 64})


def test_unapproved_event_leaf_certificate_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, fingerprint = _synthetic_signer()
    monkeypatch.setenv(_ENV, "0" * 64 if fingerprint != "0" * 64 else "1" * 64)
    with pytest.raises(NationalNfseEventError, match="Untrusted official"):
        _enforce_national_event_signer(root)


def test_event_leaf_pin_does_not_replace_icp_chain_and_crl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, fingerprint = _synthetic_signer()
    monkeypatch.setenv(_ENV, fingerprint)
    for name in (
        "NFCORE_NFSE_RECEIPT_CA_BUNDLE",
        "NFCORE_NFSE_RECEIPT_CRL_BUNDLE",
        "NFCORE_NFSE_RECEIPT_ROOT_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(NationalNfseEventError, match="ICP chain or CRL untrusted"):
        _enforce_national_event_signer(root)


@pytest.mark.parametrize("method", ["cancel", "query_cancellation"])
def test_real_event_post_and_get_preflight_trust_before_certificate(
    monkeypatch: pytest.MonkeyPatch, method: str,
) -> None:
    existing = _module(
        Path(__file__).parent / "test_nfse_nacional_event_homologation.py",
        "fis03_existing_event_fixture",
    )
    monkeypatch.delenv(_ENV, raising=False)
    exchange = Mock()
    exchange_get = Mock()
    transport, _, certificate, _, _, _, _ = existing._transport(
        exchange, exchange_get=exchange_get,
    )
    # Model the default live boundaries with mocks; no actual external I/O.
    monkeypatch.setattr(event_gateway, "_LIVE_EVENT_POST", exchange)
    monkeypatch.setattr(event_gateway, "_LIVE_EVENT_GET", exchange_get)
    with pytest.raises(NationalNfseEventError, match="signer pins unavailable"):
        getattr(transport, method)(existing._intent())
    certificate.assert_not_called()
    exchange.assert_not_called()
    exchange_get.assert_not_called()
