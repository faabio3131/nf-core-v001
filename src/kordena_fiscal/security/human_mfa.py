"""Second factor (TOTP) for portal humans: enrollment, login challenge, step-up.

Approved policy (Fábio, 20/11/2026, after reviewing Conta Azul, Omie, Domínio
and Bling):

- TOTP from an authenticator app; no SMS.
- Mandatory for owner, admin, platform admin and anyone holding
  certificate.manage or document.issue; optional for the others, and the owner
  may require it from everyone in the tenant.
- "Remember this browser" for 30 days.
- Step-up (a fresh code) before sending/replacing an A1, releasing production
  egress, changing regime/CRT and changing users or the MFA policy.
- Ten single-use recovery codes, shown once.

Secrets are AES-GCM encrypted with a deployment key bound to the account id;
codes, challenge and device tokens are stored only as digests.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Lock
from typing import Protocol, runtime_checkable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kordena_fiscal.security.human_identity import (
    HumanAccount,
    HumanAuthenticationError,
    PortalPermission,
    PortalRole,
)
from kordena_fiscal.security.totp import (
    match_totp,
    new_totp_secret,
    otpauth_uri,
    secret_to_base32,
)

RECOVERY_CODE_COUNT = 10
CHALLENGE_MAX_FAILURES = 5
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
_MANDATORY_PERMISSIONS = frozenset(
    {PortalPermission.CERTIFICATE_MANAGE, PortalPermission.DOCUMENT_ISSUE}
)


class HumanMfaError(HumanAuthenticationError):
    """Second factor missing, invalid, expired or replayed."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _recovery_digest(account_id: str, code: str) -> str:
    return _digest(f"nfcore-mfa-recovery:{account_id}:{code}")


def normalize_recovery_code(code: str) -> str | None:
    if not isinstance(code, str):
        return None
    cleaned = code.replace("-", "").replace(" ", "").upper()
    if len(cleaned) != 10 or any(ch not in _RECOVERY_ALPHABET for ch in cleaned):
        return None
    return cleaned


@dataclass(frozen=True, slots=True)
class MfaFactor:
    account_id: str
    secret_ciphertext: str
    confirmed: bool
    created_at: datetime
    confirmed_at: datetime | None = None
    last_step: int | None = None


@dataclass(frozen=True, slots=True)
class MfaChallenge:
    token_sha256: str
    account_id: str
    purpose: str  # "verify" | "enroll"
    created_at: datetime
    expires_at: datetime
    failures: int = 0
    used: bool = False


@dataclass(frozen=True, slots=True)
class TrustedDevice:
    token_sha256: str
    account_id: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False


@runtime_checkable
class HumanMfaStore(Protocol):
    def factor(self, account_id: str) -> MfaFactor | None: ...
    def save_factor(self, factor: MfaFactor) -> None: ...
    def delete_factor(self, account_id: str) -> None: ...
    def advance_step(self, account_id: str, step: int) -> bool: ...
    def replace_recovery_codes(
        self, account_id: str, digests: tuple[str, ...], now: datetime,
    ) -> None: ...
    def consume_recovery_code(self, account_id: str, digest: str, now: datetime) -> bool: ...
    def remaining_recovery_codes(self, account_id: str) -> int: ...
    def save_challenge(self, challenge: MfaChallenge) -> None: ...
    def challenge(self, token_sha256: str) -> MfaChallenge | None: ...
    def record_challenge_failure(self, token_sha256: str) -> int: ...
    def consume_challenge(self, token_sha256: str) -> bool: ...
    def save_trusted_device(self, device: TrustedDevice) -> None: ...
    def trusted_device(self, token_sha256: str) -> TrustedDevice | None: ...
    def revoke_trusted_devices(self, account_id: str) -> None: ...
    def record_step_up(self, session_id: str, account_id: str, at: datetime) -> None: ...
    def step_up_at(self, session_id: str) -> datetime | None: ...
    def tenant_requires_all(self, tenant_id: str) -> bool: ...
    def set_tenant_requires_all(
        self, tenant_id: str, value: bool, actor_account_id: str, now: datetime,
    ) -> None: ...


class InMemoryHumanMfaStore:
    """Reference store with the same atomic contracts as the PostgreSQL one."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._factors: dict[str, MfaFactor] = {}
        self._recovery: dict[str, dict[str, bool]] = {}
        self._challenges: dict[str, MfaChallenge] = {}
        self._devices: dict[str, TrustedDevice] = {}
        self._step_ups: dict[str, tuple[str, datetime]] = {}
        self._policy: dict[str, bool] = {}

    def factor(self, account_id: str) -> MfaFactor | None:
        with self._lock:
            return self._factors.get(account_id)

    def save_factor(self, factor: MfaFactor) -> None:
        with self._lock:
            self._factors[factor.account_id] = factor

    def delete_factor(self, account_id: str) -> None:
        with self._lock:
            self._factors.pop(account_id, None)
            self._recovery.pop(account_id, None)
            for key, device in tuple(self._devices.items()):
                if device.account_id == account_id:
                    self._devices[key] = replace(device, revoked=True)

    def advance_step(self, account_id: str, step: int) -> bool:
        with self._lock:
            factor = self._factors.get(account_id)
            if factor is None or (factor.last_step is not None and factor.last_step >= step):
                return False
            self._factors[account_id] = replace(factor, last_step=step)
            return True

    def replace_recovery_codes(
        self, account_id: str, digests: tuple[str, ...], now: datetime,
    ) -> None:
        with self._lock:
            self._recovery[account_id] = {digest: False for digest in digests}

    def consume_recovery_code(self, account_id: str, digest: str, now: datetime) -> bool:
        with self._lock:
            codes = self._recovery.get(account_id, {})
            if codes.get(digest) is not False:
                return False
            codes[digest] = True
            return True

    def remaining_recovery_codes(self, account_id: str) -> int:
        with self._lock:
            return sum(1 for used in self._recovery.get(account_id, {}).values() if not used)

    def save_challenge(self, challenge: MfaChallenge) -> None:
        with self._lock:
            self._challenges[challenge.token_sha256] = challenge

    def challenge(self, token_sha256: str) -> MfaChallenge | None:
        with self._lock:
            return self._challenges.get(token_sha256)

    def record_challenge_failure(self, token_sha256: str) -> int:
        with self._lock:
            found = self._challenges.get(token_sha256)
            if found is None:
                return CHALLENGE_MAX_FAILURES
            updated = replace(found, failures=found.failures + 1)
            self._challenges[token_sha256] = updated
            return updated.failures

    def consume_challenge(self, token_sha256: str) -> bool:
        with self._lock:
            found = self._challenges.get(token_sha256)
            if found is None or found.used:
                return False
            self._challenges[token_sha256] = replace(found, used=True)
            return True

    def save_trusted_device(self, device: TrustedDevice) -> None:
        with self._lock:
            self._devices[device.token_sha256] = device

    def trusted_device(self, token_sha256: str) -> TrustedDevice | None:
        with self._lock:
            return self._devices.get(token_sha256)

    def revoke_trusted_devices(self, account_id: str) -> None:
        with self._lock:
            for key, device in tuple(self._devices.items()):
                if device.account_id == account_id:
                    self._devices[key] = replace(device, revoked=True)

    def record_step_up(self, session_id: str, account_id: str, at: datetime) -> None:
        with self._lock:
            self._step_ups[session_id] = (account_id, at)

    def step_up_at(self, session_id: str) -> datetime | None:
        with self._lock:
            found = self._step_ups.get(session_id)
            return found[1] if found is not None else None

    def tenant_requires_all(self, tenant_id: str) -> bool:
        with self._lock:
            return self._policy.get(tenant_id, False)

    def set_tenant_requires_all(
        self, tenant_id: str, value: bool, actor_account_id: str, now: datetime,
    ) -> None:
        with self._lock:
            self._policy[tenant_id] = value


@dataclass(frozen=True, slots=True)
class MfaEnrollment:
    secret_base32: str
    otpauth_uri: str

    def __repr__(self) -> str:
        return "MfaEnrollment(<redacted>)"


@dataclass(frozen=True, slots=True)
class MfaStatus:
    required: bool
    enrolled: bool
    recovery_codes_remaining: int
    tenant_requires_all: bool


class HumanMfaService:
    def __init__(
        self,
        *,
        store: HumanMfaStore,
        encryption_key: bytes,
        challenge_ttl: timedelta = timedelta(minutes=5),
        trusted_device_ttl: timedelta = timedelta(days=30),
        step_up_window: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(store, HumanMfaStore):
            raise ValueError("store must implement HumanMfaStore")
        if len(encryption_key) != 32:
            raise ValueError("MFA requires a 32-byte external encryption key")
        self._store = store
        self._aes = AESGCM(encryption_key)
        self._challenge_ttl = challenge_ttl
        self._trusted_device_ttl = trusted_device_ttl
        self._step_up_window = step_up_window

    @classmethod
    def from_environ(cls, store_factory: Callable[[], HumanMfaStore]) -> HumanMfaService | None:
        mode = os.environ.get("NFCORE_HUMAN_MFA", "").strip().lower()
        if mode in {"", "disabled"}:
            return None
        if mode != "enabled":
            raise ValueError("NFCORE_HUMAN_MFA must be enabled or disabled")
        raw = os.environ.get("NFCORE_HUMAN_MFA_KEY_BASE64", "")
        try:
            key = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("NFCORE_HUMAN_MFA_KEY_BASE64 is invalid") from None
        return cls(store=store_factory(), encryption_key=key)

    # --- policy ---------------------------------------------------------------
    def required_for(self, account: HumanAccount) -> bool:
        if account.platform_admin or account.role in {PortalRole.OWNER, PortalRole.ADMIN}:
            return True
        if account.permissions & _MANDATORY_PERMISSIONS:
            return True
        return self._store.tenant_requires_all(account.tenant_id)

    def is_enrolled(self, account_id: str) -> bool:
        factor = self._store.factor(account_id)
        return factor is not None and factor.confirmed

    def status(self, account: HumanAccount) -> MfaStatus:
        return MfaStatus(
            required=self.required_for(account),
            enrolled=self.is_enrolled(account.account_id),
            recovery_codes_remaining=self._store.remaining_recovery_codes(account.account_id),
            tenant_requires_all=self._store.tenant_requires_all(account.tenant_id),
        )

    def set_tenant_requires_all(self, actor: HumanAccount, value: bool, now: datetime) -> None:
        if actor.role is not PortalRole.OWNER:
            raise HumanMfaError("only the owner changes the tenant MFA policy")
        self._store.set_tenant_requires_all(actor.tenant_id, value, actor.account_id, now)

    # --- secrets ----------------------------------------------------------------
    def _encrypt(self, account_id: str, secret: bytes) -> str:
        nonce = secrets.token_bytes(12)
        sealed = self._aes.encrypt(nonce, secret, f"nfcore-mfa:{account_id}".encode())
        return base64.b64encode(nonce + sealed).decode("ascii")

    def _decrypt(self, factor: MfaFactor) -> bytes:
        try:
            raw = base64.b64decode(factor.secret_ciphertext, validate=True)
            return self._aes.decrypt(
                raw[:12], raw[12:], f"nfcore-mfa:{factor.account_id}".encode(),
            )
        except (ValueError, binascii.Error, InvalidTag):
            raise HumanMfaError("second factor is not usable") from None

    # --- enrollment -------------------------------------------------------------
    def start_enrollment(self, account: HumanAccount, now: datetime) -> MfaEnrollment:
        if self.is_enrolled(account.account_id):
            raise HumanMfaError("second factor already enrolled")
        secret = new_totp_secret()
        self._store.save_factor(MfaFactor(
            account_id=account.account_id,
            secret_ciphertext=self._encrypt(account.account_id, secret),
            confirmed=False, created_at=now,
        ))
        return MfaEnrollment(
            secret_to_base32(secret), otpauth_uri(secret, account_label=account.email),
        )

    def confirm_enrollment(
        self, account: HumanAccount, code: str, now: datetime,
    ) -> tuple[str, ...]:
        factor = self._store.factor(account.account_id)
        if factor is None or factor.confirmed:
            raise HumanMfaError("no pending enrollment")
        step = match_totp(self._decrypt(factor), code, now, after_step=factor.last_step)
        if step is None:
            raise HumanMfaError("invalid code")
        self._store.save_factor(replace(factor, confirmed=True, confirmed_at=now, last_step=step))
        return self.regenerate_recovery_codes(account, now)

    def regenerate_recovery_codes(self, account: HumanAccount, now: datetime) -> tuple[str, ...]:
        if not self.is_enrolled(account.account_id):
            raise HumanMfaError("second factor not enrolled")
        codes = tuple(
            "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
            for _ in range(RECOVERY_CODE_COUNT)
        )
        self._store.replace_recovery_codes(
            account.account_id,
            tuple(_recovery_digest(account.account_id, code) for code in codes),
            now,
        )
        return tuple(f"{code[:5]}-{code[5:]}" for code in codes)

    def reset(self, account_id: str) -> None:
        """Remove the factor (lost phone); the user enrolls again on next login."""
        self._store.delete_factor(account_id)

    # --- verification -----------------------------------------------------------
    def verify(self, account: HumanAccount, code: str, now: datetime) -> str:
        """Accept a TOTP code (replay-protected) or one recovery code."""
        factor = self._store.factor(account.account_id)
        if factor is None or not factor.confirmed:
            raise HumanMfaError("second factor not enrolled")
        step = match_totp(self._decrypt(factor), code, now, after_step=factor.last_step)
        if step is not None and self._store.advance_step(account.account_id, step):
            return "totp"
        recovery = normalize_recovery_code(code)
        if recovery is not None and self._store.consume_recovery_code(
            account.account_id, _recovery_digest(account.account_id, recovery), now,
        ):
            return "recovery"
        raise HumanMfaError("invalid code")

    # --- login challenge --------------------------------------------------------
    def open_challenge(self, account: HumanAccount, now: datetime) -> tuple[str, str]:
        purpose = "verify" if self.is_enrolled(account.account_id) else "enroll"
        token = secrets.token_urlsafe(32)
        self._store.save_challenge(MfaChallenge(
            token_sha256=_digest(token), account_id=account.account_id, purpose=purpose,
            created_at=now, expires_at=now + self._challenge_ttl,
        ))
        return token, purpose

    def challenge_account(self, token: str, now: datetime) -> MfaChallenge:
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise HumanMfaError("challenge is not usable")
        found = self._store.challenge(_digest(token))
        if (
            found is None or found.used or now >= found.expires_at
            or found.failures >= CHALLENGE_MAX_FAILURES
        ):
            raise HumanMfaError("challenge is not usable")
        return found

    def fail_challenge(self, token: str) -> None:
        self._store.record_challenge_failure(_digest(token))

    def consume_challenge(self, token: str) -> None:
        if not self._store.consume_challenge(_digest(token)):
            raise HumanMfaError("challenge is not usable")

    # --- trusted browser --------------------------------------------------------
    def issue_trusted_device(self, account: HumanAccount, now: datetime) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = now + self._trusted_device_ttl
        self._store.save_trusted_device(TrustedDevice(
            token_sha256=_digest(token), account_id=account.account_id,
            created_at=now, expires_at=expires,
        ))
        return token, expires

    def is_trusted_device(self, account: HumanAccount, token: str | None, now: datetime) -> bool:
        if not token or len(token) > 200:
            return False
        device = self._store.trusted_device(_digest(token))
        return (
            device is not None and not device.revoked and now < device.expires_at
            and hmac.compare_digest(device.account_id, account.account_id)
            and self.is_enrolled(account.account_id)
        )

    def forget_devices(self, account: HumanAccount) -> None:
        self._store.revoke_trusted_devices(account.account_id)

    # --- step-up ----------------------------------------------------------------
    def step_up(self, account: HumanAccount, session_id: str, code: str, now: datetime) -> None:
        self.verify(account, code, now)
        self._store.record_step_up(session_id, account.account_id, now)

    def has_recent_step_up(self, session_id: str, now: datetime) -> bool:
        at = self._store.step_up_at(session_id)
        return at is not None and timedelta(0) <= now - at <= self._step_up_window
