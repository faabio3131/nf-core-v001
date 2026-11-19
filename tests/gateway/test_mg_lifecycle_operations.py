"""MG operational lifecycle uses actual offline XSD and synthetic A1 only."""
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from lxml import etree
from test_mg_homologation_authorization import _request
from test_mg_homologation_authorization import material as material

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation, ProviderBinding
from kordena_fiscal.control_plane.mg_official_homologation_catalog import mg_homologation_endpoint
from kordena_fiscal.control_plane.models import FiscalOrganization, FiscalUnitRegistration
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ElectronicInvoiceModel,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.nfe_sp_homologation import (
    MG_NFCE_HOMOLOGATION_PROVIDER_ID,
    MG_NFE_HOMOLOGATION_PROVIDER_ID,
    HomologationAuthorizationTarget,
)
from kordena_fiscal.gateway.nfe_sp_operations_homologation import (
    OfficialNfeOperationsError,
    SefazHomologationOperationsGateway,
    SefazSpHomologationOperationsGateway,
)
from kordena_fiscal.operations import (
    CancellationRequest,
    FiscalEventStatus,
    FiscalQueryRequest,
    FiscalQueryStatus,
    InutilizationRequest,
)
from kordena_fiscal.persistence.sqlite import SqliteFiscalDatabase
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    _GovernedMgQueryGateway,
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.xml.official_operation_schema import ROOTS, OfficialOperationXmlValidator

NS = "http://www.portalfiscal.inf.br/nfe"


def _gateway(material, exchange, issuer=None):
    return SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFE,
        resolve_certificate=Mock(return_value=material),
        resolve_issuer=issuer or Mock(return_value="11222333000181"),
        exchange=exchange,
    )


def _soap(xml):
    return (
        '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Body>'
        + xml + '</Body></Envelope>'
    ).encode()


def _cancel():
    request = _request()
    return CancellationRequest.build(
        scope=request.scope, access_key=request.access_key,
        authorization_protocol="131260000000001",
        justification="Cancelamento sintetico para teste interno",
    )


def _inutilize(model=ElectronicInvoiceModel.NFE):
    return InutilizationRequest.build(
        scope=_request().scope, model=model, series=1, first_number=10, last_number=12,
        justification="Inutilizacao sintetica para teste interno",
    )


def test_all_lifecycle_schemas_compile_without_network():
    OfficialOperationXmlValidator(tuple(ROOTS))


@pytest.mark.parametrize("status,expected", [
    ("100", FiscalQueryStatus.AUTHORIZED), ("101", FiscalQueryStatus.CANCELLED),
    ("217", FiscalQueryStatus.NOT_FOUND), ("105", FiscalQueryStatus.PENDING),
])
def test_mg_query_schema_and_normalization(material, status, expected):
    original = _request()
    exchange = Mock(return_value=_soap(
        f'<retConsSitNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<chNFe>{original.access_key.value}</chNFe><cStat>{status}</cStat>'
        '<nProt>131260000000001</nProt></retConsSitNFe>'
    ))
    result = _gateway(material, exchange).query(FiscalQueryRequest(
        original.scope, original.access_key,
    ))
    assert result.status is expected
    assert result.provider.provider_name == "sefaz-mg-homologacao-nfe4"
    assert exchange.call_count == 1
    assert exchange.call_args.args[0] == "NFeConsultaProtocolo4"


def test_canonical_query_dispatches_mg_only_for_exact_enabled_binding(
    tmp_path, monkeypatch, material,
):
    database = SqliteFiscalDatabase(tmp_path / "fiscal.db")
    database.initialize()
    original = _request()
    scope = replace(original.scope, host_namespace="nfcore-test")
    with database() as uow:
        uow.control_plane.add_organization(FiscalOrganization(scope.tenant_id, "Synthetic MG"))
        uow.control_plane.add_unit(FiscalUnitRegistration(scope.tenant_id, scope.unit_id, "Pilot"))
        uow.commit()
    access_key = original.access_key.value
    exchange = Mock(return_value=_soap(
        f'<retConsSitNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<chNFe>{access_key}</chNFe><cStat>217</cStat></retConsSitNFe>'
    ))
    monkeypatch.setattr(SefazHomologationOperationsGateway, "_https_exchange", exchange)
    vault = Mock()
    vault.resolve.return_value = material
    handler = build_runtime_fiscal_handler_factory(certificate_vault=vault)(
        FiscalApplicationService(database)
    )["queryFiscalDocument"]
    payload = {"access_key": access_key}
    binding = ProviderBinding(
        binding_id="mg-query",
        tenant_id=scope.tenant_id,
        unit_id=scope.unit_id,
        environment=scope.environment,
        document_kind=FiscalDocumentKind.NFE,
        jurisdiction=BrazilianJurisdiction("MG"),
        operation=ConfiguredFiscalOperation.QUERY,
        provider_id=MG_NFE_HOMOLOGATION_PROVIDER_ID,
    )

    def persist(record):
        with database() as uow:
            uow.commercial.put_provider_binding(record)
            uow.commit()

    with pytest.raises(FiscalValidationError, match="consulta MG"):
        handler(scope, payload, None)
    for denied in (
        replace(binding, binding_id="mg-authorize", operation=ConfiguredFiscalOperation.AUTHORIZE),
        replace(binding, enabled=False),
        replace(binding, provider_id="wrong-provider"),
    ):
        persist(denied)
        with pytest.raises(FiscalValidationError, match="consulta MG"):
            handler(scope, payload, None)

    persist(binding)
    for denied_scope in (
        replace(scope, tenant_id="other-tenant"),
        replace(scope, unit_id="other-unit"),
        replace(scope, environment=FiscalEnvironment.PRODUCTION),
        replace(scope, host_namespace=None),
    ):
        with pytest.raises(FiscalValidationError):
            handler(denied_scope, payload, None)
    with pytest.raises(FiscalValidationError, match="consulta MG"):
        nfce_key = _request(model=ElectronicInvoiceModel.NFCE).access_key.value
        handler(scope, {"access_key": nfce_key}, None)
    vault.resolve.assert_not_called()
    exchange.assert_not_called()

    assert handler(scope, payload, None)["status"] == FiscalQueryStatus.NOT_FOUND.value
    vault.resolve.assert_called_once_with(
        scope=scope, issuer_cnpj=original.access_key.issuer_identifier,
    )
    exchange.assert_called_once()


def test_canonical_mg55_cancellation_dispatch_requires_exact_enabled_binding():
    """Cancellation must not silently fall back to SP or another provider."""
    request = _cancel()
    application = Mock()
    mg = Mock()
    legacy = Mock()
    dispatcher = _GovernedMgQueryGateway(
        application=application, mg=mg, legacy=legacy,
    )
    application.resolve_configured_provider_id.return_value = "wrong-provider"
    with pytest.raises(FiscalValidationError, match="cancelamento MG"):
        dispatcher.cancel(request)
    mg.cancel.assert_not_called()
    legacy.cancel.assert_not_called()

    expected = object()
    mg.cancel.return_value = expected
    application.resolve_configured_provider_id.return_value = MG_NFE_HOMOLOGATION_PROVIDER_ID
    assert dispatcher.cancel(request) is expected
    mg.cancel.assert_called_once_with(request)
    legacy.cancel.assert_not_called()
    kwargs = application.resolve_configured_provider_id.call_args.kwargs
    assert kwargs["scope"] == request.scope
    assert kwargs["document_kind"] is FiscalDocumentKind.NFE
    assert kwargs["jurisdiction"] == BrazilianJurisdiction("MG")
    assert kwargs["operation"] == ConfiguredFiscalOperation.CANCEL.value


def test_mg_cancellation_never_routes_production_or_unprovisioned_nfce():
    application, mg, legacy = Mock(), Mock(), Mock()
    dispatcher = _GovernedMgQueryGateway(
        application=application, mg=mg, legacy=legacy,
    )
    original = _cancel()
    production = replace(
        original, scope=replace(original.scope, environment=FiscalEnvironment.PRODUCTION),
    )
    with pytest.raises(FiscalValidationError, match="homologação"):
        dispatcher.cancel(production)
    application.resolve_configured_provider_id.assert_not_called()
    nfce_request = CancellationRequest.build(
        scope=original.scope,
        access_key=_request(model=ElectronicInvoiceModel.NFCE).access_key,
        authorization_protocol=original.authorization_protocol,
        justification=original.justification,
    )
    application.resolve_configured_provider_id.return_value = MG_NFCE_HOMOLOGATION_PROVIDER_ID
    with pytest.raises(FiscalValidationError, match="Gateway MG"):
        dispatcher.cancel(nfce_request)
    mg.cancel.assert_not_called()
    legacy.cancel.assert_not_called()


@pytest.mark.parametrize("operation", ["query", "cancel"])
def test_mg_nfce_runtime_selects_only_bound_model65_provider(operation: str):
    original = _request(model=ElectronicInvoiceModel.NFCE)
    nfce = Mock()
    mg_nfe = Mock()
    legacy = Mock()
    application = Mock()
    dispatcher = _GovernedMgQueryGateway(
        application=application, legacy=legacy, mg=mg_nfe, mg_nfce=nfce,
    )
    if operation == "query":
        request = FiscalQueryRequest(original.scope, original.access_key)
        handler = dispatcher.query
        method = nfce.query
        expected_operation = ConfiguredFiscalOperation.QUERY
    else:
        request = CancellationRequest.build(
            scope=original.scope, access_key=original.access_key,
            authorization_protocol="131260000000065",
            justification="Cancelamento sintetico NFC-e MG de teste",
        )
        handler = dispatcher.cancel
        method = nfce.cancel
        expected_operation = ConfiguredFiscalOperation.CANCEL
    application.resolve_configured_provider_id.return_value = MG_NFE_HOMOLOGATION_PROVIDER_ID
    with pytest.raises(FiscalValidationError, match="incompatível"):
        handler(request)
    nfce.query.assert_not_called()
    nfce.cancel.assert_not_called()
    mg_nfe.query.assert_not_called()
    mg_nfe.cancel.assert_not_called()
    legacy.query.assert_not_called()
    legacy.cancel.assert_not_called()

    expected = object()
    method.return_value = expected
    application.resolve_configured_provider_id.return_value = MG_NFCE_HOMOLOGATION_PROVIDER_ID
    assert handler(request) is expected
    method.assert_called_once_with(request)
    binding_args = application.resolve_configured_provider_id.call_args.kwargs
    assert binding_args["scope"] == original.scope
    assert binding_args["document_kind"] is FiscalDocumentKind.NFCE
    assert binding_args["jurisdiction"] == BrazilianJurisdiction("MG")
    assert binding_args["operation"] == expected_operation.value
    mg_nfe.query.assert_not_called()
    mg_nfe.cancel.assert_not_called()
    legacy.query.assert_not_called()
    legacy.cancel.assert_not_called()


def test_sp_cancellation_remains_in_legacy_adapter():
    application, mg, legacy = Mock(), Mock(), Mock()
    request = CancellationRequest.build(
        scope=_cancel().scope,
        access_key=_request(uf="35").access_key,
        authorization_protocol="135260000000001",
        justification="Cancelamento sintetico de SP preservado",
    )
    marker = object()
    legacy.cancel.return_value = marker
    dispatcher = _GovernedMgQueryGateway(
        application=application, mg=mg, legacy=legacy,
    )
    assert dispatcher.cancel(request) is marker
    legacy.cancel.assert_called_once_with(request)
    mg.cancel.assert_not_called()
    application.resolve_configured_provider_id.assert_not_called()


def test_canonical_provider_factory_selects_model65_gateway_only_with_binding(
    monkeypatch,
):
    """Proof of composition: exactly bound model65 selects SEFAZ/MG NFC-e.

    The provider itself still enforces QR, XSD, XMLDSig and A1 on authorize.
    """
    import kordena_fiscal.runtime.canonical_fiscal_composition as composition

    nfe_adapter, nfce_adapter = Mock(), Mock()
    monkeypatch.setattr(
        composition, "build_mg_nfe_homologation_gateway",
        lambda **_kwargs: nfe_adapter,
    )
    monkeypatch.setattr(
        composition, "build_mg_nfce_homologation_gateway",
        lambda **_kwargs: nfce_adapter,
    )
    captured = {}

    def capture_handlers(_operations, **kwargs):
        captured.update(kwargs)
        return {
            "issueFiscalDocument": object(),
            "queryFiscalDocument": object(),
            "cancelFiscalDocument": object(),
            "reconcileFiscalOperation": object(),
        }

    monkeypatch.setattr(composition, "build_provider_operation_handlers", capture_handlers)
    app, vault = Mock(), Mock()
    composition.build_runtime_fiscal_handler_factory(certificate_vault=vault)(app)
    select = captured["select_xml_gateway"]
    model65 = _request(model=ElectronicInvoiceModel.NFCE)
    app.resolve_configured_provider_id.return_value = "wrong-provider"
    with pytest.raises(FiscalValidationError, match="incompatível"):
        select(model65)
    assert vault.resolve.call_count == 0

    app.resolve_configured_provider_id.return_value = MG_NFCE_HOMOLOGATION_PROVIDER_ID
    assert select(model65)._gateway is nfce_adapter
    kwargs = app.resolve_configured_provider_id.call_args.kwargs
    assert kwargs["document_kind"] is FiscalDocumentKind.NFCE
    assert kwargs["operation"] == ConfiguredFiscalOperation.AUTHORIZE.value
    assert kwargs["jurisdiction"] == BrazilianJurisdiction("MG")

    app.resolve_configured_provider_id.return_value = MG_NFE_HOMOLOGATION_PROVIDER_ID
    assert select(_request())._gateway is nfe_adapter
    assert select(_request(uf="35"))._gateway is not nfce_adapter
    assert vault.resolve.call_count == 0


def test_mg_cancellation_is_signed_xsd_valid_and_correlated(material):
    original = _cancel()
    exchange = Mock(return_value=_soap(
        f'<retEnvEvento xmlns="{NS}"><retEvento><infEvento>'
        f'<tpAmb>2</tpAmb><cOrgao>31</cOrgao><chNFe>{original.access_key.value}</chNFe>'
        '<tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>'
        '<cStat>135</cStat><nProt>131260000000002</nProt>'
        '</infEvento></retEvento></retEnvEvento>'
    ))
    result = _gateway(material, exchange).cancel(original)
    assert result.status is FiscalEventStatus.ACCEPTED
    from mg_golden_fixture import verify_soap_signature
    verify_soap_signature(exchange.call_args.args[1], material)
    payload = etree.fromstring(exchange.call_args.args[1])
    signature = payload.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
    assert signature is not None
    assert signature.find(
        ".//{http://www.w3.org/2000/09/xmldsig#}SignatureMethod"
    ).get("Algorithm").endswith("rsa-sha1")


def test_mg_inutilization_is_signed_xsd_valid_and_correlated(material):
    original = _inutilize()
    year = datetime.now(UTC).strftime("%y")
    exchange = Mock(return_value=_soap(
        f'<retInutNFe xmlns="{NS}"><infInut><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<ano>{year}</ano><CNPJ>11222333000181</CNPJ><mod>55</mod><serie>1</serie>'
        '<nNFIni>10</nNFIni><nNFFin>12</nNFFin><cStat>102</cStat>'
        '<nProt>131260000000003</nProt></infInut></retInutNFe>'
    ))
    result = _gateway(material, exchange).inutilize(original)
    assert result.status is FiscalEventStatus.ACCEPTED
    from mg_golden_fixture import verify_soap_signature
    verify_soap_signature(exchange.call_args.args[1], material)
    payload = exchange.call_args.args[1]
    assert etree.fromstring(payload).findtext(f".//{{{NS}}}cUF") == "31"
    assert b"ID31" in payload


@pytest.mark.parametrize("operation", ["query", "cancel"])
@pytest.mark.parametrize("uf,model", [
    ("35", ElectronicInvoiceModel.NFE), ("31", ElectronicInvoiceModel.NFCE),
])
def test_wrong_state_or_model_never_accesses_certificate(operation, uf, model):
    source = _request(uf, model)
    resolver, exchange = Mock(), Mock()
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFE,
        resolve_certificate=resolver, exchange=exchange,
    )
    request = (
        FiscalQueryRequest(source.scope, source.access_key) if operation == "query"
        else replace(_cancel(), access_key=source.access_key)
    )
    with pytest.raises(OfficialNfeOperationsError, match="state/model"):
        getattr(gateway, operation)(request)
    resolver.assert_not_called()
    exchange.assert_not_called()


def test_model65_inutilization_never_resolves_issuer_or_vault():
    issuer, resolver, exchange = Mock(), Mock(), Mock()
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFE,
        resolve_certificate=resolver, resolve_issuer=issuer, exchange=exchange,
    )
    with pytest.raises(OfficialNfeOperationsError, match="model 65"):
        gateway.inutilize(_inutilize(ElectronicInvoiceModel.NFCE))
    issuer.assert_not_called()
    resolver.assert_not_called()
    exchange.assert_not_called()


@pytest.mark.parametrize("operation", ["query", "cancel", "inutilize"])
def test_production_is_denied_before_vault(operation):
    resolver, issuer, exchange = Mock(), Mock(), Mock()
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFE, resolve_certificate=resolver,
        resolve_issuer=issuer, exchange=exchange,
    )
    source = _request()
    request = {
        "query": FiscalQueryRequest(source.scope, source.access_key),
        "cancel": _cancel(), "inutilize": _inutilize(),
    }[operation]
    request = replace(
        request, scope=replace(source.scope, environment=FiscalEnvironment.PRODUCTION),
    )
    with pytest.raises(OfficialNfeOperationsError):
        getattr(gateway, operation)(request)
    resolver.assert_not_called()
    issuer.assert_not_called()
    exchange.assert_not_called()


def test_mismatched_query_reply_never_authorizes(material):
    exchange = Mock(return_value=_soap(
        f'<retConsSitNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF><cStat>100</cStat>'
        f'<chNFe>{"1" * 44}</chNFe><nProt>131260000000001</nProt></retConsSitNFe>'
    ))
    with pytest.raises(OfficialNfeOperationsError, match="key mismatch"):
        _gateway(material, exchange).query(FiscalQueryRequest(
            _request().scope, _request().access_key,
        ))


def test_mg_nfce_query_uses_distinct_model65_state_endpoint_and_correlates(material):
    original = _request(model=ElectronicInvoiceModel.NFCE)
    exchange = Mock(return_value=_soap(
        f'<retConsSitNFe xmlns="{NS}"><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<chNFe>{original.access_key.value}</chNFe><cStat>100</cStat>'
        '<nProt>131260000000065</nProt></retConsSitNFe>'
    ))
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=Mock(return_value=material),
        exchange=exchange,
    )
    expected = mg_homologation_endpoint(
        document_kind=FiscalDocumentKind.NFCE,
        environment=FiscalEnvironment.HOMOLOGATION,
        operation=ConfiguredFiscalOperation.QUERY,
    )
    assert gateway._mg_endpoints["NFeConsultaProtocolo4"] == expected.url
    assert "hnfce.fazenda.mg.gov.br" in expected.url
    result = gateway.query(FiscalQueryRequest(original.scope, original.access_key))
    assert result.status is FiscalQueryStatus.AUTHORIZED
    assert result.protocol_reference == "131260000000065"
    assert result.provider.provider_name == "sefaz-mg-homologacao-nfce4"
    exchange.assert_called_once()


def test_mg_nfce_cancellation_correlates_signed_event_and_model65(material):
    original = _request(model=ElectronicInvoiceModel.NFCE)
    request = CancellationRequest.build(
        scope=original.scope,
        access_key=original.access_key,
        authorization_protocol="131260000000065",
        justification="Cancelamento NFC-e de teste sintetico",
    )
    exchange = Mock(return_value=_soap(
        f'<retEnvEvento xmlns="{NS}"><retEvento><infEvento>'
        f'<tpAmb>2</tpAmb><cOrgao>31</cOrgao><chNFe>{request.access_key.value}</chNFe>'
        '<tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>'
        '<cStat>135</cStat><nProt>131260000000066</nProt>'
        '</infEvento></retEvento></retEnvEvento>'
    ))
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=Mock(return_value=material),
        exchange=exchange,
    )
    result = gateway.cancel(request)
    assert result.status is FiscalEventStatus.ACCEPTED
    assert result.provider.provider_name == "sefaz-mg-homologacao-nfce4"
    from mg_golden_fixture import verify_soap_signature
    verify_soap_signature(exchange.call_args.args[1], material)
    assert gateway._mg_endpoints["NFeRecepcaoEvento4"] == mg_homologation_endpoint(
        document_kind=FiscalDocumentKind.NFCE,
        environment=FiscalEnvironment.HOMOLOGATION,
        operation=ConfiguredFiscalOperation.CANCEL,
    ).url


def test_mg_nfce_inutilization_uses_model65_signed_xml_and_response(material):
    year = datetime.now(UTC).strftime("%y")
    request = _inutilize(ElectronicInvoiceModel.NFCE)
    exchange = Mock(return_value=_soap(
        f'<retInutNFe xmlns="{NS}"><infInut><tpAmb>2</tpAmb><cUF>31</cUF>'
        f'<ano>{year}</ano><CNPJ>11222333000181</CNPJ><mod>65</mod><serie>1</serie>'
        '<nNFIni>10</nNFIni><nNFFin>12</nNFFin><cStat>102</cStat>'
        '<nProt>131260000000067</nProt></infInut></retInutNFe>'
    ))
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=Mock(return_value=material),
        resolve_issuer=Mock(return_value="11222333000181"),
        exchange=exchange,
    )
    result = gateway.inutilize(request)
    assert result.status is FiscalEventStatus.ACCEPTED
    assert result.model is ElectronicInvoiceModel.NFCE
    assert result.provider.provider_name == "sefaz-mg-homologacao-nfce4"
    from mg_golden_fixture import verify_soap_signature
    verify_soap_signature(exchange.call_args.args[1], material)
    xml = exchange.call_args.args[1]
    assert b"<mod>65</mod>" in xml
    assert gateway._mg_endpoints["NFeInutilizacao4"] == mg_homologation_endpoint(
        document_kind=FiscalDocumentKind.NFCE,
        environment=FiscalEnvironment.HOMOLOGATION,
        operation=ConfiguredFiscalOperation.INUTILIZE,
    ).url


@pytest.mark.parametrize("operation", ["query", "cancel", "inutilize"])
def test_nfce_operations_deny_model55_before_vault(operation):
    resolver, issuer, exchange = Mock(), Mock(), Mock()
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=resolver,
        resolve_issuer=issuer,
        exchange=exchange,
    )
    nfe = _request()
    request = {
        "query": FiscalQueryRequest(nfe.scope, nfe.access_key),
        "cancel": _cancel(),
        "inutilize": _inutilize(ElectronicInvoiceModel.NFE),
    }[operation]
    with pytest.raises(OfficialNfeOperationsError):
        getattr(gateway, operation)(request)
    resolver.assert_not_called()
    issuer.assert_not_called()
    exchange.assert_not_called()


def test_sp_wrapper_remains_fixed_and_invalid_target_is_denied():
    sp = SefazSpHomologationOperationsGateway(resolve_certificate=Mock())
    assert sp._state == "35"
    with pytest.raises(ValueError):
        SefazHomologationOperationsGateway(resolve_certificate=Mock(), target="mg_nfe")


@pytest.mark.parametrize("operation,field", [
    ("cancel", "chNFe"), ("cancel", "tpEvento"), ("cancel", "nSeqEvento"),
    ("cancel", "cOrgao"), ("inutilize", "CNPJ"), ("inutilize", "nNFFin"),
    ("inutilize", "serie"), ("inutilize", "mod"), ("inutilize", "ano"),
])
def test_cross_document_or_range_reply_is_denied(material, operation, field):
    source = _cancel()
    year = datetime.now(UTC).strftime("%y")
    if operation == "cancel":
        fields = {
            "tpAmb": "2", "cOrgao": "31", "chNFe": source.access_key.value,
            "tpEvento": "110111", "nSeqEvento": "1", "cStat": "135",
            "nProt": "131260000000001",
        }
        fields[field] = "999"
        body = "".join(f"<{name}>{value}</{name}>" for name, value in fields.items())
        xml = f'<retEnvEvento xmlns="{NS}"><retEvento><infEvento>{body}'
        xml += '</infEvento></retEvento></retEnvEvento>'
        request = source
    else:
        fields = {
            "tpAmb": "2", "cUF": "31", "ano": year, "CNPJ": "11222333000181",
            "mod": "55", "serie": "1", "nNFIni": "10", "nNFFin": "12",
            "cStat": "102", "nProt": "131260000000001",
        }
        fields[field] = "999"
        body = "".join(f"<{name}>{value}</{name}>" for name, value in fields.items())
        xml = f'<retInutNFe xmlns="{NS}"><infInut>{body}</infInut></retInutNFe>'
        request = _inutilize()
    exchange = Mock(return_value=_soap(xml))
    with pytest.raises(OfficialNfeOperationsError, match="correlation mismatch"):
        getattr(_gateway(material, exchange), operation)(request)
    assert exchange.call_count == 1


@pytest.mark.parametrize("operation", ["query", "cancel", "inutilize"])
def test_soap_fault_never_becomes_success(material, operation):
    exchange = Mock(return_value=_soap("<Fault/>"))
    request = {
        "query": FiscalQueryRequest(_request().scope, _request().access_key),
        "cancel": _cancel(), "inutilize": _inutilize(),
    }[operation]
    with pytest.raises(OfficialNfeOperationsError, match="SOAP"):
        getattr(_gateway(material, exchange), operation)(request)
    assert exchange.call_count == 1


@pytest.mark.parametrize("service,endpoint,method", [
    ("NFeConsultaProtocolo4", "NFeConsultaProtocolo4", "nfeConsultaNF"),
    ("NFeRecepcaoEvento4", "NFeRecepcaoEvento4", "nfeRecepcaoEvento"),
    ("NFeInutilizacao4", "NFeInutilizacao4", "nfeInutilizacaoNF"),
])
def test_fixed_mg_destination_action_and_no_redirect_handler(
    monkeypatch, material, service, endpoint, method,
):
    import ssl

    import kordena_fiscal.gateway.nfe_sp_operations_homologation as module
    from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"<reply/>"
    opener = Mock()
    opener.open.return_value = response
    build = Mock(return_value=opener)
    monkeypatch.setattr(module, "build_opener", build)
    gateway = _gateway(material, Mock())
    gateway._https_exchange(service, b"<synthetic/>", ssl.create_default_context(), 2)
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://hnfe.fazenda.mg.gov.br/nfe2/services/" + endpoint
    assert method in request.headers["Content-type"]
    assert any(isinstance(handler, RejectFiscalRedirects) for handler in build.call_args.args)


@pytest.mark.parametrize("prepared", [False, True])
def test_schema_complete_nfe_authorization_roundtrip_to_official_nfe_proc(
    material, prepared, tmp_path, monkeypatch,
):
    from mg_golden_fixture import unsigned_golden_request

    from kordena_fiscal.gateway.authorization import AuthorizationStatus
    from kordena_fiscal.gateway.nfe_sp_homologation import build_mg_nfe_homologation_gateway
    from kordena_fiscal.xml.official_operation_schema import load_operation_schema
    from kordena_fiscal.xml.schema import SchemaSet, XmlSchemaValidator
    original = unsigned_golden_request()
    def reply(payload, *_args):
        from mg_golden_fixture import verify_soap_signature
        verify_soap_signature(payload, material)
        digest = etree.fromstring(payload).findtext(
            ".//{http://www.w3.org/2000/09/xmldsig#}DigestValue"
        )
        return _soap(
            f'<retEnviNFe xmlns="{NS}" versao="4.00"><tpAmb>2</tpAmb>'
            '<verAplic>SYNTHETIC-TEST</verAplic><cStat>104</cStat>'
            '<xMotivo>Lote processado</xMotivo><cUF>31</cUF>'
            '<dhRecbto>2026-11-05T12:00:01-03:00</dhRecbto>'
            f'<protNFe versao="4.00"><infProt><tpAmb>2</tpAmb><verAplic>SYNTHETIC</verAplic>'
            f'<chNFe>{original.access_key.value}</chNFe>'
            '<dhRecbto>2026-11-05T12:00:01-03:00</dhRecbto>'
            f'<nProt>131260000000001</nProt><digVal>{digest}</digVal>'
            '<cStat>100</cStat><xMotivo>Autorizado uso NF-e</xMotivo>'
            '</infProt></protNFe></retEnviNFe>'
        )
    exchange = Mock(side_effect=reply)
    if prepared:
        _exercise_prepared_mg_runtime(original, material, exchange, tmp_path, monkeypatch)
        return
    gateway = build_mg_nfe_homologation_gateway(
        resolve_certificate=Mock(return_value=material), exchange=exchange,
    )
    result = gateway.authorize(original)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.authorized_xml
    base = load_operation_schema("NFeAutorizacao4")
    proc = SchemaSet(
        version=base.version, root_schema="nfe/procNFe_v4.00.xsd",
        resources=base.resources, source_uri=base.source_uri,
    )
    XmlSchemaValidator(proc).validate_document(result.authorized_xml)
    assert exchange.call_count == 1

def _exercise_prepared_mg_runtime(original, material, exchange, tmp_path, monkeypatch):
    from kordena_fiscal.archive import RetentionPolicyMetadata
    from kordena_fiscal.gateway.nfe_sp_homologation import SefazHomologationAuthorizationGateway
    from kordena_fiscal.lifecycle import FiscalDocumentState
    from kordena_fiscal.signing.nfe_xmldsig import NfeSignatureProfile, sign_nfe_envi_xml

    database = SqliteFiscalDatabase(tmp_path / "fiscal.db")
    database.initialize()
    application = FiscalApplicationService(database)
    scope = original.scope
    now = datetime.now(UTC)
    document_id = "mg-prepared-55"
    request = replace(original, signed_xml=sign_nfe_envi_xml(
        original.signed_xml, material, profile=NfeSignatureProfile.NFE4_OFFICIAL_RSA_SHA1,
    ))
    application.reserve_issuance(
        scope=scope, key=request.idempotency_key, request_fingerprint=request.request_fingerprint,
        document_id=document_id, created_at=now,
    )
    for state in (
        FiscalDocumentState.VALIDATING, FiscalDocumentState.READY_TO_SIGN,
        FiscalDocumentState.SIGNING,
    ):
        application.transition_lifecycle(
            document_id, state, occurred_at=now, reason="synthetic prepared NF-e",
            correlation_id=scope.correlation_id,
        )
    application.persist_prepared_authorization(
        document_id=document_id, request=request, occurred_at=now,
        retention=RetentionPolicyMetadata("synthetic-test", 1),
    )
    monkeypatch.setattr(SefazHomologationAuthorizationGateway, "_https_exchange", exchange)
    vault = Mock()
    vault.resolve.return_value = material
    handler = build_runtime_fiscal_handler_factory(certificate_vault=vault)(
        application
    )["issueFiscalDocument"]
    payload = {"document_id": document_id}
    with database() as uow:
        uow.control_plane.add_organization(FiscalOrganization(scope.tenant_id, "Synthetic MG"))
        uow.control_plane.add_unit(FiscalUnitRegistration(scope.tenant_id, scope.unit_id, "Pilot"))
        query_binding = ProviderBinding(
            binding_id="mg-query", tenant_id=scope.tenant_id, unit_id=scope.unit_id,
            environment=scope.environment, document_kind=FiscalDocumentKind.NFE,
            jurisdiction=BrazilianJurisdiction("MG"), operation=ConfiguredFiscalOperation.QUERY,
            provider_id=MG_NFE_HOMOLOGATION_PROVIDER_ID,
        )
        uow.commercial.put_provider_binding(query_binding)
        uow.commit()
    with pytest.raises(FiscalValidationError, match="indispon"):
        handler(scope, payload, "synthetic-http-intent")
    exchange.assert_not_called()
    vault.resolve.assert_not_called()

    with database() as uow:
        uow.commercial.put_provider_binding(replace(
            query_binding, binding_id="mg-authorize", operation=ConfiguredFiscalOperation.AUTHORIZE,
        ))
        uow.commit()
    assert handler(scope, payload, "synthetic-http-intent")["status"] == "authorized"
    assert handler(scope, payload, "synthetic-http-intent")["replay"] is True
    exchange.assert_called_once()
    vault.resolve.assert_called_once_with(
        scope=scope, issuer_cnpj=request.access_key.issuer_identifier,
    )
