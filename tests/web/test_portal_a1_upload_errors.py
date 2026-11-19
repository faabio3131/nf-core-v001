"""A1 upload: preflight failures must be clear 4xx, never an unhandled HTTP 500."""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault
from kordena_fiscal.web import portal_api

_CNPJ = "09107283000140"
_PASSWORD = b"senha-de-teste"


def _pfx(*, cnpj: str = _CNPJ, expired: bool = False) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Empresa Teste")])
    now = datetime.now(UTC)
    start, end = (
        (now - timedelta(days=400), now - timedelta(days=30))
        if expired else (now - timedelta(days=1), now + timedelta(days=300))
    )
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(start).not_valid_after(end)
        .add_extension(x509.KeyUsage(
            True, True, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.SubjectAlternativeName([
            x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), b"\x13\x0e" + cnpj.encode()),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"t", key, cert, None, serialization.BestAvailableEncryption(_PASSWORD))


@pytest.fixture
def client(tmp_path, monkeypatch):
    auth = SimpleNamespace(tenant_id="tenant-a")
    monkeypatch.setattr(portal_api, "_authenticated", lambda *a, **k: auth)
    monkeypatch.setattr(portal_api, "_csrf", lambda *a, **k: None)
    monkeypatch.setattr(portal_api, "_authorized", lambda *a, **k: None)
    vault = EncryptedA1Vault(directory=tmp_path / "vault", master_key=b"k" * 32)
    app = FastAPI()
    app.include_router(portal_api.create_portal_router(
        SimpleNamespace(), None, certificate_vault=vault))
    return TestClient(app)


def _post(client, pfx: bytes, *, password: bytes = _PASSWORD, cnpj: str = _CNPJ):
    body = {
        "unit_id": "u1", "environment": "homologation", "issuer_cnpj": cnpj,
        "pfx_base64": base64.b64encode(pfx).decode(), "password": password.decode(),
    }
    return client.post("/v1/portal/certificates/a1", content=json.dumps(body),
                       headers={"Content-Type": "application/json"})


def test_valid_a1_is_stored(client):
    response = _post(client, _pfx())
    assert response.status_code == 200 and response.json()["status"] == "stored"


@pytest.mark.parametrize(("kwargs", "code"), [
    ({"password": b"errada"}, "A1_FILE_OR_PASSWORD_INVALID"),
    ({"cnpj": "11222333000181"}, "A1_CNPJ_MISMATCH"),
])
def test_preflight_failures_are_422_with_specific_code(client, kwargs, code):
    response = _post(client, _pfx(), **kwargs)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_expired_a1_is_422_expired(client):
    response = _post(client, _pfx(expired=True))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "A1_EXPIRED"


def test_non_pkcs12_bytes_are_422_not_500(client):
    response = _post(client, b"not a pfx at all")
    assert response.status_code == 422
