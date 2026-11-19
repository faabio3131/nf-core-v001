"""Extrema WebISS SOAP tests; no real issuance, A1, endpoint or approval."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest
from lxml import etree
from test_mg_homologation_authorization import CNPJ, _request
from test_mg_homologation_authorization import material as material
from test_nfse_abrasf203_envelope import _CANCEL, _payload

from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    FiscalDocumentKind,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway import webiss_2026_schema
from kordena_fiscal.gateway.mg_webiss_soap import (
    EXTREMA_WEBISS_HOMOLOGATION_URL,
    EXTREMA_WEBISS_PROVIDER_ID,
    UBERABA_WEBISS_PROVIDER_ID,
    WebissExtremaHomologationTransport,
    WebissMgContractError,
    WebissUberabaHomologationTransport,
    parse_webiss_soap_response,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import (
    Abrasf203Operation,
    _validator,
    prepare_abrasf203_soap,
)
from kordena_fiscal.gateway.webiss_2026_schema import (
    Webiss2026SchemaEvidence,
    WebissMunicipalSchemaUnverified,
)

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WSDL = "http://nfse.abrasf.org.br"
EXTREMA = BrazilianJurisdiction("MG", "3125101")


@pytest.fixture(autouse=True)
def _synthetic_schema_unit_test_only(monkeypatch):
    """Test transport mechanics with generic XSD as a synthetic stand-in.

    Does NOT certify or provision the real municipal WebISS RTC 2026 schema.
    The production pin registry remains empty and blocks all actual dispatch.
    """
    digest = _validator().validate_document(
        _payload(Abrasf203Operation.QUERY_BATCH)
    ).schema_package_sha256
    monkeypatch.setattr(
        webiss_2026_schema, "PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS",
        {"3125101": digest, "3170107": digest},
    )


def _synthetic_evidence(city: str) -> Webiss2026SchemaEvidence:
    digest = _validator().validate_document(
        _payload(Abrasf203Operation.QUERY_BATCH)
    ).schema_package_sha256
    return Webiss2026SchemaEvidence(city, digest)


def _envelope(operation: Abrasf203Operation):
    return prepare_abrasf203_soap(
        operation=operation,
        xml=_payload(operation),
        scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=Mock(),
        preaudit=Mock(),
        municipal_schema_version="2.02",
        municipal_validator=_validator(),
    ) if operation in (
        Abrasf203Operation.QUERY_BATCH, Abrasf203Operation.QUERY_ISSUED,
    ) else None


def _rejection_xml(operation: Abrasf203Operation) -> str:
    roots = {
        Abrasf203Operation.GENERATE: "GerarNfseResposta",
        Abrasf203Operation.SUBMIT_BATCH: "EnviarLoteRpsResposta",
        Abrasf203Operation.QUERY_BATCH: "ConsultarLoteRpsResposta",
        Abrasf203Operation.QUERY_ISSUED: "ConsultarNfseServicoPrestadoResposta",
        Abrasf203Operation.CANCEL: "CancelarNfseResposta",
    }
    name = roots[operation]
    situation = "<Situacao>4</Situacao>" if operation is Abrasf203Operation.QUERY_BATCH else ""
    return (
        f'<{name} xmlns="http://www.abrasf.org.br/nfse.xsd">'
        + situation
        + "<ListaMensagemRetorno><MensagemRetorno><Codigo>E160</Codigo>"
        "<Mensagem>Rejeicao sintetica de teste</Mensagem>"
        "</MensagemRetorno></ListaMensagemRetorno>"
        f"</{name}>"
    )


def _response(operation: Abrasf203Operation, *, xml: str | None = None) -> bytes:
    root = etree.Element(f"{{{SOAP}}}Envelope", nsmap={"soap": SOAP})
    body = etree.SubElement(root, f"{{{SOAP}}}Body")
    wrapper = etree.SubElement(body, f"{{{WSDL}}}{operation.value[1]}Response")
    etree.SubElement(wrapper, "outputXML").text = (
        _rejection_xml(operation) if xml is None else xml
    )
    return etree.tostring(root, encoding="utf-8")


def test_extrema_webiss_soap_endpoint_is_pinned_to_restricted_environment() -> None:
    assert EXTREMA_WEBISS_HOMOLOGATION_URL == (
        "https://homologacao.webiss.com.br/ws/nfse.asmx"
    )
    assert "extremamg.webiss.com.br" not in EXTREMA_WEBISS_HOMOLOGATION_URL


@pytest.mark.parametrize("operation", [Abrasf203Operation.QUERY_BATCH])
def test_exact_municipal_binding_precedes_vault_and_transport(
    operation: Abrasf203Operation, material,
) -> None:
    resolver, cert, exchange = Mock(), Mock(return_value=material), Mock()
    resolver.resolve_provider_id.return_value = "wrong-provider"
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert, exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    envelope = _envelope(operation)
    scope = _request().scope
    args = dict(
        envelope=envelope, operation=operation, scope=scope,
        issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31), jurisdiction=EXTREMA,
    )
    with pytest.raises(WebissMgContractError, match="binding"):
        gateway.exchange_prepared(**args)
    cert.assert_not_called()
    exchange.assert_not_called()
    assert resolver.resolve_provider_id.call_args.kwargs == {
        "scope": scope,
        "document_kind": FiscalDocumentKind.NFSE,
        "jurisdiction": EXTREMA,
        "operation": ConfiguredFiscalOperation.QUERY.value,
    }
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    exchange.return_value = _response(operation)
    assert gateway.exchange_prepared(**args) == _rejection_xml(operation).encode("utf-8")
    cert.assert_called_once_with(scope, CNPJ)
    exchange.assert_called_once()
    assert envelope.soap_action == exchange.call_args.args[1]
    assert exchange.call_args.args[0] == envelope.body


@pytest.mark.parametrize("regime", [
    TaxRegimeCode.MEI,
    TaxRegimeCode.SIMPLES_NACIONAL,
    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
])
def test_national_issuer_must_not_dispatch_into_webiss(
    regime: TaxRegimeCode,
) -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert, exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    with pytest.raises(WebissMgContractError, match="Emissor Nacional"):
        gateway.exchange_prepared(
            envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=regime,
            competence_date=date(2026, 11, 11), jurisdiction=EXTREMA,
        )
    resolver.resolve_provider_id.assert_not_called()
    cert.assert_not_called()
    exchange.assert_not_called()


def test_wrong_state_or_environment_denied_before_vault() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert, exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    args = dict(
        envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
        operation=Abrasf203Operation.QUERY_BATCH,
        scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31), jurisdiction=EXTREMA,
    )
    with pytest.raises(WebissMgContractError, match="scoped MG municipality"):
        gateway.exchange_prepared(
            **{**args, "jurisdiction": BrazilianJurisdiction("MG", "3170107")}
        )
    with pytest.raises(WebissMgContractError, match="scoped MG municipality"):
        gateway.exchange_prepared(**{
            **args,
            "scope": replace(args["scope"], environment=FiscalEnvironment.PRODUCTION),
        })
    resolver.resolve_provider_id.assert_not_called()
    cert.assert_not_called()
    exchange.assert_not_called()


def test_wrong_soap_action_and_wrapper_denied_before_binding() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert, exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    env = _envelope(Abrasf203Operation.QUERY_BATCH)
    with pytest.raises(WebissMgContractError, match="SOAPAction"):
        gateway.exchange_prepared(
            envelope=replace(env, soap_action='"http://evil.invalid/Consulta"'),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31), jurisdiction=EXTREMA,
        )
    resolver.resolve_provider_id.assert_not_called()
    cert.assert_not_called()


def test_soap_fault_or_cross_operation_never_appears_fiscally_authorized() -> None:
    query = Abrasf203Operation.QUERY_BATCH
    fault = (
        f'<soap:Envelope xmlns:soap="{SOAP}">'
        "<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    ).encode()
    with pytest.raises(WebissMgContractError, match="SOAP Fault"):
        parse_webiss_soap_response(fault, query)
    with pytest.raises(WebissMgContractError, match="does not match"):
        parse_webiss_soap_response(
            _response(Abrasf203Operation.GENERATE), query,
        )
    with pytest.raises(WebissMgContractError, match="outputXML"):
        parse_webiss_soap_response(_response(query, xml="not-xml"), query)
    with pytest.raises(WebissMgContractError, match="response XML root"):
        parse_webiss_soap_response(_response(query, xml="<retorno/>"), query)
    with pytest.raises(WebissMgContractError, match="DTD"):
        parse_webiss_soap_response(
            _response(query, xml='<!DOCTYPE retorno [<!ENTITY x "untrusted">]><retorno/>'),
            query,
        )


def test_uberaba_webiss_uses_the_same_transport_with_a_distinct_provider(material) -> None:
    resolver = Mock()
    resolver.resolve_provider_id.return_value = UBERABA_WEBISS_PROVIDER_ID
    certificate = Mock(return_value=material)
    exchange = Mock(return_value=_response(Abrasf203Operation.QUERY_BATCH))
    gateway = WebissUberabaHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate,
        exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3170107"),
        municipal_schema_validator=_validator(),
    )
    args = dict(
        envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
        operation=Abrasf203Operation.QUERY_BATCH,
        scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
        issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31),
    )
    uberaba = BrazilianJurisdiction("MG", "3170107")
    assert gateway.exchange_prepared(**args, jurisdiction=uberaba) == (
        _rejection_xml(Abrasf203Operation.QUERY_BATCH).encode("utf-8")
    )
    assert resolver.resolve_provider_id.call_args.kwargs["jurisdiction"] == uberaba
    assert exchange.call_count == 1
    with pytest.raises(WebissMgContractError, match="scoped MG municipality"):
        gateway.exchange_prepared(**args, jurisdiction=EXTREMA)
    assert exchange.call_count == 1
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    with pytest.raises(WebissMgContractError, match="binding"):
        gateway.exchange_prepared(**args, jurisdiction=uberaba)
    assert exchange.call_count == 1


def test_uberaba_legacy_webiss_is_blocked_after_federal_simples_cutover() -> None:
    resolver, certificate, exchange = Mock(), Mock(), Mock()
    gateway = WebissUberabaHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate,
        exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3170107"),
        municipal_schema_validator=_validator(),
    )
    with pytest.raises(WebissMgContractError, match="Emissor Nacional"):
        gateway.exchange_prepared(
            envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
            competence_date=date(2026, 11, 1),
            jurisdiction=BrazilianJurisdiction("MG", "3170107"),
        )
    resolver.resolve_provider_id.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()


@pytest.mark.parametrize(
    ("city_ibge", "cls", "provider_id"),
    [
        ("3125101", WebissExtremaHomologationTransport, EXTREMA_WEBISS_PROVIDER_ID),
        ("3170107", WebissUberabaHomologationTransport, UBERABA_WEBISS_PROVIDER_ID),
    ],
)
def test_municipal_cancellation_is_signed_and_scope_bound_before_send(
    city_ibge, cls, provider_id, material,
) -> None:
    from unittest.mock import Mock

    resolved = Mock(return_value=material)
    cancelled = prepare_abrasf203_soap(
        operation=Abrasf203Operation.CANCEL,
        xml=_CANCEL.replace("3125101", city_ibge).encode(),
        scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=resolved,
        preaudit=Mock(),
        preaudit_cancel=Mock(),
        municipal_schema_version="2.02",
        municipal_validator=_validator(),
    )
    resolver = Mock()
    resolver.resolve_provider_id.return_value = provider_id
    exchange = Mock(return_value=_response(Abrasf203Operation.CANCEL))
    adapter = cls(
        provider_resolver=resolver,
        resolve_certificate=Mock(return_value=material),
        exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence(city_ibge),
        municipal_schema_validator=_validator(),
    )
    jurisdiction = BrazilianJurisdiction("MG", city_ibge)
    assert adapter.exchange_prepared(
        envelope=cancelled,
        operation=Abrasf203Operation.CANCEL,
        scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ),
        issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31),
        jurisdiction=jurisdiction,
    ) == _rejection_xml(Abrasf203Operation.CANCEL).encode("utf-8")
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == (
        ConfiguredFiscalOperation.CANCEL.value
    )
    assert exchange.call_args.args[1] == '"http://nfse.abrasf.org.br/CancelarNfse"'
    fake_scope = BrazilianJurisdiction(
        "MG", "3170107" if city_ibge == "3125101" else "3125101"
    )
    with pytest.raises(WebissMgContractError, match="scoped MG municipality"):
        adapter.exchange_prepared(
            envelope=cancelled,
            operation=Abrasf203Operation.CANCEL,
            scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=fake_scope,
        )
    assert exchange.call_count == 1


def test_municipal_cancellation_cross_city_payload_is_not_accepted(material) -> None:
    cancelled = prepare_abrasf203_soap(
        operation=Abrasf203Operation.CANCEL,
        xml=_CANCEL.encode(), scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=Mock(return_value=material),
        preaudit=Mock(), preaudit_cancel=Mock(),
        municipal_schema_version="2.02",
        municipal_validator=_validator(),
    )
    resolver, exchange, certificate = Mock(), Mock(), Mock()
    adapter = WebissUberabaHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate,
        exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3170107"),
        municipal_schema_validator=_validator(),
    )
    with pytest.raises(WebissMgContractError, match="bound issuer and city"):
        adapter.exchange_prepared(
            envelope=cancelled, operation=Abrasf203Operation.CANCEL,
            scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=BrazilianJurisdiction("MG", "3170107"),
        )
    resolver.resolve_provider_id.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_no_official_municipal_xsd_is_fail_closed_before_binding_or_vault(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        webiss_2026_schema, "PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS", {},
    )
    digest = _validator().validate_document(
        _payload(Abrasf203Operation.QUERY_BATCH)
    ).schema_package_sha256
    with pytest.raises(WebissMunicipalSchemaUnverified, match="not pinned"):
        Webiss2026SchemaEvidence("3125101", digest)
    resolver, certificate, exchange = Mock(), Mock(), Mock()
    adapter = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=certificate, exchange=exchange,
    )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="not installed"):
        adapter.exchange_prepared(
            envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=EXTREMA,
        )
    resolver.resolve_provider_id.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_generic_203_cannot_be_dispatched_as_webiss_2026_even_with_binding() -> None:
    resolver, certificate, exchange = Mock(), Mock(), Mock()
    adapter = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=certificate,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
        exchange=exchange,
    )
    legacy = prepare_abrasf203_soap(
        operation=Abrasf203Operation.QUERY_BATCH,
        xml=_payload(Abrasf203Operation.QUERY_BATCH),
        scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=Mock(), preaudit=Mock(),
    )
    assert legacy.schema_version == "2.03"
    with pytest.raises(WebissMunicipalSchemaUnverified, match="2.02 RTC envelope"):
        adapter.exchange_prepared(
            envelope=legacy,
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=EXTREMA,
        )
    resolver.resolve_provider_id.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_signed_cancel_tamper_does_not_reach_webiss_http(material) -> None:
    valid = prepare_abrasf203_soap(
        operation=Abrasf203Operation.CANCEL, xml=_CANCEL.encode(),
        scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
        resolve_certificate=Mock(return_value=material),
        preaudit=Mock(), preaudit_cancel=Mock(),
        municipal_schema_version="2.02", municipal_validator=_validator(),
    )
    assert b"CodigoCancelamento" in valid.body
    changed = valid.body.replace(
        b"&lt;CodigoCancelamento&gt;1&lt;/CodigoCancelamento&gt;",
        b"&lt;CodigoCancelamento&gt;2&lt;/CodigoCancelamento&gt;",
        1,
    )
    assert changed != valid.body
    resolver = Mock()
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    cert = Mock(return_value=material)
    exchange = Mock(return_value=_response(Abrasf203Operation.CANCEL))
    adapter = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
        exchange=exchange,
    )
    with pytest.raises(WebissMgContractError, match="XMLDSig does not match"):
        adapter.exchange_prepared(
            envelope=replace(valid, body=changed),
            operation=Abrasf203Operation.CANCEL,
            scope=_request().scope, issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31), jurisdiction=EXTREMA,
        )
    assert cert.call_count == 1
    exchange.assert_not_called()


def test_webiss_query_rejects_cross_taxpayer_payload_before_binding_and_a1() -> None:
    resolver = Mock()
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    certificate, exchange = Mock(), Mock()
    adapter = WebissExtremaHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate,
        exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    envelope = _envelope(Abrasf203Operation.QUERY_BATCH)
    tampered = replace(
        envelope, body=envelope.body.replace(CNPJ.encode(), b"12345678000195", 1),
    )
    assert tampered.body != envelope.body
    with pytest.raises(WebissMgContractError, match="issuer CNPJ"):
        adapter.exchange_prepared(
            envelope=tampered,
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=EXTREMA,
        )
    resolver.resolve_provider_id.assert_not_called()
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_webiss_unknown_uberaba_endpoint_never_resolves_a1() -> None:
    resolver = Mock()
    resolver.resolve_provider_id.return_value = UBERABA_WEBISS_PROVIDER_ID
    certificate = Mock()
    adapter = WebissUberabaHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate,
        municipal_schema_evidence=_synthetic_evidence("3170107"),
        municipal_schema_validator=_validator(),
    )
    with pytest.raises(WebissMgContractError, match="homologation URL"):
        adapter.exchange_prepared(
            envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=BrazilianJurisdiction("MG", "3170107"),
        )
    resolver.resolve_provider_id.assert_called_once()
    certificate.assert_not_called()


@pytest.mark.parametrize(
    ("other_issuer", "other_city"),
    [(True, False), (False, True)],
)
def test_returned_nfse_must_belong_to_scoped_issuer_and_city(
    other_issuer: bool, other_city: bool,
) -> None:
    # Isolated XML identity guard. This is intentionally NOT a municipal
    # signed receipt fixture or XSD/IBSCBS homologation evidence.
    issuer = "12345678000195" if other_issuer else CNPJ
    municipality = "3170107" if other_city else "3125101"
    inner = (
        '<ConsultarLoteRpsResposta xmlns="http://www.abrasf.org.br/nfse.xsd">'
        '<Situacao>4</Situacao><ListaNfse><CompNfse><Nfse><InfNfse>'
        '<PrestadorServico><IdentificacaoPrestador><CpfCnpj>'
        f"<Cnpj>{issuer}</Cnpj>"
        '</CpfCnpj></IdentificacaoPrestador></PrestadorServico>'
        f"<OrgaoGerador><CodigoMunicipio>{municipality}</CodigoMunicipio>"
        "<Uf>MG</Uf></OrgaoGerador></InfNfse></Nfse></CompNfse>"
        "</ListaNfse></ConsultarLoteRpsResposta>"
    )
    with pytest.raises(WebissMgContractError, match="issuer or municipality"):
        parse_webiss_soap_response(
            _response(Abrasf203Operation.QUERY_BATCH, xml=inner),
            Abrasf203Operation.QUERY_BATCH,
            issuer_cnpj=Cnpj(CNPJ),
            municipality_ibge="3125101",
        )


def test_extrema_has_no_implicit_municipal_http_route_before_wsdl_approval() -> None:
    """A public portal address is not proof of an operational fiscal SOAP URL."""
    provider, certificate = Mock(), Mock()
    provider.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=provider,
        resolve_certificate=certificate,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
        # No exchange: the municipal WSDL/endpoint has not been certified.
    )
    with pytest.raises(
        WebissMgContractError, match="city-specific homologation URL"
    ):
        gateway.exchange_prepared(
            envelope=_envelope(Abrasf203Operation.QUERY_BATCH),
            operation=Abrasf203Operation.QUERY_BATCH,
            scope=_request().scope,
            issuer_cnpj=Cnpj(CNPJ),
            issuer_tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 10, 31),
            jurisdiction=EXTREMA,
        )
    assert provider.resolve_provider_id.call_count == 1
    certificate.assert_not_called()


def test_extrema_issued_invoice_query_matches_official_soap_method(material) -> None:
    """The city publishes ConsultarNfseServicoPrestado, not just batch lookup."""
    op = Abrasf203Operation.QUERY_ISSUED
    resolver = Mock()
    resolver.resolve_provider_id.return_value = EXTREMA_WEBISS_PROVIDER_ID
    cert = Mock(return_value=material)
    exchange = Mock(return_value=_response(op))
    gateway = WebissExtremaHomologationTransport(
        provider_resolver=resolver, resolve_certificate=cert, exchange=exchange,
        municipal_schema_evidence=_synthetic_evidence("3125101"),
        municipal_schema_validator=_validator(),
    )
    prepared = _envelope(op)
    assert prepared is not None
    assert prepared.soap_action == '"http://nfse.abrasf.org.br/ConsultarNfseServicoPrestado"'
    assert gateway.exchange_prepared(
        envelope=prepared, operation=op, scope=_request().scope,
        issuer_cnpj=Cnpj(CNPJ), issuer_tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 10, 31), jurisdiction=EXTREMA,
    ) == _rejection_xml(op).encode()
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == (
        ConfiguredFiscalOperation.QUERY.value
    )
    cert.assert_called_once()
    exchange.assert_called_once()
