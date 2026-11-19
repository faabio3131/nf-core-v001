"""P1: SEFIN 4xx rejections and pre-send failures must never strand a document."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import FiscalPreDispatchError
from kordena_fiscal.gateway import nfse_nacional_homologation as gw
from kordena_fiscal.gateway.authorization import AuthorizationStatus, FiscalGatewayClient
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NfseNacionalHomologationGateway,
    NfsePreDispatchError,
    OfficialNfseTransportError,
)
from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps
from kordena_fiscal.lifecycle import FiscalDocumentState, IssuanceAttemptStatus
from kordena_fiscal.persistence import SqliteFiscalDatabase


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"p1_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_wiring = _load("test_nfv1_nfse_dps_builder_and_preaudit_wiring")
_durable = _load("test_nfv1_durable_issuance")

_REJECTION = {"erros": [{"codigo": "E0123", "descricao": "Regra de validação violada"}]}


def _patch_http_error(monkeypatch, code: int, body: bytes) -> None:
    class _Opener:
        def open(self, _request, timeout):
            raise HTTPError(gw.NACIONAL_HOMOLOGATION_NFSE_URL, code, "x", {}, io.BytesIO(body))

    monkeypatch.setattr(gw, "build_opener", lambda *_a, **_k: _Opener())


@pytest.mark.parametrize("code", [400, 422])
def test_http_4xx_with_official_rejection_list_is_returned_not_hidden(monkeypatch, code):
    body = json.dumps(_REJECTION).encode()
    _patch_http_error(monkeypatch, code, body)
    assert gw._exchange_http(b"{}", None, 1.0) == body  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("code", "body"),
    [
        (500, json.dumps(_REJECTION).encode()),  # server failure stays uncertain
        (400, b"<html>gateway</html>"),
        (400, json.dumps({"mensagem": "x"}).encode()),
        (400, json.dumps({"chaveAcesso": "1" * 50, "erros": [{"codigo": 1}]}).encode()),
    ],
)
def test_http_failures_without_a_structured_rejection_stay_uncertain(monkeypatch, code, body):
    _patch_http_error(monkeypatch, code, body)
    with pytest.raises(OfficialNfseTransportError, match="consulte antes de retransmitir"):
        gw._exchange_http(b"{}", None, 1.0)  # type: ignore[arg-type]


def test_rejection_body_without_tipo_ambiente_becomes_rejected_result():
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=lambda _s, _c: _wiring._certificate(),
        build_signed_dps=build_sefin_signed_dps,
        exchange=lambda *_a: json.dumps(_REJECTION).encode(),
    )
    result = gateway.authorize(_wiring._request())
    assert result.status is AuthorizationStatus.REJECTED
    assert result.rejection_code == "E0123"


def test_authorization_without_tipo_ambiente_is_still_refused():
    body = {"chaveAcesso": "35" + "0" * 42, "erros": [{"codigo": 1, "descricao": "x"}]}
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=lambda _s, _c: _wiring._certificate(),
        build_signed_dps=build_sefin_signed_dps,
        exchange=lambda *_a: json.dumps(body).encode(),
    )
    with pytest.raises(OfficialNfseTransportError, match="homologação"):
        gateway.authorize(_wiring._request())


def test_failure_before_send_is_a_pre_dispatch_error_and_never_calls_sefin():
    def _boom(_scope, _cnpj):
        raise RuntimeError("vault down")

    called = []
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=_boom,
        build_signed_dps=build_sefin_signed_dps,
        exchange=lambda *_a: called.append(1) or b"{}",
    )
    with pytest.raises(NfsePreDispatchError) as info:
        gateway.authorize(_wiring._request())
    assert isinstance(info.value, OfficialNfseTransportError)  # legacy callers still match
    assert isinstance(info.value, FiscalPreDispatchError)
    assert "vault down" not in str(info.value)  # no upstream detail echoed
    assert not called


def test_failure_after_send_started_is_not_marked_pre_dispatch():
    def _timeout(*_a):
        raise OfficialNfseTransportError("indisponível; consulte antes de retransmitir")

    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=lambda _s, _c: _wiring._certificate(),
        build_signed_dps=build_sefin_signed_dps,
        exchange=_timeout,
    )
    with pytest.raises(OfficialNfseTransportError) as info:
        gateway.authorize(_wiring._request())
    assert not isinstance(info.value, FiscalPreDispatchError)


def test_claim_is_closed_locally_when_failure_is_certain_to_precede_send(tmp_path):
    db, app, request = _durable.prepared(tmp_path)

    class _Provider:
        calls = 0

        def authorize(self, _request):
            self.calls += 1
            raise FiscalPreDispatchError("local preparation failed")

    # FiscalGatewayClient validates the provider's output; a raising provider
    # propagates, which is exactly the path under test.
    outcome = app.authorize_prepared_document(
        document_id="doc-test", request=request,
        gateway=FiscalGatewayClient(_Provider()), occurred_at=_durable.NOW,
    )
    assert outcome.lifecycle.state is FiscalDocumentState.REJECTED
    assert outcome.attempt.status is IssuanceAttemptStatus.REJECTED
    assert outcome.recovery_required is False
    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    replay = restarted.authorize_prepared_document(
        document_id="doc-test", request=request,
        gateway=FiscalGatewayClient(_Provider()), occurred_at=_durable.NOW,
    )
    assert replay.replay and replay.lifecycle.state is FiscalDocumentState.REJECTED
