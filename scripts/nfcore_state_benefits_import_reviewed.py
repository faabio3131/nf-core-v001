"""Trusted, non-production T09 import of reviewed state ICMS facts and policy.

No external portal, fiscal approval, tax credit, DDL or issuance. The caller is
responsible for the reviewed legal documents and their real source hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path, PurePosixPath

from kordena_fiscal.application.state_benefits_service import (
    import_reviewed_state_benefit,
)
from kordena_fiscal.cognitive.state_benefits_api import build_state_issuer_verifier
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase

SOURCE_MANIFEST_SCHEMA = "nfcore.t09.reviewed-legal-sources/v1"
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def verify_reviewed_source_bytes(
    policy: dict[str, object], manifest_path: Path,
) -> int:
    """Bind cited official URLs/digests to local, actual, immutable source bytes.

    Does not certify a law or reviewer. The manifest and source files remain
    outside version control; this is a non-production import gate only.
    """
    if (
        manifest_path.is_symlink() or not manifest_path.is_file()
        or not 0 < manifest_path.stat().st_size <= 1_048_576
    ):
        raise ValueError("reviewed legal source manifest must be a regular bounded file")
    expected: dict[str, str] = {}
    citations = policy.get("legal_citations")
    if not isinstance(citations, list) or not 1 <= len(citations) <= 10:
        raise ValueError("reviewed state rules require legal source citations")
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError("invalid legal source citation")
        url, digest = citation.get("source_url"), citation.get("source_sha256")
        if (
            not isinstance(url, str) or not url.startswith("https://")
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
        ):
            raise ValueError("invalid legal source URL or digest")
        if url in expected and expected[url] != digest:
            raise ValueError("same legal source URL has conflicting digests")
        expected[url] = digest

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "sources"}
        or manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA
        or not isinstance(manifest.get("sources"), list)
        or len(manifest["sources"]) != len(expected)
    ):
        raise ValueError("invalid reviewed legal source manifest")
    base = manifest_path.parent.resolve(strict=True)
    supplied: set[str] = set()
    for entry in manifest["sources"]:
        if not isinstance(entry, dict) or set(entry) != {
            "source_url", "relative_path",
        }:
            raise ValueError("invalid legal source mapping")
        url, filename = entry["source_url"], entry["relative_path"]
        if (
            not isinstance(url, str) or url not in expected or url in supplied
            or not isinstance(filename, str)
            or not filename or "\\" in filename
        ):
            raise ValueError("missing, extra or duplicate legal source mapping")
        relative = PurePosixPath(filename)
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or not all(re.fullmatch(r"[a-zA-Z0-9._-]+", part) for part in relative.parts)
        ):
            raise ValueError("unsafe legal source file path")
        item = base.joinpath(*relative.parts)
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("symlinked legal source paths are forbidden")
        source = item.resolve(strict=True)
        if base not in source.parents or not source.is_file():
            raise ValueError("legal source must be a local regular file")
        if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
            raise ValueError("invalid legal source byte size")
        digest_actual = hashlib.sha256()
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest_actual.update(chunk)
        if digest_actual.hexdigest() != expected[url]:
            raise ValueError("legal source bytes do not match cited SHA-256")
        supplied.add(url)
    if supplied != expected.keys():
        raise ValueError("reviewed legal source file coverage incomplete")
    return len(supplied)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--source-manifest", required=True, type=Path)
    # A governed internal HMAC receipt must also be included in benefit_content.
    # No signing action is exposed through this import script.
    args = parser.parse_args()
    if os.getenv("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("state ICMS benefit import requires a non-production environment")
    if os.getenv("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("canonical economy persistence must be enabled")
    if args.bundle.is_symlink() or not args.bundle.is_file():
        parser.error("only regular bundle files are accepted")
    if args.bundle.stat().st_size > 1_048_576:
        parser.error("reviewed state ICMS bundle exceeds size limit")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or set(bundle) != {
        "snapshot_id", "snapshot_version", "competence", "issuer_cnpj",
        "content", "benefit_id", "benefit_version", "benefit_content",
    }:
        parser.error("invalid state ICMS bundle shape")
    if not isinstance(bundle["content"], dict) or not isinstance(
        bundle["benefit_content"], dict
    ):
        parser.error("reviewed state ICMS bundle requires fact and policy objects")
    try:
        verify_reviewed_source_bytes(bundle["benefit_content"], args.source_manifest)
    except (ValueError, OSError) as exc:
        parser.error(f"legal source provenance validation failed: {exc}")
    scope = ExecutionScope(
        tenant_id=args.tenant, unit_id=args.unit,
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="state-reviewed-import", host_namespace="fm-nfcore",
    )
    database = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with database() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("canonical unit/environment is not configured")
        with database.economy(scope) as store:
            result = import_reviewed_state_benefit(
                store, snapshot_id=bundle["snapshot_id"],
                snapshot_version=bundle["snapshot_version"],
                competence=date.fromisoformat(bundle["competence"]),
                issuer=Cnpj(bundle["issuer_cnpj"]), content=bundle["content"],
                benefit_id=bundle["benefit_id"],
                benefit_version=bundle["benefit_version"],
                benefit_content=bundle["benefit_content"],
                verify_issuer=build_state_issuer_verifier(database, scope),
                verified_source_bytes=lambda policy: verify_reviewed_source_bytes(
                    policy, args.source_manifest,
                ),
            )
        print(json.dumps({
            "snapshot_id": result["snapshot_id"],
            "snapshot_digest": result["snapshot_digest"],
            "benefit_id": result["benefit_id"],
            "benefit_digest": result["benefit_digest"],
            "status": result["status"],
            "advisory_only": True,
        }, sort_keys=True))
    finally:
        database.close()


if __name__ == "__main__":
    main()
