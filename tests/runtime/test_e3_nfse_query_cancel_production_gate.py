"""E3: National NFS-e query and cancellation follow the same production gate.

Synthetic only: no SEFIN endpoint, real certificate or credential is used.
"""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway import nfse_nacional_event_homologation as events
from kordena_fiscal.gateway.nfse_nacional_event_homologation import (
    NationalNfseCancellationHomologationTransport,
    NationalNfseCancellationIntent,
    NationalNfseEventError,
)
from kordena_fiscal.gateway.nfse_national_environment import (
    ENV_PRODUCTION_ENABLED,
    ENV_PRODUCTION_GRANTS_FILE,
    ENV_PRODUCTION_URL,
    load_nfse_production_authority,
)
from kordena_fiscal.gateway.nfse_national_homologation import OfficialNfseTransportError
from kordena_fiscal.gateway.nfse_national_query import NfseNationalHomologationQueryGateway
from kordena_fiscal.gateway.production_activation import (
    FiscalProductionActivationRequiredError,
    ProductionActivationKey,
)
from kordena_fiscal.gateway.provider import ProviderOperation


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"e3_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_p2 = _load("test_p2_nfse_production_gate")
_PROD_URL = "https://sefin.nfse.gov.br/SefinNacional/nfse"
_ENV = {ENV_PRODUCTION_ENABLED: "true", ENV_PRODUCTION_URL: _PROD_URL}
_KEY = "35" + "0" * 48
_CNPJ = "11222333000181"
_NS = "http://www.sped.fazenda.gov.br/nfse"
_DS = "http://www.w3.org/2000/09/xmldsig#"
_CELL = {
    "tenant_id": "taxpayer-a", "unit_id": "tax-unit", "uf": "SP",
    "municipality_ibge_code": "3509205", "approved_by": "fabio",
    "approval_reference": "chg-77", "external_evidence_id": "ev-77",
    "approved_at": "2026-11-19T12:00:00+00:00",
}


def _authority(tmp_path, **extra):
    path = tmp_path / "grants.json"
    path.write_text(json.dumps({"grants": [{**_CELL, **extra}]}), encoding="utf-8")
    return load_nfse_production_authority({ENV_PRODUCTION_GRANTS_FILE: str(path)})


def _key(operation: ProviderOperation, municipality: str = "3509205") -> ProductionActivationKey:
    return ProductionActivationKey(
        tenant_id="taxpayer-a", unit_id="tax-unit",
        provider_id="nfse-nacional-producao-restrita",
        document_kind=FiscalDocumentKind.NFSE,
        jurisdiction=BrazilianJurisdiction("SP", municipality),
        operation=operation,
    )


# --- grants file -----------------------------------------------------------

def test_authorize_grant_implies_read_only_query_but_never_cancel(tmp_path) -> None:
    authority = _authority(tmp_path)
    authority.require_key(_key(ProviderOperation.AUTHORIZE))
    authority.require_key(_key(ProviderOperation.QUERY))
    with pytest.raises(FiscalProductionActivationRequiredError):
        authority.require_key(_key(ProviderOperation.CANCEL))


def test_cancel_must_be_listed_explicitly(tmp_path) -> None:
    authority = _authority(tmp_path, operations=["authorize", "cancel"])
    authority.require_key(_key(ProviderOperation.CANCEL))
    only_cancel = _authority(tmp_path, operations=["cancel"])
    only_cancel.require_key(_key(ProviderOperation.CANCEL))
    with pytest.raises(FiscalProductionActivationRequiredError):
        only_cancel.require_key(_key(ProviderOperation.AUTHORIZE))


@pytest.mark.parametrize("operations", [[], ["query"], ["inutilize"], ["cancel", "cancel"], "x"])
def test_unknown_or_malformed_operations_fail_closed(tmp_path, operations) -> None:
    with pytest.raises(FiscalValidationError, match="grants file is invalid"):
        _authority(tmp_path, operations=operations)


# --- query (GET) -----------------------------------------------------------

def _query(*, authority=None, environ=None, paths=None, certificate=None):
    resolver = Mock()
    resolver.resolve_provider_id.return_value = "nfse-nacional-producao-restrita"

    def get(path, _tls, _timeout):
        if paths is not None:
            paths.append(path)
        raise OfficialNfseTransportError("synthetic stop after routing")

    return NfseNationalHomologationQueryGateway(
        provider_resolver=resolver,
        resolve_certificate=certificate or (lambda _s, _c: _p2._wiring._certificate()),
        exchange_get=get, production_authority=authority, environ=environ,
    )


@pytest.mark.parametrize("environ", [{}, {ENV_PRODUCTION_ENABLED: "false"}])
def test_production_query_without_kill_switch_never_reads_a1(environ) -> None:
    certificate = Mock()
    with pytest.raises(OfficialNfseTransportError, match="not enabled|not configured"):
        _query(environ=environ, certificate=certificate).query(_p2._prod_request())
    certificate.assert_not_called()


def test_production_query_without_grant_never_reads_a1() -> None:
    certificate = Mock()
    with pytest.raises(OfficialNfseTransportError, match="human production grant"):
        _query(environ=_ENV, certificate=certificate).query(_p2._prod_request())
    certificate.assert_not_called()


def test_authorize_only_in_memory_grant_does_not_cover_query() -> None:
    # The in-memory grant below lists AUTHORIZE only; QUERY is implied solely
    # by the host grants file loader, never silently by the gateway.
    with pytest.raises(OfficialNfseTransportError, match="not active"):
        _query(authority=_p2._grant(), environ=_ENV).query(_p2._prod_request())


def test_granted_production_query_uses_production_host(tmp_path) -> None:
    authority = _authority(
        tmp_path, tenant_id="tenant-a", unit_id="unit-a", municipality_ibge_code="3550308",
    )
    paths: list[str] = []
    with pytest.raises(OfficialNfseTransportError, match="synthetic stop"):
        _query(authority=authority, environ=_ENV, paths=paths).query(_p2._prod_request())
    assert paths and paths[0].startswith("https://sefin.nfse.gov.br/SefinNacional/dps/")


def test_homologation_query_keeps_restricted_host() -> None:
    paths: list[str] = []
    with pytest.raises(OfficialNfseTransportError, match="synthetic stop"):
        _query(environ=_ENV, paths=paths).query(_p2._wiring._request())
    assert paths[0].startswith("https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional/dps/")


@pytest.mark.parametrize("path", [
    "https://evil.example/SefinNacional/dps/1",
    "http://sefin.nfse.gov.br/SefinNacional/dps/1",
    "https://sefin.nfse.gov.br:8443/SefinNacional/dps/1",
    "https://sefin.nfse.gov.br/SefinNacional/../dps/1",
])
def test_live_get_refuses_other_hosts(path) -> None:
    from kordena_fiscal.gateway.nfse_national_query import _read_only_get

    with pytest.raises(OfficialNfseTransportError, match="path invalid"):
        _read_only_get(path, Mock(), 1)


# --- cancellation event ----------------------------------------------------

def _event(tp_amb: str) -> bytes:
    return (
        f'<pedRegEvento xmlns="{_NS}" xmlns:ds="{_DS}">'
        f'<infPedReg Id="PRE{_KEY}101101"><tpAmb>{tp_amb}</tpAmb>'
        f'<CNPJAutor>{_CNPJ}</CNPJAutor><chNFSe>{_KEY}</chNFSe><e101101/>'
        '</infPedReg><ds:Signature><ds:SignedInfo>'
        f'<ds:Reference URI="#PRE{_KEY}101101"/>'
        '</ds:SignedInfo></ds:Signature></pedRegEvento>'
    ).encode()


def _intent(environment=FiscalEnvironment.PRODUCTION, tp_amb="1"):
    return NationalNfseCancellationIntent(
        scope=ExecutionScope(
            tenant_id="taxpayer-a", unit_id="tax-unit", host_namespace="nfcore",
            correlation_id="cancel-prod", environment=environment,
        ),
        issuer=Cnpj(_CNPJ),
        issuer_jurisdiction=BrazilianJurisdiction("SP", "3509205"),
        invoice_reference=_KEY, human_approval_reference="approval-12345",
        signed_event_xml=_event(tp_amb),
    )


def _receipt(tipo: int, tp_amb: str) -> bytes:
    xml = (
        f'<evento xmlns="{_NS}"><infEvento><pedRegEvento>'
        f'<infPedReg><tpAmb>{tp_amb}</tpAmb><CNPJAutor>{_CNPJ}</CNPJAutor>'
        f'<chNFSe>{_KEY}</chNFSe><e101101/></infPedReg>'
        '</pedRegEvento></infEvento></evento>'
    ).encode()
    return json.dumps({
        "tipoAmbiente": tipo,
        "eventoXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii"),
    }).encode()


def _transport(exchange, *, authority=None, environ=None, certificate=None):
    resolver = Mock()
    resolver.resolve_provider_id.return_value = "nfse-nacional-producao-restrita"
    a1 = Mock()
    a1.pkcs12_bytes = b"synthetic"
    a1.password = b"synthetic"
    return NationalNfseCancellationHomologationTransport(
        provider_resolver=resolver,
        resolve_certificate=certificate or Mock(return_value=a1),
        validate_signed_event=Mock(), validate_official_event=Mock(),
        approve_cancellation=Mock(), exchange=exchange,
        production_authority=authority, environ=environ,
    )


def test_production_event_must_declare_tpamb_1() -> None:
    assert _intent().scope.environment is FiscalEnvironment.PRODUCTION
    with pytest.raises(NationalNfseEventError, match="does not match"):
        _intent(tp_amb="2")
    with pytest.raises(NationalNfseEventError, match="does not match"):
        _intent(environment=FiscalEnvironment.HOMOLOGATION, tp_amb="1")


@pytest.mark.parametrize("environ", [{}, {ENV_PRODUCTION_ENABLED: "true"}])
def test_production_cancel_without_kill_switch_never_reads_a1(environ) -> None:
    exchange, certificate = Mock(), Mock()
    with pytest.raises(NationalNfseEventError):
        _transport(exchange, environ=environ, certificate=certificate).cancel(_intent())
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_authorize_only_grant_cannot_cancel_in_production(tmp_path) -> None:
    exchange, certificate = Mock(), Mock()
    transport = _transport(
        exchange, authority=_authority(tmp_path), environ=_ENV, certificate=certificate,
    )
    with pytest.raises(NationalNfseEventError, match="not active"):
        transport.cancel(_intent())
    certificate.assert_not_called()
    exchange.assert_not_called()


def test_granted_production_cancel_requires_production_reply(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events, "validate_a1_for_issuer", lambda *a, **k: None)
    monkeypatch.setattr(events, "build_fiscal_tls_context", lambda material: Mock())
    authority = _authority(tmp_path, operations=["authorize", "cancel"])
    wrong = _transport(Mock(return_value=_receipt(2, "2")), authority=authority, environ=_ENV)
    with pytest.raises(NationalNfseEventError):
        wrong.cancel(_intent())
    exchange = Mock(return_value=_receipt(1, "1"))
    receipt = _transport(exchange, authority=authority, environ=_ENV).cancel(_intent())
    assert receipt.confirmed is True and exchange.call_count == 1


def test_live_production_cancel_posts_to_production_host(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(key, body, tls, timeout, *, url):
        calls.append(url)
        return _receipt(1, "1")

    authority = _authority(tmp_path, operations=["cancel"])
    # Built first so the transport holds the real live POST reference.
    transport = _transport(None, authority=authority, environ=_ENV)
    monkeypatch.setattr(events, "_exchange", fake_post)
    monkeypatch.setattr(events, "_require_live_event_trust", lambda: None)
    monkeypatch.setattr(events, "validate_national_event_xml", lambda *a, **k: None)
    monkeypatch.setattr(events, "validate_a1_for_issuer", lambda *a, **k: None)
    monkeypatch.setattr(events, "build_fiscal_tls_context", lambda material: Mock())
    assert transport.cancel(_intent()).confirmed is True
    assert calls == [_PROD_URL]
