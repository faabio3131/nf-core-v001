"""Local encrypted vault for the Worker's webhook-signing secret (no GSM).

Decision of 20/11/2026: the production Worker reads its signing secret from an
AES-256-GCM file on the host instead of Google Secret Manager. The master key is
separate from the A1 vault key. The associated data binds every ciphertext to its
reference, version, tenant, unit and provider, so a file copied to another scope
or renamed to another version fails to decrypt.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kordena_fiscal.security.secrets import (
    SecretReference,
    SecretResolutionError,
    SecretScope,
    StoredSecret,
)

_FORMAT = b"nfcore-signing-vault-v1"
_NONCE = 12
MIN_SECRET_BYTES = 32


def _aad(reference: SecretReference, scope: SecretScope, provider_id: str) -> bytes:
    return _FORMAT + b"\x00" + json.dumps(
        [reference.reference_id, reference.version, scope.tenant_id, scope.unit_id,
         scope.purpose, provider_id],
        separators=(",", ":"),
    ).encode("utf-8")


def _filename(reference: SecretReference) -> str:
    if reference.version is None:
        raise SecretResolutionError("local vault requires a pinned secret version")
    return f"{reference.reference_id}.v{reference.version}.enc"


class LocalSigningVault:
    def __init__(self, *, directory: str | Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise SecretResolutionError("local signing vault key must be 32 bytes")
        self._dir = Path(directory)
        self._key = AESGCM(master_key)

    def store(
        self, reference: SecretReference, scope: SecretScope, provider_id: str, value: bytes,
    ) -> Path:
        """Write once (0600, no overwrite): rotation uses a new version."""
        if len(value) < MIN_SECRET_BYTES:
            raise SecretResolutionError("signing secret too weak")
        path = self._dir / _filename(reference)
        nonce = secrets.token_bytes(_NONCE)
        blob = nonce + self._key.encrypt(nonce, value, _aad(reference, scope, provider_id))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            handle = os.open(path, flags, 0o600)
        except FileExistsError:
            raise SecretResolutionError("signing secret version already exists") from None
        try:
            os.write(handle, blob)
            os.fsync(handle)
        finally:
            os.close(handle)
        return path

    def read(
        self, reference: SecretReference, scope: SecretScope, provider_id: str,
    ) -> StoredSecret:
        path = self._dir / _filename(reference)
        try:
            info = path.lstat()
        except OSError:
            raise SecretResolutionError("signing secret unavailable") from None
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.geteuid()
        ):
            raise SecretResolutionError("signing secret file is not trusted")
        blob = path.read_bytes()
        try:
            value = self._key.decrypt(
                blob[:_NONCE], blob[_NONCE:], _aad(reference, scope, provider_id),
            )
        except (InvalidTag, ValueError):
            raise SecretResolutionError("signing secret does not match its scope") from None
        if len(value) < MIN_SECRET_BYTES:
            raise SecretResolutionError("signing secret too weak")
        return StoredSecret(reference, scope, value)


class LocalVaultSignatureSecretBackend:
    """SecretResolver backend: scoped reads only, never unscoped."""

    def __init__(self, vault: LocalSigningVault, *, provider_id: str) -> None:
        self._vault = vault
        self._provider = provider_id

    @property
    def production_safe(self) -> bool:
        return True

    def resolve(self, reference: SecretReference) -> StoredSecret:
        del reference
        raise SecretResolutionError("local vault signature access requires explicit scope")

    def resolve_for_scope(self, reference: SecretReference, scope: SecretScope) -> StoredSecret:
        return self._vault.read(reference, scope, self._provider)
