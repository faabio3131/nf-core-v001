"""Extrema official-XSD canonical persistence/numbering/authorization/recovery E2E.

All CNPJ, certificate and invoice identifiers are synthetic. Never transmits
HTTP, never impersonates a real taxpayer and never certifies live homologation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from test_webiss_extrema_official_rtc_accepted_receipts import (
    _accepted_xml,
    _wrap_soap,
)

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
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
from kordena_fiscal.gateway.mg_webiss_soap import (
    EXTREMA_WEBISS_PROVIDER_ID,
    WebissExtremaHomologationTransport,
    WebissMgContractError,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import Abrasf203Operation
from kordena_fiscal.gateway.webiss_2026_schema import load_pinned_extrema_webiss_rtc_schema
from kordena_fiscal.gateway.webiss_extrema_canonical import (
    WebissExtremaCanonicalNfseGateway,
)
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseQueryClient,
    NfseServiceLine,
)
from kordena_fiscal.issuance.webiss_extrema_builder import (
    ExtremaRpsIntent,
    ExtremaServiceTaker,
    build_extrema_rps_xml,
    decode_extrema_intent,
    encode_extrema_intent,
)
from kordena_fiscal.lifecycle import FiscalDocumentState
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError
from kordena_fiscal.persistence.sqlite import SqliteFiscalDatabase
from kordena_fiscal.vault import EphemeralCertificateMaterial

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
RETENTION = RetentionPolicyMetadata(policy_id="nfcore-fiscal-archive", policy_version=1)


_ISSUER_CNPJ = Cnpj("11222333000181")
_PASSWORD = b"nfcore-synthetic-only"


def _certificate() -> EphemeralCertificateMaterial:
    """Generate an ephemeral test A1, never a real certificate or credential."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Extrema A1")])
    now = datetime.now(UTC)
    cn = _ISSUER_CNPJ.value.encode("ascii")
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(
                ObjectIdentifier("2.16.76.1.3.3"), bytes([0x04, len(cn)]) + cn,
            ),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return EphemeralCertificateMaterial(
        reference_id="synthetic:extrema-only",
        pkcs12_bytes=pkcs12.serialize_key_and_certificates(
            b"synthetic", key, cert, None,
            serialization.BestAvailableEncryption(_PASSWORD),
        ),
        password=_PASSWORD,
    )


def _request() -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="corr-extrema-a", host_namespace="host-a",
    )
    city = BrazilianJurisdiction("MG", "3125101")
    issuer = FiscalProfile(
        profile_id="extrema-synthetic-issuer", scope=scope,
        cnpj=_ISSUER_CNPJ, legal_name="Empresa Fiscal Sintetica de Extrema Ltda",
        tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("MG", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua de Teste", number="100", district="Centro",
            municipality_name="Extrema", jurisdiction=city, postal_code="37640000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    document = NfseCanonicalDocument(
        document_id="nfse-extrema-doc-1", scope=scope,
        source=SourceReference("service-order", "order-extrema-1"),
        issued_at=datetime(2026, 11, 6, 12, tzinfo=UTC),
        competence_date=datetime(2026, 11, 6, tzinfo=UTC).date(),
        issuer=issuer, service_jurisdiction=city,
        services=(NfseServiceLine(
            line_number=1, municipal_service_code="0107",
            national_taxation_code="010701", description="Servico sintetico",
            gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("3.00")),
            iss_withheld=False, rule_version=1, source_normative="SYNTHETIC-RTC-TEST",
        ),),
        service_taker_reference="taker-ref-1",
    )
    return NfseAuthorizationRequest.build(document)


def _intent(request, reservation) -> ExtremaRpsIntent:
    return ExtremaRpsIntent(
        request_fingerprint=request.request_fingerprint,
        issuer_cnpj=request.document.issuer.cnpj,
        reservation=reservation,
        rule_reference="urn:nfcore:test:rtc-policy:2026:rev1",
        exigibilidade_iss="1",
        incidence_municipality_ibge="3125101",
        iss_rate_fraction=Decimal("0.0300"),
        incentive_fiscal=False,
        nbs_code="123456789",
        rtc_operation_indicator="010101",
        rtc_cst="000",
        rtc_tax_class="000001",
        taker=ExtremaServiceTaker(
            reference=request.document.service_taker_reference,
            cnpj=Cnpj("12345678000195"),
            legal_name="Tomador de teste sintético",
        ),
    )


def _prepare(app: FiscalApplicationService, request) -> ExtremaRpsIntent:
    app.prepare_nfse_authorization(
        request.document, occurred_at=NOW, retention=RETENTION,
        extrema_intent_builder=lambda reservation: _intent(request, reservation),
        extrema_rps_series=1,
    )
    return app.load_extrema_rps_intent(
        request.document.scope, request.document.document_id,
    )


def _success_response(operation: Abrasf203Operation, intent) -> bytes:
    old = _accepted_xml(operation)
    insertion = (
        "<Rps><IdentificacaoRps>"
        f"<Numero>{intent.reservation.number}</Numero>"
        f"<Serie>{intent.reservation.key.series}</Serie>"
        "<Tipo>1</Tipo></IdentificacaoRps>"
        "<DataEmissao>2026-11-06</DataEmissao><Status>1</Status></Rps>"
    ).encode()
    # The mocked official receiver must echo the immutable original RPS
    # identity and canonical buyer in its signed/validated response.
    updated = old.replace(
        b"<Competencia>", insertion + b"<Competencia>", 1,
    ).replace(
        b"<Cnpj>11222333000181</Cnpj></CpfCnpj>"
        b"</IdentificacaoTomador>",
        b"<Cnpj>12345678000195</Cnpj></CpfCnpj>"
        b"</IdentificacaoTomador>",
        1,
    )
    return _wrap_soap(operation, updated)


def _gateway(app, intent, exchange):
    evidence, validator = load_pinned_extrema_webiss_rtc_schema()
    resolver = Mock()
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    certificate = Mock(return_value=_certificate())
    transport = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=certificate,
        municipal_schema_evidence=evidence,
        municipal_schema_validator=validator, exchange=exchange,
    )
    canonical_preaudit, service_preaudit = Mock(), Mock()
    gateway = WebissExtremaCanonicalNfseGateway(
        transport=transport,
        load_intent=app.load_extrema_rps_intent,
        resolve_certificate=certificate,
        canonical_preaudit=canonical_preaudit,
        service_preaudit=service_preaudit,
        cancellation_preaudit=Mock(),
        municipal_validator=validator,
    )
    return gateway, resolver, certificate, canonical_preaudit, service_preaudit


def test_builder_generates_real_xsd_valid_webiss_2026_rtc_rps(tmp_path):
    database = SqliteFiscalDatabase(tmp_path / "rps-xsd.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    request = _request()
    intent = _prepare(app, request)
    _, validator = load_pinned_extrema_webiss_rtc_schema()
    xml = build_extrema_rps_xml(request, intent, validator=validator)
    validator.validate_document(xml)
    assert b"<CodigoNbs>123456789</CodigoNbs>" in xml
    assert b"<cClassTrib>000001</cClassTrib>" in xml
    assert b"<ValorIss>3.00</ValorIss>" in xml
    assert b"<Aliquota>3.0000</Aliquota>" in xml
    assert b"<Numero>1</Numero>" in xml
    assert decode_extrema_intent(
        encode_extrema_intent(intent), scope=request.document.scope, request=request,
    ) == intent
    with pytest.raises(FiscalValidationError, match="tax intent"):
        build_extrema_rps_xml(
            request, replace(intent, iss_rate_fraction=Decimal("0.0500")),
            validator=validator,
        )


def test_canonical_durable_issue_replay_query_without_resend(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "extrema-end-to-end.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request()
    intent = _prepare(app, request)
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    assert restarted.load_extrema_rps_intent(
        request.document.scope, request.document.document_id,
    ) == intent
    with pytest.raises(Exception, match="cannot change"):
        restarted.prepare_nfse_authorization(
            request.document, occurred_at=NOW, retention=RETENTION,
        )
    replay = restarted.prepare_nfse_authorization(
        request.document, occurred_at=NOW, retention=RETENTION,
        extrema_intent_builder=lambda _reservation: pytest.fail(
            "replay must never allocate a new RPS number"
        ),
        extrema_rps_series=1,
    )
    assert replay.replay
    calls = []
    def exchange(data, soap_action, _context, _timeout):
        calls.append(soap_action)
        if "GerarNfse" in soap_action:
            raise WebissMgContractError("Synthetic ambiguous provider timeout")
        assert "ConsultarNfsePorRps" in soap_action
        return _success_response(Abrasf203Operation.QUERY_RPS, intent)

    gateway, resolver, cert, audit, service_audit = _gateway(restarted, intent, exchange)
    with pytest.raises(WebissMgContractError, match="ambiguous"):
        restarted.authorize_prepared_document(
            document_id=request.document.document_id, request=request,
            gateway=NfseGatewayClient(gateway), occurred_at=NOW,
        )
    with db() as uow:
        current = uow.lifecycle.get(request.document.document_id)
        assert current is not None
        assert current.state is FiscalDocumentState.TRANSMITTING
    assert len(calls) == 1 and "GerarNfse" in calls[0]
    same = restarted.authorize_prepared_document(
        document_id=request.document.document_id, request=request,
        gateway=NfseGatewayClient(gateway), occurred_at=NOW,
    )
    assert same.replay
    assert len(calls) == 1
    result = restarted.reconcile_prepared_nfse_authorization(
        scope=request.document.scope, document_id=request.document.document_id,
        client=NfseQueryClient(gateway), occurred_at=NOW, retention=RETENTION,
    )
    assert result.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert result.query_result.status is AuthorizationStatus.AUTHORIZED
    assert len(calls) == 2
    assert cert.call_count > 0
    assert audit.call_count == 1
    assert service_audit.call_count == 1


def test_no_duplicate_reserved_rps_or_cross_tenant_use(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "scope.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request()
    first = _prepare(app, request)
    second_request = NfseAuthorizationRequest.build(
        replace(
            request.document, document_id="nfse-2",
            source=SourceReference("service-order", "order-other-2"),
        )
    )
    second = _prepare(app, second_request)
    assert first.reservation.number + 1 == second.reservation.number
    assert first.reservation.reservation_token != second.reservation.reservation_token
    other = replace(request.document.scope, tenant_id="attacker")
    with pytest.raises((PersistenceConflictError, PersistenceStateError)):
        app.load_extrema_rps_intent(other, request.document.document_id)
    with pytest.raises(FiscalValidationError):
        build_extrema_rps_xml(
            request, replace(first, reservation=replace(first.reservation, key=replace(
                first.reservation.key, unit_id="other-unit",
            ))),
            validator=load_pinned_extrema_webiss_rtc_schema()[1],
        )


def test_tampered_immutable_archive_and_rtc_rejected_before_a1(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "tamper.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request()
    intent = _prepare(app, request)
    original = encode_extrema_intent(intent)
    import json
    mutation = json.loads(original)
    mutation["reservation"]["token"] = "0" * 64
    with pytest.raises(FiscalValidationError, match="invalid or mutated"):
        decode_extrema_intent(
            json.dumps(mutation).encode(), scope=request.document.scope, request=request,
        )
    bad_scope = replace(request.document.scope, environment=FiscalEnvironment.PRODUCTION)
    with pytest.raises(FiscalValidationError):
        app.prepare_nfse_authorization(
            replace(request.document, scope=bad_scope),
            occurred_at=NOW, retention=RETENTION,
            extrema_intent_builder=lambda reservation: _intent(request, reservation),
            extrema_rps_series=1,
        )
    wrong_muni = replace(
        request.document, service_jurisdiction=BrazilianJurisdiction("MG", "3170107"),
    )
    with pytest.raises(FiscalValidationError):
        build_extrema_rps_xml(
            NfseAuthorizationRequest.build(wrong_muni),
            intent, validator=load_pinned_extrema_webiss_rtc_schema()[1],
        )

def test_original_webiss_cancel_is_archived_and_never_resent(tmp_path):
    database = SqliteFiscalDatabase(tmp_path / "extrema-cancellation.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    request = _request()
    intent = _prepare(app, request)
    operations = []

    def exchange(_body, action, _context, _timeout):
        operations.append(action)
        if "GerarNfse" in action:
            return _success_response(Abrasf203Operation.GENERATE, intent)
        if "CancelarNfse" in action:
            return _wrap_soap(
                Abrasf203Operation.CANCEL,
                _accepted_xml(Abrasf203Operation.CANCEL),
            )
        raise AssertionError("Unexpected fiscal operation")

    gateway, _, _, _, _ = _gateway(app, intent, exchange)
    sent = app.authorize_prepared_document(
        document_id=request.document.document_id, request=request,
        gateway=NfseGatewayClient(gateway), occurred_at=NOW,
    )
    assert sent.lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert len(operations) == 1
    first = app.cancel_prepared_extrema_nfse(
        scope=request.document.scope,
        document_id=request.document.document_id,
        cancellation_code="1", gateway=gateway,
        occurred_at=NOW, retention=RETENTION,
    )
    assert first.result.confirmed
    assert first.lifecycle.state is FiscalDocumentState.CANCELLED
    assert len(operations) == 2
    from kordena_fiscal.persistence.ports import PersistenceStateError
    with pytest.raises(PersistenceStateError):
        app.cancel_prepared_extrema_nfse(
            scope=request.document.scope,
            document_id=request.document.document_id,
            cancellation_code="1", gateway=gateway,
            occurred_at=NOW, retention=RETENTION,
        )
    assert len(operations) == 2


def test_timeout_on_cancel_stays_claimed_without_duplicate_post(tmp_path):
    database = SqliteFiscalDatabase(tmp_path / "extrema-cancellation-timeout.sqlite")
    database.initialize()
    app = FiscalApplicationService(database)
    request = _request()
    intent = _prepare(app, request)
    operations = []

    def exchange(_body, action, _context, _timeout):
        operations.append(action)
        if "GerarNfse" in action:
            return _success_response(Abrasf203Operation.GENERATE, intent)
        raise WebissMgContractError("Synthetic unknown delivery state")

    gateway, _, _, _, _ = _gateway(app, intent, exchange)
    app.authorize_prepared_document(
        document_id=request.document.document_id, request=request,
        gateway=NfseGatewayClient(gateway), occurred_at=NOW,
    )
    with pytest.raises(WebissMgContractError, match="unknown delivery"):
        app.cancel_prepared_extrema_nfse(
            scope=request.document.scope,
            document_id=request.document.document_id,
            cancellation_code="1", gateway=gateway,
            occurred_at=NOW, retention=RETENTION,
        )
    with database() as uow:
        current = uow.lifecycle.get(request.document.document_id)
    assert current is not None
    assert current.state is FiscalDocumentState.CANCEL_REQUESTED
    from kordena_fiscal.persistence.ports import PersistenceStateError
    with pytest.raises(PersistenceStateError):
        app.cancel_prepared_extrema_nfse(
            scope=request.document.scope,
            document_id=request.document.document_id,
            cancellation_code="1", gateway=gateway,
            occurred_at=NOW, retention=RETENTION,
        )
    assert len(operations) == 2

def _synthetic_substitution_receipt(original, old_intent, replacement, new_intent):
    """Compose positive municipal XML from two individual schema-checked fixtures."""
    from copy import deepcopy

    from lxml import etree

    ns = "{http://www.abrasf.org.br/nfse.xsd}"
    def _source_receipt(intent):
        soap = etree.fromstring(
            _success_response(Abrasf203Operation.GENERATE, intent),
            parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
            ),
        )
        output = soap.find(".//outputXML")
        assert output is not None and output.text
        return etree.fromstring(
            output.text.encode(),
            parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
            ),
        )

    old_xml = _source_receipt(old_intent)
    new_xml = _source_receipt(new_intent)
    old_comp = old_xml.find(f"{ns}ListaNfse/{ns}CompNfse")
    new_comp = new_xml.find(f"{ns}ListaNfse/{ns}CompNfse")
    assert old_comp is not None and new_comp is not None
    original_ref = old_comp.find(f"{ns}Nfse/{ns}InfNfse/{ns}Numero")
    replacement_ref = new_comp.find(f"{ns}Nfse/{ns}InfNfse/{ns}Numero")
    assert original_ref is not None and replacement_ref is not None
    original_ref.text = "123"
    replacement_ref.text = "124"
    new_key = new_comp.find(f"{ns}Nfse/{ns}InfNfse/{ns}ChaveAcesso")
    old_key = old_comp.find(f"{ns}Nfse/{ns}InfNfse/{ns}ChaveAcesso")
    assert new_key is not None and old_key is not None
    assert new_key.text and old_key.text and len(new_key.text) == 50
    # Test-only distinct replacement key; never synthesize a provider key in
    # production code or assert that an actual municipal event happened.
    new_key.text = new_key.text[:-1] + "1"
    assert new_key.text != old_key.text
    root = etree.Element(
        f"{ns}SubstituirNfseResposta",
        nsmap={"a": "http://www.abrasf.org.br/nfse.xsd"},
    )
    retorno = etree.SubElement(root, f"{ns}RetSubstituicao")
    old = etree.SubElement(retorno, f"{ns}NfseSubstituida")
    old.append(deepcopy(old_comp))
    new = etree.SubElement(retorno, f"{ns}NfseSubstituidora")
    new.append(deepcopy(new_comp))
    data = etree.tostring(root, encoding="utf-8")
    _, validator = load_pinned_extrema_webiss_rtc_schema()
    validator.validate_document(data)
    return _wrap_soap(Abrasf203Operation.SUBSTITUTE, data)


def test_cancel_substituted_invoice_uses_new_note_never_cancelled_original(
    tmp_path,
):
    """A substitution receipt contains old and new notes: select the new one."""
    from lxml import etree

    db = SqliteFiscalDatabase(tmp_path / "substitution-chain.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    original = _request()
    old_intent = _prepare(app, original)
    replacement = NfseAuthorizationRequest.build(replace(
        original.document,
        document_id="nfse-extrema-followup",
        source=SourceReference("service-order", "order-followup"),
    ))
    new_intent = _prepare(app, replacement)
    response = etree.fromstring(
        _synthetic_substitution_receipt(
            original, old_intent, replacement, new_intent,
        ),
        parser=etree.XMLParser(no_network=True, resolve_entities=False),
    )
    content = response.find(".//outputXML")
    assert content is not None and content.text
    exchange = Mock()
    gateway, _, _, _, _ = _gateway(app, new_intent, exchange)
    signed, note_number = gateway.prepare_cancellation(
        request=replacement, authorized_xml=content.text.encode(),
        cancellation_code="1",
    )
    assert note_number == "124"
    envelope = etree.fromstring(signed.body)
    transport_data = envelope.find(".//nfseDadosMsg")
    assert transport_data is not None and transport_data.text
    municipal = etree.fromstring(
        transport_data.text.encode(),
        parser=etree.XMLParser(no_network=True, resolve_entities=False),
    )
    actual = municipal.findtext(
        ".//{http://www.abrasf.org.br/nfse.xsd}IdentificacaoNfse/"
        "{http://www.abrasf.org.br/nfse.xsd}Numero",
    )
    assert actual == "124"
    exchange.assert_not_called()


def test_real_substitution_commits_both_lifecycles_atomically(tmp_path):
    db = SqliteFiscalDatabase(tmp_path / "substitution.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    original = _request()
    old_intent = _prepare(app, original)
    from kordena_fiscal.domain import SourceReference
    from kordena_fiscal.issuance import NfseAuthorizationRequest
    replacement = NfseAuthorizationRequest.build(replace(
        original.document, document_id="nfse-extrema-replacement-2",
        source=SourceReference("service-order", "order-replacement-2"),
    ))
    new_intent = _prepare(app, replacement)
    calls = []

    def exchange(_body, action, _context, _timeout):
        calls.append(action)
        if "GerarNfse" in action:
            return _success_response(Abrasf203Operation.GENERATE, old_intent)
        if "SubstituirNfse" in action:
            return _synthetic_substitution_receipt(
                original, old_intent, replacement, new_intent,
            )
        raise AssertionError("Unexpected municipal SOAP action")

    gateway, _, _, _, _ = _gateway(app, old_intent, exchange)
    issued = app.authorize_prepared_document(
        document_id=original.document.document_id, request=original,
        gateway=NfseGatewayClient(gateway), occurred_at=NOW,
    )
    assert issued.lifecycle.state is FiscalDocumentState.AUTHORIZED
    changed = app.substitute_prepared_extrema_nfse(
        scope=original.document.scope,
        original_id=original.document.document_id,
        replacement_id=replacement.document.document_id,
        cancellation_code="1", gateway=gateway,
        occurred_at=NOW, retention=RETENTION,
    )
    assert changed.result.confirmed
    assert changed.original_lifecycle.state is FiscalDocumentState.CANCELLED
    assert changed.replacement_lifecycle.state is FiscalDocumentState.AUTHORIZED
    assert len(calls) == 2
    with pytest.raises(PersistenceStateError):
        app.substitute_prepared_extrema_nfse(
            scope=original.document.scope,
            original_id=original.document.document_id,
            replacement_id=replacement.document.document_id,
            cancellation_code="1", gateway=gateway,
            occurred_at=NOW, retention=RETENTION,
        )
    assert len(calls) == 2
