"""Santana Simpliss opt-in startup: no secret, provider or host ambiguity."""
from __future__ import annotations

import json

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.gateway.santana_simpliss_homologation import SANTANA_PROVIDER_ID
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.runtime.santana_environment import (
    _read_reviewed_manifest,
    build_santana_port_builder_from_environ,
)
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault


def _manifest(tmp_path, *, url="https://producaorestrita.simplissweb.com.br/nfse"):
    path = tmp_path / "santana-review.json"
    path.write_text(json.dumps({
        "provider_id": SANTANA_PROVIDER_ID,
        "municipality_ibge": "3547304",
        "environment": "homologation",
        "manual_version": "1.00",
        "reviewed_issue_url": url,
        "operator_reviewed": True,
    }), encoding="utf-8")
    return path


def test_reviewed_manifest_requires_exact_santana_host_and_fields(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    assert _read_reviewed_manifest(str(manifest)).issue_url.endswith("/nfse")
    wrong = _manifest(
        tmp_path, url="https://nfsesantanadeparnaiba.simplissweb.com.br/nfse"
    )
    with pytest.raises(ValueError):
        _read_reviewed_manifest(str(wrong))
    with pytest.raises(RuntimeConfigurationError):
        _read_reviewed_manifest("relative/santana-review.json")


def test_missing_a1_never_enables_santana_provider(tmp_path) -> None:
    config = _manifest(tmp_path)
    assert build_santana_port_builder_from_environ({}, vault=None) is None
    with pytest.raises(RuntimeConfigurationError, match="A1"):
        build_santana_port_builder_from_environ(
            {"NFCORE_SANTANA_SIMPLISS_CONFIG_PATH": str(config)}, vault=None,
        )


def test_reviewed_santana_uses_canonical_runtime_handlers(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    vault = EncryptedA1Vault(directory=tmp_path / "vault", master_key=b"7" * 32)
    builder = build_santana_port_builder_from_environ(
        {"NFCORE_SANTANA_SIMPLISS_CONFIG_PATH": str(manifest)}, vault=vault,
    )
    assert builder is not None
    db = SqliteFiscalDatabase(tmp_path / "santana.db")
    db.initialize()
    app = FiscalApplicationService(db)
    handlers = build_runtime_fiscal_handler_factory(
        santana_port_builder=builder,
    )(app)
    assert "issueFiscalDocument" in handlers
    assert "reconcileFiscalOperation" in handlers
