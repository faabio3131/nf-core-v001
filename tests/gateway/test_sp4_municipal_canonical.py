"""Four municipal canonical adapters: durable RPS, eligibility and official proof.

No HTTP or official fiscal endpoint is used in this suite.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4CanonicalMunicipalError,
    Sp4MunicipalCanonicalGateway,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseGatewayClient,
    NfseQueryClient,
)
from kordena_fiscal.lifecycle import IdempotencyKey

_CNPJ = Cnpj("11222333000181")
_COMPETENCE = date(2026, 11, 13)
_AMOUNT = Decimal("150.00")


def _scope() -> ExecutionScope:
    return ExecutionScope(
        host_namespace="nfcore", tenant_id="sp4-pilot-tenant",
        unit_id="accountant-unit", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="sp4-canonical",
    )


def _request(ibge: str, regime: TaxRegimeCode = TaxRegimeCode.NORMAL) -> Mock:
    request = Mock(spec=NfseAuthorizationRequest)
    doc = Mock()
    doc.scope = _scope()
    doc.document_id = "prepared-sp4-original"
    doc.issuer.address.jurisdiction = BrazilianJurisdiction("SP", ibge)
    doc.issuer.cnpj = _CNPJ
    doc.issuer.tax_regime = regime
    doc.competence_date = _COMPETENCE
    doc.totals.gross_amount.amount = _AMOUNT
    request.document = doc
    request.request_fingerprint = "a" * 64
    request.idempotency_key = IdempotencyKey("b" * 64)
    return request


def _original(ibge: str) -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=_scope(), document_id="prepared-sp4-original",
        request_fingerprint="a" * 64, issuer_cnpj=_CNPJ, issuer_ibge=ibge,
        competence_date=_COMPETENCE, rps_number="42", rps_series="NF",
        gross_amount=_AMOUNT,
    )


def _invoice(ibge: str, **overrides: object) -> Sp4VerifiedInvoice:
    fields = {
        "issuer_cnpj": _CNPJ,
        "issuer_ibge": ibge,
        "competence_date": _COMPETENCE,
        "rps_number": "42",
        "rps_series": "NF",
        "gross_amount": _AMOUNT,
        "invoice_number": "8765",
        "verification_code": "APROVADOPELOMUNICIPIO",
        "invoice_reference": "municipal-NFSe-8765",
        "authorized_xml": b"<CompNfse>offline-source-synthetic</CompNfse>",
    }
    fields.update(overrides)
    return Sp4VerifiedInvoice(**fields)  # type: ignore[arg-type]


def _ports(
    provider: str, *,
    binding: str | None = None,
    outcome: Sp4ProviderOutcome | None = None,
    original: Sp4OriginalRps | None = None,
) -> tuple[Sp4MunicipalCanonicalGateway, dict[str, Mock]]:
    ibge = SP4_MUNICIPAL_PROVIDERS[provider]
    ports: dict[str, Mock] = {
        "resolver": Mock(),
        "load": Mock(return_value=original if original is not None else _original(ibge)),
        "policy": Mock(),
        "preflight": Mock(),
        "submit": Mock(
            return_value=outcome if outcome is not None else Sp4ProviderOutcome(
                status=AuthorizationStatus.AUTHORIZED,
                official_invoice=_invoice(ibge),
            )
        ),
        "query": Mock(
            return_value=outcome if outcome is not None else Sp4ProviderOutcome(
                status=AuthorizationStatus.AUTHORIZED,
                official_invoice=_invoice(ibge),
            )
        ),
        "verify": Mock(),
    }
    ports["resolver"].resolve_provider_id.return_value = (
        provider if binding is None else binding
    )
    gateway = Sp4MunicipalCanonicalGateway(
        provider_id=provider,
        resolver=ports["resolver"],
        load_original_rps=ports["load"],
        municipal_issuer_policy=ports["policy"],
        validate_prepared_rps=ports["preflight"],
        submit_prepared_rps=ports["submit"],
        query_original_rps=ports["query"],
        verify_official_invoice_xml=ports["verify"],
    )
    return gateway, ports


@pytest.mark.parametrize("provider,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
def test_four_municipal_channels_only_authorize_source_correlated_official_invoice(
    provider: str, ibge: str,
) -> None:
    gateway, ports = _ports(provider)
    request = _request(ibge)
    result = NfseGatewayClient(gateway).authorize(request)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == "municipal-NFSe-8765"
    assert result.authorized_xml is not None
    assert result.invoice_number == "8765"
    ports["preflight"].assert_called_once()
    ports["verify"].assert_called_once()
    ports["submit"].assert_called_once()
    ports["query"].assert_not_called()
    auth = ports["resolver"].resolve_provider_id.call_args.kwargs
    assert auth["operation"] == "authorize"
    assert auth["scope"] == _scope()

    lookup = NfseQueryClient(gateway).query(request)
    assert lookup.status is AuthorizationStatus.AUTHORIZED
    ports["submit"].assert_called_once()
    ports["query"].assert_called_once()
    verify = ports["resolver"].resolve_provider_id.call_args.kwargs
    assert verify["operation"] == "query"


@pytest.mark.parametrize("provider,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
@pytest.mark.parametrize("regime", [
    TaxRegimeCode.MEI,
    TaxRegimeCode.SIMPLES_NACIONAL,
    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
])
def test_federal_mandatory_national_channel_denies_direct_municipal_dispatch(
    provider: str, ibge: str, regime: TaxRegimeCode,
) -> None:
    gateway, ports = _ports(provider)
    with pytest.raises(Sp4CanonicalMunicipalError, match="National"):
        gateway.authorize(_request(ibge, regime))
    ports["load"].assert_not_called()
    ports["submit"].assert_not_called()
    ports["resolver"].resolve_provider_id.assert_not_called()


@pytest.mark.parametrize("provider,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
def test_wrong_issuer_city_cannot_reuse_another_municipal_provider_binding(
    provider: str, ibge: str,
) -> None:
    other = next(x for x in SP4_MUNICIPAL_PROVIDERS.values() if x != ibge)
    gateway, ports = _ports(provider)
    with pytest.raises(Sp4CanonicalMunicipalError, match="issuer/municipality"):
        gateway.authorize(_request(other))
    ports["submit"].assert_not_called()
    ports["resolver"].resolve_provider_id.assert_not_called()


def test_canonical_gateway_rejects_unapproved_provider_before_prepared_rps() -> None:
    gateway, ports = _ports("osasco-rtc-homologation", binding="fake-ginfes")
    with pytest.raises(Sp4CanonicalMunicipalError, match="provider binding"):
        gateway.authorize(_request("3534401"))
    ports["load"].assert_not_called()
    ports["submit"].assert_not_called()
    ports["verify"].assert_not_called()


@pytest.mark.parametrize("mutate", [
    {"rps_number": "43"},
    {"issuer_ibge": "3505708"},
    {"gross_amount": Decimal("150.01")},
    {"competence_date": date(2026, 10, 1)},
    {"issuer_cnpj": Cnpj("00944029000121")},
])
def test_municipal_response_cannot_promote_an_unrelated_invoice(
    mutate: dict[str, object],
) -> None:
    proof = _invoice("3534401", **mutate)
    gateway, ports = _ports(
        "osasco-rtc-homologation",
        outcome=Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED, official_invoice=proof,
        ),
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="disagrees"):
        gateway.authorize(_request("3534401"))
    ports["verify"].assert_not_called()


@pytest.mark.parametrize("status", [
    AuthorizationStatus.PENDING, AuthorizationStatus.REJECTED,
])
def test_read_only_query_cannot_assert_previous_post_was_rejected(
    status: AuthorizationStatus,
) -> None:
    outcome = (
        Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
        if status is AuthorizationStatus.PENDING
        else Sp4ProviderOutcome(
            status=AuthorizationStatus.REJECTED,
            rejection_code="NOT_FOUND",
            rejection_message="No municipal record yet",
        )
    )
    gateway, ports = _ports("jundiai-giss-v2-homologation", outcome=outcome)
    result = gateway.query(_request("3525904"))
    assert result.status is AuthorizationStatus.PENDING
    assert result.rejection_code is None
    assert result.authorized_xml is None
    ports["submit"].assert_not_called()


def test_official_xml_verifier_failure_never_authorizes_invoice() -> None:
    gateway, ports = _ports("barueri-pmb004-homologation")
    ports["verify"].side_effect = Sp4CanonicalMunicipalError(
        "Official XML did not pass municipal XSD and provenance"
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="XSD"):
        gateway.authorize(_request("3505708"))
    ports["verify"].assert_called_once()


def test_missing_original_rps_fingerprint_cannot_emit_official_invoice() -> None:
    original = Sp4OriginalRps(
        scope=_scope(), document_id="prepared-sp4-original",
        request_fingerprint="c" * 64, issuer_cnpj=_CNPJ,
        issuer_ibge="3509205", competence_date=_COMPETENCE,
        rps_number="42", rps_series="NF", gross_amount=_AMOUNT,
    )
    gateway, ports = _ports("cajamar-geisweb-homologation", original=original)
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS"):
        gateway.authorize(_request("3509205"))
    ports["preflight"].assert_not_called()
    ports["submit"].assert_not_called()


def test_unproved_authorization_and_missing_official_validation_ports_rejected() -> None:
    with pytest.raises(Sp4CanonicalMunicipalError, match="official proof"):
        Sp4ProviderOutcome(status=AuthorizationStatus.AUTHORIZED)
    with pytest.raises(Sp4CanonicalMunicipalError, match="official proof ports"):
        Sp4MunicipalCanonicalGateway(
            provider_id="cajamar-geisweb-homologation",
            resolver=Mock(), load_original_rps=Mock(),
            municipal_issuer_policy=Mock(), validate_prepared_rps=Mock(),
            submit_prepared_rps=Mock(), query_original_rps=Mock(),
            verify_official_invoice_xml=None,  # type: ignore[arg-type]
        )


def test_new_query_correlation_may_reuse_original_rps_within_same_partition() -> None:
    gateway, ports = _ports("osasco-rtc-homologation")
    request = _request("3534401")
    request.document.scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="sp4-pilot-tenant",
        unit_id="accountant-unit", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="new-independent-query",
    )
    result = NfseQueryClient(gateway).query(request)
    assert result.scope == request.document.scope
    assert result.status is AuthorizationStatus.AUTHORIZED
    ports["query"].assert_called_once()


def test_other_tenant_cannot_recover_original_document_even_when_provider_is_same() -> None:
    gateway, ports = _ports("jundiai-giss-v2-homologation")
    request = _request("3525904")
    request.document.scope = ExecutionScope(
        host_namespace="nfcore", tenant_id="attacker-tenant",
        unit_id="accountant-unit", environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="cross-tenant-denied",
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS"):
        gateway.query(request)
    ports["query"].assert_not_called()
    ports["verify"].assert_not_called()


def test_only_barueri_may_use_official_blank_rps_series() -> None:
    from dataclasses import replace

    original = _original("3505708")
    blank = replace(original, rps_series="")
    assert blank.issuer_ibge == "3505708"
    invoice = _invoice("3505708", rps_series="")
    assert invoice.rps_series == ""
    for city in ("3509205", "3534401", "3525904"):
        with pytest.raises(Sp4CanonicalMunicipalError, match="RPS series"):
            replace(_original(city), rps_series="")
        with pytest.raises(Sp4CanonicalMunicipalError, match="RPS series"):
            _invoice(city, rps_series="")


@pytest.mark.parametrize("unsafe_total", [
    Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"),
    Decimal("150.001"), Decimal("-1.00"),
])
def test_municipal_source_and_invoice_proof_reject_unsafe_money(
    unsafe_total: Decimal,
) -> None:
    from dataclasses import replace

    with pytest.raises(Sp4CanonicalMunicipalError):
        replace(_original("3505708"), gross_amount=unsafe_total)
    with pytest.raises(Sp4CanonicalMunicipalError):
        replace(_invoice("3505708"), gross_amount=unsafe_total)
