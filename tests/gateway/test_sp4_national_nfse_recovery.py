"""Deterministic regression: SP4 National NFS-e recovery is GET only.

All responses are simulated. No taxpayer A1, municipal credentials or fiscal
service is contacted and no external homologation is inferred.
"""
from __future__ import annotations

import base64
import gzip
import json
from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    OfficialNfseTransportError,
)
from kordena_fiscal.gateway.nfse_nacional_query import (
    NfseNacionalHomologationQueryGateway,
    NfseNationalLookupMissing,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.issuance.nfse_dps_builder import derive_national_dps_id
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    _GovernedNationalNfseGateway,
    _GovernedNfseRouter,
)

CITIES = ("3509205", "3505708", "3534401", "3525904")


def _request(
    city: str,
    regime: TaxRegimeCode = TaxRegimeCode.SIMPLES_NACIONAL,
    competence: date = date(2026, 11, 13),
) -> Mock:
    req = Mock(spec=NfseAuthorizationRequest)
    req.document = Mock()
    doc = req.document
    doc.scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="tenant-sp4", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="sp4-recovery",
    )
    doc.issuer.cnpj.value = "11222333000181"
    doc.issuer.address.jurisdiction = BrazilianJurisdiction("SP", city)
    doc.issuer.tax_regime = regime
    doc.competence_date = competence
    doc.document_id = "sp4-" + city
    req.idempotency_key = IdempotencyKey("a" * 64)
    req.request_fingerprint = "b" * 64
    return req


def _gateway(monkeypatch: pytest.MonkeyPatch, exchange: Mock) -> tuple[
    NfseNacionalHomologationQueryGateway, Mock
]:
    from kordena_fiscal.gateway import nfse_nacional_query as mod

    vault = Mock(return_value=Mock())
    monkeypatch.setattr(mod, "validate_a1_for_issuer", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "build_fiscal_tls_context", lambda cert: Mock())
    return NfseNacionalHomologationQueryGateway(
        resolve_certificate=vault, exchange_get=exchange,
    ), vault


@pytest.mark.parametrize("ibge", CITIES)
def test_national_recovery_uses_only_two_gets_and_preserves_authorized_xml(
    ibge: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(ibge)
    dps_id = derive_national_dps_id(request)
    key = "35" + "0" * 48
    xml = (
        f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infNFSe Id="NFS{key}"/></NFSe>'
    ).encode()
    replies = [
        json.dumps({"chaveAcesso": key}).encode(),
        json.dumps({
            "chaveAcesso": key,
            "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii"),
        }).encode(),
    ]
    exchange = Mock(side_effect=replies)
    gateway, vault = _gateway(monkeypatch, exchange)
    result = gateway.query(request)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == key
    assert result.authorized_xml == xml
    assert result.document_id == request.document.document_id
    assert result.scope == request.document.scope
    assert result.provider.provider_name == NACIONAL_HOMOLOGATION_PROVIDER_ID
    assert exchange.call_count == 2
    assert exchange.call_args_list[0].args[0] == "/dps/" + dps_id
    assert exchange.call_args_list[1].args[0] == "/nfse/" + key
    vault.assert_called_once()


@pytest.mark.parametrize("ibge", CITIES)
def test_missing_dps_is_pending_not_a_second_issue(
    ibge: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Mock(side_effect=NfseNationalLookupMissing("not found"))
    gateway, _ = _gateway(monkeypatch, exchange)
    result = gateway.query(_request(ibge))
    assert result.status is AuthorizationStatus.PENDING
    assert result.invoice_reference is None
    assert exchange.call_count == 1


@pytest.mark.parametrize("ibge", CITIES)
@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.NORMAL, date(2026, 11, 13)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31)),
    (TaxRegimeCode.MEI, date(2023, 8, 31)),
])
def test_ineligible_context_fails_before_vault_or_get(
    ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    vault, exchange = Mock(), Mock()
    gateway = NfseNacionalHomologationQueryGateway(
        resolve_certificate=vault, exchange_get=exchange,
    )
    with pytest.raises(OfficialNfseTransportError, match="regime/competence"):
        gateway.query(_request(ibge, regime, competence))
    vault.assert_not_called()
    exchange.assert_not_called()


def test_invalid_access_key_blocks_second_get(monkeypatch: pytest.MonkeyPatch) -> None:
    exchange = Mock(return_value=b'{"chaveAcesso":"not-a-key"}')
    gateway, _ = _gateway(monkeypatch, exchange)
    with pytest.raises(OfficialNfseTransportError, match="chave fiscal valida"):
        gateway.query(_request("3509205"))
    exchange.assert_called_once()


def test_exact_query_binding_required_before_transport() -> None:
    original = _request("3509205")
    backend = Mock()
    app = Mock()
    app.resolve_configured_provider_id.return_value = "other-municipal-provider"
    guarded = _GovernedNationalNfseGateway(
        application=app, preaudit=Mock(), gateway=Mock(), query_gateway=backend,
    )
    with pytest.raises(FiscalValidationError, match="provider does not match"):
        guarded.query(original)
    backend.query.assert_not_called()
    call = app.resolve_configured_provider_id.call_args
    assert call.kwargs["operation"] == "query"


def test_router_requires_authorize_and_query_bindings_separately() -> None:
    request = _request("3534401")
    fake_national = Mock(spec=_GovernedNationalNfseGateway)
    fake_national.query.return_value = "query-result"
    app = Mock()
    app.resolve_configured_provider_id.return_value = NACIONAL_HOMOLOGATION_PROVIDER_ID
    router = _GovernedNfseRouter(application=app, national=fake_national, extrema=None)
    assert router.query(request) == "query-result"
    fake_national.query.assert_called_once_with(request)
