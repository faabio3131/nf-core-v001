"""Verify the user's T09 evidence archive against the Git-reviewed receipt.

Integrity and identity checks only. This cannot establish official publication,
legal effectiveness, entitlement, or authorize any fiscal calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

_RECEIPT = (
    Path(__file__).resolve().parents[1]
    / "docs/NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json"
)
_INNER_MANIFEST = "NFCORE_T09_RECEBIMENTO_FINAL_50_DOCUMENTOS_20261122.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(data)
    return hasher.hexdigest()


def _index(rows: Any, name: str) -> dict[tuple[str, str], dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != 50:
        raise ValueError(f"{name}: expected 50 captures")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError(f"{name}: invalid row")
        key = item.get("uf"), item.get("nome")
        if not all(isinstance(v, str) and v for v in key) or key in indexed:
            raise ValueError(f"{name}: duplicate/invalid evidence identity")
        if not _SHA.fullmatch(str(item.get("sha256", ""))):
            raise ValueError(f"{name}: invalid SHA-256")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise ValueError(f"{name}: invalid byte count")
        indexed[key] = item
    return indexed


def verify_archive(archive: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on altered, unexpected or misidentified evidence files."""
    expected_zip = receipt.get("consolidated_archive", {})
    sha = expected_zip.get("sha256")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ValueError("missing authentic baseline archive SHA-256")
    if _sha256(archive) != sha:
        raise ValueError("whole archive SHA-256 mismatch")
    expected = _index(receipt["files"], "git receipt")
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP entry")
        if any(
            name.startswith("/")
            or "\\" in name
            or ".." in PurePosixPath(name).parts
            for name in names
        ):
            raise ValueError("unsafe ZIP entry path")
        if bundle.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        inside = json.loads(bundle.read(_INNER_MANIFEST).decode("utf-8"))
        manifest = _index(inside["arquivos"], "archive receipt")
        if set(expected) != set(manifest):
            raise ValueError("receipt identities differ")
        for key, item in expected.items():
            archived = manifest[key]
            if item["sha256"] != archived["sha256"] or item["bytes"] != archived["bytes"]:
                raise ValueError(f"archive receipt mismatch: {key}")
            if archived.get("fonte_primaria_autenticada") is not False:
                raise ValueError(f"false legal source authentication: {key}")
            if archived.get("curadoria_aceita") is not False:
                raise ValueError(f"false legal acceptance: {key}")
            if archived.get("importacao_permitida") is not False:
                raise ValueError(f"false fiscal import authorization: {key}")
            path = f"capturas_recentes/{key[0]}/{key[1]}"
            source = bundle.read(path)
            if len(source) != item["bytes"] or hashlib.sha256(source).hexdigest() != item["sha256"]:
                raise ValueError(f"evidence corrupted: {key}")
        paths = {
            name for name in names
            if name.startswith("capturas_recentes/") and not name.endswith("/")
        }
        expected_paths = {f"capturas_recentes/{uf}/{name}" for uf, name in expected}
        if paths != expected_paths:
            raise ValueError("unmanifested/absent captured evidence")
    return {
        "schema_version": "nfcore.t09.local-archive-integrity/v1",
        "archive_sha256": sha,
        "evidence_files_verified": len(expected),
        "integrity": "PASS",
        "authenticity_of_official_publication_certified": False,
        "normative_curation_certified": False,
        "fiscal_import_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
        report = verify_archive(args.archive, receipt)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        parser.exit(1, f"T09 archive check FAILED: {e}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
