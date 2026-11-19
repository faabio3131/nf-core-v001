"""Guarulhos current GissOnline 2.04 SOAP ports, without production credentials.

2026 GISS V2 current manual 1.8 is a separate municipal channel from SEFIN.
A GISS transport cannot read A1, send SOAP or trust a SOAP success unless its
exact municipality, tenant binding, official XSD and WSDL are reviewed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissHomologationTransport,
    JundiaiGissWsdlContract,
    JundiaiSignedOperation,
)
from kordena_fiscal.gateway.jundiai_giss_rps_query_builder import build_jundiai_rps_query
from kordena_fiscal.gateway.municipal_sp_routing import (
    GUARULHOS_GISS_V2_PROVIDER_ID,
    GUARULHOS_IBGE,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.runtime.guarulhos_giss_operational_composition import (
    GuarulhosGissTrustedRuntimePorts,
)
from kordena_fiscal.runtime.jundiai_operational_composition import (
    JundiaiTrustedRuntimePorts,
)


def _operation() -> JundiaiSignedOperation:
    return JundiaiSignedOperation(
        scope=ExecutionScope(
            host_namespace="fm-nfcore", tenant_id="guarulhos-tenant",
            unit_id="guarulhos-unit", environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="guarulhos-reviewed-giss",
        ),
        issuer_cnpj=Cnpj("11222333000181"),
        tax_regime=TaxRegimeCode.NORMAL,
        competence_date=date(2026, 11, 15),
        method="ConsultarNfsePorRps",
        signed_xml=(
            b'<ConsultarNfseRpsEnvio '
            b'xmlns="http://www.giss.com.br/consultar-nfse-rps-envio-v2_04.xsd" />'
        ),
    )


def _contract(method: str) -> JundiaiGissWsdlContract:
    return JundiaiGissWsdlContract(
        method=method,
        action="http://giss.com.br/" + method,
        service_namespace="http://giss.com.br/ws",
        xsd_package_sha256="a" * 64,
        wsdl_sha256="b" * 64,
    )


def _transport(provider: str, *, validator: Mock | None = None,
               certificate: Mock | None = None, exchange: Mock | None = None):
    resolver = Mock()
    resolver.resolve_provider_id.return_value = provider
    check = validator or Mock()
    cert = certificate or Mock()
    send = exchange or Mock()
    transport = JundiaiGissHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        contract_for_method=_contract, validate_signed_xml=check,
        exchange=send, municipality_ibge=GUARULHOS_IBGE,
        provider_id=GUARULHOS_GISS_V2_PROVIDER_ID,
    )
    return transport, resolver, check, cert, send


def test_guarulhos_giss_requires_exact_municipality_and_provider() -> None:
    with pytest.raises(ValueError, match="exact reviewed"):
        JundiaiGissHomologationTransport(
            resolver=Mock(), resolve_certificate=Mock(),
            contract_for_method=_contract, validate_signed_xml=Mock(),
            municipality_ibge=GUARULHOS_IBGE,
            provider_id="jundiai-giss-v2-homologation",
        )
    transport, resolver, check, cert, send = _transport(
        "jundiai-giss-v2-homologation",
    )
    with pytest.raises(FiscalValidationError, match="durable binding"):
        transport.invoke(_operation())
    assert (
        resolver.resolve_provider_id.call_args.kwargs["jurisdiction"]
        .municipality_ibge_code == GUARULHOS_IBGE
    )
    check.assert_not_called()
    cert.assert_not_called()
    send.assert_not_called()


def test_guarulhos_invalid_official_schema_fails_before_vault_or_network() -> None:
    invalid = Mock(side_effect=FiscalValidationError("Pinned 2026 XSD not verified"))
    transport, _, check, cert, send = _transport(
        GUARULHOS_GISS_V2_PROVIDER_ID, validator=invalid,
    )
    with pytest.raises(FiscalValidationError, match="Pinned 2026 XSD"):
        transport.invoke(_operation())
    check.assert_called_once()
    cert.assert_not_called()
    send.assert_not_called()


def test_guarulhos_rejects_national_regime_routed_to_municipal_giss() -> None:
    request = _operation()
    request = JundiaiSignedOperation(
        scope=request.scope, issuer_cnpj=request.issuer_cnpj,
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        competence_date=request.competence_date, method=request.method,
        signed_xml=request.signed_xml,
    )
    transport, resolver, check, cert, send = _transport(
        GUARULHOS_GISS_V2_PROVIDER_ID,
    )
    with pytest.raises(FiscalValidationError, match="provider conflicts"):
        transport.invoke(request)
    resolver.resolve_provider_id.assert_not_called()
    check.assert_not_called()
    cert.assert_not_called()
    send.assert_not_called()


def test_guarulhos_original_rps_query_reuses_giss_builder_without_reissue() -> None:
    original = Sp4OriginalRps(
        scope=_operation().scope,
        document_id="guarulhos-original", request_fingerprint="d" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge=GUARULHOS_IBGE,
        competence_date=date(2026, 11, 15),
        rps_number="42", rps_series="R1", gross_amount=Decimal("150.00"),
        municipal_batch_id="2201",
    )
    query = build_jundiai_rps_query(
        original, TaxRegimeCode.NORMAL,
        municipal_registration="1234567",
    )
    assert query.method == "ConsultarNfsePorRps"
    assert b"42" in query.signed_xml
    assert b"1234567" in query.signed_xml
    assert query.issuer_cnpj == original.issuer_cnpj


def test_guarulhos_runtime_ports_reject_other_city_and_keep_canonical_loader() -> None:
    mismatch, *_ = _transport(GUARULHOS_GISS_V2_PROVIDER_ID)
    same = JundiaiTrustedRuntimePorts(
        transport=mismatch, build_signed_operation=Mock(),
        verify_signed_rps_identity=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(), verify_official_invoice_xml=Mock(),
    )
    reviewed = GuarulhosGissTrustedRuntimePorts(shared_giss=same)
    app = Mock(spec=FiscalApplicationService)
    ports = reviewed.attach(app)
    assert ports.load_original_rps == app.load_sp4_original_rps
    assert callable(ports.query_official_rps)

    wrong = JundiaiGissHomologationTransport(
        resolver=Mock(), resolve_certificate=Mock(),
        contract_for_method=_contract, validate_signed_xml=Mock(),
    )
    with pytest.raises(FiscalValidationError, match="Guarulhos"):
        GuarulhosGissTrustedRuntimePorts(shared_giss=JundiaiTrustedRuntimePorts(
            transport=wrong, build_signed_operation=Mock(),
            verify_signed_rps_identity=Mock(),
            fiscal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
            verify_official_invoice_xml=Mock(),
        ))
