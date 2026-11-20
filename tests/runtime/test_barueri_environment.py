"""Barueri startup contract: only pinned local artifacts and scoped fiscal rules.

No municipal endpoint, customer certificate or live issuer is accessed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kordena_fiscal.domain import TaxRegimeCode
from kordena_fiscal.runtime.barueri_environment import (
    BarueriReviewedStartup,
    build_barueri_port_builder_from_environ,
)
from kordena_fiscal.runtime.config import RuntimeConfigurationError

_TAGS = {
    "issuer_cnpj": "CnpjEmitente",
    "invoice_number": "NumeroNfse",
    "verification_code": "CodigoVerificacao",
    "invoice_reference": "ChaveNfse",
    "rps_number": "NumeroRps",
    "gross_amount": "ValorTotal",
    "invoice_issued_on": "DataEmissao",
    "invoice_series": "SerieNfse",
}
_XSD = (
    b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
    b'<xs:element name="NotaFiscal" type="xs:string"/>'
    b'</xs:schema>'
)


def _policy() -> dict[str, object]:
    return {
        "tenant_id": "empresa-1",
        "unit_id": "unidade-1",
        "issuer_cnpj": "11222333000181",
        "profile_id": "perfil-fiscal",
        "profile_version": 1,
        "tax_regime": TaxRegimeCode.NORMAL.value,
        "municipal_registration": "1234567",
        "effective_from": "2026-01-01",
        "effective_through": None,
        "canonical_service_code": "1.01",
        "pmb004_service_code": "000000101",
        "service_location_code": "1",
        "public_way_code": "1",
        "nbs_code": "000000001",
        "operation_indicator": "000001",
        "tax_classification": "000001",
        "ibs_cbs_status": "000",
        "simples_assessment": "",
        "municipal_note_series": "",
        "personal_use": "0",
        "recipient_differs": "0",
        "recipient_emails": {"11222333000181": "financeiro@example.org"},
        "non_base_allowed": False,
    }


def _manifest(folder: Path) -> Path:
    contents = {
        "rps_layout": b"%PDF-1.4 synthetic RPS layout",
        "return_layout": b"%PDF-1.4 synthetic return layout",
        "invoice_xsd": _XSD,
    }
    manifest: dict[str, object] = {
        "mode": "reviewed-homologation",
        "layout": "PMB004-v4.4",
        "invoice_tags": dict(_TAGS),
        "issuers": [_policy()],
    }
    for key, content in contents.items():
        name = key + (".xsd" if key == "invoice_xsd" else ".pdf")
        (folder / name).write_bytes(content)
        manifest[key] = {
            "file": name,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    path = folder / "reviewed-barueri.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_barueri_manifest_requires_exact_pinned_contract_and_policy(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    startup = BarueriReviewedStartup.load(str(manifest))
    assert startup.policies[0].municipal_registration == "1234567"
    assert startup.policies[0].personal_use == "0"
    assert len(startup.layout_sha256) == 64
    assert len(startup.return_layout_sha256) == 64


def test_tampered_official_contract_hash_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / "rps_layout.pdf").write_bytes(b"%PDF-1.4 tampered")
    with pytest.raises(RuntimeConfigurationError, match="hash mismatch"):
        BarueriReviewedStartup.load(str(manifest))


@pytest.mark.parametrize("missing", ["personal_use", "recipient_differs", "nbs_code"])
def test_taxpayer_fiscal_classifications_are_not_invented(
    tmp_path: Path, missing: str,
) -> None:
    manifest = _manifest(tmp_path)
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    del obj["issuers"][0][missing]
    manifest.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError):
        BarueriReviewedStartup.load(str(manifest))


def test_barueri_is_opt_in_and_refuses_missing_canonical_a1(tmp_path: Path) -> None:
    assert build_barueri_port_builder_from_environ({}, vault=None) is None
    manifest = _manifest(tmp_path)
    with pytest.raises(RuntimeConfigurationError, match="canonical encrypted A1"):
        build_barueri_port_builder_from_environ(
            {"NFCORE_BARUERI_PMB004_CONFIG_PATH": str(manifest)}, vault=None,
        )


def test_duplicate_operator_taxpayer_policy_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    obj["issuers"].append(dict(obj["issuers"][0]))
    manifest.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Duplicate"):
        BarueriReviewedStartup.load(str(manifest))
