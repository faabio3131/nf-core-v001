"""Jundiaí GissOnline operator/crypto gates independent of municipal credentials."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID
from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.jundiai_giss_homologation import JundiaiGissHomologationTransport
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.runtime.jundiai_environment import (
    JundiaiReviewedStartup,
    _pinned_file,
    _verify_signature,
    build_jundiai_port_builder_from_environ,
)
from kordena_fiscal.runtime.jundiai_operational_composition import JundiaiTrustedRuntimePorts
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet


def _certificate() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Giss offline test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def test_id_bound_a1_signature_validates_without_a_municipal_webservice() -> None:
    key, certificate = _certificate()
    root = etree.Element("{urn:test}EnviarLoteRpsEnvio", nsmap={"g": "urn:test"})
    info = etree.SubElement(root, "{urn:test}InfDeclaracaoPrestacaoServico", Id="RPS42")
    etree.SubElement(info, "{urn:test}ValorServicos").text = "100.00"
    append_nfse_signature(root, info, key, certificate, legacy_abrasf=True)
    xml = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    _verify_signature(xml, certificate=certificate, count=1)
    with pytest.raises(FiscalValidationError, match="digest"):
        _verify_signature(
            xml.replace(b"100.00", b"900.00"),
            certificate=certificate, count=1,
        )


def test_giss_two_node_original_and_lot_signatures_are_checked() -> None:
    key, certificate = _certificate()
    root = etree.Element("{urn:test}EnviarLoteRpsEnvio", nsmap={"g": "urn:test"})
    lot = etree.SubElement(root, "{urn:test}LoteRps", Id="Lote42")
    rps = etree.SubElement(lot, "{urn:test}Rps")
    info = etree.SubElement(
        rps, "{urn:test}InfDeclaracaoPrestacaoServico", Id="RPS42",
    )
    etree.SubElement(info, "{urn:test}ValorServicos").text = "100.00"
    append_nfse_signature(rps, info, key, certificate, legacy_abrasf=True)
    append_nfse_signature(root, lot, key, certificate, legacy_abrasf=True)
    xml = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    _verify_signature(xml, certificate=certificate, count=2)


def test_manifest_wont_approve_wrong_wdsl_digest_or_path(tmp_path) -> None:
    file = tmp_path / "nfse.wsdl"
    file.write_bytes(b"<definitions/>")
    correct = hashlib.sha256(file.read_bytes()).hexdigest()
    assert _pinned_file(tmp_path, file.name, correct) == b"<definitions/>"
    with pytest.raises(RuntimeConfigurationError, match="SHA"):
        _pinned_file(tmp_path, file.name, "f" * 64)
    with pytest.raises(RuntimeConfigurationError, match="Unsafe"):
        _pinned_file(tmp_path, "../nfse.wsdl", correct)


def test_missing_reviewed_contract_and_a1_are_rejected(tmp_path) -> None:
    with pytest.raises(RuntimeConfigurationError, match="absolute reviewed manifest"):
        JundiaiReviewedStartup.load(str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeConfigurationError, match="canonical A1 vault"):
        build_jundiai_port_builder_from_environ(
            {"NFCORE_JUNDIAI_GISS_CONFIG_PATH": str(tmp_path / "missing.json")},
            vault=None,
        )
    assert build_jundiai_port_builder_from_environ({}, vault=None) is None


def test_reviewed_adapter_attaches_only_canonical_fiscal_original_rps() -> None:
    transport = Mock(spec=JundiaiGissHomologationTransport)
    check = Mock()
    runtime = JundiaiTrustedRuntimePorts(
        transport=transport, build_signed_operation=check,
        verify_signed_rps_identity=check, fiscal_issuer_policy=check,
        validate_prepared_rps=check, verify_official_invoice_xml=check,
    )
    app = Mock(spec=FiscalApplicationService)
    ports = runtime.attach(app)
    assert ports.load_original_rps == app.load_sp4_original_rps
    assert ports.verify_official_invoice_xml == check
    assert callable(ports.submit_official_rps)
    assert callable(ports.query_official_rps)


@pytest.mark.parametrize("municipality", ["3525904", "3518800"])
def test_reviewed_startup_compiles_shared_official_schemas_and_binds_city(
    tmp_path, municipality,
) -> None:
    """Official XSD bytes, synthetic WSDL/certificate; no external homologation."""
    folder = Path(__file__).resolve().parents[2] / (
        "contracts/official/jundiai/giss_v2_04/xsd/Schemas_XSD-Servicos_Prestados"
    )
    resources = []
    for source in sorted(folder.glob("*.xsd")):
        raw = source.read_bytes()
        (tmp_path / source.name).write_bytes(raw)
        resources.append(SchemaResource.from_bytes(source.name, raw))
    assert len(resources) == 24
    roots = {
        "RecepcionarLoteRps": "enviar-lote-rps-envio-v2_04.xsd",
        "ConsultarLoteRps": "consultar-lote-rps-envio-v2_04.xsd",
        "ConsultarNfsePorRps": "consultar-nfse-rps-envio-v2_04.xsd",
        "CancelarNfse": "cancelar-nfse-envio-v2_04.xsd",
        "ConsultarNfseRpsResposta": "consultar-nfse-rps-resposta-v2_04.xsd",
        "CancelarNfseResposta": "cancelar-nfse-reposta-v2_04.xsd",
    }
    actions = {name: "https://example.invalid/" + name for name in list(roots)[:4]}
    wsdl = (
        '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:s="http://schemas.xmlsoap.org/wsdl/soap/" '
        'targetNamespace="https://example.invalid/giss"><binding>'
        + "".join(
            f'<operation name="{name}"><s:operation soapAction="{action}"/></operation>'
            for name, action in actions.items()
        ) + '</binding></definitions>'
    ).encode()
    (tmp_path / "contract.wsdl").write_bytes(wsdl)
    _, certificate = _certificate()
    pem = certificate.public_bytes(Encoding.PEM)
    (tmp_path / "municipal.pem").write_bytes(pem)
    policy = {
        "tenant_id": "tenant", "unit_id": "unit", "issuer_cnpj": "11222333000181",
        "profile_id": "issuer", "profile_version": 1, "tax_regime": 3,
        "municipal_registration": "1234567", "canonical_service_code": "010701",
        "item_lista_servico": "01.07", "municipal_taxation_code": "0107",
        "iss_exigibility": "1", "incidence_ibge": municipality, "iss_rate": "0.02",
        "issuer_special_regime": "0", "optante_simples": "2", "fiscal_incentive": "2",
        "national_service_code": None, "rtc": None,
    }
    spec = {
        "municipality_ibge": municipality, "mode": "reviewed-homologation",
        "wsdl_file": "contract.wsdl", "wsdl_sha256": hashlib.sha256(wsdl).hexdigest(),
        "xsd_resources": {r.name: r.sha256 for r in resources},
        "xsd_package_sha256": SchemaSet(
            version="test", root_schema=roots["CancelarNfse"],
            resources=tuple(resources), source_uri="https://example.invalid",
        ).package_sha256,
        "xsd_roots": roots, "service_namespace": "https://example.invalid/giss",
        "method_actions": actions, "municipal_signer_pem": "municipal.pem",
        "municipal_signer_sha256": hashlib.sha256(pem).hexdigest(),
        "signature_profile": "rsa-sha1-abrasf-2.04", "issuers": [policy],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(spec))
    startup = JundiaiReviewedStartup.load(str(manifest), municipality_ibge=municipality)
    assert startup.municipality_ibge == municipality
    assert startup.issuers[0].municipality_ibge == municipality
    assert set(startup.validators) == set(roots)
    other_city = "3518800" if municipality == "3525904" else "3525904"
    with pytest.raises(RuntimeConfigurationError, match="municipality"):
        JundiaiReviewedStartup.load(str(manifest), municipality_ibge=other_city)
    policy["incidence_ibge"] = other_city
    manifest.write_text(json.dumps(spec))
    with pytest.raises(RuntimeConfigurationError, match="fiscal policy"):
        JundiaiReviewedStartup.load(str(manifest), municipality_ibge=municipality)


def test_guarulhos_startup_requires_explicit_city_and_canonical_vault(tmp_path) -> None:
    from kordena_fiscal.runtime.guarulhos_giss_operational_composition import (
        build_guarulhos_port_builder_from_environ,
    )

    assert build_guarulhos_port_builder_from_environ({}, vault=None) is None
    with pytest.raises(RuntimeConfigurationError, match="canonical A1 vault"):
        build_guarulhos_port_builder_from_environ(
            {"NFCORE_GUARULHOS_GISS_CONFIG_PATH": str(tmp_path / "missing.json")},
            vault=None,
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{}')
    with pytest.raises(RuntimeConfigurationError, match="municipality"):
        JundiaiReviewedStartup.load(str(manifest), municipality_ibge="3518800")
