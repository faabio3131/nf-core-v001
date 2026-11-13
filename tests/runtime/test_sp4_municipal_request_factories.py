"""SP4 city-specific original-RPS recovery builders fit existing engine ports."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.cajamar_geisweb_request_builder import (
    CajamarGeiswebBuilderError,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.runtime.sp4_municipal_request_factories import (
    build_cajamar_reviewed_request_factory,
    build_jundiai_reviewed_request_factory,
)


def _source(city: str) -> Sp4OriginalRps:
    return Sp4OriginalRps(
        scope=ExecutionScope(
            host_namespace="nfcore", tenant_id="company", unit_id="unit",
            environment=FiscalEnvironment.HOMOLOGATION, correlation_id="factory",
        ),
        document_id="prepared", request_fingerprint="a" * 64,
        issuer_cnpj=Cnpj("11222333000181"), issuer_ibge=city,
        competence_date=date(2026, 10, 25), rps_number="42",
        rps_series="NF", gross_amount=Decimal("150.00"),
        municipal_batch_id="12345",
    )


def _request() -> NfseAuthorizationRequest:
    req = Mock(spec=NfseAuthorizationRequest)
    req.document.issuer.tax_regime = TaxRegimeCode.NORMAL
    return req


def test_cajamar_factory_does_not_build_new_note_during_lot_query() -> None:
    issue = Mock(return_value=object())
    verify = Mock()
    factory = build_cajamar_reviewed_request_factory(
        build_signed_issue=issue, sign_lot_query=lambda raw: raw,
        validate_signed_query=verify,
    )
    req = _request()
    original = _source("3509205")
    result = factory(req, original, "ConsultaLoteRps")
    assert result.method == "ConsultaLoteRps"
    assert b"12345" in result.signed_request_xml
    verify.assert_called_once()
    issue.assert_not_called()
    assert factory(req, original, "EnviaLoteRps") is issue.return_value
    issue.assert_called_once_with(req, original)


def test_jundiai_factory_reuses_original_rps_and_authorized_registration() -> None:
    issue = Mock(return_value=object())
    read_registration = Mock(return_value="1234567")
    verify = Mock()
    factory = build_jundiai_reviewed_request_factory(
        build_signed_issue=issue,
        resolve_municipal_registration=read_registration,
        sign_rps_query=lambda raw: raw, validate_signed_query=verify,
    )
    req = _request()
    original = _source("3525904")
    result = factory(req, original, "ConsultarNfsePorRps")
    assert result.method == "ConsultarNfsePorRps"
    assert b"1234567" in result.signed_xml
    assert b"42" in result.signed_xml
    read_registration.assert_called_once_with(original.scope, original.issuer_cnpj.value)
    issue.assert_not_called()
    verify.assert_called_once()
    assert factory(req, original, "RecepcionarLoteRps") is issue.return_value
    issue.assert_called_once_with(req, original)


@pytest.mark.parametrize("method", ["CancelarNfse", "ConsultarNfse"])
def test_no_method_confusion_between_cajamar_invoice_and_lot(method: str) -> None:
    factory = build_cajamar_reviewed_request_factory(
        build_signed_issue=Mock(), sign_lot_query=lambda raw: raw,
        validate_signed_query=Mock(),
    )
    with pytest.raises(Sp4CanonicalMunicipalError):
        factory(_request(), _source("3509205"), method)


def test_wrong_city_is_not_relabelled_as_cajamar() -> None:
    factory = build_cajamar_reviewed_request_factory(
        build_signed_issue=Mock(), sign_lot_query=lambda raw: raw,
        validate_signed_query=Mock(),
    )
    with pytest.raises(CajamarGeiswebBuilderError):
        factory(
            _request(),
            replace(_source("3509205"), issuer_ibge="3534401"),
            "ConsultaLoteRps",
        )
