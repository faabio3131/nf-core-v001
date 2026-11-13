"""National fiscal cancellation is opt-in, human-approved and never falsely confirmed.

All responses are synthetic. No SEFIN endpoint or certificate is contacted.
"""
from __future__ import annotations

import base64
import gzip
import json
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalEnvironment,
)
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationHomologationTransport,
    NationalNfseCancellationIntent,
    NationalNfseEventError,
    _validated_response,
)

_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_KEY = "35" + "0" * 48
_CNPJ = "11222333000181"


def _signed_event(key: str = _KEY, issuer: str = _CNPJ, environment: str = "2") -> bytes:
    return (
        f'<pedRegEvento xmlns="{_NS}" xmlns:ds="{_DS}">'
        f'<infPedReg Id="PRE{key}101101"><tpAmb>{environment}</tpAmb>'
        f'<CNPJAutor>{issuer}</CNPJAutor><chNFSe>{key}</chNFSe><e101101/>'
        '</infPedReg><ds:Signature><ds:SignedInfo>'
        f'<ds:Reference URI="#PRE{key}101101"/>'
        '</ds:SignedInfo></ds:Signature></pedRegEvento>'
    ).encode()


def _intent(
    signed_event: bytes | None = None,
    key: str = _KEY,
) -> NationalNfseCancellationIntent:
    return NationalNfseCancellationIntent(
        scope=ExecutionScope(
            tenant_id="taxpayer-a",
            unit_id="tax-unit",
            host_namespace="nfcore",
            correlation_id="cancel-sp4",
            environment=FiscalEnvironment.HOMOLOGATION,
        ),
        issuer=Cnpj(_CNPJ),
        issuer_jurisdiction=BrazilianJurisdiction("SP", "3509205"),
        invoice_reference=key,
        human_approval_reference="approval-12345",
        signed_event_xml=signed_event if signed_event is not None else _signed_event(),
    )


def _receipt(key: str = _KEY, cnpj: str = _CNPJ) -> bytes:
    event_xml = (
        f'<evento xmlns="{_NS}"><infEvento><pedRegEvento>'
        f'<infPedReg><tpAmb>2</tpAmb><CNPJAutor>{cnpj}</CNPJAutor>'
        f'<chNFSe>{key}</chNFSe><e101101/></infPedReg>'
        '</pedRegEvento></infEvento></evento>'
    ).encode()
    return json.dumps({
        "tipoAmbiente": 2,
        "eventoXmlGZipB64": base64.b64encode(gzip.compress(event_xml)).decode("ascii"),
    }).encode()


def _transport(exchange: Mock, resolver: Mock | None = None, **kw: object):
    from kordena_fiscal.gateway import nfse_nacional_event_homologation as mod

    provider = resolver if resolver is not None else Mock()
    if resolver is None:
        provider.resolve_provider_id.return_value = (
            "nfse-nacional-producao-restrita"
        )
    a1 = Mock()
    a1.pkcs12_bytes = b"synthetic"
    a1.password = b"synthetic"
    certificate = Mock(return_value=a1)
    signed_validator = Mock()
    official_validator = Mock()
    approval = Mock()
    return (
        NationalNfseCancellationHomologationTransport(
            provider_resolver=provider,
            resolve_certificate=certificate,
            validate_signed_event=signed_validator,
            validate_official_event=official_validator,
            approve_cancellation=approval,
            exchange=exchange,
            **kw,
        ),
        provider, certificate, signed_validator, official_validator, approval, mod,
    )


def test_event_correlation_enforces_original_key_issuer_and_ambiente() -> None:
    _intent()
    for event in (
        _signed_event(issuer="00000000000000"),
        _signed_event(environment="1"),
        _signed_event(key="35" + "1" * 48),
    ):
        with pytest.raises(NationalNfseEventError):
            _intent(signed_event=event)


def test_official_response_requires_same_invoice_and_taxpayer() -> None:
    for reply in (
        _receipt(key="35" + "1" * 48),
        _receipt(cnpj="00000000000000"),
        b'{"tipoAmbiente":2,"eventoXmlGZipB64":"not base64"}',
        b'{"tipoAmbiente":1,"eventoXmlGZipB64":"AA=="}',
    ):
        with pytest.raises(NationalNfseEventError):
            _validated_response(reply, _intent())


def test_only_matching_governed_binding_can_access_approval_or_certificate() -> None:
    exchange = Mock(return_value=_receipt())
    provider = Mock()
    provider.resolve_provider_id.return_value = "unapproved-provider"
    transport, _, cert, verify, official, approval, _ = _transport(exchange, provider)
    with pytest.raises(NationalNfseEventError, match="binding mismatch"):
        transport.cancel(_intent())
    cert.assert_not_called()
    verify.assert_not_called()
    official.assert_not_called()
    approval.assert_not_called()
    exchange.assert_not_called()


def test_cancel_requires_official_event_signature_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, provider, cert, signed, official, approval, module = _transport(
        Mock(return_value=_receipt()),
    )
    monkeypatch.setattr(module, "validate_a1_for_issuer", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "build_fiscal_tls_context", lambda material: Mock())
    official.side_effect = NationalNfseEventError("Invalid official signature")
    with pytest.raises(NationalNfseEventError, match="Invalid official signature"):
        transport.cancel(_intent())
    provider.resolve_provider_id.assert_called_once()
    approval.assert_called_once()
    cert.assert_called_once()
    signed.assert_called_once()
    official.assert_called_once()


def test_cancel_returns_official_event_only_after_all_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = Mock(return_value=_receipt())
    transport, provider, cert, signed, official, approval, module = _transport(exchange)
    monkeypatch.setattr(module, "validate_a1_for_issuer", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "build_fiscal_tls_context", lambda material: Mock())
    result = transport.cancel(_intent())
    assert result.confirmed is True
    assert result.invoice_reference == _KEY
    assert b"<evento" in result.event_xml
    provider.resolve_provider_id.assert_called_once()
    assert provider.resolve_provider_id.call_args.kwargs["operation"] == "cancel"
    signed.assert_called_once()
    official.assert_called_once_with(result.event_xml)
    cert.assert_called_once()
    approval.assert_called_once()
    assert exchange.call_count == 1
    payload = json.loads(exchange.call_args.args[1])
    assert gzip.decompress(
        base64.b64decode(payload["pedidoRegistroEventoXmlGZipB64"])
    ) == _signed_event()
