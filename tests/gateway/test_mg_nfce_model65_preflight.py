"""MG NFC-e model 65 preflight: official state endpoints, QR and isolation.

No real certificate, CSC, official HTTP, authorization or fiscal readiness is
claimed here. This target remains uncomposed in the canonical runtime until
QR version, event operations, contingency and receipt gates are certified.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_mg_homologation_authorization import _request

from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
from kordena_fiscal.control_plane.mg_official_homologation_catalog import mg_homologation_endpoint
from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    FiscalDocumentKind,
    FiscalEnvironment,
)
from kordena_fiscal.gateway.nfe_sp_homologation import (
    MG_NFCE_HOMOLOGATION_PROVIDER_ID,
    HomologationAuthorizationTarget,
    OfficialNfeTransportError,
    _validate_mg_authorization_scope,
    build_mg_nfce_homologation_gateway,
)
from kordena_fiscal.gateway.nfe_sp_operations_homologation import (
    OfficialNfeOperationsError,
    SefazHomologationOperationsGateway,
)
from kordena_fiscal.operations import FiscalQueryRequest


def _with_qr(
    request,
    *,
    qr_url: str | None = None,
    consultation_url: str = "https://hportalsped.fazenda.mg.gov.br/portalnfce",
):
    qr_url = qr_url or (
        "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml"
        f"?p={request.access_key.value}|3|2"
    )
    child = (
        f"<infNFeSupl><qrCode>{qr_url}</qrCode>"
        f"<urlChave>{consultation_url}</urlChave></infNFeSupl>"
    ).encode()
    xml = request.signed_xml.replace(b"</ide>", b"<tpEmis>1</tpEmis></ide>")
    xml = xml.replace(b"</NFe>", child + b"</NFe>")
    return replace(request, signed_xml=xml)


def test_nfce_target_uses_pinned_mg65_endpoint_and_distinct_provider() -> None:
    gateway = build_mg_nfce_homologation_gateway(resolve_certificate=Mock())
    expected = mg_homologation_endpoint(
        document_kind=FiscalDocumentKind.NFCE,
        environment=FiscalEnvironment.HOMOLOGATION,
        operation=ConfiguredFiscalOperation.AUTHORIZE,
    )
    assert gateway._endpoint == expected.url
    assert gateway._provider.provider_name == MG_NFCE_HOMOLOGATION_PROVIDER_ID
    assert "hnfce.fazenda.mg.gov.br" in gateway._endpoint


def test_nfce_model65_must_include_official_qr_before_vault_or_transport() -> None:
    resolve = Mock(side_effect=AssertionError("A1 must not be touched"))
    exchange = Mock(side_effect=AssertionError("network must not be touched"))
    gateway = build_mg_nfce_homologation_gateway(
        resolve_certificate=resolve, exchange=exchange,
    )
    with pytest.raises(OfficialNfeTransportError, match="QR Code"):
        gateway.authorize(_request(model=ElectronicInvoiceModel.NFCE))
    with pytest.raises(OfficialNfeTransportError, match="model 65"):
        gateway.authorize(_request(model=ElectronicInvoiceModel.NFE))
    resolve.assert_not_called()
    exchange.assert_not_called()


@pytest.mark.parametrize(
    ("qr", "consultation"),
    [
        (
            "https://attacker.example/qrcode.xhtml?p=123",
            "https://hportalsped.fazenda.mg.gov.br/portalnfce",
        ),
        (
            "http://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml?p=123",
            "https://hportalsped.fazenda.mg.gov.br/portalnfce",
        ),
        (
            "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml?p=123",
            "https://hportalsped.fazenda.mg.gov.br/portalnfce",
        ),
        (
            "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml?p=123",
            "https://attacker.example/portalnfce",
        ),
    ],
)
def test_nfce_rejects_wrong_qr_origin_and_mismatched_access_key(
    qr: str, consultation: str,
) -> None:
    req = _with_qr(
        _request(model=ElectronicInvoiceModel.NFCE),
        qr_url=qr, consultation_url=consultation,
    )
    with pytest.raises(OfficialNfeTransportError, match="QR/consulta"):
        _validate_mg_authorization_scope(req, model=65)


def test_nfce_refuses_asynchronous_one_invoice_batch() -> None:
    req = _with_qr(_request(model=ElectronicInvoiceModel.NFCE))
    asynchronous = replace(
        req,
        signed_xml=req.signed_xml.replace(b"<indSinc>1</indSinc>", b"<indSinc>0</indSinc>"),
    )
    with pytest.raises(OfficialNfeTransportError, match="synchronous"):
        _validate_mg_authorization_scope(asynchronous, model=65)


def test_nfce_preflight_recognizes_a_structurally_bound_official_qr() -> None:
    req = _with_qr(_request(model=ElectronicInvoiceModel.NFCE))
    _validate_mg_authorization_scope(req, model=65)


def test_nfce_qrv3_online_rejects_unexpected_trailing_fields_or_legacy_v2() -> None:
    original = _request(model=ElectronicInvoiceModel.NFCE)
    for suffix in ("|3|2|untrusted", "|2|2|12345|untrusted", "|3|1"):
        url = (
            "https://portalsped.fazenda.mg.gov.br/portalnfce/sistema/qrcode.xhtml"
            f"?p={original.access_key.value}{suffix}"
        )
        with pytest.raises(OfficialNfeTransportError, match="QR/consulta"):
            _validate_mg_authorization_scope(
                _with_qr(original, qr_url=url), model=65,
            )


def test_nfce_offline_contingency_is_blocked_until_qr_signature_port_exists() -> None:
    original = _with_qr(_request(model=ElectronicInvoiceModel.NFCE))
    offline = replace(
        original,
        signed_xml=original.signed_xml.replace(b"<tpEmis>1</tpEmis>", b"<tpEmis>9</tpEmis>"),
    )
    with pytest.raises(OfficialNfeTransportError, match="contingencia"):
        _validate_mg_authorization_scope(offline, model=65)


def test_nfce_operations_model65_adapter_is_isolated_from_model55() -> None:
    """The dedicated model65 adapter rejects 55 before reading Vault."""
    vault = Mock()
    gateway = SefazHomologationOperationsGateway(
        target=HomologationAuthorizationTarget.MG_NFCE,
        resolve_certificate=vault,
    )
    original = _request()
    with pytest.raises(OfficialNfeOperationsError):
        gateway.query(FiscalQueryRequest(original.scope, original.access_key))
    vault.assert_not_called()
