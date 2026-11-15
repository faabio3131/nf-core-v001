"""Santana Simpliss 2026: provider binding, signed receipt and no-replay tests.

All specimens are synthetic. No municipality, taxpayer or external API is called.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway import santana_simpliss_homologation as santana
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseGatewayClient,
    NfseQueryClient,
    NfseServiceLine,
)
from kordena_fiscal.runtime.canonical_fiscal_composition import _GovernedNfseRouter


def _request(city: str = santana.SANTANA_IBGE) -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        "tenant-santana", "unit-santana", FiscalEnvironment.HOMOLOGATION,
        "test-correlation", "fm-nfcore",
    )
    city_jurisdiction = BrazilianJurisdiction("SP", city)
    now = datetime.now(UTC)
    profile = FiscalProfile(
        profile_id="santana-fixture", scope=scope, cnpj=Cnpj("11222333000181"),
        legal_name="Emissor Sintetico",
        tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="10", district="Centro",
            municipality_name="Santana de Parnaiba",
            jurisdiction=city_jurisdiction, postal_code="06501000",
        ),
        effective_from=now - timedelta(days=1),
    )
    line = NfseServiceLine(
        line_number=1, municipal_service_code="0107",
        national_taxation_code="010701",
        description="Servico sintetico fiscalmente revisado",
        gross_amount=Money(Decimal("100.00")),
        iss_amount=Money(Decimal("3.00")),
        iss_withheld=False,
    )
    document = NfseCanonicalDocument(
        document_id="santana-document-1", scope=scope,
        source=SourceReference("synthetic-test", "santana-service-1"),
        issued_at=now, competence_date=now.date(),
        issuer=profile, service_jurisdiction=city_jurisdiction,
        services=(line,), dps_number=1,
    )
    return NfseAuthorizationRequest.build(document)


def _gateway(monkeypatch: pytest.MonkeyPatch, *, response: bytes, key: str | None = None):
    material = Mock()
    monkeypatch.setattr(santana, "validate_a1_for_issuer", Mock())
    monkeypatch.setattr(santana, "build_fiscal_tls_context", Mock(return_value=Mock()))
    monkeypatch.setattr(santana, "encode_signed_dps", Mock(
        return_value=b'{"dpsXmlGZipB64":"synthetic"}',
    ))
    receipt = Mock(return_value=b"<NFSe>SYNTHETIC-CRYPTO-VERIFIED-BOUNDARY</NFSe>")
    monkeypatch.setattr(santana, "_validate_official_nfse", receipt)
    resolver = Mock()
    resolver.resolve_provider_id.return_value = santana.SANTANA_PROVIDER_ID
    sender = Mock(return_value=response)
    signer = Mock(return_value=b"<synthetic-signed-DPS/>")
    preaudit = Mock()
    gateway = santana.SantanaSimplissHomologationGateway(
        endpoint=santana.SantanaSimplissEndpoint(
            "https://producaorestrita.simplissweb.com.br/API/SEFIN/nfse"
        ),
        provider_resolver=resolver,
        resolve_certificate=Mock(return_value=material),
        build_signed_dps=signer,
        preaudit=preaudit,
        resolve_known_key=(lambda _request: key) if key is not None else None,
        exchange=sender,
    )
    return gateway, sender, signer, preaudit, resolver, receipt


def test_provider_url_is_derived_only_from_operator_reviewed_simpliss() -> None:
    endpoint = santana.SantanaSimplissEndpoint(
        "https://producaorestrita.simplissweb.com.br/API/SEFIN/nfse"
    )
    assert endpoint.invoice_url("35" + "0" * 48).endswith("/nfse/" + "35" + "0" * 48)
    assert endpoint.events_url("35" + "0" * 48).endswith("/eventos")
    for candidate in (
        "http://producaorestrita.simplissweb.com.br/nfse",
        "https://nfsesantanadeparnaiba.simplissweb.com.br/nfse",
        "https://www.nfse.gov.br/nfse",
        "https://producaorestrita.simplissweb.com.br/nfse?token=secret",
        "https://producaorestrita.simplissweb.com.br/../nfse",
        "https://producaorestrita.simplissweb.com.br/nfse/other",
        "https://user:secret@producaorestrita.simplissweb.com.br/nfse",
        "https://producaorestrita.simplissweb.com.br:4433/nfse",
    ):
        with pytest.raises(santana.SantanaSimplissError):
            santana.SantanaSimplissEndpoint(candidate)


def test_approved_santana_invoice_uses_bound_provider_and_one_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "35" + "1" * 48
    gateway, sender, signer, preaudit, resolver, receipt = _gateway(
        monkeypatch, response=json.dumps({
            "tipoAmbiente": 2, "chaveAcesso": key, "nfseXmlGZipB64": "synthetic",
        }).encode(),
    )
    request = _request()
    result = NfseGatewayClient(gateway).authorize(request)
    assert result.status is AuthorizationStatus.AUTHORIZED
    assert result.invoice_reference == key
    assert result.provider.provider_name == santana.SANTANA_PROVIDER_ID
    assert result.authorized_xml == b"<NFSe>SYNTHETIC-CRYPTO-VERIFIED-BOUNDARY</NFSe>"
    assert sender.call_count == 1
    assert sender.call_args.args[0] == "POST"
    assert sender.call_args.args[1].endswith("/nfse")
    assert signer.call_count == 1
    assert preaudit.call_count == 1
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == "authorize"
    receipt.assert_called_once()


def test_read_only_santana_query_can_only_use_known_original_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "35" + "2" * 48
    gateway, sender, signer, _, resolver, _ = _gateway(
        monkeypatch, key=key,
        response=json.dumps({"chaveAcesso": key, "nfseXmlGZipB64": "synthetic"}).encode(),
    )
    response = NfseQueryClient(gateway).query(_request())
    assert response.invoice_reference == key
    assert sender.call_count == 1
    assert sender.call_args.args[0] == "GET"
    assert sender.call_args.args[2] is None
    assert sender.call_args.args[1].endswith("/nfse/" + key)
    signer.assert_not_called()
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == "query"


def test_pending_post_without_access_key_does_not_invent_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, sender, _, _, _, _ = _gateway(
        monkeypatch, response=b'{"tipoAmbiente":2,"idDps":"SANTANA-PENDING"}',
    )
    result = gateway.authorize(_request())
    assert result.status is AuthorizationStatus.PENDING
    with pytest.raises(santana.SantanaSimplissError, match="original"):
        gateway.query(_request())
    assert sender.call_count == 1


def test_rejections_keep_evidence_and_never_infer_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, _, _, _, _, _ = _gateway(
        monkeypatch,
        response=json.dumps({
            "tipoAmbiente": 2,
            "erros": [
                {"Codigo": "E0001", "Descricao": "Regra fiscal de teste"},
                {"codigo": "E0002", "descricao": "Erro adicional sintético"},
            ],
        }).encode(),
    )
    result = gateway.authorize(_request())
    assert result.status is AuthorizationStatus.REJECTED
    assert result.rejection_code == "E0001"
    assert len(result.rejections) == 2
    assert all(item.origin == "SIMPLISS_SANTANA" for item in result.rejections)
    assert result.authorized_xml is None


def test_no_cross_city_or_unbound_issuer_can_sign_or_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, sender, signer, _, resolver, _ = _gateway(
        monkeypatch, response=b'{"tipoAmbiente":2}',
    )
    with pytest.raises(santana.SantanaSimplissError, match="Santana"):
        gateway.authorize(_request("3505708"))
    resolver.resolve_provider_id.return_value = "nfse-nacional-producao-restrita"
    with pytest.raises(santana.SantanaSimplissError, match="binding"):
        gateway.authorize(_request())
    signer.assert_not_called()
    sender.assert_not_called()


@pytest.mark.parametrize("payload", [
    b"[]", b"<xml/>", b'{"tipoAmbiente":1}',
    b'{"chaveAcesso":"350"}', b'{"erros":{}}', b'{"erros":[{"Codigo":true,"Descricao":"x"}]}',
    b'{"nfseXmlGZipB64":"synthetic","chaveAcesso":"bad"}',
])
def test_invalid_or_ambiguous_response_is_not_authorization(
    monkeypatch: pytest.MonkeyPatch, payload: bytes,
) -> None:
    gateway, _, _, _, _, _ = _gateway(monkeypatch, response=payload)
    with pytest.raises(santana.SantanaSimplissError):
        gateway.authorize(_request())


def test_gateway_is_available_through_one_existing_canonical_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, _, _, _, _, _ = _gateway(monkeypatch, response=b'{"tipoAmbiente":2}')
    application = Mock()
    application.resolve_configured_provider_id.return_value = santana.SANTANA_PROVIDER_ID
    router = _GovernedNfseRouter(
        application=application, national=None, extrema=None,
        municipal_issuance={santana.SANTANA_PROVIDER_ID: NfseGatewayClient(gateway)},
        municipal_recovery={santana.SANTANA_PROVIDER_ID: NfseQueryClient(gateway)},
    )
    assert NfseGatewayClient(router).authorize(_request()).status is AuthorizationStatus.PENDING
