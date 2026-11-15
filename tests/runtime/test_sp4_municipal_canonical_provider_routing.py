"""SP4 canonical admission: municipal transports never bypass durable bindings.

The underlying municipal implementations have their own schema/credentials
tests; no live fiscal submission is attempted here.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.issuance import NfseGatewayClient, NfseQueryClient
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    _SP4_MUNICIPAL_PROVIDER_IBGE,
    _GovernedNfseRouter,
    _require_sp4_municipal_channel,
)


def _request(ibge: str, regime: TaxRegimeCode, competence: date) -> Mock:
    request = Mock()
    request.document.scope.environment = FiscalEnvironment.HOMOLOGATION
    request.document.scope.host_namespace = "nfcore"
    request.document.issuer.address.jurisdiction = BrazilianJurisdiction("SP", ibge)
    request.document.issuer.tax_regime = regime
    request.document.competence_date = competence
    return request


def _router(provider_id: str) -> tuple[_GovernedNfseRouter, Mock, Mock, Mock]:
    application = Mock()
    application.resolve_configured_provider_id.return_value = provider_id
    authorization = Mock(spec=NfseGatewayClient)
    query = Mock(spec=NfseQueryClient)
    router = _GovernedNfseRouter(
        application=application,
        national=None,
        extrema=None,
        sp4_municipal_gateways={provider_id: authorization},
        sp4_municipal_query={provider_id: query},
        sp4_preaudit=Mock(),
    )
    return router, application, authorization, query


@pytest.mark.parametrize("provider,ibge", sorted(_SP4_MUNICIPAL_PROVIDER_IBGE.items()))
def test_municipal_normal_issuer_with_persisted_binding_can_reach_opt_in_port(
    provider: str, ibge: str,
) -> None:
    router, application, authorization, query = _router(provider)
    request = _request(ibge, TaxRegimeCode.NORMAL, date(2026, 11, 13))
    token = object()
    authorization.authorize.return_value = token
    query.query.return_value = token
    assert router.authorize(request) is token
    assert router.query(request) is token
    assert authorization.authorize.call_count == 1
    assert query.query.call_count == 1
    assert application.resolve_configured_provider_id.call_count == 3


@pytest.mark.parametrize("provider,ibge", sorted(_SP4_MUNICIPAL_PROVIDER_IBGE.items()))
@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 13)),
])
def test_federal_channel_prevents_municipal_execution_with_valid_provider_binding(
    provider: str, ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    router, _, authorize, query = _router(provider)
    request = _request(ibge, regime, competence)
    with pytest.raises(FiscalValidationError, match="National NFS-e"):
        router.authorize(request)
    with pytest.raises(FiscalValidationError, match="National NFS-e"):
        router.query(request)
    authorize.authorize.assert_not_called()
    query.query.assert_not_called()


@pytest.mark.parametrize("provider,ibge", sorted(_SP4_MUNICIPAL_PROVIDER_IBGE.items()))
def test_provider_binding_to_wrong_sp_municipality_fails_before_io(
    provider: str, ibge: str,
) -> None:
    wrong_ibge = next(code for code in _SP4_MUNICIPAL_PROVIDER_IBGE.values() if code != ibge)
    router, _, authorize, query = _router(provider)
    request = _request(wrong_ibge, TaxRegimeCode.NORMAL, date(2026, 11, 13))
    with pytest.raises(FiscalValidationError, match="binding/city mismatch"):
        router.authorize(request)
    with pytest.raises(FiscalValidationError, match="binding/city mismatch"):
        router.query(request)
    authorize.authorize.assert_not_called()
    query.query.assert_not_called()


def test_absent_provider_authority_cannot_select_any_sp4_transport() -> None:
    router, app, authorize, query = _router("osasco-rtc-homologation")
    app.resolve_configured_provider_id.return_value = "unapproved-provider"
    req = _request("3534401", TaxRegimeCode.NORMAL, date(2026, 11, 13))
    with pytest.raises(FiscalValidationError, match="no approved matching provider"):
        router.authorize(req)
    with pytest.raises(FiscalValidationError, match="recovery is unavailable"):
        router.query(req)
    authorize.authorize.assert_not_called()
    query.query.assert_not_called()


def test_unknown_municipal_provider_is_not_implicitly_registered() -> None:
    with pytest.raises(ValueError, match="reviewed provider IDs"):
        _GovernedNfseRouter(
            application=Mock(), national=None, extrema=None,
            sp4_municipal_gateways={"unapproved": Mock(spec=NfseGatewayClient)},
            sp4_preaudit=Mock(),
        )


def test_sp4_query_without_matching_issuance_port_is_invalid() -> None:
    with pytest.raises(ValueError, match="matching issuer gateway"):
        _GovernedNfseRouter(
            application=Mock(), national=None, extrema=None,
            sp4_municipal_query={
                "jundiai-giss-v2-homologation": Mock(spec=NfseQueryClient)
            },
            sp4_preaudit=Mock(),
        )


def test_sp4_untrusted_gateway_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="canonical NFS-e"):
        _GovernedNfseRouter(
            application=Mock(), national=None, extrema=None,
            sp4_municipal_gateways={"barueri-pmb004-homologation": object()},
            sp4_preaudit=Mock(),
        )


def test_out_of_state_issuer_cannot_reach_sp4_municipal_channel() -> None:
    req = _request("3505708", TaxRegimeCode.NORMAL, date(2026, 11, 13))
    req.document.issuer.address.jurisdiction = BrazilianJurisdiction("MG", "3106200")
    with pytest.raises(FiscalValidationError, match="requires SP"):
        _require_sp4_municipal_channel(req)


def test_municipal_query_needs_a_separate_durable_query_binding() -> None:
    from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation

    router, application, authorization, query = _router(
        "osasco-rtc-homologation"
    )
    application.resolve_configured_provider_id.side_effect = (
        lambda **kw: "not-authorized-for-query"
        if kw["operation"] == ConfiguredFiscalOperation.QUERY.value
        else "osasco-rtc-homologation"
    )
    req = _request("3534401", TaxRegimeCode.NORMAL, date(2026, 11, 13))
    with pytest.raises(FiscalValidationError, match="read-only provider binding mismatch"):
        router.query(req)
    authorization.authorize.assert_not_called()
    query.query.assert_not_called()


@pytest.mark.parametrize("invalid", ["2026-11-13", None, 1234])
def test_malformed_competence_cannot_bypass_federal_channel(invalid: object) -> None:
    request = _request("3509205", TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 13))
    request.document.competence_date = invalid
    with pytest.raises(FiscalValidationError, match="reviewed issuer regime and competence"):
        _require_sp4_municipal_channel(request)


def test_municipal_gateways_cannot_be_installed_without_canonical_preaudit() -> None:
    with pytest.raises(ValueError, match="canonical fiscal pre-audit"):
        _GovernedNfseRouter(
            application=Mock(), national=None, extrema=None,
            sp4_municipal_gateways={
                "cajamar-geisweb-homologation": Mock(spec=NfseGatewayClient),
            },
        )
