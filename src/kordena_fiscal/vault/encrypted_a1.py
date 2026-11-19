"""Contabo-compatible encrypted A1 storage behind a scope-bound Vault port.

No plaintext certificate, private key or password is written to persistent media.
A deployment-owned 256-bit AES-GCM key is mandatory; no generated fallback key.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import A1CertificatePreflight, validate_a1_for_issuer

_MAX_PFX_BYTES = 2 * 1024 * 1024


class A1VaultUnavailable(FiscalValidationError):
    """Encrypted A1 material unavailable for the specified authorized scope."""


class EncryptedA1Vault:
    """Encrypted file Vault driver; infrastructure key must be supplied out of band."""

    def __init__(self, *, directory: str | Path, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("A1 Vault requires a 32-byte external encryption key")
        self._key = AESGCM(master_key)
        self._directory = Path(directory)
        if self._directory.exists() and self._directory.is_symlink():
            raise A1VaultUnavailable("A1 Vault directory is not trusted")
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._directory, 0o700)

    @classmethod
    def from_environ(cls) -> EncryptedA1Vault | None:
        directory = os.environ.get("NFCORE_A1_VAULT_DIR")
        key_string = os.environ.get("NFCORE_A1_VAULT_KEY_BASE64")
        if not directory and not key_string:
            return None
        if not directory or not key_string:
            raise A1VaultUnavailable("A1 Vault exige diretório e chave externa")
        try:
            master_key = base64.b64decode(key_string, validate=True)
        except (ValueError, binascii.Error):
            raise A1VaultUnavailable("Chave de proteção do A1 inválida") from None
        return cls(directory=directory, master_key=master_key)

    @staticmethod
    def _aad(scope: ExecutionScope, issuer: Cnpj) -> bytes:
        if scope.environment is not FiscalEnvironment.HOMOLOGATION:
            raise A1VaultUnavailable("Cadastro A1 liberado somente em homologação")
        if scope.host_namespace is None:
            raise A1VaultUnavailable("Escopo autenticado sem host namespace")
        return json.dumps(
            [scope.host_namespace, scope.tenant_id, scope.unit_id,
             scope.environment.value, issuer.value],
            ensure_ascii=True, separators=(",", ":"),
        ).encode("ascii")

    def _path(self, aad: bytes) -> Path:
        return self._directory / (hashlib.sha256(aad).hexdigest() + ".a1.enc")

    def provision(
        self, *, scope: ExecutionScope, issuer_cnpj: str,
        pkcs12_bytes: bytes, password: bytes,
    ) -> A1CertificatePreflight:
        issuer = Cnpj(issuer_cnpj)
        if len(pkcs12_bytes) > _MAX_PFX_BYTES or not pkcs12_bytes:
            raise A1VaultUnavailable("Arquivo A1 inválido ou excede 2 MB")
        evidence = validate_a1_for_issuer(
            pkcs12_bytes, password, issuer_cnpj=issuer, at=datetime.now(UTC),
        )
        aad = self._aad(scope, issuer)
        content = json.dumps({
            "version": 1,
            "pfx": base64.b64encode(pkcs12_bytes).decode("ascii"),
            "password": base64.b64encode(password).decode("ascii"),
        }, separators=(",", ":")).encode("ascii")
        nonce = secrets.token_bytes(12)
        sealed = b"NFA1\x01" + nonce + self._key.encrypt(nonce, content, aad)
        destination = self._path(aad)
        if destination.is_symlink():
            raise A1VaultUnavailable("A1 Vault destination is not trusted")
        descriptor, temporary = tempfile.mkstemp(
            dir=self._directory, prefix=".nfcore-a1-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                if hasattr(os, "fchmod"):
                    os.fchmod(output.fileno(), 0o600)
                else:
                    os.chmod(temporary, 0o600)
                output.write(sealed)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return evidence

    def inspect(
        self, *, scope: ExecutionScope, issuer_cnpj: str,
    ) -> A1CertificatePreflight | None:
        """Read back the scope-bound encrypted record without returning secrets.

        None means no certificate exists in this precise tenant/unit/environment.
        A corrupt, unreadable or invalid existing record raises, not "absent".
        This checks local A1 preflight, not ICP-Brasil revocation/official issuance.
        """
        issuer = Cnpj(issuer_cnpj)
        path = self._path(self._aad(scope, issuer))
        if path.is_symlink():
            raise A1VaultUnavailable("A1 Vault destination is not trusted")
        if not path.exists():
            return None
        if not path.is_file():
            raise A1VaultUnavailable("A1 Vault record is not a regular file")
        material = self.resolve(scope=scope, issuer_cnpj=issuer.value)
        return validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=issuer, at=datetime.now(UTC),
        )

    def resolve(self, *, scope: ExecutionScope, issuer_cnpj: str) -> EphemeralCertificateMaterial:
        issuer = Cnpj(issuer_cnpj)
        aad = self._aad(scope, issuer)
        path = self._path(aad)
        if path.is_symlink() or not path.is_file():
            raise A1VaultUnavailable("Certificado A1 não cadastrado para o CNPJ emitente")
        try:
            sealed = path.read_bytes()
            if not sealed.startswith(b"NFA1\x01") or len(sealed) > 3 * _MAX_PFX_BYTES:
                raise ValueError
            plaintext = self._key.decrypt(sealed[5:17], sealed[17:], aad)
            record = json.loads(plaintext)
            if record["version"] != 1:
                raise ValueError
            pfx = base64.b64decode(record["pfx"], validate=True)
            password = base64.b64decode(record["password"], validate=True)
            validate_a1_for_issuer(
                pfx, password, issuer_cnpj=issuer, at=datetime.now(UTC),
            )
            reference = hashlib.sha256(aad).hexdigest()
            return EphemeralCertificateMaterial(
                reference_id="ref:nfcore-a1-" + reference,
                pkcs12_bytes=pfx,
                password=password,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError):
            raise A1VaultUnavailable("Certificado A1 indisponível ou inválido") from None
