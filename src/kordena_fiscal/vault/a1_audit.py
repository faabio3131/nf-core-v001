"""Durable, tamper-evident audit trail for A1 certificate operations.

One JSON object per line, appended under an exclusive file lock, fsynced, and
chained: each record carries the SHA-256 of the previous line, so editing or
deleting a past line breaks verification. The file lives next to the encrypted
records (host bind mount), mode 0600.

Never written: PKCS#12 bytes, password, private key, master key or file paths.
Recorded: when, which operation, outcome (and error class), scope, issuer CNPJ,
certificate fingerprint when known, and the acting human when the caller knows it.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from kordena_fiscal.domain import FiscalValidationError

AUDIT_FILENAME = "a1-audit.jsonl"
_GENESIS = "0" * 64
_MAX_TAIL = 64 * 1024
_ALLOWED_KEYS = frozenset({
    "at", "event", "outcome", "error", "host_namespace", "tenant_id", "unit_id",
    "environment", "issuer_cnpj", "fingerprint_sha256", "actor", "prev_sha256",
})
_EVENTS = frozenset({"provision", "inspect", "resolve", "withdraw"})


class A1AuditUnavailable(FiscalValidationError):
    """The A1 audit trail could not be written; the operation must not proceed."""


def _line_digest(line: bytes) -> str:
    return hashlib.sha256(line.rstrip(b"\n")).hexdigest()


def _last_line(handle: int) -> bytes | None:
    size = os.fstat(handle).st_size
    if size == 0:
        return None
    start = max(0, size - _MAX_TAIL)
    os.lseek(handle, start, os.SEEK_SET)
    tail = os.read(handle, size - start)
    lines = [line for line in tail.split(b"\n") if line]
    if not lines:
        return None
    return lines[-1]


class A1AuditLog:
    def __init__(self, directory: str | Path) -> None:
        self._path = Path(directory) / AUDIT_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def ensure_writable(self) -> None:
        """Pre-check before a state change, so nothing changes unaudited."""
        if self._path.is_symlink():
            raise A1AuditUnavailable("A1 audit trail is not trusted")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            os.close(os.open(self._path, flags, 0o600))
        except OSError:
            raise A1AuditUnavailable("Auditoria do A1 indisponível") from None

    def append(self, record: Mapping[str, object]) -> str:
        """Append one chained record; returns its digest. Fails closed."""
        if set(record) - _ALLOWED_KEYS or record.get("event") not in _EVENTS:
            raise A1AuditUnavailable("A1 audit record has unexpected fields")
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX hosts are unsupported
            raise A1AuditUnavailable("A1 audit requires a POSIX host") from None
        if self._path.is_symlink():
            raise A1AuditUnavailable("A1 audit trail is not trusted")
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        try:
            handle = os.open(self._path, flags, 0o600)
        except OSError:
            raise A1AuditUnavailable("Auditoria do A1 indisponível") from None
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            previous = _last_line(handle)
            body = {
                **dict(record),
                "prev_sha256": _GENESIS if previous is None else _line_digest(previous),
            }
            line = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            os.write(handle, line + b"\n")
            os.fsync(handle)
            return _line_digest(line)
        except OSError:
            raise A1AuditUnavailable("Auditoria do A1 indisponível") from None
        finally:
            os.close(handle)


def a1_audit_record(
    *, event: str, outcome: str, scope: object, issuer_cnpj: str,
    fingerprint_sha256: str | None = None, actor: str | None = None,
    error: BaseException | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
        "event": event,
        "outcome": outcome,
        "host_namespace": getattr(scope, "host_namespace", None),
        "tenant_id": getattr(scope, "tenant_id", None),
        "unit_id": getattr(scope, "unit_id", None),
        "environment": getattr(getattr(scope, "environment", None), "value", None),
        "issuer_cnpj": issuer_cnpj if isinstance(issuer_cnpj, str) else None,
    }
    if fingerprint_sha256 is not None:
        record["fingerprint_sha256"] = fingerprint_sha256
    if actor is not None:
        record["actor"] = actor[:128]
    if error is not None:
        # Class name only: exception messages may echo caller-supplied text.
        record["error"] = type(error).__name__
    return record


def verify_a1_audit_chain(path: str | Path) -> int:
    """Return the number of records; raise if any line was edited or removed."""
    expected = _GENESIS
    count = 0
    with open(path, "rb") as stream:
        for raw in stream:
            line = raw.rstrip(b"\n")
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                raise A1AuditUnavailable("A1 audit trail is corrupt") from None
            if not isinstance(record, dict) or record.get("prev_sha256") != expected:
                raise A1AuditUnavailable("A1 audit chain is broken")
            expected = _line_digest(line)
            count += 1
    return count
