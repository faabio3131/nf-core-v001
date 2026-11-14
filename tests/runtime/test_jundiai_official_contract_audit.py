"""Contract inventory tests: full XSD closure, WSDL methods and immutable hashes."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.verify_jundiai_giss_official_contracts import (
    _EXPECTED,
    ContractAuditError,
    _schema_resources,
    _wsdl_bindings,
    audit,
)

_XS = "http://www.w3.org/2001/XMLSchema"
_NS = "http://www.giss.com.br/"


def _fake_wsdl() -> bytes:
    binding = "".join(
        f'<wsdl:operation name="{op}">'
        f'<soap:operation soapAction="http://giss.test/{op}" />'
        "</wsdl:operation>"
        for op in sorted(set(_EXPECTED) - {
            "ConsultarNfseRpsResposta", "CancelarNfseResposta",
        })
    )
    return (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" '
        'targetNamespace="http://nfse.abrasf.org.br">'
        '<wsdl:binding name="GissService">'
        '<soap:binding style="document" '
        'transport="http://schemas.xmlsoap.org/soap/http" />'
        f"{binding}</wsdl:binding></wsdl:definitions>"
    ).encode()


def _fake_xsd_dir(path: Path) -> Path:
    path.mkdir()
    (path / "tipos-v2_04.xsd").write_text(
        f'<xs:schema xmlns:xs="{_XS}" targetNamespace="{_NS}tipos-v2_04.xsd">'
        '<xs:element name="Aux" type="xs:string" /></xs:schema>',
        encoding="utf-8",
    )
    for name, (root, namespace_suffix) in _EXPECTED.items():
        del name
        (path / namespace_suffix).write_text(
            f'<xs:schema xmlns:xs="{_XS}" '
            f'targetNamespace="{_NS}{namespace_suffix}" '
            'elementFormDefault="qualified">'
            f'<xs:import namespace="{_NS}tipos-v2_04.xsd" '
            'schemaLocation="tipos-v2_04.xsd" />'
            f'<xs:element name="{root}" type="xs:string" />'
            '</xs:schema>',
            encoding="utf-8",
        )
    return path


def test_official_contract_inventory_compiles_every_giss_xsd_root(tmp_path: Path) -> None:
    folder = _fake_xsd_dir(tmp_path / "schemas")
    resources, roots = _schema_resources(folder)
    assert set(roots) == set(_EXPECTED)
    assert len(resources) == 7
    assert all(len(item.sha256) == 64 for item in resources)


def test_unverified_or_incomplete_xsd_distribution_fails_closed(tmp_path: Path) -> None:
    folder = _fake_xsd_dir(tmp_path / "schemas")
    (folder / "tipos-v2_04.xsd").unlink()
    with pytest.raises(ContractAuditError, match="tipos-v2_04"):
        _schema_resources(folder)


def test_external_dependency_cannot_be_fetched_during_xsd_validation(tmp_path: Path) -> None:
    folder = _fake_xsd_dir(tmp_path / "schemas")
    file = folder / "cancelar-nfse-envio-v2_04.xsd"
    file.write_text(
        file.read_text(encoding="utf-8").replace(
            'schemaLocation="tipos-v2_04.xsd"',
            'schemaLocation="https://untrusted.test/tipos-v2_04.xsd"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractAuditError, match="Unresolved/remote"):
        _schema_resources(folder)


def test_missing_official_wsdl_method_not_equivalent_to_success() -> None:
    valid = _fake_wsdl()
    namespace, actions = _wsdl_bindings(valid)
    assert namespace == "http://nfse.abrasf.org.br"
    assert len(actions) == 4
    with pytest.raises(ContractAuditError, match="methods missing"):
        _wsdl_bindings(valid.replace(b"RecepcionarLoteRps", b"OtherMethod"))


def test_inventory_does_not_claim_provenance_or_homologation(tmp_path: Path) -> None:
    folder = _fake_xsd_dir(tmp_path / "schemas")
    wsdl = tmp_path / "nfse.wsdl"
    wsdl.write_bytes(_fake_wsdl())
    package = tmp_path / "Schemas_XSD-Servicos_Prestados.rar"
    package.write_bytes(b"offline synthetic package for test only")
    report = audit(wsdl, folder, package)
    assert report["source_authenticity"] == "requires_independent_review"
    assert report["municipal_homologation"] == "not_claimed"
    assert report["wsdl_sha256"] == hashlib.sha256(wsdl.read_bytes()).hexdigest()
    assert report["source_rar_sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    assert report["xsd_package_sha256"]
    assert report["all_operation_xsd_compilation"] == "passed"
