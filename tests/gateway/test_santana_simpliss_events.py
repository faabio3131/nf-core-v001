"""Santana 101101 event transport preserves human approval and issuer authority."""
from __future__ import annotations

import base64
import gzip
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

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
from kordena_fiscal.signing.nfse_xmldsig import append_nfse_signature
from kordena_fiscal.xml.schema import XmlSchemaValidationError


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


def _signed_official_santana_event(
    *, code: str, original_key: str, replacement_key: str | None = None,
) -> bytes:
    """Real two-level XMLDSig with synthetic test identity and municipal XSD."""
    ns = "http://www.sped.fazenda.gov.br/nfse"
    tag = "{" + ns + "}"
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Santana Event")
    ])
    certificate = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(private, hashes.SHA256())
    )
    root = etree.Element(tag + "evento", nsmap={None: ns})
    root.set("versao", "1.01")
    info = etree.SubElement(root, tag + "infEvento")
    info.set("Id", "EVT" + original_key + code + "001")
    etree.SubElement(info, tag + "verAplic").text = "NFCORE1"
    etree.SubElement(info, tag + "ambGer").text = "1"
    etree.SubElement(info, tag + "nSeqEvento").text = "1"
    etree.SubElement(info, tag + "dhProc").text = now.isoformat(timespec="seconds")
    etree.SubElement(info, tag + "nDFe").text = "1"
    request = etree.SubElement(info, tag + "pedRegEvento")
    request.set("versao", "1.01")
    intent = etree.SubElement(request, tag + "infPedReg")
    intent.set("Id", "PRE" + original_key + code + "001")
    etree.SubElement(intent, tag + "tpAmb").text = "2"
    etree.SubElement(intent, tag + "verAplic").text = "NFCORE1"
    etree.SubElement(intent, tag + "dhEvento").text = now.isoformat(timespec="seconds")
    etree.SubElement(intent, tag + "CNPJAutor").text = "11222333000181"
    etree.SubElement(intent, tag + "chNFSe").text = original_key
    etree.SubElement(intent, tag + "nPedRegEvento").text = "1"
    detail = etree.SubElement(intent, tag + "e" + code)
    etree.SubElement(detail, tag + "xDesc").text = (
        "Cancelamento de NFS-e" if code == "101101"
        else "Cancelamento de NFS-e por Substituicao"
    )
    etree.SubElement(detail, tag + "cMotivo").text = (
        "1" if code == "101101" else "99"
    )
    etree.SubElement(detail, tag + "xMotivo").text = (
        "Correcao revisada da nota fiscal de servico"
    )
    if replacement_key is not None:
        etree.SubElement(detail, tag + "chSubstituta").text = replacement_key
    append_nfse_signature(
        request, intent, private, certificate, legacy_abrasf=False,
    )
    append_nfse_signature(
        root, info, private, certificate, legacy_abrasf=False,
    )
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


@pytest.mark.parametrize("code", ["101101", "105102"])
def test_read_only_santana_event_get_verifies_official_xsd_and_dual_signatures(
    code: str,
) -> None:
    """Municipal 1.01 event signed twice; both signatures are audited."""
    original = "35" + "1" * 48
    replacement = "35" + "2" * 48 if code == "105102" else None
    xml = _signed_official_santana_event(
        code=code, original_key=original, replacement_key=replacement,
    )
    events.validate_santana_event_xml(xml, kind="response")
    recovered = events.read_santana_official_events(
        xml, original_key=original, issuer_cnpj="11222333000181",
    )
    assert len(recovered) == 1
    assert recovered[0].event_code == code
    assert recovered[0].original_access_key == original
    assert recovered[0].replacement_access_key == replacement
    with pytest.raises((SantanaSimplissError, XmlSchemaValidationError)):
        events.read_santana_official_events(
            xml, original_key="35" + "9" * 48,
            issuer_cnpj="11222333000181",
        )
    with pytest.raises((SantanaSimplissError, XmlSchemaValidationError)):
        events.read_santana_official_events(
            xml, original_key=original, issuer_cnpj="11222333000182",
        )


def test_santana_empty_event_get_is_pending_never_confirmed() -> None:
    raw = (
        '<eventos xmlns="http://www.sped.fazenda.gov.br/nfse"/>'
    ).encode("ascii")
    assert events.read_santana_official_events(
        raw, original_key="35" + "1" * 48,
        issuer_cnpj="11222333000181",
    ) == ()
    with pytest.raises(SantanaSimplissError):
        events.read_santana_official_events(
            b"<html>not official XML</html>",
            original_key="35" + "1" * 48,
            issuer_cnpj="11222333000181",
        )
