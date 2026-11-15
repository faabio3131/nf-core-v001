"""Santana substitution: exact XML order, original review and re-signing."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import santana_simpliss_events as events
from kordena_fiscal.gateway import santana_simpliss_substitution as subst
from kordena_fiscal.gateway.nfse_nacional_homologation import build_nfse_dps_request
from kordena_fiscal.gateway.santana_simpliss_homologation import SANTANA_IBGE
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator
from kordena_fiscal.xml.santana_simpliss_schema import santana_official_validator

_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_KEY = "35" + "1" * 48


def _request(city: str = SANTANA_IBGE) -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        "tenant-santana", "unit-santana", FiscalEnvironment.HOMOLOGATION,
        "test-correlation", "fm-nfcore",
    )
    city_jurisdiction = BrazilianJurisdiction("SP", city)
    now = datetime.now(UTC)
    profile = FiscalProfile(
        profile_id="santana-fixture", scope=scope, cnpj=Cnpj("11222333000181"),
        legal_name="Emissor Sintetico",
        tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="10", district="Centro",
            municipality_name="Santana de Parnaiba",
            jurisdiction=city_jurisdiction, postal_code="06501000",
        ),
        effective_from=now - timedelta(days=1),
    )
    line = NfseServiceLine(
        line_number=1, municipal_service_code="0107",
        national_taxation_code="010701",
        description="Servico sintetico fiscalmente revisado",
        gross_amount=Money(Decimal("100.00")),
        iss_amount=Money(Decimal("3.00")),
        iss_withheld=False,
    )
    document = NfseCanonicalDocument(
        document_id="santana-document-1", scope=scope,
        source=SourceReference("synthetic-test", "santana-service-1"),
        issued_at=now, competence_date=now.date(),
        issuer=profile, service_jurisdiction=city_jurisdiction,
        services=(line,), dps_number=1,
    )
    return NfseAuthorizationRequest.build(document)



def _review(*, code: str = "99", reason: str | None = "Retificacao revisada fiscalmente"):
    return subst.SantanaSubstitutionReview(
        original_document_id="santana-original-001",
        original_access_key=_KEY,
        reason_code=code, reason_description=reason,
        human_approval_reference="human-reviewed-001",
    )


@pytest.mark.parametrize("code", ["", "00", "06", "98", "1", "99a"])
def test_only_official_replacement_reason_codes_are_accepted(code: str) -> None:
    with pytest.raises(FiscalValidationError):
        _review(code=code)


def test_invalid_original_key_or_short_description_is_rejected() -> None:
    with pytest.raises(FiscalValidationError):
        subst.SantanaSubstitutionReview(
            original_document_id="source", original_access_key="35",
            reason_code="99", reason_description="correcao",
            human_approval_reference="approved-source",
        )
    with pytest.raises(FiscalValidationError):
        _review(reason="curto")


def test_substitution_requires_numbered_canonical_santana_request() -> None:
    with pytest.raises(FiscalValidationError, match="numbered"):
        subst.build_santana_signed_replacement_dps(
            Mock(), Mock(), review=_review(), verify_original=Mock(),
        )


def test_reviewed_dps_adds_subst_in_xsd_order_then_signs_final_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = etree.fromstring((
        f'<DPS xmlns="{_NS}" xmlns:ds="{_DS}">'
        '<infDPS Id="DPS-SYNTHETIC"><tpAmb>2</tpAmb>'
        '<cLocEmi>3547304</cLocEmi><prest><CNPJ>11222333000181</CNPJ></prest></infDPS>'
        '<ds:Signature/></DPS>'
    ).encode())
    info = root[0]
    validator = Mock()
    signed_final = b"synthetic-signed-replacement"
    signer = Mock(return_value=signed_final)
    parsed = Mock(side_effect=[info, info])
    monkeypatch.setattr(subst, "build_signed_dps", Mock(
        return_value=etree.tostring(root),
    ))
    monkeypatch.setattr(subst, "parse_signed_dps_info", parsed)
    monkeypatch.setattr(subst, "national_dps_validator", Mock(return_value=validator))
    monkeypatch.setattr(subst, "sign_nfse_dps_xml", signer)
    review = _review()
    original = Mock()
    request = _request()
    material = EphemeralCertificateMaterial(
        reference_id="santana-substitution-test",
        pkcs12_bytes=b"synthetic-not-a-real-certificate",
        password=b"synthetic-test-only",
    )
    result = subst.build_santana_signed_replacement_dps(
        request, material, review=review, verify_original=original,
    )
    assert result == signed_final
    original.assert_called_once_with(request, review)
    assert validator.validate_document.call_count == 1
    unsigned = etree.fromstring(validator.validate_document.call_args.args[0])
    descendants = list(unsigned.find("{" + _NS + "}infDPS"))
    tags = [etree.QName(child).localname for child in descendants]
    assert tags.index("cLocEmi") + 1 == tags.index("subst")
    replaced = unsigned.find(".//{" + _NS + "}subst")
    assert replaced is not None
    assert replaced.findtext("{" + _NS + "}chSubstda") == _KEY
    assert replaced.findtext("{" + _NS + "}cMotivo") == "99"
    assert unsigned.find("{" + _DS + "}Signature") is None
    signer.assert_called_once_with(
        validator.validate_document.call_args.args[0], material,
    )
    assert parsed.call_count == 2



def test_santana_real_signed_replacement_passes_official_xsd_101() -> None:
    """Build, re-sign and verify XSD 1.01 with an ephemeral synthetic test key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Santana")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pwd = b"synthetic-test-password"
    pfx = pkcs12.serialize_key_and_certificates(
        name=b"santana-test", key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(pwd),
    )
    material = EphemeralCertificateMaterial(
        reference_id="synthetic-santana-only", pkcs12_bytes=pfx, password=pwd,
    )
    request = _request()
    verified_source = Mock()
    signed = subst.build_santana_signed_replacement_dps(
        request, material, review=_review(), verify_original=verified_source,
    )
    verified_source.assert_called_once()
    root = etree.fromstring(signed)
    info = root.find("{" + _NS + "}infDPS")
    assert info is not None
    subst_node = info.find("{" + _NS + "}subst")
    assert subst_node is not None
    assert subst_node.findtext("{" + _NS + "}chSubstda") == _KEY
    assert subst_node.findtext("{" + _NS + "}cMotivo") == "99"
    assert len(root.findall("{" + _DS + "}Signature")) == 1
    national_dps_validator("1.01").validate_document(signed)
    santana_official_validator("dps").validate_document(signed)
    wrapped = build_nfse_dps_request(
        signed,
        issuer_cnpj="11222333000181",
        issuer_municipality_ibge="3547304",
    )
    assert b"dpsXmlGZipB64" in wrapped


def test_santana_real_101101_signed_event_passes_offline_xsd_and_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real RSA-SHA256 signature and pinned national XSD without network/A1 secrets."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Santana")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(private, hashes.SHA256())
    )
    password = b"synthetic-santana-test"
    material = EphemeralCertificateMaterial(
        reference_id="santana-only-synthetic-event-certificate",
        pkcs12_bytes=pkcs12.serialize_key_and_certificates(
            name=b"santana-ephemeral", key=private, cert=certificate, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(password),
        ),
        password=password,
    )
    # The production A1 issuer identity preflight remains mandatory. The fixture
    # certificate is deliberately NOT an ICP-Brasil A1 or a real taxpayer ID.
    preflight = Mock()
    monkeypatch.setattr(events, "validate_a1_for_issuer", preflight)
    intent = events.build_signed_santana_cancellation(
        request=_request(), key=_KEY, reason_code="1",
        reason_description="Correcao sintetica da emissao original",
        approval_reference="human-approval-santana-test",
        occurred_at=now, material=material,
    )
    preflight.assert_called_once()
    assert intent.invoice_reference == _KEY
    events.validate_santana_event_xml(intent.signed_event_xml, kind="request")
    root = etree.fromstring(intent.signed_event_xml)
    assert root.findtext(".//{" + _NS + "}chNFSe") == _KEY
    assert root.findtext(".//{" + _NS + "}cMotivo") == "1"
    assert len(root.findall("{" + _DS + "}Signature")) == 1
    invalid = intent.signed_event_xml.replace(
        b"Correcao sintetica", b"CorrecaO sintetica",
    )
    with pytest.raises(FiscalValidationError):
        events.validate_santana_event_xml(invalid, kind="request")
