"""SP accounting pilot: national NFS-e negative gate before A1/network access.

Cajamar is outside the SP-22 catalog; Osasco and Barueri are inside it.
No test here issues a real invoice, configures a municipal provider or certifies one.
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
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NfseNacionalHomologationGateway,
    OfficialNfseTransportError,
    require_nfse_national_issuer_eligibility,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

SP_ACCOUNTING_PILOT = {
    "3509205": "Cajamar",
    "3534401": "Osasco",
    "3505708": "Barueri",
}


def _request(ibge: str, regime: TaxRegimeCode, competence: date) -> Mock:
    # The signed-document construction is tested separately. Here the specific
    # preflight guarantee is that no cert or transport can be accessed.
    request = Mock(spec=NfseAuthorizationRequest)
    request.document = Mock()
    request.document.scope.environment = FiscalEnvironment.HOMOLOGATION
    request.document.issuer.cnpj.value = "11222333000181"
    request.document.issuer.address.jurisdiction = BrazilianJurisdiction("SP", ibge)
    request.document.issuer.tax_regime = regime
    request.document.competence_date = competence
    return request


@pytest.mark.parametrize("ibge", SP_ACCOUNTING_PILOT)
@pytest.mark.parametrize(
    ("regime", "competence"),
    [
        (TaxRegimeCode.NORMAL, date(2026, 11, 13)),
        (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 10, 31)),
        (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 10, 31)),
        (TaxRegimeCode.MEI, date(2023, 8, 31)),
    ],
)
def test_ineligible_sp_national_issuer_never_reaches_vault_or_http(
    ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    resolve_certificate = Mock()
    build_signed_dps = Mock()
    exchange = Mock()
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=resolve_certificate,
        build_signed_dps=build_signed_dps,
        exchange=exchange,
    )
    with pytest.raises(OfficialNfseTransportError, match=f"IBGE {ibge}/SP"):
        gateway.authorize(_request(ibge, regime, competence))
    resolve_certificate.assert_not_called()
    build_signed_dps.assert_not_called()
    exchange.assert_not_called()


@pytest.mark.parametrize("ibge", SP_ACCOUNTING_PILOT)
@pytest.mark.parametrize(
    ("regime", "competence"),
    [
        (TaxRegimeCode.MEI, date(2023, 9, 1)),
        (TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 1)),
        (TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT, date(2026, 11, 13)),
    ],
)
def test_eligible_sp_context_reaches_but_does_not_bypass_certificate_gate(
    ibge: str, regime: TaxRegimeCode, competence: date,
) -> None:
    # Reaching the vault is not proof of successful signing or SEFIN issuance.
    resolve_certificate = Mock(side_effect=RuntimeError("A1 prerequisite"))
    exchange = Mock()
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=resolve_certificate,
        build_signed_dps=Mock(),
        exchange=exchange,
    )
    with pytest.raises(RuntimeError, match="A1 prerequisite"):
        gateway.authorize(_request(ibge, regime, competence))
    resolve_certificate.assert_called_once()
    exchange.assert_not_called()


@pytest.mark.parametrize("ibge", SP_ACCOUNTING_PILOT)
def test_national_channel_does_not_accept_an_unreviewed_sp_normal_issuer(
    ibge: str,
) -> None:
    with pytest.raises(FiscalValidationError, match="not nationally established"):
        require_nfse_national_issuer_eligibility(
            jurisdiction=BrazilianJurisdiction("SP", ibge),
            tax_regime=TaxRegimeCode.NORMAL,
            competence_date=date(2026, 11, 13),
        )


def test_cajamar_pilot_is_not_limited_by_the_22_city_candidate_catalog() -> None:
    from kordena_fiscal.gateway.municipal_sp_routing import SP_MUNICIPAL_CANDIDATES

    assert "3509205" not in SP_MUNICIPAL_CANDIDATES
    require_nfse_national_issuer_eligibility(
        jurisdiction=BrazilianJurisdiction("SP", "3509205"),
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        competence_date=date(2026, 11, 13),
    )


def test_official_national_authorization_keeps_the_xml_for_auditable_archival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An access key without its matching NFSe XML is not sufficient evidence."""
    import base64
    import gzip
    import json

    from kordena_fiscal.domain import ExecutionScope
    from kordena_fiscal.gateway import nfse_nacional_homologation as national
    from kordena_fiscal.gateway.authorization import AuthorizationStatus
    from kordena_fiscal.lifecycle import IdempotencyKey

    key = "35" + "0" * 48
    xml = (
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infNFSe Id="NFS{key}"/></NFSe>'
    ).encode()
    response = json.dumps({
        "tipoAmbiente": 2,
        "chaveAcesso": key,
        "idDps": "DPS-SYNTHETIC",
        "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii"),
    }).encode("utf-8")
    request = _request(
        "3509205", TaxRegimeCode.SIMPLES_NACIONAL, date(2026, 11, 13)
    )
    request.document.scope = ExecutionScope(
        tenant_id="pilot-tenant", unit_id="pilot-unit",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="cajamar-no-transport",
    )
    request.document.document_id = "nfse-cajamar-local-only"
    request.idempotency_key = IdempotencyKey("a" * 64)
    request.request_fingerprint = "b" * 64

    # This is a deterministic OFFLINE adapter unit test, not a signed-DPS or
    # network homologation. The separate signing/XSD suites remain mandatory.
    monkeypatch.setattr(national, "validate_a1_for_issuer", lambda *args, **kw: None)
    monkeypatch.setattr(national, "build_fiscal_tls_context", lambda cert: Mock())
    monkeypatch.setattr(national, "encode_signed_dps", lambda *args, **kw: b"{}")
    exchange = Mock(return_value=response)
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=Mock(return_value=Mock()),
        build_signed_dps=Mock(return_value=b"synthetic-signature"),
        exchange=exchange,
    )
    result = gateway.authorize(request)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == key
    assert result.authorized_xml == xml
    exchange.assert_called_once()


def test_osasco_catalog_does_not_invent_sigiss_or_betha_contracts() -> None:
    from kordena_fiscal.gateway.municipal_sp_routing import SP_MUNICIPAL_CANDIDATES

    assert SP_MUNICIPAL_CANDIDATES["3534401"] == (
        "Osasco", ("osasco-proprio-rtc", "nfse-nacional")
    )
    assert SP_MUNICIPAL_CANDIDATES["3505708"][1] == ("barueri-proprio",)
