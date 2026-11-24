"""Execute the standard API fiscal factory with a synthetic Osasco manifest.

All inputs are fixtures: no real issuer, municipal key, network or live database.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.gateway.osasco_rtc_tax_policy import OsascoReviewedRtcPolicy
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.api import build_entrypoint_fiscal_handler_factory
from kordena_fiscal.runtime.config import RuntimeConfigurationError, RuntimeSettings
from kordena_fiscal.runtime.osasco_environment import OsascoReviewedStartup
from kordena_fiscal.runtime.osasco_gsm_bootstrap import build_osasco_gsm_secret_factory


def _contract(tmp_path: Path, filename: str, content: bytes) -> dict[str, str]:
    (tmp_path / filename).write_bytes(content)
    return {"file": filename, "sha256": hashlib.sha256(content).hexdigest()}


def _policy() -> dict[str, object]:
    values: dict[str, object] = {
        key.name: "REVIEWED_FIXTURE" for key in fields(OsascoReviewedRtcPolicy)
    }
    values.update({
        "source_normative": "Synthetic fixture only - not municipal legislation",
        "rule_version": 1,
        "effective_from": "2026-01-01",
        "effective_through": None,
        "municipal_service_code": "0101",
        "national_taxation_code": "010101",
        "activity": "TEST",
        "class_trib": "TEST",
        "nbs_code": "TEST",
        "incidence_location": "TEST",
        "operation_indicator": "TEST",
        "service_city": "Osasco",
        "service_city_ibge": "3534401",
        "service_state": "SP",
        "recipient_street_type": "R",
        "iss_rate": "2.00",
        "pis": "0.00", "cofins": "0.00", "csll": "0.00",
        "income_tax": "0.00", "inss": "0.00", "other_taxes": "0.00",
        "test_only": True, "no_iss_incidence": False, "additional_info": "",
        "pis_own": "0.00", "cofins_own": "0.00", "cartorio_values": None,
    })
    return values


def _manifest(tmp_path: Path) -> Path:
    wsdl = b'''<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
        xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
        targetNamespace="http://tempuri.org/">
        <wsdl:binding name="BasicHttpBinding_Fixture">
          <soap:binding transport="http://schemas.xmlsoap.org/soap/http"/>
          <wsdl:operation name="RTC_EmitirNFE"><soap:operation
            soapAction="http://tempuri.org/INotaFiscalEletronica/RTC_EmitirNFE"/></wsdl:operation>
          <wsdl:operation name="ConsultarNotaCompleta"><soap:operation
            soapAction="http://tempuri.org/INotaFiscalEletronica/ConsultarNotaCompleta"/></wsdl:operation>
          <wsdl:operation name="Cancelar"><soap:operation
            soapAction="http://tempuri.org/INotaFiscalEletronica/Cancelar"/></wsdl:operation>
        </wsdl:binding></wsdl:definitions>'''
    def xsd(namespace: str, root: str) -> bytes:
        return (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            f'targetNamespace="{namespace}">'
            f'<xs:element name="{root}" type="xs:anyType"/></xs:schema>'
        ).encode()
    doc = {
        "wsdl": _contract(tmp_path, "fixture.wsdl", wsdl),
        "binding_name": "BasicHttpBinding_Fixture",
        "schemas": {
            "issue_request": _contract(
                tmp_path, "issue.xsd", xsd("http://tempuri.org/", "RTC_EmitirNFE"),
            ),
            "query_request": _contract(
                tmp_path, "query.xsd", xsd("http://tempuri.org/", "ConsultarNotaCompleta"),
            ),
            "cancel_request": _contract(
                tmp_path, "cancel.xsd", xsd("http://tempuri.org/", "Cancelar"),
            ),
            "full_invoice_response": _contract(
                tmp_path, "full.xsd",
                xsd("http://schemas.xmlsoap.org/soap/envelope/", "Envelope"),
            ),
            "cancel_response": _contract(
                tmp_path, "reply.xsd",
                xsd("http://schemas.xmlsoap.org/soap/envelope/", "Envelope"),
            ),
        },
        "issuers": [{
            "tenant_id": "fixture-tenant",
            "unit_id": "fixture-unit",
            "issuer_cnpj": "11222333000181",
            "municipal_registration": "123456",
            "policy": _policy(),
        }],
    }
    target = tmp_path / "osasco-reviewed.json"
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


def _settings(env: str = "staging") -> RuntimeSettings:
    return RuntimeSettings.from_mapping({
        "NFCORE_ENVIRONMENT": env,
        "NFCORE_PERSISTENCE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://fixture:fixture@db/nfcore",
        "NFCORE_SECRET_BACKEND": "external",
    })


def test_api_entrypoint_attaches_osasco_with_canonical_uow_and_no_key_io(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    provider_vault = Mock()
    factory = build_entrypoint_fiscal_handler_factory(
        _settings(),
        {"NFCORE_OSASCO_WCF_CONFIG_PATH": str(manifest)},
        None,
        osasco_secret_vault=provider_vault,
    )
    assert factory is not None
    db = SqliteFiscalDatabase(tmp_path / "fiscal.sqlite")
    db.initialize()
    handlers = factory(FiscalApplicationService(db))
    assert {
        "issueFiscalDocument", "queryFiscalDocument",
        "cancelOsascoNfse", "substituteOsascoNfse",
    } <= set(handlers)
    provider_vault.resolve.assert_not_called()
    no_osasco = build_entrypoint_fiscal_handler_factory(_settings(), {}, None)
    assert no_osasco is not None
    assert "cancelOsascoNfse" not in no_osasco(FiscalApplicationService(db))


def test_manifest_never_silently_downgrades_when_unreviewed(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    env = {"NFCORE_OSASCO_WCF_CONFIG_PATH": str(manifest)}
    with pytest.raises(RuntimeConfigurationError, match="municipal"):
        build_entrypoint_fiscal_handler_factory(_settings("development"), env, None)
    with pytest.raises(RuntimeConfigurationError, match="GSM"):
        build_entrypoint_fiscal_handler_factory(_settings(), env, None)
    with pytest.raises(RuntimeConfigurationError, match="GSM"):
        build_osasco_gsm_secret_factory({})

    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["wsdl"]["sha256"] = "f" * 64
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="digest"):
        OsascoReviewedStartup.load(str(manifest))


def test_osasco_rejects_xsd_drift_duplicate_profiles_and_unversioned_tax(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["schemas"]["issue_request"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="digest"):
        OsascoReviewedStartup.load(str(manifest))

    doc = json.loads(_manifest(tmp_path).read_text(encoding="utf-8"))
    doc["issuers"].append(dict(doc["issuers"][0]))
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Duplicate"):
        OsascoReviewedStartup.load(str(manifest))

    doc = json.loads(_manifest(tmp_path).read_text(encoding="utf-8"))
    doc["issuers"][0]["policy"]["rule_version"] = 0
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="classification"):
        OsascoReviewedStartup.load(str(manifest))


def test_osasco_manifest_cannot_escape_artifact_directory(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["wsdl"]["file"] = "../other.wsdl"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Unsafe"):
        OsascoReviewedStartup.load(str(manifest))



def test_osasco_v22_operator_review_accepts_only_scoped_tax_and_notary_values(
    tmp_path: Path,
) -> None:
    """Tax buckets are independent; eight notary deductions are exact decimals."""
    manifest = _manifest(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    policy = raw["issuers"][0]["policy"]
    policy["pis"] = "1.10"
    policy["cofins"] = "2.20"
    policy["pis_own"] = "3.30"
    policy["cofins_own"] = "4.40"
    notary = {
        "vl_contrib_sta_casa": "0.00",
        "vl_emolumento": "10.00",
        "vl_fundo_tj": "0.00",
        "vl_intimacao": "0.00",
        "vl_min_publico": "0.00",
        "vl_repasse_estadual": "0.00",
        "vl_sefaz": "0.00",
        "vl_sinoreg": "0.00",
    }
    policy["cartorio_values"] = notary
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    config = OsascoReviewedStartup.load(str(manifest))
    reviewed = config.issuers[0].policy
    assert (str(reviewed.pis), str(reviewed.pis_own)) == ("1.10", "3.30")
    assert (str(reviewed.cofins), str(reviewed.cofins_own)) == ("2.20", "4.40")
    assert reviewed.cartorio_values is not None
    assert str(reviewed.cartorio_values.vl_emolumento) == "10.00"

    for forbidden in ("NaN", "Infinity", "-1.00", "1.001", "not-a-money"):
        notary["vl_emolumento"] = forbidden
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(RuntimeConfigurationError, match="classification"):
            OsascoReviewedStartup.load(str(manifest))
    notary.pop("vl_sinoreg")
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="deductions"):
        OsascoReviewedStartup.load(str(manifest))
