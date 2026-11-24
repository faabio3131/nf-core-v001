"""Pinned WCF v2.1 SOAP 1.1 operations are never guessed from a browser."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kordena_fiscal.runtime.osasco_wsdl_contract import (
    OsascoWsdlIntegrityError,
    load_osasco_pinned_wsdl,
)


def _wsdl() -> bytes:
    return b'''<?xml version="1.0" encoding="utf-8"?>
    <wsdl:definitions
        xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
        xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
        targetNamespace="http://tempuri.org/">
      <wsdl:binding name="BasicHttpBinding_Test" type="tns:INotaFiscalEletronica">
        <soap:binding transport="http://schemas.xmlsoap.org/soap/http"
                      style="document"/>
        <wsdl:operation name="RTC_EmitirNFE">
          <soap:operation soapAction="http://tempuri.org/INotaFiscalEletronica/RTC_EmitirNFE"/>
        </wsdl:operation>
        <wsdl:operation name="ConsultarNotaCompleta">
          <soap:operation
              soapAction="http://tempuri.org/INotaFiscalEletronica/ConsultarNotaCompleta"/>
        </wsdl:operation>
        <wsdl:operation name="Cancelar">
          <soap:operation soapAction="http://tempuri.org/INotaFiscalEletronica/Cancelar"/>
        </wsdl:operation>
      </wsdl:binding>
    </wsdl:definitions>'''


def _load(xml: bytes):
    return load_osasco_pinned_wsdl(
        document=xml,
        expected_sha256=hashlib.sha256(xml).hexdigest(),
        binding_name="BasicHttpBinding_Test",
    )


def test_pinned_osasco_wsdl_resolves_exact_contract_without_network() -> None:
    c = _load(_wsdl())
    assert set(c.operations) == {"RTC_EmitirNFE", "ConsultarNotaCompleta", "Cancelar"}
    assert c.contract_for_method("Cancelar").action.endswith("/Cancelar")
    assert c.contract_for_method("RTC_EmitirNFE").wsdl_sha256 == c.sha256
    with pytest.raises(TypeError):
        c.operations["Otro"] = c.contract_for_method("Cancelar")  # type: ignore[index]


def test_wsdl_binding_hash_and_method_are_mandatory() -> None:
    xml = _wsdl()
    with pytest.raises(OsascoWsdlIntegrityError, match="hash"):
        load_osasco_pinned_wsdl(
            document=xml, expected_sha256="a" * 64,
            binding_name="BasicHttpBinding_Test",
        )
    with pytest.raises(OsascoWsdlIntegrityError, match="binding"):
        load_osasco_pinned_wsdl(
            document=xml, expected_sha256=hashlib.sha256(xml).hexdigest(),
            binding_name="Unrelated",
        )
    with pytest.raises(OsascoWsdlIntegrityError, match="operation"):
        _load(xml.replace(b'<wsdl:operation name="Cancelar">', b'<wsdl:operation name="Other">'))


def test_wsdl_disallows_duplicate_soap_action_and_unapproved_protocol() -> None:
    xml = _wsdl()
    double = xml.replace(
        b'<wsdl:operation name="Cancelar">',
        b'<wsdl:operation name="Cancelar"><soap:operation soapAction="http://tempuri.org/dup"/>'
        b'</wsdl:operation><wsdl:operation name="Cancelar">',
    )
    with pytest.raises(OsascoWsdlIntegrityError, match="Duplicate"):
        _load(double)
    bad = xml.replace(
        b"http://schemas.xmlsoap.org/soap/http",
        b"http://invalid.example/wsdl/not-soap",
    )
    with pytest.raises(OsascoWsdlIntegrityError, match="SOAP 1.1"):
        _load(bad)
    no_action = xml.replace(
        b"http://tempuri.org/INotaFiscalEletronica/Cancelar",
        b"http://untrusted.example/Cancel",
    )
    with pytest.raises(OsascoWsdlIntegrityError, match="SOAPAction"):
        _load(no_action)


def test_wsdl_rejects_dtd_and_xml_entity_aliasing() -> None:
    xml = _wsdl().replace(
        b'<wsdl:definitions',
        b'<!DOCTYPE wsdl:definitions [<!ENTITY exploit SYSTEM "file:///etc/passwd">]>'
        b'<wsdl:definitions',
    )
    with pytest.raises(OsascoWsdlIntegrityError, match="DTD"):
        _load(xml)



def test_osasco_official_2026_single_wsdl_sha_and_soap_actions_are_exact() -> None:
    """Source bytes fetched by GET from Prefeitura; no synthetic interface name."""
    root = (
        Path(__file__).resolve().parents[2]
        / "contracts/official/osasco/homologation"
    )
    raw = (root / "NotaFiscalEletronica.singleWsdl.xml").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == (
        "0e6798bbe317e690d0795cdfac876225961686d8a77cccbbf92c9aab6b50b22c"
    )
    contract = load_osasco_pinned_wsdl(
        document=raw, expected_sha256=digest,
        binding_name="BasicHttpBinding_INotaFiscalEletronicaServico",
    )
    assert set(contract.operations) == {
        "RTC_EmitirNFE", "ConsultarNotaCompleta", "Cancelar",
    }
    for name, method in contract.operations.items():
        assert method.action == (
            "http://tempuri.org/INotaFiscalEletronicaServico/" + name
        )
        assert method.wsdl_sha256 == digest
