"""Santana 101101 event transport preserves human approval and issuer authority."""
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
from kordena_fiscal.gateway import santana_simpliss_events as events
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationIntent,
)
from kordena_fiscal.gateway.santana_simpliss_homologation import (
    SANTANA_PROVIDER_ID,
    SantanaSimplissEndpoint,
    SantanaSimplissError,
)


def _intent(city: str = "3547304") -> NationalNfseCancellationIntent:
    key = "35" + "1" * 48
    identifier = "PRE" + key + "101101"
    xml = (
        '<pedRegEvento xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infPedReg Id="{identifier}"><tpAmb>2</tpAmb>'
        '<CNPJAutor>11222333000181</CNPJAutor>'
        f'<chNFSe>{key}</chNFSe><e101101/></infPedReg>'
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        f'<ds:SignedInfo><ds:Reference URI="#{identifier}"/>'
        '</ds:SignedInfo></ds:Signature></pedRegEvento>'
    ).encode("ascii")
    return NationalNfseCancellationIntent(
        scope=ExecutionScope(
            "tenant-santana", "unit-santana",
            FiscalEnvironment.HOMOLOGATION, "event-test-1", "fm-nfcore",
        ),
        issuer=Cnpj("11222333000181"),
        issuer_jurisdiction=BrazilianJurisdiction("SP", city),
        invoice_reference=key,
        human_approval_reference="review-approved-123456",
        signed_event_xml=xml,
    )


def test_santana_approved_cancel_calls_municipal_events_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = _intent()
    approval = Mock()
    signer = Mock()
    receipt_check = Mock()
    exchange = Mock(return_value=b'{"tipoAmbiente":2,"eventoXmlGZipB64":"synthetic"}')
    resolver = Mock()
    resolver.resolve_provider_id.return_value = SANTANA_PROVIDER_ID
    monkeypatch.setattr(events, "validate_a1_for_issuer", Mock())
    monkeypatch.setattr(events, "build_fiscal_tls_context", Mock(return_value=Mock()))
    monkeypatch.setattr(events, "_validated_response", Mock(return_value=b"<official-event/>"))
    transport = events.SantanaSimplissEventTransport(
        endpoint=SantanaSimplissEndpoint(
            "https://producaorestrita.simplissweb.com.br/SEFIN/nfse"
        ),
        provider_resolver=resolver,
        resolve_certificate=Mock(return_value=Mock()),
        approve_cancellation=approval,
        validate_signed_event=signer,
        validate_official_event=receipt_check,
        exchange=exchange,
    )
    received = transport.cancel(intent)
    assert received.invoice_reference == intent.invoice_reference
    assert received.event_xml == b"<official-event/>"
    approval.assert_called_once_with(intent)
    signer.assert_called_once_with(intent.signed_event_xml)
    receipt_check.assert_called_once_with(b"<official-event/>")
    assert exchange.call_count == 1
    method, url, payload = exchange.call_args.args[:3]
    assert method == "POST" and url.endswith("/nfse/" + intent.invoice_reference + "/eventos")
    assert isinstance(payload, bytes)
    signed_xml = gzip.decompress(base64.b64decode(
        json.loads(payload)["pedidoRegistroEventoXmlGZipB64"],
    ))
    assert signed_xml == intent.signed_event_xml
    assert resolver.resolve_provider_id.call_args.kwargs["operation"] == "cancel"


def test_santana_rejects_wrong_issuer_and_does_not_transmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = Mock()
    resolver = Mock()
    resolver.resolve_provider_id.return_value = "nfse-nacional-producao-restrita"
    transport = events.SantanaSimplissEventTransport(
        endpoint=SantanaSimplissEndpoint(
            "https://producaorestrita.simplissweb.com.br/SEFIN/nfse"
        ),
        provider_resolver=resolver, resolve_certificate=Mock(),
        approve_cancellation=Mock(), validate_signed_event=Mock(),
        validate_official_event=Mock(), exchange=sender,
    )
    with pytest.raises(SantanaSimplissError, match="municipality"):
        transport.cancel(_intent("3505708"))
    with pytest.raises(SantanaSimplissError, match="binding"):
        transport.cancel(_intent())
    sender.assert_not_called()


def test_bad_official_event_never_counts_as_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = Mock()
    resolver.resolve_provider_id.return_value = SANTANA_PROVIDER_ID
    monkeypatch.setattr(events, "validate_a1_for_issuer", Mock())
    monkeypatch.setattr(events, "build_fiscal_tls_context", Mock(return_value=Mock()))
    monkeypatch.setattr(events, "_validated_response", Mock(
        side_effect=SantanaSimplissError("invalid official receipt"),
    ))
    sender = Mock(return_value=b"not approved")
    transport = events.SantanaSimplissEventTransport(
        endpoint=SantanaSimplissEndpoint(
            "https://producaorestrita.simplissweb.com.br/SEFIN/nfse"
        ),
        provider_resolver=resolver, resolve_certificate=Mock(return_value=Mock()),
        approve_cancellation=Mock(), validate_signed_event=Mock(),
        validate_official_event=Mock(), exchange=sender,
    )
    with pytest.raises(SantanaSimplissError, match="not officially validated"):
        transport.cancel(_intent())
    sender.assert_called_once()
