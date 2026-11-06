"""Unit tests for the deterministic Sentinela Normativo pre-audit gate."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kordena_fiscal.compliance.nfse_preaudit import NfsePreauditRejection, nfse_preaudit
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
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)

_INSTANT = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _scope() -> ExecutionScope:
    return ExecutionScope(
        tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="corr-preaudit-1",
    )


def _issuer() -> FiscalProfile:
    return FiscalProfile(
        profile_id="issuer-preaudit-1",
        scope=_scope(),
        cnpj=Cnpj("12345678000195"),
        legal_name="Empresa Sintetica de Servicos Ltda",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica",
            number="100",
            district="Centro",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _service(**overrides) -> NfseServiceLine:
    base = dict(
        line_number=1,
        municipal_service_code="0107",
        national_taxation_code="010701",
        description="Servico sintetico de tecnologia",
        gross_amount=Money(Decimal("100.00")),
        deduction_amount=Money.zero(),
        iss_amount=Money(Decimal("3.00")),
        iss_withheld=False,
    )
    base.update(overrides)
    return NfseServiceLine(**base)


def _request(services=None) -> NfseAuthorizationRequest:
    document = NfseCanonicalDocument(
        document_id="nfse-preaudit-doc-1",
        scope=_scope(),
        source=SourceReference("service-order", "order-preaudit-1"),
        issued_at=_INSTANT,
        competence_date=_INSTANT.date(),
        issuer=_issuer(),
        service_jurisdiction=BrazilianJurisdiction("SP", "3550308"),
        services=services if services is not None else (_service(),),
        service_taker_reference="taker-ref-1",
    )
    return NfseAuthorizationRequest.build(document)


def test_nfse_preaudit_accepts_well_formed_request_within_statutory_rate() -> None:
    assert nfse_preaudit(_request()) is None


def test_nfse_preaudit_accepts_rate_exactly_at_the_statutory_floor() -> None:
    request = _request(
        services=(
            _service(gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("2.00"))),
        )
    )
    assert nfse_preaudit(request) is None


def test_nfse_preaudit_accepts_rate_exactly_at_the_statutory_ceiling() -> None:
    request = _request(
        services=(
            _service(gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("5.00"))),
        )
    )
    assert nfse_preaudit(request) is None


def test_nfse_preaudit_rejects_rate_below_statutory_floor() -> None:
    request = _request(
        services=(
            _service(gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("1.00"))),
        )
    )
    with pytest.raises(NfsePreauditRejection, match="faixa legal"):
        nfse_preaudit(request)


def test_nfse_preaudit_rejects_rate_above_statutory_ceiling() -> None:
    request = _request(
        services=(
            _service(gross_amount=Money(Decimal("100.00")), iss_amount=Money(Decimal("7.00"))),
        )
    )
    with pytest.raises(NfsePreauditRejection, match="faixa legal"):
        nfse_preaudit(request)


def test_nfse_preaudit_allows_zero_iss_line_without_rate_check() -> None:
    request = _request(services=(_service(iss_amount=Money.zero()),))
    assert nfse_preaudit(request) is None


def test_nfse_preaudit_rejects_missing_national_taxation_code() -> None:
    request = _request(services=(_service(national_taxation_code=None),))
    with pytest.raises(NfsePreauditRejection, match="cTribNac"):
        nfse_preaudit(request)


def test_nfse_preaudit_rejects_zero_item_or_subitem_in_cTribNac() -> None:
    request = _request(services=(_service(national_taxation_code="000101"),))
    with pytest.raises(NfsePreauditRejection, match="item ou subitem"):
        nfse_preaudit(request)


def test_nfse_preaudit_rejects_more_than_one_service_line() -> None:
    request = _request(services=(_service(line_number=1), _service(line_number=2)))
    with pytest.raises(NfsePreauditRejection, match="exatamente um"):
        nfse_preaudit(request)


def test_nfse_preaudit_rejects_non_request_argument() -> None:
    with pytest.raises(FiscalValidationError, match="NfseAuthorizationRequest"):
        nfse_preaudit(object())
