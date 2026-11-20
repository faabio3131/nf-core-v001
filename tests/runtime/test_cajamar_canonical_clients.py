"""Cajamar canonical gateway acceptance: source, channel, replay and proof.

Uses synthetic evidence only. No A1 material or municipal HTTP requests.
"""
from __future__ import annotations

from dataclasses import replace
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
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
    build_sp4_canonical_clients,
)

_PROVIDER = "cajamar-geisweb-homologation"
_CNPJ = Cnpj("11222333000181")
_AMOUNT = Decimal("150.00")
_COMPETENCE = date(2026, 10, 31)


def _scope(
    *, tenant: str = "tenant-cajamar", unit: str = "unit-a",
) -> ExecutionScope:
    return ExecutionScope(
        host_namespace="nfcore", tenant_id=tenant, unit_id=unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="cajamar-source",
    )


def _request(
    *, competence: date = _COMPETENCE,
    regime: TaxRegimeCode = TaxRegimeCode.NORMAL,
    tenant: str = "tenant-cajamar",
    unit: str = "unit-a",
    cnpj: Cnpj = _CNPJ,
) -> Mock:
    request = Mock(spec=NfseAuthorizationRequest)
    doc = Mock()
    doc.scope = _scope(tenant=tenant, unit=unit)
    doc.document_id = "cajamar-original-42"
    doc.issuer.address.jurisdiction = BrazilianJurisdiction("SP", "3509205")
    doc.issuer.cnpj = cnpj
    doc.issuer.tax_regime = regime
    doc.competence_date = competence
    doc.totals.gross_amount.amount = _AMOUNT
    request.document = doc
    request.request_fingerprint = "a" * 64
    request.idempotency_key = IdempotencyKey("b" * 64)
    return request


def _original() -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=_scope(), document_id="cajamar-original-42",
        request_fingerprint="a" * 64, issuer_cnpj=_CNPJ,
        issuer_ibge="3509205", competence_date=_COMPETENCE,
        rps_number="42", rps_series="NF", gross_amount=_AMOUNT,
        municipal_batch_id="42",
    )


def _invoice(**changes: object) -> Sp4VerifiedInvoice:
    fields = {
        "issuer_cnpj": _CNPJ,
        "issuer_ibge": "3509205",
        "competence_date": _COMPETENCE,
        "rps_number": "42",
        "rps_series": "NF",
        "gross_amount": _AMOUNT,
        "invoice_number": "8765",
        "verification_code": "ABCDEF1234",
        "invoice_reference": "8765",
        "authorized_xml": b"<ConsultaLoteRpsResposta>synthetic</ConsultaLoteRpsResposta>",
    }
    fields.update(changes)
    return Sp4VerifiedInvoice(**fields)  # type: ignore[arg-type]


def _clients(
    *, official: Sp4ProviderOutcome | None = None,
    binding: str = _PROVIDER,
    original: Sp4OriginalRps | None = None,
) -> tuple[object, object, dict[str, Mock]]:
    mocks = {
        "resolver": Mock(),
        "canonical_load": Mock(return_value=original if original is not None else _original()),
        "untrusted_load": Mock(side_effect=AssertionError("parallel source of truth used")),
        "policy": Mock(),
        "preflight": Mock(),
        "submit": Mock(return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)),
        "query": Mock(return_value=official if official is not None else Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED, official_invoice=_invoice(),
        )),
        "verify": Mock(),
    }
    mocks["resolver"].resolve_provider_id.return_value = binding
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=mocks["untrusted_load"],
        fiscal_issuer_policy=mocks["policy"],
        validate_prepared_rps=mocks["preflight"],
        submit_official_rps=mocks["submit"],
        query_official_rps=mocks["query"],
        verify_official_invoice_xml=mocks["verify"],
    )
    issued, lookup = build_sp4_canonical_clients(
        canonical_resolver=mocks["resolver"],
        configured_municipalities={_PROVIDER: ports},
        canonical_rps_loader=mocks["canonical_load"],
    )
    return issued[_PROVIDER], lookup[_PROVIDER], mocks


def test_cajamar_issue_pending_then_lot_query_authorizes_without_second_post() -> None:
    issue, query, mocks = _clients()
    request = _request()
    submitted = issue.authorize(request)
    assert submitted.status is AuthorizationStatus.PENDING
    recovered = query.query(request)
    assert recovered.status is AuthorizationStatus.AUTHORIZED
    assert recovered.invoice_number == "8765"
    assert recovered.verification_code == "ABCDEF1234"
    assert recovered.authorized_xml == _invoice().authorized_xml
    mocks["submit"].assert_called_once_with(request, _original())
    mocks["query"].assert_called_once_with(request, _original())
    assert mocks["canonical_load"].call_count == 2
    mocks["untrusted_load"].assert_not_called()
    mocks["verify"].assert_called_once()
    assert mocks["resolver"].resolve_provider_id.call_args.kwargs["operation"] == "query"


@pytest.mark.parametrize("regime,competence", [
    (TaxRegimeCode.MEI, date(2023, 9, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
    (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 2)),
])
def test_national_competence_never_enters_cajamar_municipal_transport(
    regime: TaxRegimeCode, competence: date,
) -> None:
    issue, _, mocks = _clients()
    with pytest.raises(Sp4CanonicalMunicipalError, match="National"):
        issue.authorize(_request(regime=regime, competence=competence))
    mocks["resolver"].resolve_provider_id.assert_not_called()
    mocks["canonical_load"].assert_not_called()
    mocks["submit"].assert_not_called()


def test_cajamar_before_november_me_epp_follows_binding_without_invented_authority() -> None:
    issue, _, mocks = _clients()
    assert issue.authorize(
        _request(regime=TaxRegimeCode.SIMPLES_NACIONAL),
    ).status is AuthorizationStatus.PENDING
    mocks["submit"].assert_called_once()


def test_unapproved_provider_never_reads_original_or_opens_transport() -> None:
    issue, _, mocks = _clients(binding="another-provider")
    with pytest.raises(Sp4CanonicalMunicipalError, match="provider binding"):
        issue.authorize(_request())
    mocks["canonical_load"].assert_not_called()
    mocks["submit"].assert_not_called()


@pytest.mark.parametrize("changes", [
    {"tenant": "different-tenant"},
    {"unit": "different-unit"},
    {"cnpj": Cnpj("00944029000121")},
])
def test_unrelated_taxpayer_cannot_use_original_rps_even_in_same_unit(
    changes: dict[str, object],
) -> None:
    issue, _, mocks = _clients()
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS"):
        issue.authorize(_request(**changes))  # type: ignore[arg-type]
    mocks["submit"].assert_not_called()
    mocks["verify"].assert_not_called()


@pytest.mark.parametrize("changed", [
    {"issuer_cnpj": Cnpj("00944029000121")},
    {"rps_number": "43"},
    {"gross_amount": Decimal("150.01")},
    {"competence_date": date(2026, 10, 30)},
])
def test_cajamar_fiscal_proof_must_match_source_before_verification(
    changed: dict[str, object],
) -> None:
    outcome = Sp4ProviderOutcome(
        status=AuthorizationStatus.AUTHORIZED,
        official_invoice=_invoice(**changed),
    )
    _, query, mocks = _clients(official=outcome)
    with pytest.raises(Sp4CanonicalMunicipalError, match="disagrees"):
        query.query(_request())
    mocks["verify"].assert_not_called()


def test_recovery_not_found_never_proves_original_post_was_rejected() -> None:
    _, query, mocks = _clients(official=Sp4ProviderOutcome(
        status=AuthorizationStatus.REJECTED,
        rejection_code="NOT_FOUND",
        rejection_message="No lot result yet",
    ))
    result = query.query(_request())
    assert result.status is AuthorizationStatus.PENDING
    assert result.rejection_code is None
    mocks["submit"].assert_not_called()


def test_failed_official_xml_verification_prevents_authorized_transition() -> None:
    _, query, mocks = _clients()
    mocks["verify"].side_effect = Sp4CanonicalMunicipalError(
        "Unverified municipal official schema/signature"
    )
    with pytest.raises(Sp4CanonicalMunicipalError, match="schema/signature"):
        query.query(_request())
    mocks["submit"].assert_not_called()


def test_spoofed_original_rps_fingerprint_cannot_bypass_canonical_loader() -> None:
    wrong = replace(_original(), request_fingerprint="f" * 64)
    issue, _, mocks = _clients(original=wrong)
    with pytest.raises(Sp4CanonicalMunicipalError, match="original RPS"):
        issue.authorize(_request())
    mocks["submit"].assert_not_called()


def test_alternate_municipal_loader_is_not_a_fallback_authority() -> None:
    with pytest.raises(Sp4CanonicalMunicipalError, match="canonical original RPS"):
        build_sp4_canonical_clients(
            canonical_resolver=Mock(),
            configured_municipalities={},
            canonical_rps_loader=None,  # type: ignore[arg-type]
        )
