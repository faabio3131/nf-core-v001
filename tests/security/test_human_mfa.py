"""Second factor: RFC 6238, policy, login challenge, trusted browser and step-up."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanIdentityService,
    InMemoryHumanAccountRepository,
    InMemoryWebSessionRepository,
    PortalRole,
    ScryptPasswordHasher,
)
from kordena_fiscal.security.human_mfa import (
    HumanMfaError,
    HumanMfaService,
    InMemoryHumanMfaStore,
)
from kordena_fiscal.security.totp import hotp, match_totp, otpauth_uri, totp_at
from kordena_fiscal.web.app import create_app

RFC_SECRET = b"12345678901234567890"
KEY = bytes(range(32))
PASSWORD = "Senha-forte-para-teste-1"


def test_rfc6238_vectors_and_drift_and_replay() -> None:
    # RFC 6238 appendix B (SHA1), truncated to the 6 digits authenticator apps show.
    assert totp_at(RFC_SECRET, datetime.fromtimestamp(59, UTC)) == "287082"
    assert totp_at(RFC_SECRET, datetime.fromtimestamp(1111111109, UTC)) == "081804"
    assert totp_at(RFC_SECRET, datetime.fromtimestamp(1234567890, UTC)) == "005924"
    assert hotp(RFC_SECRET, 0) == "755224"  # RFC 4226 appendix D
    now = datetime.fromtimestamp(1234567890, UTC)
    previous = totp_at(RFC_SECRET, now - timedelta(seconds=30))
    step = match_totp(RFC_SECRET, previous, now, after_step=None)
    assert step == 1234567890 // 30 - 1
    assert match_totp(RFC_SECRET, previous, now, after_step=step) is None
    assert match_totp(RFC_SECRET, totp_at(RFC_SECRET, now - timedelta(seconds=90)),
                      now, after_step=None) is None
    assert match_totp(RFC_SECRET, "12a456", now, after_step=None) is None
    uri = otpauth_uri(RFC_SECRET, account_label="dono@empresa.com.br")
    assert uri.startswith("otpauth://totp/FM%20NFCORE:dono@empresa.com.br?secret=GEZDGNBV")


def _account(role: PortalRole, email: str) -> HumanAccount:
    return HumanAccount(
        account_id=f"acc-{role.value}", email=email,
        password_hash=ScryptPasswordHasher().hash(PASSWORD),
        tenant_id="tenant-a", role=role,
    )


@pytest.fixture
def world():
    accounts = InMemoryHumanAccountRepository((
        _account(PortalRole.OWNER, "dono@empresa.com.br"),
        _account(PortalRole.AUDITOR, "auditor@empresa.com.br"),
        _account(PortalRole.OPERATOR, "operador@empresa.com.br"),
    ))
    identity = HumanIdentityService(
        accounts=accounts, sessions=InMemoryWebSessionRepository(),
        password_hasher=ScryptPasswordHasher(),
    )
    store = InMemoryHumanMfaStore()
    mfa = HumanMfaService(store=store, encryption_key=KEY)
    client = TestClient(create_app(human_identity=identity, human_mfa=mfa),
                        base_url="https://testserver")
    return client, identity, mfa, accounts


def _login(client, email):
    response = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _secret(body) -> bytes:
    import base64
    raw = body["secret_base32"]
    return base64.b32decode(raw + "=" * (-len(raw) % 8))


def test_policy_mandatory_roles_and_owner_can_require_everyone(world) -> None:
    _, _, mfa, accounts = world
    owner = accounts.by_id("acc-owner")
    auditor = accounts.by_id("acc-auditor")
    operator = accounts.by_id("acc-operator")
    assert mfa.required_for(owner) and mfa.required_for(operator)  # document.issue
    assert not mfa.required_for(auditor)
    with pytest.raises(HumanMfaError):
        mfa.set_tenant_requires_all(operator, True, datetime.now(UTC))
    mfa.set_tenant_requires_all(owner, True, datetime.now(UTC))
    assert mfa.required_for(auditor)


def test_full_login_enrollment_verify_trusted_browser_and_step_up(world) -> None:
    client, _, _, _ = world
    # Optional role, not enrolled: password alone opens the session.
    assert "account" in _login(client, "auditor@empresa.com.br")
    client.cookies.clear()

    # Mandatory role, first login: no session until the app is enrolled.
    first = _login(client, "dono@empresa.com.br")
    assert first == {"mfa": {"challenge": first["mfa"]["challenge"], "purpose": "enroll"}}
    assert "nfcore_session" not in client.cookies
    challenge = first["mfa"]["challenge"]
    start = client.post("/v1/auth/mfa/enroll/start", json={"challenge": challenge})
    assert start.status_code == 200 and start.json()["otpauth_uri"].startswith("otpauth://")
    qr = start.json()["qr_data_uri"]
    assert qr is None or qr.startswith("data:image/svg+xml")
    secret = _secret(start.json())
    bad = client.post("/v1/auth/mfa/enroll/confirm", json={"challenge": challenge,
                                                             "code": "000000"})
    assert bad.status_code == 401
    now = datetime.now(UTC)
    done = client.post("/v1/auth/mfa/enroll/confirm", json={
        "challenge": challenge, "code": totp_at(secret, now - timedelta(seconds=30)),
    })
    assert done.status_code == 200, done.text
    recovery = done.json()["recovery_codes"]
    assert len(recovery) == 10 and len(set(recovery)) == 10
    assert "nfcore_session" in client.cookies
    me = client.get("/v1/auth/me").json()
    assert me["mfa"]["enrolled"] and me["mfa"]["recovery_codes_remaining"] == 10

    # Sensitive operation without a fresh code is refused.
    csrf = {"X-CSRF-Token": client.cookies["nfcore_csrf"]}
    refused = client.post("/v1/auth/mfa/policy", json={"require_all": True}, headers=csrf)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    replay = client.post("/v1/auth/mfa/step-up", headers=csrf, json={
        "code": totp_at(secret, now - timedelta(seconds=30)),
    })
    assert replay.status_code == 401  # same step as enrollment: replay refused
    ok = client.post("/v1/auth/mfa/step-up", headers=csrf,
                     json={"code": totp_at(secret, now)})
    assert ok.status_code == 200
    assert client.post("/v1/auth/mfa/policy", json={"require_all": True},
                       headers=csrf).json() == {"tenant_requires_all": True}
    client.post("/v1/auth/logout", headers=csrf)
    client.cookies.clear()

    # Next login: verify with a recovery code and remember the browser.
    second = _login(client, "dono@empresa.com.br")["mfa"]
    assert second["purpose"] == "verify"
    wrong_purpose = client.post("/v1/auth/mfa/enroll/start",
                                json={"challenge": second["challenge"]})
    assert wrong_purpose.status_code == 401
    verified = client.post("/v1/auth/mfa/verify", json={
        "challenge": second["challenge"], "code": recovery[0].lower(),
        "remember_device": True,
    })
    assert verified.status_code == 200, verified.text
    reused = client.post("/v1/auth/mfa/verify", json={
        "challenge": second["challenge"], "code": recovery[1],
    })
    assert reused.status_code == 401  # challenge is single use
    device = client.cookies.get("nfcore_mfa_device")
    assert device
    csrf = {"X-CSRF-Token": client.cookies["nfcore_csrf"]}
    client.post("/v1/auth/logout", headers=csrf)
    client.cookies.clear()
    client.cookies.set("nfcore_mfa_device", device, path="/v1/auth")
    assert "account" in _login(client, "dono@empresa.com.br")  # trusted browser
    assert client.get("/v1/auth/me").json()["mfa"]["recovery_codes_remaining"] == 9


def test_challenge_locks_after_five_failures(world) -> None:
    client, _, mfa, accounts = world
    owner = accounts.by_id("acc-owner")
    now = datetime.now(UTC)
    enrollment = mfa.start_enrollment(owner, now)
    import base64
    secret = base64.b32decode(enrollment.secret_base32 + "=" * (-len(enrollment.secret_base32) % 8))
    mfa.confirm_enrollment(owner, totp_at(secret, now - timedelta(seconds=30)), now)
    challenge = _login(client, "dono@empresa.com.br")["mfa"]["challenge"]
    for _ in range(5):
        assert client.post("/v1/auth/mfa/verify", json={
            "challenge": challenge, "code": "111111"}).status_code == 401
    locked = client.post("/v1/auth/mfa/verify", json={
        "challenge": challenge, "code": totp_at(secret, now)})
    assert locked.status_code == 401
    assert locked.json()["detail"]["code"] == "MFA_CHALLENGE_INVALID"


def test_secret_is_encrypted_and_bound_to_the_account(world) -> None:
    _, _, mfa, accounts = world
    owner = accounts.by_id("acc-owner")
    enrollment = mfa.start_enrollment(owner, datetime.now(UTC))
    stored = mfa._store.factor(owner.account_id)
    assert enrollment.secret_base32 not in stored.secret_ciphertext
    moved = type(stored)(account_id="acc-auditor", secret_ciphertext=stored.secret_ciphertext,
                         confirmed=True, created_at=stored.created_at)
    with pytest.raises(HumanMfaError):
        mfa._decrypt(moved)
    assert "redacted" in repr(enrollment)


def test_portal_requires_enrollment_and_step_up_for_sensitive_operations(world) -> None:
    import base64

    client, identity, mfa, accounts = world
    owner = accounts.by_id("acc-owner")
    now = datetime.now(UTC)
    # A session opened before MFA was switched on cannot use the portal.
    issued = identity.login(email=owner.email, password=PASSWORD, now=now)
    client.cookies.set("nfcore_session", issued.session_token)
    client.cookies.set("nfcore_csrf", issued.csrf_token)
    headers = {"X-CSRF-Token": issued.csrf_token, "Idempotency-Key": "k-1"}
    body = {"unit_id": "matriz", "environment": "homologation", "crt": "3",
            "expected_version": 1}
    blocked = client.post("/v1/portal/operations/changeFiscalProfileCrt", json=body,
                          headers=headers)
    assert blocked.json()["detail"]["code"] == "MFA_ENROLLMENT_REQUIRED"
    enrollment = mfa.start_enrollment(owner, now)
    raw = enrollment.secret_base32
    secret = base64.b32decode(raw + "=" * (-len(raw) % 8))
    mfa.confirm_enrollment(owner, totp_at(secret, now - timedelta(seconds=30)), now)
    gated = client.post("/v1/portal/operations/changeFiscalProfileCrt", json=body,
                        headers=headers)
    assert gated.status_code == 403
    assert gated.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    assert client.post("/v1/auth/mfa/step-up", headers=headers,
                       json={"code": totp_at(secret, now)}).status_code == 200
    passed = client.post("/v1/portal/operations/changeFiscalProfileCrt", json=body,
                         headers=headers)
    assert passed.status_code == 503  # gate passed; this harness has no executor
    reset = client.post("/v1/auth/mfa/reset", headers=headers,
                        json={"account_id": "acc-operator"})
    assert reset.status_code == 200
    assert client.post("/v1/auth/mfa/reset", headers=headers,
                       json={"account_id": "acc-owner"}).status_code == 404
