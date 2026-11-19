"""P2: NFS-e Nacional production path is kill-switched and human-granted per exact cell."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
    NfseNacionalHomologationGateway,
    NfsePreDispatchError,
)
from kordena_fiscal.gateway.nfse_national_environment import (
    ENV_PRODUCTION_ENABLED,
    ENV_PRODUCTION_GRANTS_FILE,
    ENV_PRODUCTION_URL,
    SEFIN_HOMOLOGATION_NFSE_URL,
    load_nfse_production_authority,
    resolve_national_environment,
    validate_production_nfse_url,
)
from kordena_fiscal.gateway.production_activation import (
    ProductionActivationKey,
    ProductionActivationRecord,
    ProductionActivationState,
    ProductionExecutionAuthority,
)
from kordena_fiscal.gateway.provider import ProviderOperation
from kordena_fiscal.issuance.nfse_dps_builder import build_sefin_signed_dps


def _load(name: str):
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"p2_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_wiring = _load("test_nfv1_nfse_dps_builder_and_preaudit_wiring")
_PROD_URL = "https://sefin.nfse.gov.br/SefinNacional/nfse"
_ENV = {ENV_PRODUCTION_ENABLED: "true", ENV_PRODUCTION_URL: _PROD_URL}
_NOW = datetime(2026, 11, 19, tzinfo=UTC)


def _prod_request():
    request = _wiring._request()
    document = request.document
    scope = replace(document.scope, environment=FiscalEnvironment.PRODUCTION)
    issuer = replace(document.issuer, scope=scope)
    document = replace(document, scope=scope, issuer=issuer)
    return type(request).build(document)


def _grant(municipality: str = "3550308", unit: str = "unit-a") -> ProductionExecutionAuthority:
    return ProductionExecutionAuthority((ProductionActivationRecord(
        key=ProductionActivationKey(
            tenant_id="tenant-a", unit_id=unit,
            provider_id=NACIONAL_HOMOLOGATION_PROVIDER_ID,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", municipality),
            operation=ProviderOperation.AUTHORIZE,
        ),
        state=ProductionActivationState.ACTIVE,
        approval_reference="chg-1", external_evidence_id="ev-1",
        changed_by="admin", changed_at=_NOW, correlation_id="c-1",
    ),))


def _exchange_factory(sent: list):
    def _exchange(payload: bytes, *args) -> bytes:
        sent.append(args)
        dps = gzip.decompress(base64.b64decode(json.loads(payload)["dpsXmlGZipB64"]))
        assert etree.fromstring(dps).findtext(".//{*}tpAmb") == "1"
        return json.dumps({"erros": [{"codigo": "E1", "descricao": "regra"}]}).encode()
    return _exchange


def _gateway(*, authority=None, environ=None, sent=None):
    return NfseNacionalHomologationGateway(
        resolve_certificate=lambda _s, _c: _wiring._certificate(),
        build_signed_dps=build_sefin_signed_dps,
        exchange=_exchange_factory(sent if sent is not None else []),
        production_authority=authority, environ=environ,
    )


def test_homologation_profile_is_fixed_and_ignores_env():
    profile = resolve_national_environment(FiscalEnvironment.HOMOLOGATION, env=_ENV)
    assert (profile.tp_amb, profile.nfse_url) == (2, SEFIN_HOMOLOGATION_NFSE_URL)


@pytest.mark.parametrize("env", [
    {},
    {ENV_PRODUCTION_ENABLED: "false", ENV_PRODUCTION_URL: _PROD_URL},
    {ENV_PRODUCTION_ENABLED: "true"},
])
def test_production_needs_kill_switch_and_url(env):
    with pytest.raises(FiscalValidationError):
        resolve_national_environment(FiscalEnvironment.PRODUCTION, env=env)


@pytest.mark.parametrize("url", [
    "http://sefin.nfse.gov.br/SefinNacional/nfse",
    "https://evil.example/SefinNacional/nfse",
    "https://sefin.nfse.gov.br.evil.example/nfse",
    "https://user@sefin.nfse.gov.br/nfse",
    "https://sefin.nfse.gov.br:8443/nfse",
    "https://sefin.nfse.gov.br/nfse?x=1",
    "https://sefin.nfse.gov.br/../nfse",
    "https://sefin.nfse.gov.br/a//nfse",
    "https://sefin.nfse.gov.br/other",
    "", None,
])
def test_production_url_validation_rejects_non_official(url):
    with pytest.raises(FiscalValidationError):
        validate_production_nfse_url(url)


def test_production_profile_when_enabled():
    profile = resolve_national_environment(FiscalEnvironment.PRODUCTION, env=_ENV)
    assert (profile.tp_amb, profile.nfse_url) == (1, _PROD_URL)


def test_production_without_kill_switch_is_refused_before_send():
    sent: list = []
    with pytest.raises(NfsePreDispatchError):
        _gateway(authority=_grant(), environ={}, sent=sent).authorize(_prod_request())
    assert sent == []


def test_production_without_human_grant_is_refused_before_send():
    sent: list = []
    with pytest.raises(FiscalValidationError, match="human production grant"):
        _gateway(authority=None, environ=_ENV, sent=sent).authorize(_prod_request())
    assert sent == []


@pytest.mark.parametrize(("municipality", "unit"), [("3518800", "unit-a"), ("3550308", "unit-b")])
def test_grant_for_another_cell_is_refused(municipality, unit):
    sent: list = []
    authority = _grant(municipality=municipality, unit=unit)
    with pytest.raises(FiscalValidationError, match="not active"):
        _gateway(authority=authority, environ=_ENV, sent=sent).authorize(_prod_request())
    assert sent == []


def test_granted_production_sends_tpamb1_to_production_url():
    sent: list = []
    result = _gateway(authority=_grant(), environ=_ENV, sent=sent).authorize(_prod_request())
    assert result.status is AuthorizationStatus.REJECTED
    assert sent  # exchange was reached with tpAmb=1 DPS (asserted in the fake)


def test_scope_type_is_unchanged():
    assert isinstance(_prod_request().document.scope, ExecutionScope)


def _grants_file(tmp_path, entries):
    path = tmp_path / "grants.json"
    path.write_text(json.dumps({"grants": entries}), encoding="utf-8")
    return {ENV_PRODUCTION_GRANTS_FILE: str(path)}


_ENTRY = {
    "tenant_id": "tenant-a", "unit_id": "unit-a", "uf": "SP",
    "municipality_ibge_code": "3550308", "approved_by": "fabio",
    "approval_reference": "chg-9", "external_evidence_id": "ev-9",
    "approved_at": "2026-11-19T12:00:00+00:00",
}


def test_grants_file_absent_means_no_authority():
    assert load_nfse_production_authority({}) is None


def test_grants_file_loads_exact_cells_only(tmp_path):
    authority = load_nfse_production_authority(_grants_file(tmp_path, [_ENTRY]))
    result = _gateway(authority=authority, environ=_ENV).authorize(_prod_request())
    assert result.status is AuthorizationStatus.REJECTED  # reached SEFIN stub
    other = load_nfse_production_authority(
        _grants_file(tmp_path, [{**_ENTRY, "municipality_ibge_code": "3518800"}])
    )
    with pytest.raises(FiscalValidationError, match="not active"):
        _gateway(authority=other, environ=_ENV).authorize(_prod_request())


@pytest.mark.parametrize("bad", [{"grants": "x"}, {"grants": [{"tenant_id": "t"}]}, [], "oops"])
def test_malformed_grants_file_fails_closed(tmp_path, bad):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(FiscalValidationError, match="grants file is invalid"):
        load_nfse_production_authority({ENV_PRODUCTION_GRANTS_FILE: str(path)})
    with pytest.raises(FiscalValidationError):
        load_nfse_production_authority({ENV_PRODUCTION_GRANTS_FILE: str(tmp_path / "nope.json")})
