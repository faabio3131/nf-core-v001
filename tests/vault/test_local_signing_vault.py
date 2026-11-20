from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from kordena_fiscal.runtime.config import RuntimeConfigurationError
from kordena_fiscal.runtime.production_local_vault import (
    MODE,
    local_vault_config,
    production_local_vault_worker_handler_factory,
)
from kordena_fiscal.security.secrets import (
    SecretReference,
    SecretResolutionError,
    SecretResolver,
    SecretScope,
)
from kordena_fiscal.vault.local_signing_vault import (
    LocalSigningVault,
    LocalVaultSignatureSecretBackend,
)

REF = SecretReference("sec_worker_signing_01", 1)
SCOPE = SecretScope("tenant-a", "unit-a", "webhook-signing")


def _vault(tmp_path: Path, key: bytes | None = None) -> LocalSigningVault:
    return LocalSigningVault(directory=tmp_path, master_key=key or b"k" * 32)


def test_round_trip_and_production_resolver(tmp_path: Path) -> None:
    value = secrets.token_bytes(48)
    path = _vault(tmp_path).store(REF, SCOPE, "provider-a", value)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert value not in path.read_bytes()
    resolver = SecretResolver(
        LocalVaultSignatureSecretBackend(_vault(tmp_path), provider_id="provider-a"),
        environment="production",
    )
    with resolver.resolve(REF, scope=SCOPE) as material:
        assert material.reveal() == value


@pytest.mark.parametrize("scope, provider", [
    (SecretScope("tenant-b", "unit-a", "webhook-signing"), "provider-a"),
    (SecretScope("tenant-a", "unit-b", "webhook-signing"), "provider-a"),
    (SCOPE, "provider-b"),
])
def test_ciphertext_is_bound_to_scope_and_provider(
    tmp_path: Path, scope: SecretScope, provider: str,
) -> None:
    _vault(tmp_path).store(REF, SCOPE, "provider-a", secrets.token_bytes(48))
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path).read(REF, scope, provider)


def test_wrong_key_renamed_version_weak_or_loose_file_are_refused(tmp_path: Path) -> None:
    path = _vault(tmp_path).store(REF, SCOPE, "p", secrets.token_bytes(48))
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path, b"x" * 32).read(REF, SCOPE, "p")
    os.rename(path, tmp_path / "sec_worker_signing_01.v2.enc")
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path).read(SecretReference("sec_worker_signing_01", 2), SCOPE, "p")
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path).store(REF, SCOPE, "p", b"short")
    other = _vault(tmp_path).store(SecretReference("sec_worker_signing_02", 1), SCOPE, "p",
                                   secrets.token_bytes(48))
    other.chmod(0o644)
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path).read(SecretReference("sec_worker_signing_02", 1), SCOPE, "p")


def test_versions_are_never_overwritten(tmp_path: Path) -> None:
    _vault(tmp_path).store(REF, SCOPE, "p", secrets.token_bytes(48))
    with pytest.raises(SecretResolutionError):
        _vault(tmp_path).store(REF, SCOPE, "p", secrets.token_bytes(48))


def _env(tmp_path: Path) -> dict[str, str]:
    import base64
    return {
        "NFCORE_ENVIRONMENT": "production",
        "NFCORE_WORKER_LOCAL_VAULT_MODE": MODE,
        "NFCORE_WORKER_LOCAL_VAULT_DIR": str(tmp_path),
        "NFCORE_WORKER_LOCAL_VAULT_KEY_BASE64": base64.b64encode(b"k" * 32).decode(),
        "NFCORE_WORKER_LOCAL_VAULT_TENANT_ID": "tenant-a",
        "NFCORE_WORKER_LOCAL_VAULT_UNIT_ID": "unit-a",
        "NFCORE_WORKER_LOCAL_VAULT_HOST_NAMESPACE": "fm-nfcore",
        "NFCORE_WORKER_LOCAL_VAULT_DESTINATION_ID": "dest-a",
        "NFCORE_WORKER_LOCAL_VAULT_SIGNING_REFERENCE": REF.reference_id,
        "NFCORE_WORKER_LOCAL_VAULT_SIGNING_VERSION": "1",
        "NFCORE_WORKER_LOCAL_VAULT_PROVIDER_ID": "provider-a",
    }


def test_config_fails_closed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert local_vault_config(env)[1] == REF
    for broken in (
        {"NFCORE_ENVIRONMENT": "staging"},
        {"NFCORE_WORKER_LOCAL_VAULT_TENANT_ID": "*"},
        {"NFCORE_WORKER_LOCAL_VAULT_KEY_BASE64": "not-base64!"},
        {"NFCORE_WORKER_LOCAL_VAULT_SIGNING_REFERENCE": "plain"},
        {"NFCORE_WORKER_LOCAL_VAULT_SIGNING_VERSION": "0"},
        {"NFCORE_WORKER_LOCAL_VAULT_UNIT_ID": ""},
    ):
        with pytest.raises(RuntimeConfigurationError):
            local_vault_config({**env, **broken})
    with pytest.raises(RuntimeConfigurationError):
        production_local_vault_worker_handler_factory(
            {**env, "NFCORE_WORKER_LOCAL_VAULT_MODE": "other"},
        )


def test_worker_main_refuses_both_backends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kordena_fiscal.runtime import worker_main

    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NFCORE_WORKER_GSM_MODE", "scoped-production-sa-v1")
    monkeypatch.delenv("NFCORE_WORKER_ONESHOT", raising=False)
    monkeypatch.delenv("NFCORE_WORKER_CONNECTOR", raising=False)
    with pytest.raises(RuntimeConfigurationError):
        worker_main.main()
