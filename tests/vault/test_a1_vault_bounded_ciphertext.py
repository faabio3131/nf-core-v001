"""A1 Vault reads must remain bounded even for corrupt ciphertext files."""

from __future__ import annotations

from pathlib import Path

import pytest

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.vault.encrypted_a1 import A1VaultUnavailable, EncryptedA1Vault

_CNPJ = "11222333000181"


def test_oversized_encrypted_a1_record_fails_closed_without_eager_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = EncryptedA1Vault(directory=tmp_path / "vault", master_key=b"t" * 32)
    scope = ExecutionScope(
        host_namespace="fm.iron", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="vault-bounded-test",
    )
    ciphertext = vault._path(vault._aad(scope, Cnpj(_CNPJ)))
    ciphertext.write_bytes(b"NFA1\x01" + b"X" * (3 * 2 * 1024 * 1024))
    ciphertext.chmod(0o600)

    def forbidden_eager_read(_path: Path) -> bytes:
        pytest.fail("Vault must not materialize unbounded ciphertext via Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", forbidden_eager_read)
    with pytest.raises(A1VaultUnavailable, match="indisponível"):
        vault.resolve(scope=scope, issuer_cnpj=_CNPJ)
