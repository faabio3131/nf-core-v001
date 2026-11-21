"""Hash locally saved T09 legal-source bytes without claiming legal approval.

Windows: py -3 obter_e_hashear_fontes.py --hash-local
No network access, TLS override, tax import, external reviewer or signatures.
The declared source URL is user-supplied metadata, NOT authenticated provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path

_CAPTURE = run_path(
    str(Path(__file__).resolve().with_name("nfcore_t09_capture_public_evidence.py")),
)
inspect_bytes = _CAPTURE["inspect_bytes"]
official_url = _CAPTURE["official_url"]

_SCHEMA = "nfcore.t09.windows-local-source-kit/v1"
_MAX_BYTES = 32 * 1024 * 1024
_FILENAME = re.compile(r"[A-Z]{2}_[A-Za-z0-9._-]+\.(?:pdf|html|htm)\Z")
_EXPECTED_UFS = {"AC", "AL", "AP", "PA", "PI", "RJ", "RN", "SE"}


def build_manifest(links: dict, source_dir: Path) -> dict:
    if links.get("schema_version") != _SCHEMA:
        raise ValueError("unexpected or outdated links schema")
    entries = links.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 60:
        raise ValueError("invalid source request count")
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("fontes must be a real directory, not a symlink")
    files_seen = set()
    results = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid source row")
        uf = entry.get("uf")
        filename = entry.get("filename")
        url = entry.get("source_url")
        if (
            uf not in _EXPECTED_UFS or not isinstance(filename, str)
            or _FILENAME.fullmatch(filename) is None
            or not filename.startswith(f"{uf}_")
            or filename.casefold() in files_seen
            or (url is not None and (not isinstance(url, str) or not official_url(url)))
        ):
            raise ValueError("untrusted filename, UF, duplicate, or non-official URL")
        files_seen.add(filename.casefold())
        path = source_dir / filename
        result = {
            "uf": uf,
            "candidate_id": entry.get("candidate_id"),
            "document_role": entry.get("document_role"),
            "expected_act": entry.get("expected_act"),
            "filename": filename,
            "declared_source_url": url,
            "review_status": "unreviewed",
            "user_source_attribution_not_independently_verified": True,
            "source_matches_normative_act_verified": False,
            "full_amendment_chain_verified": False,
            "reviewed_by_external_professional": False,
            "import_authorized": False,
            "eligible_for_fiscal_application": False,
        }
        if path.is_symlink():
            result.update(status="rejected",error="symbolic link forbidden")
        elif not path.exists():
            result.update(status="missing")
        elif not path.is_file():
            result.update(status="rejected",error="not a regular file")
        else:
            size = path.stat().st_size
            if size == 0 or size > _MAX_BYTES:
                result.update(status="rejected",error="empty or over 32 MiB")
            else:
                raw = path.read_bytes()
                try:
                    kind = inspect_bytes(raw)
                    expected_kind = (
                        "pdf" if path.suffix.lower() == ".pdf" else "html"
                    )
                    if kind != expected_kind:
                        raise ValueError("extension and bytes format mismatch")
                except ValueError as exc:
                    result.update(status="rejected",error=str(exc)[:180])
                else:
                    result.update(
                        status="bytes_hashed_unreviewed",
                        format_detected=kind,
                        byte_length=size,
                        sha256_real=hashlib.sha256(raw).hexdigest(),
                    )
        results.append(result)
    return {
        "schema_version": "nfcore.t09.local-evidence-manifest/v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "capture_method": "manual_browser_local_files_then_sha256",
        "source_origin_authenticated": False,
        "legal_consolidation_completed": False,
        "independent_external_review_received": False,
        "import_authorized": False,
        "approved_for_tax": False,
        "hashed_count": sum(
            row["status"] == "bytes_hashed_unreviewed" for row in results
        ),
        "missing_count": sum(row["status"] == "missing" for row in results),
        "rejected_count": sum(row["status"] == "rejected" for row in results),
        "sources": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hash-local", action="store_true", required=True,
        help="only read local files; never download or bypass TLS",
    )
    parser.add_argument("--links", type=Path, default=Path("links_validos.json"))
    parser.add_argument("--sources", type=Path, default=Path("fontes"))
    parser.add_argument(
        "--output", type=Path, default=Path("manifesto_sha256_reais.json"),
    )
    args = parser.parse_args()
    if args.links.is_symlink() or not args.links.is_file():
        parser.error("links file missing or symlinked")
    links = json.loads(args.links.read_text(encoding="utf-8"))
    try:
        manifest = build_manifest(links, args.sources)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    # Never mix human evidence with a reviewed-source import manifest.
    if args.output.is_symlink() or args.output.resolve() in {
        args.links.resolve(),
    }:
        parser.error("unsafe output path")
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, args.output)
    print(json.dumps({
        "hashed": manifest["hashed_count"],
        "missing": manifest["missing_count"],
        "rejected": manifest["rejected_count"],
        "manifest": str(args.output),
        "approval": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
