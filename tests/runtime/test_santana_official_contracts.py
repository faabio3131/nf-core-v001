"""Reproducible checksum/XSD tests against exact Santana official 2025-12-10 ZIP.

No network, credentials or simulated municipal evidence. An official byte
change fails before any fiscal operation; the original municipal package is
preserved separately from its one documented regex derivation.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.xml.santana_simpliss_schema import santana_official_validator
from kordena_fiscal.xml.schema import XmlSchemaValidationError

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "contracts" / "official" / "santana" / "simpliss_2026" / "manifest.json"
_RUNTIME = files("kordena_fiscal.xml").joinpath("official", "SANTANA_SIMPLISS_2026")


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def test_santana_official_18_original_xsds_have_exact_provenance_and_sha() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["municipality_ibge"] == "3547304"
    assert manifest["provider"] == "Simpliss"
    assert len(manifest["schemas"]) == 18
    assert len({row["path"] for row in manifest["schemas"]}) == 18
    assert set(manifest["sources"]) == {
        "manual", "schemas", "layout_dps", "layout_event", "layout_rtc",
    }
    for row in manifest["schemas"]:
        original = _ROOT / row["path"]
        content = original.read_bytes()
        assert len(content) == row["size_bytes"]
        assert _digest(content) == row["sha256"], original
        if original.name in {
            "DPS_v1.01.xsd", "NFSe_v1.01.xsd", "evento_v1.01.xsd",
            "pedRegEvento_v1.01.xsd", "tiposComplexos_v1.01.xsd",
            "tiposEventos_v1.01.xsd", "tiposSimples_v1.01.xsd",
            "xmldsig-core-schema.xsd",
        }:
            runtime = _RUNTIME.joinpath(original.name).read_bytes()
            assert runtime == content, original.name


@pytest.mark.parametrize("kind", ["dps", "invoice", "request", "response"])
def test_santana_compiles_exact_pinned_municipal_xsd_without_network(kind: str) -> None:
    validator = santana_official_validator(kind)
    assert validator is santana_official_validator(kind)
    with pytest.raises(XmlSchemaValidationError):
        validator.validate_document(
            b'<WrongFiscalDocument xmlns="http://www.sped.fazenda.gov.br/nfse"/>'
        )


def test_santana_pinned_schema_rejects_unreviewed_kind() -> None:
    with pytest.raises(FiscalValidationError):
        # The source type is governed and never inferred from arbitrary caller XML.
        santana_official_validator("unknown")
