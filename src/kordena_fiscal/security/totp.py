"""RFC 6238 TOTP (HMAC-SHA1, 6 digits, 30 s) as used by authenticator apps.

Google Authenticator, Microsoft Authenticator, Authy and 1Password all accept
the otpauth URI built here. Verification accepts one step of clock drift on
each side and returns the matched step so callers can refuse its replay.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_DRIFT_STEPS = 1
_SECRET_BYTES = 20  # 160 bits, RFC 4226 recommendation


def new_totp_secret() -> bytes:
    return secrets.token_bytes(_SECRET_BYTES)


def secret_to_base32(secret: bytes) -> str:
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def hotp(secret: bytes, counter: int) -> str:
    if counter < 0:
        raise ValueError("counter must be non-negative")
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def time_step(now: datetime) -> int:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return int(now.timestamp()) // TOTP_PERIOD_SECONDS


def totp_at(secret: bytes, now: datetime) -> str:
    return hotp(secret, time_step(now))


def normalize_code(code: str) -> str | None:
    if not isinstance(code, str):
        return None
    cleaned = code.replace(" ", "").replace("-", "")
    if len(cleaned) != TOTP_DIGITS or not cleaned.isascii() or not cleaned.isdigit():
        return None
    return cleaned


def match_totp(secret: bytes, code: str, now: datetime, *, after_step: int | None) -> int | None:
    """Return the matched time step, or None. Steps <= after_step are replays."""
    cleaned = normalize_code(code)
    if cleaned is None:
        return None
    current = time_step(now)
    matched: int | None = None
    for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
        if step < 0:
            continue
        # Compare every candidate so timing does not reveal which step matched.
        if hmac.compare_digest(hotp(secret, step), cleaned) and matched is None:
            matched = step
    if matched is None or (after_step is not None and matched <= after_step):
        return None
    return matched


def otpauth_uri(secret: bytes, *, account_label: str, issuer: str = "FM NFCORE") -> str:
    label = quote(f"{issuer}:{account_label}", safe="@:")
    return (
        f"otpauth://totp/{label}?secret={secret_to_base32(secret)}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}"
        f"&period={TOTP_PERIOD_SECONDS}"
    )
