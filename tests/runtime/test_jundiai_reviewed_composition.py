"""Jundiaí GissOnline operator/crypto gates independent of municipal credentials."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
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
