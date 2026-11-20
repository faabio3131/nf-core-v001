from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kordena_fiscal.connectors.bling_canonical import map_bling_document
from kordena_fiscal.documents import (
    FiscalPaymentSnapshot,
    FiscalRecipientSnapshot,
    PaymentMethodKind,
    canonical_sha256,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProductProfile,
    FiscalProfile,
    FiscalUnitCode,
    FiscalValidationError,
    Money,
    NcmCode,
    ProductOrigin,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.tax import (
    TaxRule,
    TaxRuleAmbiguityError,
    TaxRuleNotFoundError,
    TaxRuleOutcome,
    TaxRuleSelector,
)

NOW = datetime(2026, 11, 9, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgres"])
def preparation_database(tmp_path, request):
    from test_bling_workflow import workflow_database

    with workflow_database(tmp_path, request.param) as database:
        yield database


@pytest.fixture
def mapping():
    scope = ExecutionScope(
        "tenant", "unit", FiscalEnvironment.HOMOLOGATION, "test", host_namespace="bling"
    )
    issuer = FiscalProfile(
        "issuer",
        scope,
        Cnpj("12345678000195"),
        "Synthetic",
        TaxRegimeCode.SIMPLES_NACIONAL,
        StateRegistration("SP", "123456789"),
        CnaeCode("5611201"),
        FiscalAddress(
            "Rua Sintetica",
            "1",
            "Centro",
            "Sao Paulo",
            BrazilianJurisdiction("SP", "3550308"),
            "01001000",
        ),
        NOW,
    )
    product = FiscalProductProfile(
        "product",
        "p1",
        scope,
        "SKU",
        "Synthetic",
        NcmCode("21069090"),
        FiscalUnitCode("UN"),
        FiscalUnitCode("UN"),
        ProductOrigin.NATIONAL,
        NOW,
    )
    rule = TaxRule(
        "synthetic",
        1,
        TaxRuleSelector(state_code="SP"),
        TaxRuleOutcome("5102", "102", "07", "07"),
        "SYNTHETIC TEST ONLY",
        NOW,
    )
    return dict(
        company_id="company",
        recipient=FiscalRecipientSnapshot(
            Cnpj("12345678000195"), "Synthetic customer", issuer.address, 9, True
        ),
        document_id="doc",
        issued_at=NOW,
        issuer=issuer,
        products_by_code={"SKU": product},
        rules=(rule,),
        payments=(),
    )


def order():
    return {
        "id": 123,
        "itens": [
            {
                "codigo": "SKU",
                "quantidade": "3",
                "valor": "0.3333333333",
                "ncm": "99999999",
                "cfop": "9999",
                "desconto": 10,
            }
        ],
        "totalProdutos": "1.00",
        "total": "1.00",
    }


def test_maps_real_shape_without_provider_tax_hints_or_double_discount(mapping):
    document = map_bling_document(order(), **mapping)
    assert document.items[0].product.ncm.value == "21069090"
    assert document.items[0].tax_decision.outcome.cfop == "5102"
    assert document.items[0].tax_decision.rule_id == "synthetic"
    assert document.items[0].quantity == Decimal("3")
    assert document.totals.net_amount.amount == Decimal("1.00")
    assert canonical_sha256(document) == canonical_sha256(map_bling_document(order(), **mapping))


def test_allocations_reconcile_every_cent_and_payments(mapping):
    raw = {
        "id": 123,
        "itens": [{"codigo": "SKU", "quantidade": "1", "valor": "1.00"} for _ in range(3)],
        "desconto": {"valor": "0.02", "unidade": "REAL"},
        "transporte": {"frete": "0.01"},
        "outrasDespesas": "0.03",
        "totalProdutos": "3.00",
        "total": "3.02",
    }
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("3.02"))),)
    document = map_bling_document(raw, **mapping)
    assert [line.discount_amount.amount for line in document.items] == [
        Decimal(".01"),
        Decimal(".01"),
        0,
    ]
    assert sum(line.surcharge_amount.amount for line in document.items) == Decimal(".04")
    assert document.totals.net_amount.amount == document.totals.payment_amount.amount


@pytest.mark.parametrize(
    "field,value",
    [
        ("total", "0.99"),
        ("totalProdutos", "1.01"),
        ("id", True),
        ("desconto", {"valor": "10", "unidade": "PERCENTUAL"}),
        ("outrasDespesas", "NaN"),
        ("itens", []),
    ],
)
def test_rejects_unreconciled_or_invalid_facts(mapping, field, value):
    raw = order()
    raw[field] = value
    with pytest.raises(FiscalValidationError):
        map_bling_document(raw, **mapping)


def test_scoped_profiles_and_rule_resolution_are_mandatory(mapping):
    product = mapping["products_by_code"]["SKU"]
    mapping["products_by_code"] = {
        "SKU": replace(product, scope=replace(product.scope, tenant_id="other"))
    }
    with pytest.raises(FiscalValidationError, match="another scope"):
        map_bling_document(order(), **mapping)
    mapping["products_by_code"] = {"SKU": product}
    rule = mapping["rules"][0]
    mapping["rules"] = ()
    with pytest.raises(TaxRuleNotFoundError):
        map_bling_document(order(), **mapping)
    mapping["rules"] = (rule, replace(rule, rule_id="another"))
    with pytest.raises(TaxRuleAmbiguityError):
        map_bling_document(order(), **mapping)


def test_recipient_and_rates_are_bound_to_canonical_fingerprint(mapping):
    from kordena_fiscal.tax.nfe_calculation import NfeRateParameters

    original = map_bling_document(order(), **mapping)
    changed = replace(original, recipient=replace(original.recipient, name="Another recipient"))
    assert canonical_sha256(original) != canonical_sha256(changed)
    rule = mapping["rules"][0]
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                nfe_rates=NfeRateParameters(Decimal(0), Decimal(0), Decimal(0), "net", "net"),
            ),
        ),
    )
    assert canonical_sha256(original) != canonical_sha256(map_bling_document(order(), **mapping))


@pytest.fixture
def signing_material():
    from datetime import timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    from kordena_fiscal.vault import EphemeralCertificateMaterial

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic preparation")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), b"\x0c\x0e12345678000195")]
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return EphemeralCertificateMaterial(
        reference_id="synthetic-preparation",
        password=b"test-only",
        pkcs12_bytes=pkcs12.serialize_key_and_certificates(
            b"test-only", key, cert, None, serialization.BestAvailableEncryption(b"test-only")
        ),
    )


def sale_document(mapping, *, normal=False):
    from kordena_fiscal.domain import Gtin
    from kordena_fiscal.tax.nfe_calculation import NfeRateParameters

    if normal:
        mapping["issuer"] = replace(mapping["issuer"], tax_regime=TaxRegimeCode.NORMAL)
    product = mapping["products_by_code"]["SKU"]
    mapping["products_by_code"] = {"SKU": replace(product, gtin=Gtin("SEM GTIN"))}
    rule = mapping["rules"][0]
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                icms_code="00" if normal else "102",
                pis_cst="01" if normal else "07",
                cofins_cst="01" if normal else "07",
                nfe_rates=NfeRateParameters(
                    Decimal("18") if normal else Decimal(0),
                    Decimal("1.65") if normal else Decimal(0),
                    Decimal("7.6") if normal else Decimal(0),
                    "net_less_icms",
                    "net_less_icms",
                ),
            ),
        ),
    )
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("1.00"))),)
    return map_bling_document(order(), **mapping)


@pytest.mark.parametrize("normal", [False, True])
def test_real_order_to_signed_official_schema_and_crypto(mapping, signing_material, normal):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import (
        NfeSignatureProfile,
        sign_nfe_envi_xml,
        verify_official_nfe4_signature,
    )
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    document = sale_document(mapping, normal=normal)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    unsigned = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    signed = sign_nfe_envi_xml(
        unsigned, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)
    verify_official_nfe4_signature(etree.fromstring(signed), signing_material)


def test_taxable_conversion_is_explicit_reconciled_and_signed(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import (
        NfeSignatureProfile,
        sign_nfe_envi_xml,
    )
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping)
    product = mapping["products_by_code"]["SKU"]
    mapping["products_by_code"] = {"SKU": replace(product, taxable_unit=FiscalUnitCode("KG"))}
    document = map_bling_document(order(), **mapping, taxable_factors={"SKU": Decimal("2")})
    line = document.items[0]
    assert line.taxable_quantity == Decimal("6")
    assert line.taxable_unit_price == Decimal("0.1666666667")
    assert canonical_sha256(document) != canonical_sha256(sale_document(mapping))
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='qTrib'])") == "6.0000"
    assert root.xpath("string(//*[local-name()='vUnTrib'])") == "0.1666666667"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)
    with pytest.raises(FiscalValidationError, match="conversion"):
        build_nfe_sale(
            replace(document, items=(replace(line, taxable_unit_price=Decimal("1")),)),
            key,
            NfeSaleOptions("VENDA", 1, 9),
        )
    with pytest.raises(FiscalValidationError, match="precision"):
        map_bling_document(order(), **mapping, taxable_factors={"SKU": Decimal("0.00001")})


def test_integrated_card_binds_transaction_to_xml_and_fingerprint(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    document = sale_document(mapping)
    payment = FiscalPaymentSnapshot(
        PaymentMethodKind.CREDIT_CARD,
        Money(Decimal("1.00")),
        card_acquirer_cnpj="12345678000195",
        card_brand="01",
        card_authorization="TEST123",
    )
    document = replace(document, payments=(payment,))
    assert canonical_sha256(document) != canonical_sha256(
        replace(document, payments=(replace(payment, card_authorization="TEST456"),))
    )
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9, card_integration_type=1))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='card']/*[local-name()='cAut'])") == "TEST123"
    assert root.xpath("string(//*[local-name()='card']/*[local-name()='CNPJ'])") == "12345678000195"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)
    with pytest.raises(FiscalValidationError, match="conflict"):
        build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9, card_integration_type=2))
    with pytest.raises(FiscalValidationError, match="complete"):
        replace(payment, card_brand=None)


def test_fcp_own_operation_is_versioned_calculated_and_signed(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    original = sale_document(mapping, normal=True)
    line = original.items[0]
    rates = replace(line.tax_decision.outcome.nfe_rates, fcp_rate=Decimal("2"))
    decision = replace(
        line.tax_decision, outcome=replace(line.tax_decision.outcome, nfe_rates=rates)
    )
    document = replace(original, items=(replace(line, tax_decision=decision),))
    assert canonical_sha256(original) != canonical_sha256(document)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='ICMS00']/*[local-name()='pFCP'])") == "2.0000"
    assert root.xpath("string(//*[local-name()='ICMS00']/*[local-name()='vFCP'])") == "0.02"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vFCP'])") == "0.02"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)
    with pytest.raises(FiscalValidationError, match="FCP"):
        mapping["issuer"] = replace(mapping["issuer"], tax_regime=TaxRegimeCode.SIMPLES_NACIONAL)
        simple = sale_document(mapping)
        simple_line = simple.items[0]
        simple_rates = replace(simple_line.tax_decision.outcome.nfe_rates, fcp_rate=Decimal("2"))
        simple_decision = replace(
            simple_line.tax_decision,
            outcome=replace(simple_line.tax_decision.outcome, nfe_rates=simple_rates),
        )
        build_nfe_sale(
            replace(simple, items=(replace(simple_line, tax_decision=simple_decision),)),
            key,
            NfeSaleOptions("VENDA", 1, 9),
        )


def test_bling_rule_loads_explicit_fcp_rate():
    from kordena_fiscal.runtime.bling_preparation import _rule

    rule = _rule(
        {
            "rule_id": "fcp-test",
            "version": 1,
            "priority": 1,
            "source_normative": "SYNTHETIC ONLY",
            "effective_from": NOW.isoformat(),
            "selector": {
                "state_code": "SP",
                "tax_regime": 3,
                "recipient_profile": "consumer_final",
                "ncm_prefix": "21",
            },
            "outcome": {
                "cfop": "5102",
                "icms_code": "00",
                "pis_cst": "07",
                "cofins_cst": "07",
                "nfe_rates": {
                    "icms_rate": "18",
                    "pis_rate": "0",
                    "cofins_rate": "0",
                    "pis_base": "net",
                    "cofins_base": "net",
                    "fcp_rate": "2",
                },
            },
        }
    )
    assert rule.outcome.nfe_rates.fcp_rate == Decimal("2")


def test_ipi_reconciles_order_payments_and_signed_xml(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        ipi_rate=Decimal("10"),
        ipi_enquiry_code="999",
        ipi_calculation_mode="net_icms_excluded",
    )
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, nfe_rates=rates)),)
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("1.10"))),)
    raw = order()
    raw["total"] = "1.10"
    raw["itens"][0]["aliquotaIPI"] = "10"
    document = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='vIPI'])") == "0.10"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.10"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)
    raw["itens"][0]["aliquotaIPI"] = "12"
    with pytest.raises(FiscalValidationError, match="IPI hint"):
        map_bling_document(raw, **mapping)


def test_ipi_rule_rejects_incomplete_or_implicit_calculation():
    from kordena_fiscal.runtime.bling_preparation import _rule

    rule = {
        "rule_id": "ipi-test",
        "version": 1,
        "priority": 1,
        "source_normative": "SYNTHETIC ONLY",
        "effective_from": NOW.isoformat(),
        "selector": {
            "state_code": "SP",
            "tax_regime": 3,
            "recipient_profile": "consumer_final",
            "ncm_prefix": "21",
        },
        "outcome": {
            "cfop": "5102",
            "icms_code": "00",
            "pis_cst": "07",
            "cofins_cst": "07",
            "nfe_rates": {
                "icms_rate": "18",
                "pis_rate": "0",
                "cofins_rate": "0",
                "pis_base": "net",
                "cofins_base": "net",
                "ipi_rate": "10",
                "ipi_enquiry_code": "999",
            },
        },
    }
    with pytest.raises(FiscalValidationError, match="mode"):
        _rule(rule)
    rule["outcome"]["nfe_rates"]["ipi_calculation_mode"] = "net_icms_excluded"
    assert _rule(rule).outcome.nfe_rates.ipi_rate == Decimal("10")


def test_atomic_preparation_replays_without_certificate_and_rolls_back_number(
    mapping, signing_material, tmp_path, preparation_database
):
    from kordena_fiscal.application.nfe_preparation import prepare_nfe_sale
    from kordena_fiscal.application.service import FiscalApplicationService
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions
    from kordena_fiscal.lifecycle import FiscalDocumentState

    database = preparation_database
    document = sale_document(mapping)
    options = NfeSaleOptions("VENDA", 1, 9)
    with pytest.raises(FiscalValidationError, match="certificate"):
        prepare_nfe_sale(database, document, options=options, series=1, certificate=None, now=NOW)
    result = prepare_nfe_sale(
        database,
        document,
        options=options,
        series=1,
        certificate=signing_material,
        now=datetime.now(UTC),
    )
    assert result == "doc"
    assert (
        prepare_nfe_sale(database, document, options=options, series=1, certificate=None, now=NOW)
        == result
    )
    prepared = FiscalApplicationService(database).load_prepared_document_authorization(
        document.scope, result
    )
    assert prepared.access_key.value[25:34] == "000000001"
    with database() as uow:
        assert uow.lifecycle.get(result).state is FiscalDocumentState.READY_TO_TRANSMIT
        assert len(uow.archive.list_for_document(document.scope, result)) == 2


@pytest.mark.parametrize("ipi_enabled", [False, True])
def test_configured_native_preparer_queues_signed_document_atomically(
    mapping, signing_material, tmp_path, monkeypatch, preparation_database, ipi_enabled
):
    import base64
    import hashlib
    import json

    from test_bling_workflow import Transport, create_installation, review_client

    from kordena_fiscal.application.service import FiscalApplicationService
    from kordena_fiscal.runtime.bling_preparation import BlingSalePreparer
    from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    database = preparation_database
    _db, application, orders = create_installation(database)
    sale_document(mapping, normal=ipi_enabled)
    mapping["products_by_code"]["SKU"] = replace(
        mapping["products_by_code"]["SKU"], taxable_unit=FiscalUnitCode("KG")
    )
    from kordena_fiscal.control_plane.models import FiscalOrganization, FiscalUnitRegistration

    with database() as uow:
        uow.control_plane.add_organization(FiscalOrganization("tenant", "Synthetic"))
        uow.control_plane.add_unit(
            FiscalUnitRegistration(
                "tenant", "unit", "Synthetic", frozenset({FiscalEnvironment.HOMOLOGATION})
            )
        )
        uow.control_plane.add_profile(mapping["issuer"])
        uow.commercial.add_product_profile(mapping["products_by_code"]["SKU"])
        uow.commit()
    raw = {
        **order(),
        "situacao": {"id": 1},
        "parcelas": [{"valor": "1.10" if ipi_enabled else "1.00", "formaPagamento": {"id": 7}}],
    }
    if ipi_enabled:
        raw["total"] = "1.10"
        raw["itens"][0]["aliquotaIPI"] = "10"
    row = orders.stage(123, raw, event_id="native-test", now=NOW)
    policy = {
        "schema_version": 1,
        "policy_id": "SYNTHETIC-ONLY",
        "version": 1,
        "company_id": orders.company_id,
        "tenant_id": "tenant",
        "unit_id": "unit",
        "environment": "homologation",
        "issuer_profile_id": "issuer",
        "issuer_profile_version": 1,
        "products": {"SKU": {"product_id": "p1", "version": 1, "taxable_factor": "2"}},
        "payment_methods": {"7": "credit_card"},
        "series": 1,
        "sale_options": {
            "nature": "VENDA",
            "presence": 1,
            "freight_mode": 9,
            "card_integration_type": 1,
        },
        "rules": [
            {
                "rule_id": "synthetic-rule",
                "version": 1,
                "source_normative": "SYNTHETIC ONLY",
                "effective_from": NOW.isoformat(),
                "priority": 1,
                "selector": {
                    "state_code": "SP",
                    "tax_regime": 3 if ipi_enabled else 1,
                    "recipient_profile": "consumer_final",
                    "ncm_prefix": "2106",
                },
                "outcome": {
                    "cfop": "5102",
                    "icms_code": "00" if ipi_enabled else "102",
                    "pis_cst": "07",
                    "cofins_cst": "07",
                    "nfe_rates": {
                        "icms_rate": "0",
                        "pis_rate": "0",
                        "cofins_rate": "0",
                        "pis_base": "net",
                        "cofins_base": "net",
                    },
                },
            }
        ],
    }
    if ipi_enabled:
        policy["rules"][0]["outcome"]["nfe_rates"].update(
            {
                "ipi_rate": "10",
                "ipi_enquiry_code": "999",
                "ipi_calculation_mode": "net_icms_excluded",
            }
        )
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    preparer = BlingSalePreparer(
        {"NFCORE_BLING_FISCAL_POLICY_FILE": str(path), "NFCORE_BLING_FISCAL_POLICY_SHA256": digest}
    )
    payload = {
        "card_payments": {
            "0": {"acquirer_cnpj": "12345678000195", "brand": "01", "authorization": "TEST123"}
        },
        "snapshot_sha256": row["snapshot_sha256"],
        "policy_sha256": digest,
        "issued_at": NOW.isoformat(),
        "recipient": {
            "document": "12345678000195",
            "name": "Synthetic buyer",
            "street": "Rua Sintetica",
            "number": "1",
            "district": "Centro",
            "municipality_name": "Sao Paulo",
            "municipality_ibge_code": "3550308",
            "state": "SP",
            "postal_code": "01001000",
            "ie_indicator": 9,
            "final_consumer": True,
        },
    }
    with pytest.raises(FiscalValidationError):
        preparer.prepare(orders, 123, payload, "reviewer")
    assert orders.get(123)["document_id"] is None
    with database() as uow:
        policies = [
            entry
            for entry in uow.archive.list_for_scope(orders.scope)
            if entry.media_type == "application/vnd.nfcore.bling-fiscal-policy.v1+json"
        ]
        assert len(policies) == 1
        assert policies[0].content == path.read_bytes()
        assert policies[0].content_sha256 == digest
    monkeypatch.setenv("NFCORE_A1_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("NFCORE_A1_VAULT_KEY_BASE64", base64.b64encode(bytes(range(32))).decode())
    vault = EncryptedA1Vault.from_environ()
    vault.provision(
        scope=orders.scope,
        issuer_cnpj="12345678000195",
        pkcs12_bytes=signing_material.pkcs12_bytes,
        password=signing_material.password,
    )
    client = review_client(orders, preparer=preparer)
    path = "/v1/portal/integrations/bling/orders/123"
    assert client.get(path).json()["preparation"]["sha256"] == digest
    assert client.post(path + "/prepare", json=payload).status_code == 403
    response = client.post(
        path + "/prepare", json=payload, headers={"X-CSRF-Token": client.cookies.get("nfcore_csrf")}
    )
    assert response.status_code == 200, response.text
    document_id = response.json()["document_id"]
    assert orders.get(123)["state"] == "queued"
    assert orders.get(123)["document_id"] == document_id
    prepared = FiscalApplicationService(database).load_prepared_document_authorization(
        orders.scope, document_id
    )
    OfficialNfeEnvelopeValidator()(prepared.signed_xml)
    monkeypatch.delenv("NFCORE_A1_VAULT_DIR")
    monkeypatch.delenv("NFCORE_A1_VAULT_KEY_BASE64")
    assert preparer.prepare(orders, 123, payload, "reviewer") == document_id
    assert prepared.access_key.value[25:34] == "000000001"

    from kordena_fiscal.application.bling_orders import ISSUE_ORDER, PUBLISH_STATUS
    from kordena_fiscal.application.bling_processing import BlingProcessingHandler
    from kordena_fiscal.application.bling_status_delivery import BlingStatusPublisher
    from kordena_fiscal.application.outbox_worker import DurableFiscalOutboxWorker
    from kordena_fiscal.contingency import FiscalOutboxStatus
    from kordena_fiscal.contingency.outbox import OutboxClaimSelection
    from kordena_fiscal.gateway import FiscalGatewayClient
    from kordena_fiscal.runtime.fiscal_runtime import CanonicalFiscalOperationPath
    from kordena_fiscal.runtime.provider_issuance_handler import build_provider_issuance_handler

    transport = Transport()
    fiscal_path = CanonicalFiscalOperationPath(
        application,
        handlers={
            "issueFiscalDocument": build_provider_issuance_handler(
                application,
                resolve_prepared=application.load_prepared_document_authorization,
                gateway=FiscalGatewayClient(transport),
            )
        },
    )
    issue = BlingProcessingHandler(orders, lambda _id: raw, fiscal_path)
    worker = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=issue,
        claim_selection=OutboxClaimSelection(orders.scope, frozenset({ISSUE_ORDER})),
    )
    (job,) = worker.run_once(now=datetime.now(UTC))
    assert job.status is FiscalOutboxStatus.SUCCEEDED
    assert orders.get(123)["state"] == "authorized"
    issue.dispatch(job)
    assert transport.calls == 1
    writes = []
    publisher = BlingStatusPublisher(
        orders,
        {"authorized": 10, "rejected": 11},
        lambda _id: raw,
        lambda order_id, status_id: writes.append((order_id, status_id)),
    )
    returned = DurableFiscalOutboxWorker(
        uow_factory=database,
        handler=publisher,
        claim_selection=OutboxClaimSelection(orders.scope, frozenset({PUBLISH_STATUS})),
    )
    assert returned.run_once(now=datetime.now(UTC))[0].status is FiscalOutboxStatus.SUCCEEDED
    assert writes == [(123, 10)]
    from kordena_fiscal.persistence import PersistenceConflictError

    # Even a newly pinned file cannot rewrite an already used policy version.
    policy["rules"][0]["priority"] = 2
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    changed_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    changed = BlingSalePreparer(
        {
            "NFCORE_BLING_FISCAL_POLICY_FILE": str(path),
            "NFCORE_BLING_FISCAL_POLICY_SHA256": changed_digest,
        }
    )
    with pytest.raises(PersistenceConflictError):
        changed.prepare(orders, 123, {**payload, "policy_sha256": changed_digest}, "reviewer")
    assert orders.get(123)["state"] == "authorized"
    assert transport.calls == 1


@pytest.mark.parametrize(
    "method",
    [
        PaymentMethodKind.PIX,
        PaymentMethodKind.CASH,
        PaymentMethodKind.BOLETO,
        PaymentMethodKind.VOUCHER,
        PaymentMethodKind.CREDIT_CARD,
        PaymentMethodKind.DEBIT_CARD,
    ],
)
def test_internet_sale_payment_groups_match_official_schema(mapping, signing_material, method):
    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    doc = sale_document(mapping)
    doc = replace(doc, payments=(FiscalPaymentSnapshot(method, Money(Decimal("1.00"))),))
    key = build_access_key(
        AccessKeyInput("35", NOW, doc.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678)
    )
    options = NfeSaleOptions(
        "VENDA",
        2,
        9,
        intermediary_indicator=1,
        intermediary_cnpj="12345678000195",
        intermediary_registration="synthetic-merchant",
        card_integration_type=2,
    )
    signed = sign_nfe_envi_xml(
        build_nfe_sale(doc, key, options),
        signing_material,
        profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1,
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_canonical_rate_arithmetic_is_explicit_and_unsupported_never_defaults_to_zero(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    doc = sale_document(mapping, normal=True)
    decision = doc.items[0].tax_decision
    taxes = calculate_nfe_line(decision, net_amount=Decimal("100.00"), regime=TaxRegimeCode.NORMAL)
    assert taxes.icms_base == Decimal("100.00")
    assert taxes.icms_amount == Decimal("18.00")
    assert taxes.pis_base == taxes.cofins_base == Decimal("82.00")
    assert taxes.pis_amount == Decimal("1.35")
    assert taxes.cofins_amount == Decimal("6.23")
    for outcome in (
        replace(decision.outcome, nfe_rates=None),
        replace(decision.outcome, icms_code="60"),
        replace(decision.outcome, pis_cst="49"),
        replace(decision.outcome, ibs_cbs_classification_code="000001"),
    ):
        with pytest.raises(FiscalValidationError):
            calculate_nfe_line(
                replace(decision, outcome=outcome),
                net_amount=Decimal("100.00"),
                regime=TaxRegimeCode.NORMAL,
            )


def test_snapshot_conflict_rolls_back_signed_preparation_and_number(
    mapping, signing_material, tmp_path, preparation_database
):
    from kordena_fiscal.application.bling_orders import BlingOrders
    from kordena_fiscal.application.nfe_preparation import prepare_nfe_sale
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions
    from kordena_fiscal.persistence import PersistenceConflictError

    db = preparation_database
    doc = sale_document(mapping)
    orders = BlingOrders(db, doc.scope, "company")
    row = orders.stage(123, order(), event_id="one", now=NOW)
    orders.stage(123, {**order(), "observacoes": "changed"}, event_id="two", now=NOW)
    options = NfeSaleOptions("VENDA", 1, 9)
    with pytest.raises(PersistenceConflictError):
        orders.prepare_sale(
            123,
            doc,
            snapshot_sha256=row["snapshot_sha256"],
            actor_id="actor",
            now=datetime.now(UTC),
            options=options,
            series=1,
            certificate=signing_material,
        )
    with db() as uow:
        assert uow.lifecycle.get(doc.document_id) is None
        assert not uow.archive.list_for_document(doc.scope, doc.document_id)
    from kordena_fiscal.application.service import FiscalApplicationService

    prepare_nfe_sale(
        db, doc, options=options, series=1, certificate=signing_material, now=datetime.now(UTC)
    )
    request = FiscalApplicationService(db).load_prepared_document_authorization(
        doc.scope, doc.document_id
    )
    assert request.access_key.value[25:34] == "000000001"


def test_concurrent_native_preparation_has_one_number_document_and_job(
    mapping, signing_material, preparation_database
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from kordena_fiscal.application.bling_orders import ISSUE_ORDER, BlingOrders
    from kordena_fiscal.application.service import FiscalApplicationService
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions

    database = preparation_database
    document = sale_document(mapping)
    orders = BlingOrders(database, document.scope, "company")
    row = orders.stage(123, order(), event_id="concurrent-native", now=NOW)

    barrier = Barrier(4)

    def prepare(_):
        barrier.wait(timeout=10)
        return orders.prepare_sale(
            123,
            document,
            snapshot_sha256=row["snapshot_sha256"],
            actor_id="actor",
            options=NfeSaleOptions("VENDA", 1, 9),
            series=1,
            certificate=signing_material,
            now=datetime.now(UTC),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(prepare, range(4)))
    assert results == [document.document_id] * 4
    prepared = FiscalApplicationService(database).load_prepared_document_authorization(
        document.scope, document.document_id
    )
    assert prepared.access_key.value[25:34] == "000000001"
    with database() as uow:
        entries = uow.archive.list_for_document(document.scope, document.document_id)
        assert len(entries) == 2
        jobs = uow.outbox.list_for_scope(document.scope, operations=frozenset({ISSUE_ORDER}))
        assert len(jobs) == 1


def test_policy_pin_scope_and_versions_are_enforced(mapping, tmp_path):
    import hashlib
    import json
    from pathlib import Path

    from kordena_fiscal.application.bling_orders import BlingOrders
    from kordena_fiscal.persistence import SqliteFiscalDatabase
    from kordena_fiscal.runtime.bling_preparation import BlingSalePreparer

    database = SqliteFiscalDatabase(tmp_path / "policy.sqlite")
    database.initialize()
    orders = BlingOrders(database, mapping["issuer"].scope, "company")
    example = json.loads(
        Path("contracts/integrations/bling-fiscal-policy.example.json").read_text()
    )
    example["company_id"] = "company"
    path = tmp_path / "policy.json"

    def configured(policy):
        path.write_text(json.dumps(policy))
        return BlingSalePreparer(
            {
                "NFCORE_BLING_FISCAL_POLICY_FILE": str(path),
                "NFCORE_BLING_FISCAL_POLICY_SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    preparer = configured(example)
    assert preparer.policy(orders)[0]["version"] == 1
    path.write_text(path.read_text() + " ")
    with pytest.raises(FiscalValidationError):
        preparer.policy(orders)
    for changes in (
        {"tenant_id": "other"},
        {"environment": "production"},
        {"version": True},
        {"issuer_profile_version": True},
        {"schema_version": True},
        {"unknown": "field"},
        {"products": {"SKU": {"product_id": "p1", "version": True}}},
    ):
        with pytest.raises(FiscalValidationError):
            configured({**example, **changes}).policy(orders)


@pytest.mark.parametrize("hint", ["fiscal_benefit_code", "ibs_cbs_classification_code"])
def test_special_product_metadata_is_never_silently_dropped(mapping, signing_material, hint):
    from kordena_fiscal.domain import ElectronicInvoiceModel, TaxClassificationHints
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.xml import AccessKeyInput, build_access_key

    document = sale_document(mapping)
    line = document.items[0]
    product = replace(line.product, hints=TaxClassificationHints(**{hint: "SYNTHETIC"}))
    document = replace(document, items=(replace(line, product=product),))
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    with pytest.raises(FiscalValidationError, match="special fiscal metadata"):
        build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))


def test_icms_st_fcp_st_and_payment_are_signed_and_schema_valid(mapping, signing_material):
    """No implicit ST/MVA: approved rule drives tax, money and XML together."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        st_rate=Decimal("30"),
        st_mva_rate=Decimal("40"),
        st_base_mode="net_mva",
        fcp_st_rate=Decimal("2"),
    )
    mapping["rules"] = (
        replace(rule, outcome=replace(rule.outcome, icms_code="10", nfe_rates=rates)),
    )
    # ST: 1.40*30%=0.42, less own ICMS 0.18 -> 0.24; FCP-ST: 0.028 -> 0.03
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("1.27"))),)
    raw = order()
    raw["total"] = "1.27"
    document = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)

    def xpath(tag):
        return root.xpath("string(//*[local-name()='ICMS10']/*[local-name()='" + tag + "'])")

    assert xpath("vBCST") == "1.40"
    assert xpath("vICMSST") == "0.24"
    assert xpath("vFCPST") == "0.03"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.27"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_interstate_difal_and_fcp_destination_signed_schema_valid(mapping, signing_material):
    """DIFAL and FCP destination are not silently omitted or added to vNF."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    recipient = mapping["recipient"]
    mapping["recipient"] = replace(
        recipient,
        address=replace(
            recipient.address,
            jurisdiction=BrazilianJurisdiction("RJ", "3304557"),
            municipality_name="Rio de Janeiro",
        ),
    )
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        icms_rate=Decimal("12"),
        difal_destination_rate=Decimal("18"),
        difal_interstate_rate=Decimal("12"),
        difal_destination_share=Decimal("100"),
        fcp_destination_rate=Decimal("2"),
    )
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, cfop="6102", nfe_rates=rates)),)
    document = map_bling_document(order(), **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)

    def xpath(tag):
        return root.xpath("string(//*[local-name()='ICMSUFDest']/*[local-name()='" + tag + "'])")

    assert xpath("pICMSInter") == "12.00"
    assert xpath("vICMSUFDest") == "0.06"
    assert xpath("vFCPUFDest") == "0.02"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.00"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_icms_st_and_difal_rules_fail_closed_when_incomplete(mapping):

    sale_document(mapping, normal=True)
    rates = mapping["rules"][0].outcome.nfe_rates
    with pytest.raises(FiscalValidationError, match="ST requires"):
        replace(rates, st_rate=Decimal("18"))
    with pytest.raises(FiscalValidationError, match="DIFAL requires"):
        replace(rates, difal_destination_rate=Decimal("18"))
    with pytest.raises(FiscalValidationError, match="destination FCP"):
        replace(rates, fcp_destination_rate=Decimal("2"))
    with pytest.raises(FiscalValidationError, match="full destination share"):
        replace(
            rates,
            difal_destination_rate=Decimal("18"),
            difal_interstate_rate=Decimal("12"),
            difal_destination_share=Decimal("60"),
        )


def test_rtc_2026_full_taxation_is_signed_schema_valid_and_separate_from_payment(
    mapping, signing_material
):
    """RTC CST 000 is versioned and not guessed from the Bling order."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        rtc_uf_rate=Decimal("0.1"),
        rtc_municipal_rate=Decimal("0"),
        rtc_cbs_rate=Decimal("0.9"),
        rtc_base_mode="net",
        rtc_financial_mode="informational_2026",
    )
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                ibs_cbs_cst_code="000",
                ibs_cbs_classification_code="000001",
                ibs_cbs_classification_table_version="IT-2025.002-v1.71",
                nfe_rates=rates,
            ),
        ),
    )
    document = map_bling_document(order(), **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IBSCBS']/*[local-name()='CST'])") == "000"
    assert root.xpath("string(//*[local-name()='IBSCBS']/*[local-name()='cClassTrib'])") == "000001"
    assert root.xpath("string(//*[local-name()='IBSCBSTot']/*[local-name()='vBCIBSCBS'])") == "1.00"
    assert root.xpath("string(//*[local-name()='total']/*[local-name()='vNFTot'])") == "1.01"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.00"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_rtc_requires_explicit_rates_and_classification(mapping):
    sale_document(mapping, normal=True)
    rates = mapping["rules"][0].outcome.nfe_rates
    with pytest.raises(FiscalValidationError, match="RTC requires complete"):
        replace(rates, rtc_cbs_rate=Decimal("0.9"))
    with pytest.raises(FiscalValidationError, match="RTC financial mode"):
        replace(
            rates,
            rtc_uf_rate=Decimal("0.1"),
            rtc_municipal_rate=Decimal("0"),
            rtc_cbs_rate=Decimal("0.9"),
            rtc_base_mode="net",
            rtc_financial_mode="collect_without_approval",
        )


def test_ipi_per_taxable_unit_uses_explicit_quantity_and_reconciles_payments(
    mapping, signing_material
):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        ipi_unit_amount=Decimal("0.2000"),
        ipi_enquiry_code="999",
        ipi_calculation_mode="per_taxable_unit",
        ipi_cst="50",
    )
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, nfe_rates=rates)),)
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("1.60"))),)
    raw = order()
    raw["total"] = "1.60"
    document = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='qUnid'])") == "3.0000"
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='vUnid'])") == "0.2000"
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='vIPI'])") == "0.60"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.60"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


@pytest.mark.parametrize("ipi_cst", ["51", "52", "53", "54", "55"])
def test_ipi_non_taxed_output_cst_uses_ipint_and_validates_schema(
    mapping, signing_material, ipi_cst
):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        ipi_cst=ipi_cst,
        ipi_enquiry_code="999",
        ipi_calculation_mode="non_taxed",
    )
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, nfe_rates=rates)),)
    document = map_bling_document(order(), **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IPINT']/*[local-name()='CST'])") == ipi_cst
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vIPI'])") == "0.00"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_ipi_per_unit_requires_taxable_quantity(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=True)
    line = document.items[0]
    rates = replace(
        line.tax_decision.outcome.nfe_rates,
        ipi_unit_amount=Decimal("0.2000"),
        ipi_enquiry_code="999",
        ipi_calculation_mode="per_taxable_unit",
        ipi_cst="50",
    )
    decision = replace(
        line.tax_decision, outcome=replace(line.tax_decision.outcome, nfe_rates=rates)
    )
    with pytest.raises(FiscalValidationError, match="taxable quantity"):
        calculate_nfe_line(
            decision,
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
        )


def test_bling_policy_rule_parses_all_explicit_st_difal_rtc_and_ipi_modes():
    from kordena_fiscal.runtime.bling_preparation import _rule

    base = {
        "rule_id": "synthetic-complete",
        "version": 1,
        "priority": 1,
        "source_normative": "SYNTHETIC ONLY",
        "effective_from": NOW.isoformat(),
        "selector": {
            "state_code": "RJ",
            "tax_regime": 3,
            "recipient_profile": "consumer_final",
            "ncm_prefix": "21",
        },
        "outcome": {
            "cfop": "6102",
            "icms_code": "00",
            "pis_cst": "01",
            "cofins_cst": "01",
            "ibs_cbs_cst_code": "000",
            "ibs_cbs_classification_code": "000001",
            "ibs_cbs_classification_table_version": "SYNTHETIC_TABLE",
            "nfe_rates": {
                "icms_rate": "12",
                "pis_rate": "1.65",
                "cofins_rate": "7.6",
                "pis_base": "net",
                "cofins_base": "net",
                "difal_destination_rate": "18",
                "difal_interstate_rate": "12",
                "difal_destination_share": "100",
                "fcp_destination_rate": "2",
                "rtc_uf_rate": "0.1",
                "rtc_municipal_rate": "0",
                "rtc_cbs_rate": "0.9",
                "rtc_base_mode": "net",
                "rtc_financial_mode": "informational_2026",
                "ipi_cst": "51",
                "ipi_enquiry_code": "999",
                "ipi_calculation_mode": "non_taxed",
            },
        },
    }
    rule = _rule(base)
    rates = rule.outcome.nfe_rates
    assert rates is not None
    assert rates.difal_destination_rate == Decimal("18")
    assert rates.fcp_destination_rate == Decimal("2")
    assert rates.rtc_cbs_rate == Decimal("0.9")
    assert rates.ipi_cst == "51"
    assert rule.outcome.ibs_cbs_classification_table_version == "SYNTHETIC_TABLE"


@pytest.mark.parametrize(
    ("cst", "extra", "expected"),
    [
        ("20", {"icms_reduction_rate": "20", "fcp_rate": "2"}, ("0.80", "0.14", "0.00", "1.00")),
        (
            "30",
            {
                "st_rate": "18",
                "st_mva_rate": "40",
                "st_base_mode": "net_mva",
                "fcp_st_rate": "2",
                "icms_rate": "0",
            },
            ("0.00", "0.00", "0.25", "1.28"),
        ),
        (
            "70",
            {
                "icms_reduction_rate": "20",
                "st_rate": "30",
                "st_mva_rate": "40",
                "st_base_mode": "net_mva",
                "fcp_st_rate": "2",
            },
            ("0.80", "0.14", "0.28", "1.31"),
        ),
    ],
)
def test_expanded_icms_reduction_st_signed_official_schema(
    mapping, signing_material, cst, extra, expected
):
    """ICMS 20/30/70 require approved parameters, signed XML and payment identity."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    updates = {k: Decimal(v) if k.endswith("_rate") else v for k, v in extra.items()}
    rates = replace(rule.outcome.nfe_rates, **updates)
    mapping["rules"] = (
        replace(rule, outcome=replace(rule.outcome, icms_code=cst, nfe_rates=rates)),
    )
    mapping["payments"] = (
        FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal(expected[3]))),
    )
    raw = order()
    raw["total"] = expected[3]
    document = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput(
            "35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678
        )
    )
    xml = build_nfe_sale(document, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)

    def field(name):
        return root.xpath(
            "string(//*[local-name()='ICMS" + cst + "']/*[local-name()='" + name + "'])"
        )

    if cst != "30":
        assert field("vBC") == expected[0]
        assert field("vICMS") == expected[1]
        assert field("pRedBC") == "20.0000"
    else:
        assert field("modBCST") == "4"
        assert field("vBCST") == "1.40"
        assert not field("vBC")
    if cst in {"30", "70"}:
        assert field("vICMSST") == expected[2]
        assert field("vFCPST") == "0.03"
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == expected[3]
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_ipi_99_other_output_taxed_signed_schema(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        ipi_rate=Decimal("10"),
        ipi_cst="99",
        ipi_enquiry_code="999",
        ipi_calculation_mode="net_icms_excluded",
    )
    mapping["rules"] = (replace(rule, outcome=replace(rule.outcome, nfe_rates=rates)),)
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("1.10"))),)
    raw = order()
    raw["total"] = "1.10"
    doc = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput("35", NOW, doc.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678)
    )
    xml = build_nfe_sale(doc, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='CST'])") == "99"
    assert root.xpath("string(//*[local-name()='IPITrib']/*[local-name()='vIPI'])") == "0.10"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_pis_cofins_quantity_cst03_signed_schema(mapping, signing_material):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        pis_rate=Decimal(0),
        cofins_rate=Decimal(0),
        pis_unit_amount=Decimal("0.0500"),
        cofins_unit_amount=Decimal("0.1000"),
    )
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                pis_cst="03",
                cofins_cst="03",
                nfe_rates=rates,
            ),
        ),
    )
    doc = map_bling_document(order(), **mapping)
    key = build_access_key(
        AccessKeyInput("35", NOW, doc.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678)
    )
    xml = build_nfe_sale(doc, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    for kind, result, unit in (("PIS", "0.15", "0.0500"), ("COFINS", "0.30", "0.1000")):

        def field(name, kind=kind):
            return root.xpath(
                "string(//*[local-name()='" + kind + "Qtde']/*[local-name()='" + name + "'])"
            )

        assert field("CST") == "03"
        assert field("qBCProd") == "3.0000"
        assert field("vAliqProd") == unit
        assert field("v" + kind) == result
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_tax_matrix_missing_rate_or_wrong_cst_fails_closed(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=True)
    line = document.items[0]
    rates = line.tax_decision.outcome.nfe_rates
    assert rates is not None
    with pytest.raises(FiscalValidationError, match="reduction"):
        calculate_nfe_line(
            replace(line.tax_decision, outcome=replace(line.tax_decision.outcome, icms_code="20")),
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
        )
    with pytest.raises(FiscalValidationError, match="ST policy"):
        calculate_nfe_line(
            replace(line.tax_decision, outcome=replace(line.tax_decision.outcome, icms_code="30")),
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
        )
    with pytest.raises(FiscalValidationError, match="CST 03"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    line.tax_decision.outcome,
                    pis_cst="03",
                    nfe_rates=replace(rates, pis_rate=Decimal(0)),
                ),
            ),
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
            taxable_quantity=Decimal("3"),
        )
    with pytest.raises(FiscalValidationError, match="unit contribution"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    line.tax_decision.outcome,
                    nfe_rates=replace(rates, pis_unit_amount=Decimal("0.0500")),
                ),
            ),
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
        )


@pytest.mark.parametrize(
    ("rtc_cst", "class_code", "extra", "expected_total"),
    [
        (
            "200",
            "200001",
            {
                "rtc_uf_rate": Decimal("0.1"),
                "rtc_municipal_rate": Decimal("0"),
                "rtc_cbs_rate": Decimal("0.9"),
                "rtc_base_mode": "net",
                "rtc_uf_reduction_rate": Decimal("60"),
                "rtc_municipal_reduction_rate": Decimal("60"),
                "rtc_cbs_reduction_rate": Decimal("60"),
            },
            "100.40",
        ),
        ("410", "410008", {"rtc_base_mode": "non_taxed"}, "100.00"),
        ("400", "400003", {"rtc_base_mode": "non_taxed"}, "100.00"),
    ],
)
def test_rtc_expanded_cst200_410_signed_schema(
    mapping, signing_material, rtc_cst, class_code, extra, expected_total
):
    """Synthetic legal classification tests only; approval remains policy-dependent."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        rtc_financial_mode="informational_2026",
        **extra,
    )
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                ibs_cbs_cst_code=rtc_cst,
                ibs_cbs_classification_code=class_code,
                ibs_cbs_classification_table_version="IT-2025.002-v1.71",
                nfe_rates=rates,
            ),
        ),
    )
    mapping["payments"] = (FiscalPaymentSnapshot(PaymentMethodKind.PIX, Money(Decimal("100.00"))),)
    raw = order()
    raw["itens"][0]["quantidade"] = "1"
    raw["itens"][0]["valor"] = "100.00"
    raw["totalProdutos"] = "100.00"
    raw["total"] = "100.00"
    doc = map_bling_document(raw, **mapping)
    key = build_access_key(
        AccessKeyInput("35", NOW, doc.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678)
    )
    xml = build_nfe_sale(doc, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    assert root.xpath("string(//*[local-name()='IBSCBS']/*[local-name()='CST'])") == rtc_cst
    assert (
        root.xpath("string(//*[local-name()='total']/*[local-name()='vNFTot'])") == expected_total
    )
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "100.00"
    if rtc_cst == "200":
        assert (
            root.xpath(
                "string(//*[local-name()='gIBSUF']/*[local-name()='gRed']/*[local-name()='pRedAliq'])"
            )
            == "60.0000"
        )
        assert (
            root.xpath(
                "string(//*[local-name()='gIBSUF']/*[local-name()='gRed']/*[local-name()='pAliqEfet'])"
            )
            == "0.0400"
        )
        assert root.xpath("string(//*[local-name()='gCBS']/*[local-name()='vCBS'])") == "0.36"
    else:
        assert not root.xpath("//*[local-name()='IBSCBS']/*[local-name()='gIBSCBS']")
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_rtc_cst200_and_410_reject_incoherent_policy(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=True)
    line = document.items[0]
    original = line.tax_decision.outcome
    rates = original.nfe_rates
    assert rates is not None
    base_rates = replace(
        rates,
        rtc_uf_rate=Decimal("0.1"),
        rtc_municipal_rate=Decimal("0"),
        rtc_cbs_rate=Decimal("0.9"),
        rtc_base_mode="net",
        rtc_financial_mode="informational_2026",
    )
    with pytest.raises(FiscalValidationError, match="requires explicit reductions"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    original,
                    ibs_cbs_cst_code="200",
                    ibs_cbs_classification_code="200001",
                    ibs_cbs_classification_table_version="v1.71",
                    nfe_rates=base_rates,
                ),
            ),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )
    with pytest.raises(FiscalValidationError, match="forbids standard taxation"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    original,
                    ibs_cbs_cst_code="410",
                    ibs_cbs_classification_code="410008",
                    ibs_cbs_classification_table_version="v1.71",
                    nfe_rates=base_rates,
                ),
            ),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )
    with pytest.raises(FiscalValidationError, match="classification must be approved"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    original,
                    ibs_cbs_cst_code="410",
                    ibs_cbs_classification_code="000001",
                    ibs_cbs_classification_table_version="v1.71",
                    nfe_rates=replace(
                        rates, rtc_base_mode="non_taxed", rtc_financial_mode="informational_2026"
                    ),
                ),
            ),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )


@pytest.mark.parametrize(
    ("cst", "mode", "expected_pis", "expected_cofins"),
    [
        ("99", "zero", "0.00", "0.00"),
        ("49", "percentage", "0.01", "0.06"),
        ("99", "per_unit", "0.15", "0.30"),
    ],
)
def test_pis_cofins_other_outgoing_cst_schema(
    mapping, signing_material, cst, mode, expected_pis, expected_cofins
):
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=True)
    rule = mapping["rules"][0]
    rates = replace(
        rule.outcome.nfe_rates,
        pis_rate=Decimal(0) if mode != "percentage" else Decimal("1.65"),
        cofins_rate=Decimal(0) if mode != "percentage" else Decimal("7.6"),
        pis_unit_amount=Decimal("0.0500") if mode == "per_unit" else None,
        cofins_unit_amount=Decimal("0.1000") if mode == "per_unit" else None,
        pis_other_mode=mode,
        cofins_other_mode=mode,
    )
    mapping["rules"] = (
        replace(
            rule,
            outcome=replace(
                rule.outcome,
                pis_cst=cst,
                cofins_cst=cst,
                nfe_rates=rates,
            ),
        ),
    )
    doc = map_bling_document(order(), **mapping)
    key = build_access_key(
        AccessKeyInput("35", NOW, doc.issuer.cnpj, ElectronicInvoiceModel.NFE, 1, 1, 1, 12345678)
    )
    xml = build_nfe_sale(doc, key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    for name, expected in (("PIS", expected_pis), ("COFINS", expected_cofins)):
        outer = root.xpath("//*[local-name()='" + name + "Outr']")
        assert len(outer) == 1
        value = outer[0].xpath("string(./*[local-name()='v" + name + "'])")
        assert value == expected
        assert outer[0].xpath("string(./*[local-name()='CST'])") == cst
        if mode == "zero":
            assert outer[0].xpath("string(./*[local-name()='qBCProd'])") == "0.0000"
            assert outer[0].xpath("string(./*[local-name()='vAliqProd'])") == "0.0000"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1
    )
    OfficialNfeEnvelopeValidator()(signed)


def test_pis_cofins_other_mode_is_never_inferred(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=True)
    line = document.items[0]
    original = line.tax_decision.outcome
    rates = original.nfe_rates
    assert rates is not None
    with pytest.raises(FiscalValidationError, match="explicit calculation mode"):
        calculate_nfe_line(
            replace(line.tax_decision, outcome=replace(original, pis_cst="99")),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )
    with pytest.raises(FiscalValidationError, match="zero other contribution"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    original,
                    pis_cst="99",
                    nfe_rates=replace(rates, pis_other_mode="zero"),
                ),
            ),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )
    with pytest.raises(FiscalValidationError, match="requires CST"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(
                    original,
                    nfe_rates=replace(rates, pis_other_mode="percentage"),
                ),
            ),
            net_amount=Decimal("1.00"),
            regime=TaxRegimeCode.NORMAL,
        )


@pytest.mark.parametrize(
    ("normal", "code", "group"),
    [
        (True, "40", "ICMS40"),
        (True, "41", "ICMS40"),
        (True, "50", "ICMS40"),
        (False, "103", "ICMSSN102"),
        (False, "300", "ICMSSN102"),
        (False, "400", "ICMSSN102"),
    ],
)
def test_b01_additional_supported_icms_codes_have_signed_official_schema(
    mapping, signing_material, normal, code, group
):
    """Previously supported no-ICMS codes must never invent rates or credit."""
    from lxml import etree

    from kordena_fiscal.domain import ElectronicInvoiceModel
    from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions, build_nfe_sale
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml
    from kordena_fiscal.xml import AccessKeyInput, build_access_key
    from kordena_fiscal.xml.official_nfe_schema import OfficialNfeEnvelopeValidator

    sale_document(mapping, normal=normal)
    rule = mapping["rules"][0]
    rates = replace(rule.outcome.nfe_rates, icms_rate=Decimal("0"))
    mapping["rules"] = (
        replace(rule, outcome=replace(rule.outcome, icms_code=code, nfe_rates=rates)),
    )
    document = map_bling_document(order(), **mapping)
    access_key = build_access_key(
        AccessKeyInput("35", NOW, document.issuer.cnpj, ElectronicInvoiceModel.NFE,
                       1, 1, 1, 12345678)
    )
    xml = build_nfe_sale(document, access_key, NfeSaleOptions("VENDA", 1, 9))
    root = etree.fromstring(xml)
    matches = root.xpath("//*[local-name()='" + group + "']")
    assert len(matches) == 1
    element = matches[0]
    code_field = "CST" if normal else "CSOSN"
    assert element.xpath("string(./*[local-name()='" + code_field + "'])") == code
    assert not element.xpath("./*[local-name()='vICMS']")
    assert not element.xpath("./*[local-name()='pICMS']")
    assert root.xpath("string(//*[local-name()='ICMSTot']/*[local-name()='vNF'])") == "1.00"
    signed = sign_nfe_envi_xml(
        xml, signing_material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1,
    )
    OfficialNfeEnvelopeValidator()(signed)


@pytest.mark.parametrize(
    ("normal", "code"),
    [
        (True, "51"), (True, "60"), (True, "90"),
        (False, "101"), (False, "201"), (False, "202"),
        (False, "203"), (False, "500"), (False, "900"),
    ],
)
def test_b01_unmodelled_icms_never_degrades_to_a_supported_tax_group(
    mapping, normal, code
):
    """Explicitly block retained ST, credits, deferment and opaque CST modes."""
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=normal)
    line = document.items[0]
    with pytest.raises(FiscalValidationError, match="unsupported"):
        calculate_nfe_line(
            replace(
                line.tax_decision,
                outcome=replace(line.tax_decision.outcome, icms_code=code),
            ),
            net_amount=line.net_amount.amount,
            regime=document.issuer.tax_regime,
        )


def test_rtc_cst400_and_unsupported_group_classifications_are_refused(mapping):
    from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

    document = sale_document(mapping, normal=True)
    line = document.items[0]
    original = line.tax_decision.outcome
    rates = original.nfe_rates
    assert rates is not None
    taxed = replace(
        rates, rtc_uf_rate=Decimal("0.1"), rtc_municipal_rate=Decimal("0"),
        rtc_cbs_rate=Decimal("0.9"), rtc_base_mode="net",
        rtc_financial_mode="informational_2026",
    )

    def calc(cst, code, policy):
        return calculate_nfe_line(
            replace(line.tax_decision, outcome=replace(
                original, ibs_cbs_cst_code=cst, ibs_cbs_classification_code=code,
                ibs_cbs_classification_table_version="v1.71", nfe_rates=policy,
            )),
            net_amount=Decimal("1.00"), regime=TaxRegimeCode.NORMAL,
        )

    with pytest.raises(FiscalValidationError, match="CST 400 forbids standard taxation"):
        calc("400", "400003", taxed)
    with pytest.raises(FiscalValidationError, match="gCredPresOper"):
        calc("000", "000003", taxed)
    with pytest.raises(FiscalValidationError, match="gEstornoCred"):
        calc("410", "410026", replace(
            rates, rtc_base_mode="non_taxed", rtc_financial_mode="informational_2026",
        ))
    with pytest.raises(FiscalValidationError, match="approved and aligned"):
        calc("510", "510001", taxed)
