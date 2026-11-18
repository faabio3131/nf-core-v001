"""MF-04: live National NFS-e dispatch requires the current pinned tax decision.

These tests use only synthetic files and canonical documents. They do not
connect to SEFIN, load an A1 from a real Vault or imply fiscal homologation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.domain import FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.runtime.native_nfse_policy import (
    POLICY_ENV,
    require_current_national_treatment_for_live_dispatch,
    resolve_national_treatment,
)
from kordena_fiscal.runtime.native_sale_policy import sale_policy_key

_FIXTURE = Path(__file__).parents[1] / "issuance/test_nfse_dps_builder.py"


def _document():
    spec = importlib.util.spec_from_file_location("mf04_fiscal_document_fixture", _FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._document()


def _installed_policy(tmp_path: Path, document):
    line = document.services[0]
    scope = document.scope
    selector = {
        "issuer_profile_id": document.issuer.profile_id,
        "issuer_profile_version": document.issuer.version,
        "issuer_cnpj": document.issuer.cnpj.value,
        "issuer_tax_regime": int(document.issuer.tax_regime),
        "issuer_municipality_ibge": (
            document.issuer.address.jurisdiction.municipality_ibge_code
        ),
        "service_state_code": document.service_jurisdiction.state_code,
        "service_municipality_ibge": document.service_jurisdiction.municipality_ibge_code,
        "national_taxation_code": line.national_taxation_code,
        "municipal_service_code": line.municipal_service_code,
        "taker_country": "BR",
        "iss_withheld": line.iss_withheld,
        "nbs_code": line.nbs_code,
        "municipal_taxation_detail": line.municipal_taxation_detail,
        "source_normative": line.source_normative,
        "rule_version": line.rule_version,
    }
    treatment = {
        "iss_taxation_code": "1",
        "special_regime_code": "0",
        "normative_reference": "urn:nfcore:synthetic:reviewed-for-test",
        "rule_version": 1,
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
        "simples_assessment_code": None,
        "result_country_code": None,
        "immunity_type_code": None,
    }
    data = {
        "schema_version": 1, "policy_id": "synthetic-mf04-test", "version": 1,
        "host_namespace": scope.host_namespace, "tenant_id": scope.tenant_id,
        "unit_id": scope.unit_id, "environment": scope.environment.value,
        "document_kind": FiscalDocumentKind.NFSE.value,
        "rules": [{"rule_id": "ordinary", "selector": selector, "treatment": treatment}],
    }
    folder = tmp_path / "reviewed"
    folder.mkdir()
    name = sale_policy_key(scope, FiscalDocumentKind.NFSE)
    raw = json.dumps(data, sort_keys=True).encode()
    (folder / (name + ".json")).write_bytes(raw)
    (folder / (name + ".sha256")).write_text(hashlib.sha256(raw).hexdigest())
    env = {POLICY_ENV: str(folder)}
    resolved = resolve_national_treatment(env, scope, selector, document.competence_date)
    assert resolved is not None
    return env, replace(document, national_tax_treatment=resolved.treatment), folder, name


def test_live_dispatch_refuses_unreviewed_default_codes() -> None:
    document = _document()
    with pytest.raises(FiscalValidationError, match="pinned, reviewed"):
        require_current_national_treatment_for_live_dispatch({}, document)


def test_live_dispatch_accepts_exact_effective_scoped_policy(tmp_path: Path) -> None:
    env, document, _, _ = _installed_policy(tmp_path, _document())
    approved = require_current_national_treatment_for_live_dispatch(env, document)
    assert approved.treatment == document.national_tax_treatment


def test_live_dispatch_rejects_missing_or_rotated_policy(tmp_path: Path) -> None:
    env, document, folder, name = _installed_policy(tmp_path, _document())
    with pytest.raises(FiscalValidationError, match="differs from current pinned policy"):
        require_current_national_treatment_for_live_dispatch({}, document)

    path = folder / (name + ".json")
    raw = json.loads(path.read_text())
    raw["version"] = 2
    raw["rules"][0]["treatment"]["normative_reference"] = "urn:changed-policy"
    changed = json.dumps(raw, sort_keys=True).encode()
    path.write_bytes(changed)
    (folder / (name + ".sha256")).write_text(hashlib.sha256(changed).hexdigest())
    with pytest.raises(FiscalValidationError, match="differs from current pinned policy"):
        require_current_national_treatment_for_live_dispatch(env, document)


def test_live_dispatch_rejects_changed_service_or_tenant(tmp_path: Path) -> None:
    env, document, _, _ = _installed_policy(tmp_path, _document())
    replaced_service = replace(document.services[0], municipal_service_code="0108")
    with pytest.raises(FiscalValidationError, match="policy unavailable"):
        require_current_national_treatment_for_live_dispatch(
            env, replace(document, services=(replaced_service,)),
        )


def test_live_gateway_checks_policy_before_fiscal_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kordena_fiscal.gateway import nfse_nacional_homologation as gate
    from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

    document = _document()
    monkeypatch.delenv(POLICY_ENV, raising=False)
    request = NfseAuthorizationRequest.build(document)
    material = Mock()
    resolver = Mock(return_value=material)
    exchange = Mock()
    monkeypatch.setattr(gate, "require_national_receipt_signer_pins", Mock())
    from kordena_fiscal.gateway import nfse_receipt_pki

    monkeypatch.setattr(nfse_receipt_pki, "require_national_receipt_pki_ready", Mock())
    monkeypatch.setattr(gate, "validate_a1_for_issuer", Mock())
    monkeypatch.setattr(gate, "encode_signed_dps", Mock(return_value=b"{}"))
    monkeypatch.setattr(gate, "parse_signed_dps_info", Mock())
    monkeypatch.setattr(
        gate.NationalReceiptIdentity, "from_dps_info", Mock(return_value="same-id"),
    )
    monkeypatch.setattr(
        gate.NationalReceiptIdentity, "from_request", Mock(return_value="same-id"),
    )
    # Make the injectable transport identical to the live call boundary;
    # no real network function is installed or called in this test.
    monkeypatch.setattr(gate, "_LIVE_EXCHANGE", exchange)
    gateway = gate.NfseNacionalHomologationGateway(
        resolve_certificate=resolver, build_signed_dps=lambda *_: b"test-signed",
        exchange=exchange,
    )
    with pytest.raises(FiscalValidationError, match="pinned, reviewed"):
        gateway.authorize(request)
    exchange.assert_not_called()
