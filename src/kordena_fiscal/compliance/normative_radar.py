"""T03: extend the existing normative watch checkpoint; no fiscal rule authority.

Public source observations are fetched once, not separately per tenant. A scoped
portal projection distributes review alerts, never eligibility or savings claims.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from kordena_fiscal.domain import ExecutionScope

from .normative_watch import ECONOMY_SOURCES, MAX_BYTES, SOURCES, NormativeWatchError

REGISTRY = {**SOURCES, **ECONOMY_SOURCES}
CATEGORIES = {
    "legislacao": r"\b(lei|decreto|portaria|resolucao|instrucao normativa|convenio)\b",
    "anistia": r"\b(anistia|anistias|remissao)\b",
    "refis": r"\b(refis|refis-[a-z]+|recuperacao fiscal)\b",
    "parcelamento": r"\b(parcelamento|parcelamentos|reparcelamento)\b",
    "transacao": r"\b(transacao tributaria|transacao por adesao|edital de transacao)\b",
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
STATE_LIMIT = 524_288
MAX_SIGNALS = 50
MAX_AGE = timedelta(hours=48)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode().split()
    )


class _Headlines(HTMLParser):
    """Extract visible headings/link labels, not scripts, HTML or executable content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: list[str] = []
        self._capture: str | None = None
        self._parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1
        elif not self._ignored and tag in {"a", "h1", "h2", "h3", "h4"} and not self._capture:
            self._capture = tag
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored = max(0, self._ignored - 1)
        elif self._capture == tag and not self._ignored:
            self.labels.append(_normalize(" ".join(self._parts))[:1000])
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture and not self._ignored:
            self._parts.append(data)


def detect_signals(payload: bytes) -> tuple[tuple[str, str], ...]:
    """Keyword signals only. Hash labels rather than storing potentially personal text."""
    parser = _Headlines()
    parser.feed(payload.decode("utf-8", errors="replace"))
    parser.close()
    signals = {
        (kind, _sha(label.encode()))
        for label in parser.labels if label
        for kind, pattern in CATEGORIES.items()
        if re.search(pattern, label)
    }
    return tuple(sorted(signals))[:MAX_SIGNALS]


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise NormativeWatchError("invalid observation timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise NormativeWatchError("invalid observation timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise NormativeWatchError("invalid observation timezone")
    return result.astimezone(UTC)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _load(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
        raise NormativeWatchError("invalid radar state path")
    if not path.exists():
        return {"schema_version": 2, "hashes": {}, "sources": {}, "alerts": {}}
    if not path.is_file() or path.stat().st_size > STATE_LIMIT:
        raise NormativeWatchError("invalid radar state file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise NormativeWatchError("radar state cannot be parsed") from exc
    if not isinstance(data, dict):
        raise NormativeWatchError("invalid radar checkpoint")
    hashes = data.get("hashes")
    if not isinstance(hashes, dict) or not all(
        key in REGISTRY and _is_digest(value) for key, value in hashes.items()
    ):
        raise NormativeWatchError("invalid radar hashes")
    if data.get("schema_version") == 1:
        if set(hashes) != set(SOURCES):
            raise NormativeWatchError("invalid legacy source set")
        return {"schema_version": 2, "hashes": hashes, "sources": {}, "alerts": {}}
    if data.get("schema_version") != 2:
        raise NormativeWatchError("unsupported radar state")
    sources, alerts = data.get("sources"), data.get("alerts")
    if not isinstance(sources, dict) or not isinstance(alerts, dict):
        raise NormativeWatchError("invalid radar records")
    if not set(sources) <= set(REGISTRY) or not set(alerts) <= set(REGISTRY):
        raise NormativeWatchError("unknown radar source")
    _timestamp(data.get("observed_at"))
    for source, status in sources.items():
        if not isinstance(status, dict) or status.get("status") not in {"ok", "unavailable"}:
            raise NormativeWatchError("invalid radar source status")
        _timestamp(status.get("checked_at"))
        if status["status"] == "ok" and source not in hashes:
            raise NormativeWatchError("missing source evidence")
    for source, entries in alerts.items():
        if not isinstance(entries, list) or len(entries) > MAX_SIGNALS + 1:
            raise NormativeWatchError("invalid radar alert list")
        for event in entries:
            if not isinstance(event, dict) or set(event) != {
                "category", "signal_sha256", "source_sha256", "observed_at", "alert_id",
            }:
                raise NormativeWatchError("invalid radar alert")
            if event["category"] not in {*CATEGORIES, "alteracao_portal"} or not all(
                _is_digest(event[key])
                for key in ("signal_sha256", "source_sha256", "alert_id")
            ):
                raise NormativeWatchError("invalid radar evidence")
            if source not in hashes or event["source_sha256"] != hashes[source]:
                raise NormativeWatchError("alert not linked to source checkpoint")
            if event["alert_id"] != _alert_id(
                source, event["category"], event["signal_sha256"], event["source_sha256"],
            ):
                raise NormativeWatchError("radar alert digest mismatch")
            _timestamp(event["observed_at"])
    return data


def _alert_id(source: str, category: str, signal: str, digest: str) -> str:
    return _sha(f"normative-radar/v1:{source}:{category}:{signal}:{digest}".encode())


def poll_radar_locked(
    state_path: Path, temp: Path, fetch: Callable[[str], bytes], when: datetime,
) -> tuple[dict[str, str], ...]:
    """Called only under the original normative_watch cross-process lock."""
    state = _load(state_path)
    hashes: dict[str, str] = dict(state["hashes"])
    alerts: dict[str, list[dict[str, str]]] = dict(state["alerts"])
    statuses: dict[str, dict[str, str]] = {}
    events: list[dict[str, str]] = []
    timestamp = when.astimezone(UTC).isoformat()
    for source, url in REGISTRY.items():
        old = hashes.get(source, "")
        try:
            payload = fetch(url)
            if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BYTES:
                raise NormativeWatchError("invalid portal response")
            digest = _sha(payload)
            signals = detect_signals(payload)
        except (NormativeWatchError, OSError, ValueError):
            statuses[source] = {"status": "unavailable", "checked_at": timestamp}
            events.append({
                "source": source, "url": url, "status": "SOURCE_UNAVAILABLE",
                "sha256": old, "previous_sha256": old, "observed_at": timestamp,
                "normative_approved": "false",
            })
            continue
        statuses[source] = {"status": "ok", "checked_at": timestamp}
        hashes[source] = digest
        changed = old != digest or source not in alerts
        if changed:
            alerts[source] = [
                {
                    "category": category, "signal_sha256": signal,
                    "source_sha256": digest, "observed_at": timestamp,
                    "alert_id": _alert_id(source, category, signal, digest),
                }
                for category, signal in (("alteracao_portal", digest), *signals)
            ]
        events.append({
            "source": source, "url": url, "sha256": digest, "previous_sha256": old,
            "observed_at": timestamp, "normative_approved": "false",
            "status": (
                "FIRST_OBSERVATION_REVIEW_REQUIRED" if not old
                else "PORTAL_CONTENT_CHANGED_REVIEW_REQUIRED" if changed
                else "UNCHANGED"
            ),
        })
    data = {
        "schema_version": 2, "observed_at": timestamp,
        "hashes": hashes, "sources": statuses, "alerts": alerts,
    }
    encoded = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if len(encoded) > STATE_LIMIT:
        raise NormativeWatchError("radar checkpoint size limit exceeded")
    # Public facts only; mount the dedicated directory read-only in the API.
    with os.fdopen(os.open(str(temp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644), "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, state_path)
    return tuple(events)


def project_radar(
    path: Path, scope: ExecutionScope, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Caller must have resolved tenant/unit/environment through canonical Portal auth."""
    state = _load(path)
    checked = now or datetime.now(UTC)
    if checked.tzinfo is None or checked.utcoffset() is None:
        raise NormativeWatchError("invalid projection time")
    statuses = state["sources"]
    scope_key = json.dumps(scope.identity_material, separators=(",", ":"))
    alerts = []
    availability = []
    for source, url in REGISTRY.items():
        status = statuses.get(source)
        age = checked - _timestamp(status["checked_at"]) if status else None
        current = bool(status and status["status"] == "ok" and age is not None
                       and timedelta(0) <= age <= MAX_AGE)
        availability.append({
            "source": source, "url": url,
            "status": "observed" if current else "unavailable_or_stale",
            "checked_at": status["checked_at"] if status else None,
        })
        for event in state["alerts"].get(source, []):
            alerts.append({
                **event, "alert_id": _sha(f"{scope_key}:{event['alert_id']}".encode()),
                "source": source, "source_url": url,
                "jurisdiction": "BR", "status": "review_required",
                "source_current": current, "eligibility_checked": False,
                "normative_approved": False, "fiscal_production_approved": False,
            })
    return {
        "schema_version": "nfcore.normative.radar/v1",
        "tenant_id": scope.tenant_id, "unit_id": scope.unit_id,
        "environment": scope.environment.value,
        "status": "review_required" if all(
            item["status"] == "observed" for item in availability
        ) else "partial_or_unavailable",
        "sources": availability, "alerts": alerts,
        "disclaimer": (
            "Sinais de portais públicos para revisão contábil; não comprovam vigência, "
            "elegibilidade, mudança de lei, desconto ou aprovação fiscal."
        ),
    }
