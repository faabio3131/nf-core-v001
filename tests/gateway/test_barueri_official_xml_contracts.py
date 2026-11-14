"""Barueri: assert REAL transport bytes against unmodified municipal ZIP v1.

The adapter's exchange callback receives the same envelope as the HTTP boundary.
No real certificate, SOAP request or municipal NFS-e is transmitted.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.gateway import barueri_pmb004_homologation as barueri

_ZIP = (Path(__file__).resolve().parents[2] /
        "contracts/official/barueri/XML_RPS_Schemas_V01.zip")
_SHA256 = "3fb4b61f013e1c0a0d156913230643a2f4accb7486343854c7295c1a1dee9aa4"
_NS = "http://www.barueri.sp.gov.br/nfe"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_CASES = (
    ("NFeLoteEnviarArquivo", (
        ("InscricaoMunicipal", "1234567"),
        ("CPFCNPJContrib", "11222333000181"),
        ("NomeArquivoRPS", "20261113001.txt"),
        ("ApenasValidaArq", "false"),
        ("ArquivoRPSBase64", "UFBCTDAwNA=="),
    )),
    ("NFeLoteStatusArquivo", (
        ("InscricaoMunicipal", "1234567"),
        ("CPFCNPJContrib", "11222333000181"),
        ("ProtocoloRemessa", "PROTO123"),
    )),
    ("NFeLoteListarArquivos", (
        ("InscricaoMunicipal", "1234567"),
        ("CPFCNPJContrib", "11222333000181"),
        ("DataEnvioArq", "2026-11-13"),
        ("SituacaoArq", "1"),
    )),
    ("NFeLoteBaixarArquivo", (
        ("InscricaoMunicipal", "1234567"),
        ("CPFCNPJContrib", "11222333000181"),
        ("NomeArqRetorno", "return.txt"),
    )),
)


def _schema(method: str) -> etree.XMLSchema:
    payload = _ZIP.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == _SHA256
    with ZipFile(_ZIP) as archive:
        path = "XML_RPS_Schemas_V01/" + method + ".v1.xsd"
        content = archive.read(path)
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    return etree.XMLSchema(etree.fromstring(content, parser=parser))


def _inner(wire: bytes, method: str) -> etree._Element:
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    outer = etree.fromstring(wire, parser=parser)
    assert outer.tag == f"{{{_SOAP}}}Envelope"
    container = outer.find(f".//{{{_NS}}}{method}")
    assert container is not None
    assert container.findtext(f"{{{_NS}}}VersaoSchema") == "1"
    raw = container.findtext(f"{{{_NS}}}MensagemXML")
    assert raw
    return etree.fromstring(raw.encode("utf-8"), parser=parser)


@pytest.mark.parametrize("method,fields", _CASES)
def test_actual_exchange_payload_validates_official_schema(
    monkeypatch: pytest.MonkeyPatch, method: str, fields: tuple[tuple[str,str], ...],
) -> None:
    monkeypatch.setattr(barueri, "validate_a1_for_issuer", lambda *a, **kw: None)
    monkeypatch.setattr(barueri, "build_fiscal_tls_context", lambda cert: Mock())
    resolver = Mock()
    resolver.resolve_provider_id.return_value = barueri.BARUERI_PMB004_PROVIDER
    captured: list[tuple[bytes, str]] = []

    def exchange(wire: bytes, action: str, tls: object, timeout: float) -> bytes:
        captured.append((wire, action))
        return (
            f'<soap:Envelope xmlns:soap="{_SOAP}" xmlns:b="{_NS}">'
            f"<soap:Body><b:{method}Response><b:{method}Result>"
            "<b:ListaMensagemRetorno><b:Codigo>OK200</b:Codigo>"
            "</b:ListaMensagemRetorno>"
            f"</b:{method}Result></b:{method}Response></soap:Body></soap:Envelope>"
        ).encode("utf-8")

    adapter = barueri.BarueriPmb004HomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=Mock(return_value=Mock()),
        validate_pmb004=Mock(), exchange=exchange,
    )
    scope = ExecutionScope(host_namespace="nfcore", tenant_id="tenant-a",
                           unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
                           correlation_id="barueri-official-wire")
    adapter._send(scope=scope, cnpj=Cnpj("11222333000181"),
                  method=method, fields=fields,
                  operation="authorize" if method == "NFeLoteEnviarArquivo" else "query")
    assert len(captured) == 1
    wire, action = captured[0]
    assert action == f'"{_NS}/{method}"'
    real_inner = _inner(wire, method)
    _schema(method).assertValid(real_inner)
    assert real_inner.tag == f"{{{_NS}}}{method}"
    assert [(child.tag, child.text) for child in real_inner] == [
        (f"{{{_NS}}}{name}", value) for name, value in fields
    ]

    root_unqualified = etree.Element(method)
    for field_name, value in fields:
        etree.SubElement(root_unqualified, f"{{{_NS}}}{field_name}").text = value
    assert not _schema(method).validate(root_unqualified)

    field_unqualified = etree.fromstring(etree.tostring(real_inner))
    field_unqualified[0].tag = fields[0][0]
    assert not _schema(method).validate(field_unqualified)

    removed_field = etree.fromstring(etree.tostring(real_inner))
    removed_field.remove(removed_field[-1])
    assert not _schema(method).validate(removed_field)


def test_unsupported_soap_method_not_serialized() -> None:
    with pytest.raises(barueri.BarueriContractError, match="Unsupported"):
        barueri._build_soap("NFeLoteExcluirArquivo", ())
