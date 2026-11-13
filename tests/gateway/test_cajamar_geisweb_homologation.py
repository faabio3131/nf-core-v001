"""Cajamar GeisWeb offline preflight: no municipal network or A1 is contacted."""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, TaxRegimeCode
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CAJAMAR_GEISWEB_PROVIDER,
    CajamarGeiswebContractError,
    CajamarGeiswebHomologationTransport,
    CajamarGeiswebWsdl,
    CajamarPreparedNfse,
    _soap,
)


def _contract(endpoint: str = (
    "https://www.gerenciadecidades.com.br/homologacao/reforma/modelo/"
    "webservice/GeisWebServiceImpl.php"
)) -> CajamarGeiswebWsdl:
    return CajamarGeiswebWsdl(
        endpoint=endpoint, namespace="http://www.geisweb.com.br/",
        wsdl_sha256="a" * 64, xsd_package_sha256="b" * 64,
        method_actions={name: "http://www.geisweb.com.br/" + name for name in (
            "EnviaLoteRps", "ConsultaLoteRps", "ConsultaNfse", "CancelaNfse",
        )},
    )


def _request(
    method: str = "EnviaLoteRps",
    regime: TaxRegimeCode = TaxRegimeCode.NORMAL,
    competence: date = date(2026, 11, 13),
    approved: bool = False,
) -> CajamarPreparedNfse:
    return CajamarPreparedNfse(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="tenant-c", unit_id="unit-c",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="cajamar",
        ),
        issuer_cnpj=Cnpj("11222333000181"), tax_regime=regime,
        competence_date=competence, method=method,
        signed_request_xml=b'<Pedido xmlns="urn:test">signed-by-canonical-port</Pedido>',
        human_approved=approved,
    )


@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 9, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 13)),
])
def test_national_issuer_never_routes_to_geisweb(
    regime: TaxRegimeCode, competence: date,
) -> None:
    with pytest.raises(CajamarGeiswebContractError, match="National NFS-e"):
        _request(regime=regime, competence=competence)


@pytest.mark.parametrize("day", [
    date(2026, 8, 31), date(2026, 1, 1),
])
def test_cajamar_simples_municipal_pre_cutover_date_preserved(day: date) -> None:
    # City published July 15, 2026 that the national switchover starts
    # September 1, not November 1.
    assert _request(
        regime=TaxRegimeCode.SIMPLES_NACIONAL, competence=day,
    ).method == "EnviaLoteRps"


@pytest.mark.parametrize("day", [date(2026, 9, 1), date(2026, 10, 1)])
def test_cajamar_simples_after_official_september_2026_switch(day: date) -> None:
    with pytest.raises(CajamarGeiswebContractError, match="National NFS-e"):
        _request(
            regime=TaxRegimeCode.SIMPLES_NACIONAL, competence=day,
        )


def test_cancellation_requires_operator_approval() -> None:
    with pytest.raises(CajamarGeiswebContractError, match="human approval"):
        _request(method="CancelaNfse")
    assert _request(method="CancelaNfse", approved=True).human_approved


@pytest.mark.parametrize("endpoint", [
    "http://www.geisweb.net.br/homologacao/modelo/webservice/GeisWebServiceImpl.php",
    "https://attacker.example/homologacao/modelo/webservice/GeisWebServiceImpl.php",
    "https://www.geisweb.net.br/homologacao/modelo/webservice/GeisWebServiceImpl.php?token=x",
])
def test_unverified_host_or_query_rejected(endpoint: str) -> None:
    with pytest.raises(CajamarGeiswebContractError, match="Unverified"):
        _contract(endpoint)


def test_signed_xml_is_escaped_in_soap_body() -> None:
    soap = _soap(_request(), _contract())
    assert b"&lt;Pedido" in soap
    assert b"EnviaLoteRps" in soap


def test_wrong_binding_never_reaches_certificate() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    resolver.resolve_provider_id.return_value = "old-foreign-provider"
    adapter = CajamarGeiswebHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        signed_xml_validator=Mock(), contract=_contract(),
        exchange=exchange,
    )
    with pytest.raises(CajamarGeiswebContractError, match="durable provider binding"):
        adapter.invoke(_request())
    cert.assert_not_called()
    exchange.assert_not_called()


def test_official_validator_blocks_before_a1() -> None:
    resolver, cert, exchange = Mock(), Mock(), Mock()
    resolver.resolve_provider_id.return_value = CAJAMAR_GEISWEB_PROVIDER
    validate = Mock(side_effect=CajamarGeiswebContractError("schema not pinned"))
    adapter = CajamarGeiswebHomologationTransport(
        resolver=resolver, resolve_certificate=cert,
        signed_xml_validator=validate, contract=_contract(), exchange=exchange,
    )
    with pytest.raises(CajamarGeiswebContractError, match="schema not pinned"):
        adapter.invoke(_request())
    cert.assert_not_called()
    exchange.assert_not_called()
