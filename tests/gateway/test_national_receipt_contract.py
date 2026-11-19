"""National receipt XSD, canonical correlation and nested signature regressions."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from kordena_fiscal.gateway.nfse_national_receipt import (
    NationalReceiptIdentity,
    NfseReceiptVerificationError,
    validate_national_nfse_xml,
    validate_nfse_receipt_integrity,
    validate_official_nfse_receipt,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps, build_signed_dps
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.xml.nfse_national_profiles import (
    NT009_RESTRICTED_PROFILE,
    PRODUCTION_PROFILE,
    national_restricted_validator,
)

_spec = importlib.util.spec_from_file_location(
    'national_receipt_fixture', Path(__file__).parents[1] / 'support/national_receipt_fixture.py',
)
assert _spec and _spec.loader
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)
N = '{http://www.sped.fazenda.gov.br/nfse}'
D = '{http://www.w3.org/2000/09/xmldsig#}'


@pytest.fixture(scope='module')
def sample():
    request, material = fixture.sample()
    dps = build_sefin_signed_dps(request, material)
    xml = fixture.complete_receipt(dps, material)
    return request, material, xml, fixture.key_for(dps)


def response(xml, **extra):
    return json.dumps({
        'nfseXmlGZipB64': base64.b64encode(gzip.compress(xml)).decode(), **extra,
    }).encode()


def resign(root, material, *, inner=True):
    private, cert, _ = pkcs12.load_key_and_certificates(material.pkcs12_bytes, material.password)
    root.remove(root.find(D + 'Signature'))
    info = root.find(N + 'infNFSe')
    dps = info.find(N + 'DPS')
    if dps is not None and inner:
        signature = dps.find(D + 'Signature')
        if signature is not None:
            dps.remove(signature)
        append_nfse_signature(dps, dps[0], private, cert, legacy_abrasf=False)
    append_nfse_signature(root, info, private, cert, legacy_abrasf=False)
    return etree.tostring(root)


def validate(sample, xml):
    return validate_official_nfse_receipt(
        response(xml), sample[3], expected=NationalReceiptIdentity.from_request(sample[0]),
        schema_profile=NT009_RESTRICTED_PROFILE,
    )


def test_complete_receipt_with_signed_dps_preserves_exact_bytes(sample):
    assert validate(sample, sample[2]) == sample[2]


def test_dps_signature_is_optional_under_official_nfse_contract(sample):
    root = etree.fromstring(sample[2])
    dps = root.find(N + 'infNFSe/' + N + 'DPS')
    dps.remove(dps.find(D + 'Signature'))
    xml = resign(root, sample[1], inner=False)
    national_restricted_validator('NFSe_v1.01.xsd').validate_document(xml)
    assert validate(sample, xml) == xml


def test_valid_signature_cannot_authorize_empty_nfse(sample):
    root = etree.fromstring(sample[2])
    info = root.find(N + 'infNFSe')
    for node in list(info):
        info.remove(node)
    xml = resign(root, sample[1])
    # Separate integrity boundary retained for municipal contracts; not authorization.
    assert validate_nfse_receipt_integrity(response(xml), sample[3]) == xml
    with pytest.raises(NfseReceiptVerificationError, match='official XSD'):
        validate(sample, xml)


@pytest.mark.parametrize(('path', 'value'), [
    ('DPS/infDPS/serie', '17'), ('DPS/infDPS/nDPS', '567'),
    ('DPS/infDPS/cLocEmi', '3545209'), ('DPS/infDPS/prest/CNPJ', '11222333000181'),
    ('DPS/infDPS/tpAmb', '1'), ('emit/CNPJ', '11222333000181'),
    ('emit/enderNac/cMun', '3545209'), ('ambGer', '1'),
])
def test_signed_receipt_with_changed_identity_cannot_authorize(sample, path, value):
    root = etree.fromstring(sample[2])
    node = root.find(N + 'infNFSe/' + '/'.join(N + part for part in path.split('/')))
    node.text = value
    xml = resign(root, sample[1])
    national_restricted_validator('NFSe_v1.01.xsd').validate_document(xml)
    with pytest.raises(NfseReceiptVerificationError, match='identity|canonical DPS'):
        validate(sample, xml)


def test_other_valid_reserved_dps_is_not_the_original_request(sample):
    other = NfseAuthorizationRequest.build(replace(sample[0].document, dps_number=765))
    dps = build_sefin_signed_dps(other, sample[1])
    xml = fixture.complete_receipt(dps, sample[1], key=sample[3])
    with pytest.raises(NfseReceiptVerificationError, match='canonical DPS'):
        validate(sample, xml)


@pytest.mark.parametrize('field', ['DigestValue', 'SignatureValue'])
def test_outer_signature_does_not_hide_invalid_inner_signature(sample, field):
    root = etree.fromstring(sample[2])
    node = root.find(N + 'infNFSe/' + N + 'DPS/' + D + 'Signature')
    target = node.find('.//' + D + field)
    target.text = 'AAAA'
    xml = resign(root, sample[1], inner=False)
    with pytest.raises(NfseReceiptVerificationError, match='XMLDSig integrity'):
        validate(sample, xml)


def test_signature_outside_exact_dps_position_is_rejected(sample):
    root = etree.fromstring(sample[2])
    info = root.find(N + 'infNFSe')
    dps = info.find(N + 'DPS')
    info.append(dps.find(D + 'Signature'))
    with pytest.raises(NfseReceiptVerificationError, match='signature placement'):
        validate(sample, resign(root, sample[1], inner=False))


def test_duplicate_inner_id_is_rejected(sample):
    root = etree.fromstring(sample[2])
    info = root.find(N + 'infNFSe')
    info.find(N + 'emit').set('Id', info.find(N + 'DPS/' + N + 'infDPS').get('Id'))
    with pytest.raises(NfseReceiptVerificationError, match='signature placement'):
        validate(sample, resign(root, sample[1]))


def test_envelope_identity_cannot_override_signed_identity(sample):
    with pytest.raises(NfseReceiptVerificationError, match='envelope DPS mismatch'):
        validate_official_nfse_receipt(
            response(sample[2], idDps='another-dps'), sample[3],
            expected=NationalReceiptIdentity.from_request(sample[0]),
            schema_profile=NT009_RESTRICTED_PROFILE,
        )


def test_receipt_requires_explicit_context_and_supported_profile(sample):
    with pytest.raises(NfseReceiptVerificationError, match='explicit DPS and schema'):
        validate_official_nfse_receipt(response(sample[2]), sample[3])
    with pytest.raises(NfseReceiptVerificationError, match='schema profile unsupported'):
        validate_national_nfse_xml(
            sample[2], sample[3], expected=NationalReceiptIdentity.from_request(sample[0]),
            schema_profile='unsupported-profile',
        )


@pytest.mark.parametrize('different_dps', [False, True])
def test_get_correlates_receipt_without_any_post(sample, monkeypatch, different_dps):
    from kordena_fiscal.gateway import nfse_national_query as query
    from kordena_fiscal.gateway.authorization import AuthorizationStatus
    from kordena_fiscal.gateway.nfse_national_homologation import OfficialNfseTransportError

    scope = replace(sample[0].document.scope, host_namespace='synthetic-host')
    request = NfseAuthorizationRequest.build(replace(
        sample[0].document, scope=scope,
        issuer=replace(sample[0].document.issuer, scope=scope),
    ))
    receipt_request = NfseAuthorizationRequest.build(replace(
        request.document, dps_number=765 if different_dps else request.document.dps_number,
    ))
    dps = build_sefin_signed_dps(receipt_request, sample[1])
    xml = fixture.complete_receipt(dps, sample[1], key=sample[3])
    # This test isolates GET/correlation. A1 and TLS have separate integration tests.
    monkeypatch.setattr(query, 'validate_a1_for_issuer', Mock())
    monkeypatch.setattr(query, 'build_fiscal_tls_context', Mock())
    exchange = Mock(side_effect=[json.dumps({'chaveAcesso': sample[3]}).encode(), response(xml)])
    resolver = Mock()
    resolver.resolve_provider_id.return_value = 'nfse-nacional-producao-restrita'
    gateway = query.NfseNationalHomologationQueryGateway(
        provider_resolver=resolver, resolve_certificate=lambda *_: sample[1],
        exchange_get=exchange,
    )
    if different_dps:
        with pytest.raises(OfficialNfseTransportError, match='canonical DPS'):
            gateway.query(request)
    else:
        result = gateway.query(request)
        assert result.status is AuthorizationStatus.AUTHORIZED
        assert result.authorized_xml == xml
    assert exchange.call_count == 2
    assert '/dps/' in exchange.call_args_list[0].args[0]
    assert '/nfse/' in exchange.call_args_list[1].args[0]
    resolver.resolve_provider_id.assert_called_once()
    assert resolver.resolve_provider_id.call_args.kwargs['operation'] == 'query'


def test_low_level_transport_checks_dps_identity_before_exchange(sample, monkeypatch):
    from kordena_fiscal.gateway import nfse_national_homologation as transport

    dps = etree.fromstring(build_sefin_signed_dps(sample[0], sample[1]))
    dps[0].find(N + 'nDPS').text = '765'  # Legal shape, inconsistent with its Id.
    dps.remove(dps.find(D + 'Signature'))
    private, cert, _ = pkcs12.load_key_and_certificates(
        sample[1].pkcs12_bytes, sample[1].password,
    )
    append_nfse_signature(dps, dps[0], private, cert, legacy_abrasf=False)
    xml = etree.tostring(dps)
    national_restricted_validator('DPS_v1.01.xsd').validate_document(xml)
    tls = Mock()
    monkeypatch.setattr(transport, 'build_fiscal_tls_context', tls)
    exchange = Mock()
    gateway = transport.NfseNationalHomologationTransport(
        certificate=sample[1], exchange=exchange,
    )
    with pytest.raises(NfseReceiptVerificationError, match='canonical DPS receipt identity'):
        gateway.submit_signed_dps(xml)
    exchange.assert_not_called()
    tls.assert_not_called()


@pytest.mark.parametrize(('start', 'end', 'value'), [
    (0, 7, '3545209'), (7, 8, '1'), (8, 9, '1'), (9, 23, '11222333000181'),
])
def test_access_key_must_match_signed_issuer_and_generator(sample, start, end, value):
    key = sample[3][:start] + value + sample[3][end:]
    dps = build_sefin_signed_dps(sample[0], sample[1])
    xml = fixture.complete_receipt(dps, sample[1], key=key)
    with pytest.raises(NfseReceiptVerificationError, match='canonical DPS'):
        validate_national_nfse_xml(
            xml, key, expected=NationalReceiptIdentity.from_request(sample[0]),
            schema_profile=NT009_RESTRICTED_PROFILE,
        )


def test_february_receipt_uses_independent_pinned_types(sample):
    request, material = sample[:2]
    dps = build_signed_dps(request, material, schema_profile=PRODUCTION_PROFILE)
    key = fixture.key_for(dps)
    xml = fixture.complete_receipt(dps, material, schema_profile=PRODUCTION_PROFILE)
    expected = NationalReceiptIdentity.from_request(request, schema_profile=PRODUCTION_PROFILE)
    assert validate_national_nfse_xml(
        xml, key, expected=expected, schema_profile=PRODUCTION_PROFILE,
    ) == xml
    with pytest.raises(NfseReceiptVerificationError, match='official XSD'):
        validate_national_nfse_xml(
            xml, key, expected=expected, schema_profile=NT009_RESTRICTED_PROFILE,
        )


def test_nt009_receipt_cannot_use_february_types(sample):
    with pytest.raises(NfseReceiptVerificationError, match='official XSD'):
        validate_national_nfse_xml(
            sample[2], sample[3],
            expected=NationalReceiptIdentity.from_request(sample[0]),
            schema_profile=PRODUCTION_PROFILE,
        )
