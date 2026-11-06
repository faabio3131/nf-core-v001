"""Unit tests for the National NFS-e DPS builder (build_signed_dps)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
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
from kordena_fiscal.domain.profile import MunicipalRegistration
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator

_NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
_INSTANT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="corr-dps-1",
    )


def _issuer(
    *, tax_regime: TaxRegimeCode = TaxRegimeCode.SIMPLES_NACIONAL,
    cnpj: str = "12345678000195", municipal_registration: MunicipalRegistration | None = None,
) -> FiscalProfile:
    return FiscalProfile(
        profile_id="issuer-dps-1",
        scope=_scope(),
        cnpj=Cnpj(cnpj),
        legal_name="Empresa Sintetica de Servicos Ltda",
        tax_regime=tax_regime,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica",
            number="100",
            district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        municipal_registration=municipal_registration,
    )


def _service(**overrides) -> NfseServiceLine:
    base = dict(
        line_number=1,
        municipal_service_code="0107",
        national_taxation_code="010701",
        description="Servico sintetico de tecnologia",
        gross_amount=Money(Decimal("100.00")),
        deduction_amount=Money.zero(),
        iss_amount=Money(Decimal("3.00")),
        iss_withheld=False,
    )
    base.update(overrides)
    return NfseServiceLine(**base)


def _document(*, issuer: FiscalProfile | None = None, services=None) -> NfseCanonicalDocument:
    return NfseCanonicalDocument(
        document_id="nfse-dps-doc-1",
        scope=_scope(),
        source=SourceReference("service-order", "order-dps-1"),
        issued_at=_INSTANT,
        competence_date=_INSTANT.date(),
        issuer=issuer or _issuer(),
        service_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        services=services if services is not None else (_service(),),
        service_taker_reference="taker-ref-1",
    )


def _request(document: NfseCanonicalDocument | None = None) -> NfseAuthorizationRequest:
    return NfseAuthorizationRequest.build(document or _document())


def _certificate() -> EphemeralCertificateMaterial:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NFCore DPS Builder Test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    blob = pkcs12.serialize_key_and_certificates(
        b"nfcore-dps-test", key, cert, None, BestAvailableEncryption(b"unit-test"),
    )
    return EphemeralCertificateMaterial(
        reference_id="ref:dps-builder-test", pkcs12_bytes=blob, password=b"unit-test",
    )


def test_build_signed_dps_produces_schema_valid_and_signed_document() -> None:
    signed = build_signed_dps(_request(), _certificate())

    # The builder validates its own UNSIGNED XML against the pinned XSD
    # before handing it to sign_nfse_dps_xml() (see build_signed_dps's last
    # two lines). Re-validating the SIGNED document against the full pinned
    # schema (including xmldsig-core-schema.xsd's fixed RSA-SHA1
    # SignatureMethod/DigestMethod) now also passes, since sign_nfse_dps_xml()
    # signs the National DPS flow with RSA-SHA1 to match that constraint.
    national_dps_validator("1.00").validate_document(signed)

    root = etree.fromstring(signed)
    assert root.tag == f"{{{_NFSE_NS}}}DPS"
    assert root.get("versao") == "1.00"
    info = root.find(f"{{{_NFSE_NS}}}infDPS")
    assert info is not None
    dps_id = info.get("Id")
    assert dps_id.startswith("DPS") and len(dps_id) == 45 and dps_id[3:].isdigit()
    assert info.findtext(f"{{{_NFSE_NS}}}tpAmb") == "2"
    assert info.findtext(f"{{{_NFSE_NS}}}cLocEmi") == "3550308"
    signature = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
    assert signature is not None
    signature_method = signature.find(
        ".//{http://www.w3.org/2000/09/xmldsig#}SignatureMethod"
    )
    assert signature_method is not None
    assert signature_method.get("Algorithm") == "http://www.w3.org/2000/09/xmldsig#rsa-sha1"


def test_build_signed_dps_is_deterministic_for_the_same_request() -> None:
    request = _request()
    first = build_signed_dps(request, _certificate())
    second = build_signed_dps(request, _certificate())
    first_id = etree.fromstring(first).find(f"{{{_NFSE_NS}}}infDPS").get("Id")
    second_id = etree.fromstring(second).find(f"{{{_NFSE_NS}}}infDPS").get("Id")
    assert first_id == second_id


def test_build_signed_dps_rejects_more_than_one_service_line() -> None:
    document = _document(services=(_service(line_number=1), _service(line_number=2)))
    with pytest.raises(FiscalValidationError, match="exactly one"):
        build_signed_dps(_request(document), _certificate())


def test_build_signed_dps_rejects_missing_national_taxation_code() -> None:
    document = _document(services=(_service(national_taxation_code=None),))
    with pytest.raises(FiscalValidationError, match="national_taxation_code"):
        build_signed_dps(_request(document), _certificate())


def test_build_signed_dps_rejects_alphanumeric_cnpj() -> None:
    # A known-valid alphanumeric CNPJ (Brazil's 2026 CNPJ-alfanumerico reform);
    # the legacy DPS 1.00/1.01 Id/CNPJ elements only accept numeric digits.
    issuer = _issuer(cnpj="AB.C12.345/0001-10")
    document = _document(issuer=issuer)
    with pytest.raises(FiscalValidationError, match="numeric CNPJ"):
        build_signed_dps(_request(document), _certificate())

# NB: a scenario where the issuer/service-jurisdiction lacks an IBGE
# municipality code is not reachable through this builder -- both
# FiscalAddress and NfseCanonicalDocument already enforce
# municipality_ibge_code is not None at construction time, so the
# equivalent guard inside build_signed_dps is defense in depth rather than
# something a unit test can trigger via normal domain construction.


@pytest.mark.parametrize(
    ("tax_regime", "expected_op_simp_nac"),
    [
        (TaxRegimeCode.NORMAL, "1"),
        (TaxRegimeCode.MEI, "2"),
        (TaxRegimeCode.SIMPLES_NACIONAL, "3"),
        (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, "3"),
    ],
)
def test_build_signed_dps_translates_tax_regime_to_op_simp_nac(
    tax_regime: TaxRegimeCode, expected_op_simp_nac: str,
) -> None:
    document = _document(issuer=_issuer(tax_regime=tax_regime))
    signed = build_signed_dps(_request(document), _certificate())
    root = etree.fromstring(signed)
    reg_trib = root.find(
        f"{{{_NFSE_NS}}}infDPS/{{{_NFSE_NS}}}prest/{{{_NFSE_NS}}}regTrib"
    )
    assert reg_trib.findtext(f"{{{_NFSE_NS}}}opSimpNac") == expected_op_simp_nac
    if tax_regime is TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT:
        assert reg_trib.findtext(f"{{{_NFSE_NS}}}regApTribSN") == "3"
    else:
        assert reg_trib.find(f"{{{_NFSE_NS}}}regApTribSN") is None


def test_build_signed_dps_includes_deduction_and_withheld_retention_code() -> None:
    document = _document(
        services=(
            _service(
                deduction_amount=Money(Decimal("10.00")),
                iss_amount=Money(Decimal("4.50")),
                iss_withheld=True,
            ),
        ),
    )
    signed = build_signed_dps(_request(document), _certificate())
    root = etree.fromstring(signed)
    info = root.find(f"{{{_NFSE_NS}}}infDPS")
    valores = info.find(f"{{{_NFSE_NS}}}valores")
    assert valores.findtext(f"{{{_NFSE_NS}}}vDedRed/{{{_NFSE_NS}}}vDR") == "10.00"
    trib_mun = valores.find(f"{{{_NFSE_NS}}}trib/{{{_NFSE_NS}}}tribMun")
    assert trib_mun.findtext(f"{{{_NFSE_NS}}}tpRetISSQN") == "2"
    assert trib_mun.findtext(f"{{{_NFSE_NS}}}pAliq") == "5.00"


def test_build_signed_dps_rejects_municipal_registration_over_limit() -> None:
    issuer = _issuer(municipal_registration=MunicipalRegistration("1" * 16))
    document = _document(issuer=issuer)
    with pytest.raises(FiscalValidationError, match="15-character"):
        build_signed_dps(_request(document), _certificate())
