"""Loader for official NCM and cClassTrib tables shipped with a SHA-256 manifest.

The data files are derived from official public sources (see ``official/manifest.json``).
They are integrity-checked at load time: a file whose SHA-256 differs from the manifest is
refused, so a corrupted or tampered table can never silently feed advice. The tables keep
``PENDING_NORMATIVE_REVIEW``: official origin and integrity are proven, human review is not.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from kordena_fiscal.domain import FiscalValidationError

from .classification import (
    CatalogEntry,
    CatalogKind,
    ClassificationCatalog,
    default_classification_catalog,
)

OFFICIAL_DIR = Path(__file__).parent / "official"
_SCHEMA = "nfcore.cognitive.official-tables/v1"


class OfficialTablesError(FiscalValidationError):
    """Official tables are missing, malformed or fail their integrity check."""


def _read_verified(directory: Path, spec: dict[str, Any]) -> list[list[str]]:
    path = directory / str(spec["file"])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OfficialTablesError(f"official table unreadable: {path.name}") from exc
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise OfficialTablesError(f"official table failed SHA-256 check: {path.name}")
    try:
        entries = json.loads(raw)["entries"]
    except (ValueError, KeyError, TypeError) as exc:
        raise OfficialTablesError(f"official table malformed: {path.name}") from exc
    if not isinstance(entries, list) or len(entries) != spec["rows"]:
        raise OfficialTablesError(f"official table row count mismatch: {path.name}")
    return entries


def read_manifest(directory: Path = OFFICIAL_DIR) -> dict[str, Any]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OfficialTablesError("official tables manifest unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != _SCHEMA:
        raise OfficialTablesError("official tables manifest has an unexpected schema")
    return manifest


def load_official_catalog(directory: Path = OFFICIAL_DIR) -> ClassificationCatalog:
    """Seed catalogs plus the official NCM and cClassTrib tables (integrity-verified)."""
    manifest = read_manifest(directory)
    seed = default_classification_catalog()
    entries: list[CatalogEntry] = [
        e
        for kind in (CatalogKind.CST_ICMS, CatalogKind.CSOSN, CatalogKind.CST_PIS_COFINS)
        for e in seed.entries(kind)
    ]
    try:
        for code, text, start, end in _read_verified(directory, manifest["ncm"]):
            entries.append(
                CatalogEntry(
                    CatalogKind.NCM, code, text, date.fromisoformat(start), date.fromisoformat(end)
                )
            )
        for code, text, cst, cst_text in _read_verified(directory, manifest["cclasstrib"]):
            label = f"{text} (CST {cst} — {cst_text})" if cst else text
            entries.append(CatalogEntry(CatalogKind.CCLASSTRIB, code, label))
        ncm_ver = manifest["ncm"]["source_vigencia"]
        cc_ver = manifest["cclasstrib"]["source_version"]["versaoDb"]
    except OfficialTablesError:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise OfficialTablesError("official tables content invalid") from exc
    return ClassificationCatalog(
        entries, version=f"{seed.version}+official[ncm:{ncm_ver};cclasstrib:{cc_ver}]"
    )


@lru_cache(maxsize=1)
def cached_official_catalog() -> ClassificationCatalog:
    return load_official_catalog()
