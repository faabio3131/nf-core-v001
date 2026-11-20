"""Non-authoritative monitoring of public regulatory portal page changes.

Detects only changes in fetched portal bytes; NEVER claims that a law, table or
tax rule changed or that a source document is authentic. Approval remains human.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCES: dict[str, str] = {
    "NFE": "https://www.nfe.fazenda.gov.br/portal/",
    "SVRS": "https://dfe-portal.svrs.rs.gov.br/Nfe/Conformidade",
    "NFSE": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc",
    "DOU": "https://www.in.gov.br/",
}
ECONOMY_SOURCES: dict[str, str] = {
    "PGFN_EDITAIS": (
        "https://www.gov.br/pgfn/pt-br/servicos/editais-de-notificacao/"
        "acordo-de-transacao-por-adesao-1"
    ),
    "RFB_TRANSACAO": (
        "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/"
        "pagamentos-e-parcelamentos/transacao-tributaria"
    ),
}
MAX_BYTES = 2 * 1024 * 1024
_STATE_SCHEMA = 1


class NormativeWatchError(ValueError):
    """A source, snapshot or durable observation is unsafe/unavailable."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def fetch_official_portal(url: str) -> bytes:
    """Fetch an immutable allowlisted portal URL, without following redirects."""
    if url not in (*SOURCES.values(), *ECONOMY_SOURCES.values()):
        raise NormativeWatchError("normative portal URL is not allowlisted")
    request = Request(
        url,
        headers={
            "User-Agent": "NFCore-Normative-ReadOnly-Watch/1",
            "Accept": "text/html,application/pdf,application/octet-stream",
        },
        method="GET",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            media = (response.headers.get("Content-Type") or "").split(";", 1)[0]
            if media not in (
                "text/html",
                "application/xhtml+xml",
                "application/pdf",
                "application/octet-stream",
            ):
                raise NormativeWatchError("unexpected official portal response type")
            data = response.read(MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise NormativeWatchError("official portal temporarily unavailable") from exc
    if not data or len(data) > MAX_BYTES:
        raise NormativeWatchError("official portal response is empty or oversized")
    return cast(bytes, data)


def _load_state(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise NormativeWatchError("symlink state file forbidden")
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > 32_768:
        raise NormativeWatchError("invalid snapshot state file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise NormativeWatchError("normative state cannot be parsed") from exc
    if not isinstance(data, dict) or data.get("schema_version") != _STATE_SCHEMA:
        raise NormativeWatchError("unsupported normative state schema")
    known = data.get("hashes")
    if not isinstance(known, dict) or set(known) != set(SOURCES):
        raise NormativeWatchError("normative snapshot source set differs")
    if not all(
        isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
        for v in known.values()
    ):
        raise NormativeWatchError("invalid normative snapshot hashes")
    return known


def poll_normative_sources(
    *,
    state_path: Path,
    fetch: Callable[[str], bytes] = fetch_official_portal,
    observed_at: datetime | None = None,
    economy: bool = False,
) -> tuple[dict[str, str], ...]:
    """Compare portal bytes, write checkpoint atomically, return review events.

    Cross-process lock refuses a second poll (no silent lost updates).
    The state is MONITORING CACHE ONLY; not the normative baseline ledger.
    """
    if not state_path.is_absolute():
        raise NormativeWatchError("absolute monitoring state path required")
    if not state_path.parent.is_dir() or state_path.parent.is_symlink():
        raise NormativeWatchError("monitoring directory must pre-exist without symlinks")
    when = observed_at or datetime.now(UTC)
    if when.tzinfo is None or when.utcoffset() is None:
        raise NormativeWatchError("observed_at must be timezone-aware")
    lock = state_path.with_suffix(state_path.suffix + ".lock")
    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    if lock.is_symlink() or temp.is_symlink():
        raise NormativeWatchError("monitoring lock/scratch symlink forbidden")
    try:
        handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise NormativeWatchError("normative monitoring lock unavailable") from exc
    try:
        os.close(handle)
        if economy:
            from .normative_radar import poll_radar_locked

            return poll_radar_locked(state_path, temp, fetch, when)
        before = _load_state(state_path)
        now: dict[str, str] = {}
        events: list[dict[str, str]] = []
        for source, url in SOURCES.items():
            content = fetch(url)
            if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
                raise NormativeWatchError("portal fetch returned invalid bytes")
            digest = hashlib.sha256(content).hexdigest()
            now[source] = digest
            status = (
                "FIRST_OBSERVATION_REVIEW_REQUIRED"
                if source not in before
                else "PORTAL_CONTENT_CHANGED_REVIEW_REQUIRED"
                if before[source] != digest
                else "UNCHANGED"
            )
            events.append(
                {
                    "source": source,
                    "url": url,
                    "sha256": digest,
                    "previous_sha256": before.get(source, ""),
                    "observed_at": when.isoformat(),
                    "status": status,
                    "normative_approved": "false",
                }
            )
        payload = {
            "schema_version": _STATE_SCHEMA,
            "observed_at": when.isoformat(),
            "hashes": now,
        }
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
        with os.fdopen(
            os.open(str(temp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, state_path)
        return tuple(events)
    finally:
        if temp.exists():
            temp.unlink()
        lock.unlink(missing_ok=True)
