"""End-to-end wiring of the real DPS builder and Sentinela preaudit gate.

Unlike ``tests/runtime/test_nfv1_nfse_preparation_recovery.py`` (which proves
``_GovernedNationalNfseGateway`` enforces binding/preaudit ordering using
mocks), this test wires the *real* ``build_signed_dps`` and ``nfse_preaudit``
functions -- the ones ``runtime/api.py`` now passes instead of ``None`` --
through a real ``NfseNacionalHomologationGateway`` (network call replaced by
a fake, in-memory ``exchange``) to prove the full chain authorizes a
synthetic document end to end, and that the preaudit gate still blocks
before any certificate/XML work happens.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

from kordena_fiscal.compliance.nfse_preaudit import NfsePreauditRejection, nfse_preaudit
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
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    NfseNacionalHomologationGateway,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.runtime.canonical_fiscal_composition import _GovernedNationalNfseGateway
from kordena_fiscal.vault import EphemeralCertificateMaterial

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_ISSUER_CNPJ = Cnpj("11222333000181")
_PASSWORD = b"synthetic-only-password"


def _pfx() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic A1 entity")])
    encoded = _ISSUER_CNPJ.value.encode("ascii")
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_NOW - timedelta(days=1)).not_valid_after(_NOW + timedelta(days=30))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"),
                               bytes([0x04, len(encoded)]) + encoded)
            ]), critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"test-a1", key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(_PASSWORD),
    )


def _certificate() -> EphemeralCertificateMaterial:
    return EphemeralCertificateMaterial(
        reference_id="ref:nfse-wiring-test", pkcs12_bytes=_pfx(), password=_PASSWORD,
    )


def _scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="corr-wiring-1",
        host_namespace="host-a",
    )


def _request(**service_overrides) -> NfseAuthorizationRequest:
    scope = _scope()
    issuer = FiscalProfile(
        profile_id="issuer-wiring-1",
        scope=scope,
        cnpj=_ISSUER_CNPJ,
        legal_name="Empresa Sintetica de Servicos Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="100", district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    service_fields = dict(
        line_number=1, municipal_service_code="0107", national_taxation_code="010701",
        description="Servico sintetico de tecnologia", gross_amount=Money(Decimal("100.00")),
        iss_amount=Money(Decimal("3.00")), iss_withheld=False,
    )
    service_fields.update(service_overrides)
    document = NfseCanonicalDocument(
        document_id="nfse-wiring-doc-1",
        scope=scope,
        source=SourceReference("service-order", "order-wiring-1"),
        issued_at=_NOW,
        competence_date=_NOW.date(),
        issuer=issuer,
        service_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        services=(NfseServiceLine(**service_fields),),
        service_taker_reference="taker-ref-1",
    )
    return NfseAuthorizationRequest.build(document)


def _fake_exchange(payload: bytes, *_args) -> bytes:
    json.loads(payload)  # confirms the gateway sent well-formed JSON
    return json.dumps({
        "tipoAmbiente": 2, "chaveAcesso": "35" + "0" * 42, "idDps": "dps-wiring-ok",
    }).encode()


def _governed_gateway(*, resolver_return: str = NACIONAL_HOMOLOGATION_PROVIDER_ID):
    transport = NfseNacionalHomologationGateway(
        resolve_certificate=lambda scope, cnpj: _certificate(),
        build_signed_dps=build_signed_dps,
        exchange=_fake_exchange,
    )
    application = Mock()
    application.resolve_configured_provider_id.return_value = resolver_return
    return _GovernedNationalNfseGateway(
        application=application, preaudit=nfse_preaudit, gateway=transport,
    )


def test_real_builder_and_preaudit_authorize_a_valid_document_end_to_end() -> None:
    """Preaudit passes, build_signed_dps produces a schema-valid unsigned DPS,
    sign_nfse_dps_xml() signs it with RSA-SHA1 (matching the pinned
    xml/official/NFSE_NACIONAL_1.00/xmldsig-core-schema.xsd's fixed
    SignatureMethod/DigestMethod), and the governed gateway's own downstream
    re-validation of the SIGNED document against the full pinned XSD now
    passes -- so the fake homologation exchange authorizes the document.
    """
    gateway = _governed_gateway()
    result = gateway.authorize(_request())
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == "35" + "0" * 42


def test_real_preaudit_blocks_before_any_signing_on_rate_divergence() -> None:
    gateway = _governed_gateway()
    request = _request(gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("90.00")))
    with pytest.raises(NfsePreauditRejection):
        gateway.authorize(request)


def test_real_preaudit_blocks_before_any_signing_on_missing_c_trib_nac() -> None:
    gateway = _governed_gateway()
    request = _request(national_taxation_code=None)
    with pytest.raises(FiscalValidationError):
        gateway.authorize(request)
