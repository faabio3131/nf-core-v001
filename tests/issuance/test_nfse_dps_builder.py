"""Unit tests for the National NFS-e DPS builder (build_signed_dps)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
    NfseNationalTaxTreatment,
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


def _document(
    *, issuer: FiscalProfile | None = None, services=None,
    tax_treatment: NfseNationalTaxTreatment | None = None,
) -> NfseCanonicalDocument:
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
        # Standalone builder fixture models an already-UoW-reserved number.
        dps_number=1,
        national_tax_treatment=tax_treatment,
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

    # The 1.01 builder validates unsigned XML before signing. Its pinned
    # official XMLDSig schema permits RSA-SHA256 for the signed document;
    # the old 1.00 schema required the legacy SHA-1 method.
    national_dps_validator("1.01").validate_document(signed)

    root = etree.fromstring(signed)
    assert root.tag == f"{{{_NFSE_NS}}}DPS"
    assert root.get("versao") == "1.01"
    info = root.find(f"{{{_NFSE_NS}}}infDPS")
    assert info is not None
    dps_id = info.get("Id")
    assert dps_id.startswith("DPS") and len(dps_id) == 45 and dps_id[3:].isdigit()
    assert info.findtext(f"{{{_NFSE_NS}}}tpAmb") == "2"
    assert info.findtext(f"{{{_NFSE_NS}}}cLocEmi") == "3550308"
    national_address = info.find(
        f"{{{_NFSE_NS}}}prest/{{{_NFSE_NS}}}end/{{{_NFSE_NS}}}endNac"
    )
    assert national_address is not None
    assert national_address.findtext(f"{{{_NFSE_NS}}}cMun") == "3550308"
    assert national_address.findtext(f"{{{_NFSE_NS}}}CEP") == "01001000"
    signature = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
    assert signature is not None
    signature_method = signature.find(
        ".//{http://www.w3.org/2000/09/xmldsig#}SignatureMethod"
    )
    assert signature_method is not None
    assert signature_method.get("Algorithm") == "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"


def test_build_signed_dps_is_deterministic_for_the_same_request() -> None:
    request = _request()
    first = build_signed_dps(request, _certificate())
    second = build_signed_dps(request, _certificate())
    first_id = etree.fromstring(first).find(f"{{{_NFSE_NS}}}infDPS").get("Id")
    second_id = etree.fromstring(second).find(f"{{{_NFSE_NS}}}infDPS").get("Id")
    assert first_id == second_id


def test_builder_refuses_unreserved_fiscal_serial_instead_of_hash() -> None:
    unreserved = replace(_document(), dps_number=None)
    with pytest.raises(FiscalValidationError, match="not reserved"):
        build_signed_dps(_request(unreserved), _certificate())


def test_signed_dps_uses_exact_reserved_number_and_series_in_official_id() -> None:
    document = replace(_document(), dps_number=2345, dps_series=17)
    signed = build_signed_dps(_request(document), _certificate())
    national_dps_validator("1.01").validate_document(signed)
    info = etree.fromstring(signed).find(f"{{{_NFSE_NS}}}infDPS")
    assert info is not None
    assert info.findtext(f"{{{_NFSE_NS}}}serie") == "17"
    assert info.findtext(f"{{{_NFSE_NS}}}nDPS") == "2345"
    assert info.get("Id", "").endswith("00017" + "000000000002345")


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
    treatment = (
        NfseNationalTaxTreatment(
            iss_taxation_code="1", special_regime_code="0",
            simples_assessment_code="3",
            normative_reference="Reviewed synthetic Simples sublimit decision",
            rule_version=2, effective_from=date(2026, 1, 1),
        )
        if tax_regime is TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT else None
    )
    services = (
        (_service(iss_amount=Money.zero()),)
        if tax_regime is TaxRegimeCode.MEI else None
    )
    document = _document(
        issuer=_issuer(tax_regime=tax_regime),
        services=services, tax_treatment=treatment,
    )
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
    if tax_regime is TaxRegimeCode.MEI:
        trib = root.find(
            f"{{{_NFSE_NS}}}infDPS/{{{_NFSE_NS}}}valores/"
            f"{{{_NFSE_NS}}}trib/{{{_NFSE_NS}}}tribMun"
        )
        assert trib is not None
        assert trib.findtext(f"{{{_NFSE_NS}}}tribISSQN") == "1"
        assert trib.find(f"{{{_NFSE_NS}}}pAliq") is None
        assert reg_trib.findtext(f"{{{_NFSE_NS}}}regEspTrib") == "0"


@pytest.mark.parametrize(
    ("iss", "withheld"), [("3.00", False), ("0.00", True)],
)
def test_mei_canonical_nfse_refuses_iss_highlight_and_withholding(
    iss: str, withheld: bool,
) -> None:
    with pytest.raises(FiscalValidationError, match="MEI cannot highlight"):
        _document(
            issuer=_issuer(tax_regime=TaxRegimeCode.MEI),
            services=(_service(
                iss_amount=Money(Decimal(iss)), iss_withheld=withheld,
            ),),
        )


def test_mei_canonical_nfse_refuses_special_iss_regime() -> None:
    treatment = NfseNationalTaxTreatment(
        iss_taxation_code="1", special_regime_code="2",
        normative_reference="synthetic:MEI:invalid-special-regime",
        rule_version=1, effective_from=date(2026, 1, 1),
    )
    with pytest.raises(FiscalValidationError, match="MEI cannot claim special"):
        _document(
            issuer=_issuer(tax_regime=TaxRegimeCode.MEI),
            services=(_service(iss_amount=Money.zero()),),
            tax_treatment=treatment,
        )


@pytest.mark.parametrize(
    "national_code",
    [
        "070201", "070501", "090101", "100101", "100201",
        "100301", "100401", "100501", "100801", "170601",
    ],
)
def test_bh_canonical_rejects_documentary_deduction_without_proof(
    national_code: str,
) -> None:
    """A direct domain/gateway caller cannot bypass the Portal's BH gate."""
    initial = _document()
    city = BrazilianJurisdiction("MG", "3106200")
    issuer = replace(
        initial.issuer,
        state_registration=StateRegistration("MG", "123456789"),
        address=replace(
            initial.issuer.address,
            jurisdiction=city, municipality_name="Belo Horizonte",
        ),
    )
    with pytest.raises(FiscalValidationError, match="BH documentary deduction"):
        replace(
            initial, issuer=issuer, service_jurisdiction=city,
            services=(_service(
                national_taxation_code=national_code,
                deduction_amount=Money(Decimal("10.00")),
            ),),
        )


def test_bh_canonical_allows_ordinary_service_or_zero_deduction() -> None:
    initial = _document()
    city = BrazilianJurisdiction("MG", "3106200")
    issuer = replace(
        initial.issuer,
        state_registration=StateRegistration("MG", "123456789"),
        address=replace(
            initial.issuer.address,
            jurisdiction=city, municipality_name="Belo Horizonte",
        ),
    )
    for national_code, deduction in (("070201", "0.00"), ("010701", "10.00")):
        document = replace(
            initial, issuer=issuer, service_jurisdiction=city,
            services=(_service(
                national_taxation_code=national_code,
                deduction_amount=Money(Decimal(deduction)),
            ),),
        )
        assert document.issuer.address.jurisdiction.municipality_ibge_code == "3106200"


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


def test_reserved_dps_id_is_exactly_the_read_only_recovery_identifier() -> None:
    """National GET and XMLDSig must use the same UoW-reserved legal series/number."""
    from kordena_fiscal.gateway.nfse_national_query import (
        OfficialNfseTransportError,
        _dps_id,
    )

    document = replace(_document(), dps_series=17, dps_number=2345)
    request = _request(document)
    signed = build_signed_dps(request, _certificate())
    info = etree.fromstring(signed).find(f"{{{_NFSE_NS}}}infDPS")
    assert info is not None
    assert info.get("Id") == _dps_id(request)
    assert _dps_id(request).endswith("00017" + "000000000002345")

    no_reservation = _request(replace(_document(), dps_number=None))
    with pytest.raises(OfficialNfseTransportError, match="durably reserved"):
        _dps_id(no_reservation)


@pytest.mark.parametrize(
    ("identity", "expected_xml_field"),
    [("cpf", "CPF"), ("cnpj", "CNPJ"), ("nif", "NIF"), ("none", "cNaoNIF")],
)
def test_tomador_identification_and_address_match_xsd101(
    identity: str, expected_xml_field: str,
) -> None:
    from kordena_fiscal.domain import Cpf
    from kordena_fiscal.issuance.nfe_nfse import (
        NfseForeignAddress,
        NfseServiceTaker,
    )

    foreign = NfseForeignAddress(
        country_code="US", postal_code="10001", city="New York",
        region="New York", street="Fifth Avenue", number="10",
        district="Manhattan",
    )
    national = FiscalAddress(
        street="Rua Central", number="10", district="Centro",
        municipality_name="Sao Paulo",
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        postal_code="01001000",
    )
    if identity == "nif":
        taker = NfseServiceTaker(
            tax_id=None, legal_name="Foreign Company", nif="US-TAX-1299",
            address=foreign,
        )
    elif identity == "none":
        taker = NfseServiceTaker(
            tax_id=None, legal_name="Foreign Company", no_nif_reason="2",
            address=foreign,
        )
    else:
        identifier = (
            Cnpj("12345678000195") if identity == "cnpj" else Cpf("52998224725")
        )
        taker = NfseServiceTaker(
            tax_id=identifier, legal_name="Tomador Nacional", address=national,
        )
    document = replace(_document(), service_taker=taker, dps_number=321)
    request = _request(document)
    signed = build_signed_dps(request, _certificate())
    national_dps_validator("1.01").validate_document(signed)
    root = etree.fromstring(signed)
    toma = root.find(f"{{{_NFSE_NS}}}infDPS/{{{_NFSE_NS}}}toma")
    assert toma is not None
    value = toma.findtext(f"{{{_NFSE_NS}}}{expected_xml_field}")
    assert value is not None
    assert toma.find(f"{{{_NFSE_NS}}}xNome") is not None
    if identity in {"nif", "none"}:
        assert toma.find(f"{{{_NFSE_NS}}}end/{{{_NFSE_NS}}}endExt") is not None
    else:
        assert toma.find(f"{{{_NFSE_NS}}}end/{{{_NFSE_NS}}}endNac") is not None

    from kordena_fiscal.issuance.nfse_archive import decode_prepared_nfse, encode_prepared_nfse

    recovered = decode_prepared_nfse(
        encode_prepared_nfse(request), scope=document.scope,
    )
    assert recovered.document.service_taker == taker
    assert recovered.request_fingerprint == request.request_fingerprint


def test_tomador_rejects_ambiguous_and_invalid_foreign_identification() -> None:
    from kordena_fiscal.domain import Cpf
    from kordena_fiscal.issuance.nfe_nfse import NfseForeignAddress, NfseServiceTaker

    with pytest.raises(FiscalValidationError, match="exactly one"):
        NfseServiceTaker(
            tax_id=Cpf("52998224725"), legal_name="Invalid", nif="US-9999",
        )
    with pytest.raises(FiscalValidationError, match="cNaoNIF"):
        NfseServiceTaker(
            tax_id=None, legal_name="Invalid", no_nif_reason="3",
        )
    with pytest.raises(FiscalValidationError, match="two uppercase ISO letters"):
        NfseForeignAddress(
            country_code="us", postal_code="10001", city="New York",
            region="New York", street="Fifth Avenue", number="10",
            district="Manhattan",
        )


def test_tomador_changes_request_fingerprint_and_protects_idempotency() -> None:
    from kordena_fiscal.issuance.nfe_nfse import NfseServiceTaker

    original = _document()
    amended = replace(
        original, service_taker=NfseServiceTaker(
            tax_id=Cnpj("12345678000195"), legal_name="Tomador Novo",
        ),
    )
    assert _request(original).request_fingerprint != _request(amended).request_fingerprint


def test_national_sublimit_fails_closed_without_reviewed_assessment() -> None:
    unreviewed = _document(
        issuer=_issuer(tax_regime=TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT)
    )
    with pytest.raises(FiscalValidationError, match="reviewed regApTribSN"):
        build_signed_dps(_request(unreviewed), _certificate())


@pytest.mark.parametrize(
    ("iss_taxation", "result_country", "immunity_type", "expected_element"),
    [
        ("1", None, None, None),
        ("2", None, "1", "tpImunidade"),
        ("3", "US", None, "cPaisResult"),
        ("4", None, None, None),
    ],
)
def test_reviewed_national_iss_treatments_are_xsd101_valid(
    iss_taxation: str, result_country: str | None,
    immunity_type: str | None, expected_element: str | None,
) -> None:
    decision = NfseNationalTaxTreatment(
        iss_taxation_code=iss_taxation, special_regime_code="0",
        result_country_code=result_country, immunity_type_code=immunity_type,
        normative_reference="Pinned National DPS 1.01 + approved fiscal classification",
        rule_version=3, effective_from=date(2026, 1, 1),
    )
    line = _service(
        iss_amount=Money(Decimal("3.00" if iss_taxation == "1" else "0.00")),
    )
    doc = _document(services=(line,), tax_treatment=decision)
    xml = build_signed_dps(_request(doc), _certificate())
    national_dps_validator("1.01").validate_document(xml)
    root = etree.fromstring(xml)
    tax = root.find(
        f"{{{_NFSE_NS}}}infDPS/{{{_NFSE_NS}}}valores/"
        f"{{{_NFSE_NS}}}trib/{{{_NFSE_NS}}}tribMun"
    )
    assert tax is not None
    assert tax.findtext(f"{{{_NFSE_NS}}}tribISSQN") == iss_taxation
    if expected_element is not None:
        assert tax.findtext(f"{{{_NFSE_NS}}}{expected_element}") == (
            result_country if iss_taxation == "3" else immunity_type
        )


def test_reviewed_special_regime_and_sublimit_are_not_guessed() -> None:
    decision = NfseNationalTaxTreatment(
        iss_taxation_code="1", special_regime_code="4",
        simples_assessment_code="2", rule_version=5,
        effective_from=date(2026, 1, 1),
        normative_reference="Reviewed special regime and SN sublimit",
    )
    doc = _document(
        issuer=_issuer(tax_regime=TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT),
        tax_treatment=decision,
    )
    xml = build_signed_dps(_request(doc), _certificate())
    national_dps_validator("1.01").validate_document(xml)
    reg = etree.fromstring(xml).find(
        f"{{{_NFSE_NS}}}infDPS/{{{_NFSE_NS}}}prest/{{{_NFSE_NS}}}regTrib"
    )
    assert reg is not None
    assert reg.findtext(f"{{{_NFSE_NS}}}regEspTrib") == "4"
    assert reg.findtext(f"{{{_NFSE_NS}}}regApTribSN") == "2"


def test_reviewed_tax_decision_is_immutable_in_archive_and_fingerprint() -> None:
    from kordena_fiscal.issuance.nfse_archive import (
        decode_prepared_nfse,
        encode_prepared_nfse,
    )
    decision = NfseNationalTaxTreatment(
        iss_taxation_code="3", special_regime_code="0",
        result_country_code="US", normative_reference="Reviewed export classification",
        rule_version=4, effective_from=date(2026, 1, 1),
    )
    request = _request(_document(
        services=(_service(iss_amount=Money.zero()),), tax_treatment=decision,
    ))
    encoded = encode_prepared_nfse(request)
    decoded = decode_prepared_nfse(encoded, scope=_scope())
    assert decoded.request_fingerprint == request.request_fingerprint
    assert decoded.document.national_tax_treatment == decision
    altered = json.loads(encoded)
    # A valid-but-different normative decision must fail the immutable
    # fingerprint, not fail earlier due to mutually inconsistent ISS fields.
    altered["national_tax_treatment"]["normative_reference"] = "TAMPERED-DECISION"
    # The durable boundary intentionally masks internal fingerprint details
    # with the same public error used for other invalid archived artifacts.
    with pytest.raises(FiscalValidationError, match="invalid prepared NFS-e artifact"):
        decode_prepared_nfse(json.dumps(altered).encode(), scope=_scope())


def test_reviewed_tax_decision_rejects_conflicts_and_stale_competence() -> None:
    with pytest.raises(FiscalValidationError, match="only valid"):
        NfseNationalTaxTreatment(
            iss_taxation_code="1", special_regime_code="0", result_country_code="US",
            normative_reference="reviewed", rule_version=1,
            effective_from=date(2026, 1, 1),
        )
    future = NfseNationalTaxTreatment(
        iss_taxation_code="1", special_regime_code="0", normative_reference="reviewed",
        rule_version=1, effective_from=date(2027, 1, 1),
    )
    with pytest.raises(FiscalValidationError, match="not effective"):
        _document(tax_treatment=future)
    non_taxable = NfseNationalTaxTreatment(
        iss_taxation_code="2", special_regime_code="0", immunity_type_code="1",
        normative_reference="reviewed", rule_version=1,
        effective_from=date(2026, 1, 1),
    )
    with pytest.raises(FiscalValidationError, match="cannot charge"):
        _document(tax_treatment=non_taxable)


