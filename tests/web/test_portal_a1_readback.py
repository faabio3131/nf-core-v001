"""Synthetic A1 vault readback proves storage, not fiscal homologation."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from fastapi.testclient import TestClient

from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web import create_app
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

_ISSUER = "11222333000181"
_PASSWORD = b"synthetic-password-only"
_LOGIN = "local-test-account-password"


def _synthetic_a1() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Test A1")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.OtherName(
                    ObjectIdentifier("2.16.76.1.3.3"),
                    bytes.fromhex("0c0e") + _ISSUER.encode("ascii"),
                ),
            ]), critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"synthetic-test", key=key, cert=certificate, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(_PASSWORD),
    )


def _client(
    vault: EncryptedA1Vault | None,
    *, tenant: str = "tenant-a", role: PortalRole = PortalRole.OWNER,
) -> TestClient:
    hasher = ScryptPasswordHasher()
    user = HumanAccount(
        account_id=f"test-{tenant}",
        email="local-test@example.com",
        password_hash=hasher.hash(_LOGIN),
        tenant_id=tenant,
        role=role,
        unit_ids=frozenset({"unit-a"}),
    )
    identity = HumanIdentityService(
        accounts=InMemoryHumanAccountRepository((user,)),
        sessions=InMemoryWebSessionRepository(),
        password_hasher=hasher,
        session_ttl=timedelta(hours=8),
    )
    client = TestClient(
        create_app(human_identity=identity, certificate_vault=vault),
        base_url="https://nfcore.test",
    )
    login = client.post(
        "/v1/auth/login",
        json={"email": user.email, "password": _LOGIN},
    )
    assert login.status_code == 200
    return client


def _url(*, unit: str = "unit-a", env: str = "homologation") -> str:
    return (
        "/v1/portal/certificates/a1/status"
        f"?unit_id={unit}&environment={env}&issuer_cnpj={_ISSUER}"
    )


def test_readback_returns_absent_then_confirmed_after_post_and_restart(tmp_path) -> None:
    root = tmp_path / "persisted-a1"
    vault = EncryptedA1Vault(directory=root, master_key=b"q" * 32)
    client = _client(vault)
    absent = client.get(_url())
    assert absent.status_code == 200
    assert absent.json() == {"status": "absent"}
    assert absent.headers["Cache-Control"] == "no-store"

    original = _synthetic_a1()
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf
    written = client.post(
        "/v1/portal/certificates/a1",
        headers={CSRF_HEADER: csrf},
        json={
            "unit_id": "unit-a", "environment": "homologation",
            "issuer_cnpj": _ISSUER,
            "pfx_base64": base64.b64encode(original).decode("ascii"),
            "password": _PASSWORD.decode("ascii"),
        },
    )
    assert written.status_code == 200
    assert written.json()["status"] == "stored"
    after = client.get(_url())
    assert after.status_code == 200
    assert after.json()["status"] == "stored"
    assert after.json()["fingerprint_sha256"] == written.json()["fingerprint_sha256"]
    assert after.json()["expires_at"] == written.json()["expires_at"]
    assert after.headers["Cache-Control"] == "no-store"
    assert "password" not in after.text.casefold()
    assert "pfx" not in after.text.casefold()
    assert original not in next(root.glob("*.a1.enc")).read_bytes()

    # A new vault object reads the same encrypted record, not an in-memory flag.
    restarted = EncryptedA1Vault(directory=root, master_key=b"q" * 32)
    new_client = _client(restarted)
    assert new_client.get(_url()).json()["fingerprint_sha256"] == (
        written.json()["fingerprint_sha256"]
    )
    # A different tenant must not see another tenant's certificate.
    other = _client(restarted, tenant="tenant-b")
    assert other.get(_url()).json() == {"status": "absent"}


def test_readback_fail_closed_for_wrong_unit_missing_vault_and_corrupted_file(tmp_path) -> None:
    root = tmp_path / "encrypted"
    vault = EncryptedA1Vault(directory=root, master_key=b"m" * 32)
    client = _client(vault)
    assert client.get(_url(unit="other-unit")).status_code == 403
    assert client.get(_url(env="production")).status_code == 400
    without_vault = _client(None)
    assert without_vault.get(_url()).status_code == 503

    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf
    payload = _synthetic_a1()
    result = client.post(
        "/v1/portal/certificates/a1",
        headers={CSRF_HEADER: csrf},
        json={
            "unit_id": "unit-a", "environment": "homologation",
            "issuer_cnpj": _ISSUER,
            "pfx_base64": base64.b64encode(payload).decode("ascii"),
            "password": _PASSWORD.decode("ascii"),
        },
    )
    assert result.status_code == 200
    next(root.glob("*.a1.enc")).write_bytes(b"invalid cipher")
    unreadable = client.get(_url())
    assert unreadable.status_code == 503
    assert unreadable.json()["detail"]["code"] == "A1_STATUS_UNVERIFIABLE"
    assert _PASSWORD.decode() not in unreadable.text


def test_readback_requires_login_and_certificate_manage_permission(tmp_path) -> None:
    vault = EncryptedA1Vault(directory=tmp_path / "vault", master_key=b"m" * 32)
    guest = TestClient(create_app(), base_url="https://nfcore.test")
    assert guest.get(_url()).status_code == 404  # portal is not installed without identity
    operator = _client(vault, role=PortalRole.OPERATOR)
    assert operator.get(_url()).status_code == 403


def test_invalid_pkcs12_returns_controlled_error_without_storing_file(tmp_path) -> None:
    root = tmp_path / "vault"
    client = _client(EncryptedA1Vault(directory=root, master_key=b"m" * 32))
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf
    result = client.post(
        "/v1/portal/certificates/a1",
        headers={CSRF_HEADER: csrf},
        json={
            "unit_id": "unit-a", "environment": "homologation",
            "issuer_cnpj": _ISSUER,
            "pfx_base64": base64.b64encode(b"invalid-pkcs12").decode("ascii"),
            "password": _PASSWORD.decode("ascii"),
        },
    )
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "A1_VALIDATION_FAILED"
    assert not list(root.glob("*.a1.enc"))
