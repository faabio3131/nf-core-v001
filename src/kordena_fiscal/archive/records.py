"""Immutable content-addressed fiscal archive with tamper-evident manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol

from kordena_fiscal.domain import ExecutionScope, FiscalDomainError, FiscalValidationError


class ArchiveConflictError(FiscalDomainError):
    """Raised when an immutable archive identity is reused with different content."""


class ArchiveIntegrityError(FiscalDomainError):
    """Raised when archived content or its manifest fails integrity verification."""


class FiscalArchiveKind(StrEnum):
    AUTHORIZED_XML = "authorized_xml"
    AUTHORIZATION_PROTOCOL = "authorization_protocol"
    FISCAL_EVENT = "fiscal_event"
    PROVIDER_RESPONSE = "provider_response"
    DANFE = "danfe"
    AUXILIARY_PDF = "auxiliary_pdf"  # virtual rendering, not fiscal evidence
    OTHER = "other"


def _required(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_sha256(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise FiscalValidationError(f"{field_name} must be SHA-256 hex")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise FiscalValidationError(f"{field_name} must be hexadecimal") from exc
    return normalized


@dataclass(frozen=True, slots=True)
class RetentionPolicyMetadata:
    """Policy metadata only; legal retention periods are configured outside the engine."""

    policy_id: str
    policy_version: int
    retain_until: datetime | None = None
    legal_basis_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _required(self.policy_id, "policy_id", 128))
        if self.policy_version < 1:
            raise FiscalValidationError("policy_version must be >= 1")
        if self.retain_until is not None:
            _aware(self.retain_until, "retain_until")
        if self.legal_basis_reference is not None:
            reference = _required(
                self.legal_basis_reference,
                "legal_basis_reference",
                512,
            )
            object.__setattr__(self, "legal_basis_reference", reference)


@dataclass(frozen=True, slots=True)
class FiscalArchiveEntry:
    """One immutable fiscal artifact with content-addressed identity."""

    entry_id: str
    scope: ExecutionScope
    document_reference: str
    kind: FiscalArchiveKind
    content: bytes
    content_sha256: str
    media_type: str
    archived_at: datetime
    retention: RetentionPolicyMetadata
    previous_manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _validate_sha256(self.entry_id, "entry_id"))
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        object.__setattr__(
            self,
            "document_reference",
            _required(self.document_reference, "document_reference", 256),
        )
        if not isinstance(self.kind, FiscalArchiveKind):
            raise FiscalValidationError("kind must be FiscalArchiveKind")
        if not isinstance(self.content, bytes) or not self.content:
            raise FiscalValidationError("content must be non-empty bytes")
        digest = _validate_sha256(self.content_sha256, "content_sha256")
        if digest != _sha256(self.content):
            raise FiscalValidationError("content_sha256 does not match content")
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "media_type", _required(self.media_type, "media_type", 128))
        _aware(self.archived_at, "archived_at")
        if not isinstance(self.retention, RetentionPolicyMetadata):
            raise FiscalValidationError("retention must be RetentionPolicyMetadata")
        if self.retention.retain_until is not None:
            if self.retention.retain_until < self.archived_at:
                raise FiscalValidationError("retain_until cannot be before archived_at")
        if self.previous_manifest_sha256 is not None:
            previous = _validate_sha256(
                self.previous_manifest_sha256,
                "previous_manifest_sha256",
            )
            object.__setattr__(self, "previous_manifest_sha256", previous)

    @classmethod
    def build(
        cls,
        *,
        scope: ExecutionScope,
        document_reference: str,
        kind: FiscalArchiveKind,
        content: bytes,
        media_type: str,
        archived_at: datetime,
        retention: RetentionPolicyMetadata,
        previous_manifest_sha256: str | None = None,
    ) -> FiscalArchiveEntry:
        if not isinstance(content, bytes) or not content:
            raise FiscalValidationError("content must be non-empty bytes")
        content_sha256 = _sha256(content)
        material = {
            "tenant_id": scope.tenant_id,
            "unit_id": scope.unit_id,
            "environment": scope.environment.value,
            "document_reference": document_reference.strip(),
            "kind": kind.value,
            "content_sha256": content_sha256,
        }
        if scope.host_namespace is not None:
            material["host_namespace"] = scope.host_namespace
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return cls(
            entry_id=_sha256(encoded),
            scope=scope,
            document_reference=document_reference,
            kind=kind,
            content=content,
            content_sha256=content_sha256,
            media_type=media_type,
            archived_at=archived_at,
            retention=retention,
            previous_manifest_sha256=previous_manifest_sha256,
        )


@dataclass(frozen=True, slots=True)
class FiscalArchiveManifest:
    """Tamper-evident metadata representation of one archive entry."""

    entry_id: str
    scope_partition: tuple[str, ...]
    document_reference: str
    kind: FiscalArchiveKind
    content_sha256: str
    media_type: str
    archived_at: datetime
    retention_policy_id: str
    retention_policy_version: int
    previous_manifest_sha256: str | None
    manifest_sha256: str

    @classmethod
    def from_entry(cls, entry: FiscalArchiveEntry) -> FiscalArchiveManifest:
        if not isinstance(entry, FiscalArchiveEntry):
            raise FiscalValidationError("entry must be FiscalArchiveEntry")
        scope_partition = entry.scope.identity_material
        payload = {
            "entry_id": entry.entry_id,
            "scope_partition": scope_partition,
            "document_reference": entry.document_reference,
            "kind": entry.kind.value,
            "content_sha256": entry.content_sha256,
            "media_type": entry.media_type,
            "archived_at": entry.archived_at.isoformat(),
            "retention_policy_id": entry.retention.policy_id,
            "retention_policy_version": entry.retention.policy_version,
            "previous_manifest_sha256": entry.previous_manifest_sha256,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return cls(
            entry_id=entry.entry_id,
            scope_partition=scope_partition,
            document_reference=entry.document_reference,
            kind=entry.kind,
            content_sha256=entry.content_sha256,
            media_type=entry.media_type,
            archived_at=entry.archived_at,
            retention_policy_id=entry.retention.policy_id,
            retention_policy_version=entry.retention.policy_version,
            previous_manifest_sha256=entry.previous_manifest_sha256,
            manifest_sha256=_sha256(encoded),
        )


class FiscalArchiveStore(Protocol):
    def list_for_scope(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[FiscalArchiveEntry, ...]: ...

    def append(self, entry: FiscalArchiveEntry) -> FiscalArchiveEntry: ...

    def get(self, entry_id: str) -> FiscalArchiveEntry | None: ...

    def list_for_document(
        self,
        scope: ExecutionScope,
        document_reference: str,
    ) -> tuple[FiscalArchiveEntry, ...]: ...


class InMemoryFiscalArchiveStore:
    """Thread-safe immutable reference store; production storage is a private adapter."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, FiscalArchiveEntry] = {}
        self._by_document: dict[tuple[str, ...], list[str]] = {}

    def list_for_scope(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[FiscalArchiveEntry, ...]:
        if not isinstance(scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise FiscalValidationError("limit must be an integer between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
            raise FiscalValidationError("offset must be an integer between 0 and 10000")
        with self._lock:
            rows = sorted(
                (
                    item
                    for item in self._entries.values()
                    if item.scope.identity_material == scope.identity_material
                ),
                key=lambda item: (item.archived_at, item.entry_id),
                reverse=True,
            )
            return tuple(rows[offset : offset + limit])

    def append(self, entry: FiscalArchiveEntry) -> FiscalArchiveEntry:
        if not isinstance(entry, FiscalArchiveEntry):
            raise FiscalValidationError("entry must be FiscalArchiveEntry")
        key = (*entry.scope.identity_material, entry.document_reference)
        with self._lock:
            existing = self._entries.get(entry.entry_id)
            if existing is not None:
                if existing == entry:
                    return existing
                raise ArchiveConflictError(
                    "archive entry identity already exists with other content"
                )
            self._entries[entry.entry_id] = entry
            self._by_document.setdefault(key, []).append(entry.entry_id)
            return entry

    def get(self, entry_id: str) -> FiscalArchiveEntry | None:
        normalized = _validate_sha256(entry_id, "entry_id")
        with self._lock:
            return self._entries.get(normalized)

    def list_for_document(
        self,
        scope: ExecutionScope,
        document_reference: str,
    ) -> tuple[FiscalArchiveEntry, ...]:
        if not isinstance(scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        reference = _required(document_reference, "document_reference", 256)
        key = (*scope.identity_material, reference)
        with self._lock:
            return tuple(self._entries[entry_id] for entry_id in self._by_document.get(key, ()))


class FiscalArchiveVerifier:
    """Verify payload integrity and optional append-chain continuity."""

    def verify_entry(self, entry: FiscalArchiveEntry) -> FiscalArchiveManifest:
        if not isinstance(entry, FiscalArchiveEntry):
            raise FiscalValidationError("entry must be FiscalArchiveEntry")
        if _sha256(entry.content) != entry.content_sha256:
            raise ArchiveIntegrityError("archived content digest mismatch")
        manifest = FiscalArchiveManifest.from_entry(entry)
        _validate_sha256(manifest.manifest_sha256, "manifest_sha256")
        return manifest

    def verify_chain(
        self,
        entries: tuple[FiscalArchiveEntry, ...],
    ) -> tuple[FiscalArchiveManifest, ...]:
        manifests: list[FiscalArchiveManifest] = []
        previous_manifest_sha256: str | None = None
        for entry in entries:
            manifest = self.verify_entry(entry)
            if entry.previous_manifest_sha256 != previous_manifest_sha256:
                raise ArchiveIntegrityError("archive manifest chain is not contiguous")
            manifests.append(manifest)
            previous_manifest_sha256 = manifest.manifest_sha256
        return tuple(manifests)
