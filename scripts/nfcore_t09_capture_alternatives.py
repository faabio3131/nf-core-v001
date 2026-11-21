"""Run a provenance-only trial for additional official T09 state sources.

Never imports benefit rules or changes draft/review/signature status. Reuses the
canonical capture_one implementation and preserves source-type annotations.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from typing import Any

_CAPTURE = run_path(
    str(Path(__file__).resolve().with_name("nfcore_t09_capture_public_evidence.py")),
)
capture_one = _CAPTURE["capture_one"]
official_url = _CAPTURE["official_url"]

EXPECTED_UFS = frozenset({"AC", "AL", "AP", "PA", "PI", "RJ", "RN", "SE"})
SOURCE_SCHEMA = "nfcore.t09.official-alternative-source-trial/v1"


def verify_workset(
    catalog: dict[str, Any], data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ensure an alternate URL cannot become a new tax authority."""
    if data.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError("unsupported alternative source schema")
    if data.get("authorized_for_import") is not False:
        raise ValueError("alternative source trial cannot approve imports")
    if data.get("legal_validity_certified") is not False:
        raise ValueError("alternative source trial cannot certify law")
    if data.get("independent_approval_received") is not False:
        raise ValueError("alternative source trial cannot issue external approval")
    original = catalog.get("candidates")
    if not isinstance(original, list) or len(original) != 27:
        raise ValueError("expected the full canonical 27-UF draft catalog")
    known = {item["uf"]: item for item in original}
    if len(known) != 27 or not EXPECTED_UFS.issubset(known):
        raise ValueError("invalid canonical T09 candidate registry")
    if any(
        row.get("review_status") != "draft"
        or row.get("import_authorized") is not False
        for row in original
    ):
        raise ValueError("canonical candidates are not all non-authorized drafts")
    sources = data.get("entries")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        raise ValueError("invalid alternative source set")
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid alternate source")
        uf, url = source.get("uf"), source.get("source_url")
        if (
            not isinstance(uf, str) or uf not in EXPECTED_UFS
            or source.get("candidate_id") != known[uf]["candidate_id"]
            or not isinstance(url, str) or not official_url(url)
            or url in seen or source.get("review_status") != "unreviewed"
            or source.get("eligible_for_tax_calculation") is not False
            or not isinstance(source.get("source_kind"), str)
            or not source.get("source_kind")
        ):
            raise ValueError("invalid, duplicate or unauthorized alternative source")
        seen.add(url)
    return sources


def capture_alternatives(
    catalog: dict[str, Any], data: dict[str, Any], output: Path,
    *, timeout: int = 18, workers: int = 5,
) -> dict[str, Any]:
    sources = verify_workset(catalog, data)
    if not (1 <= timeout <= 120 and 1 <= workers <= 8):
        raise ValueError("unsafe capture bounds")
    output.mkdir(parents=True, exist_ok=True)

    def capture(source: dict[str, Any]) -> dict[str, Any]:
        row = {
            "uf": source["uf"],
            "candidate_id": source["candidate_id"],
            "state_official_source_url": source["source_url"],
        }
        result = capture_one(row, output, timeout)
        return {
            **result,
            "source_kind": source["source_kind"],
            "verification_note": source.get("verification_note"),
            "review_status": "unreviewed",
            "benefit_eligible": False,
            "matches_target_legal_act": False,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(capture, sources))
    results.sort(key=lambda x: (x["uf"], x["source_url"]))
    manifest = {
        "schema_version": "nfcore.t09.alternate-source-capture/v1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "Public-source byte capture, not legal consolidation",
        "review_required": True,
        "import_authorized": False,
        "independent_legal_approval": False,
        "captured_count": sum(x["status"] == "captured_unreviewed" for x in results),
        "unavailable_count": sum(x["status"] != "captured_unreviewed" for x in results),
        "sources": results,
    }
    manifest_path = output / "alternative_capture_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    bundle = output / "nfcore_t09_official_alternatives_unreviewed.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, manifest_path.name)
        written: set[str] = set()
        for row in results:
            if row["status"] == "captured_unreviewed":
                rel = row["relative_path"]
                if rel not in written:
                    archive.write(output / rel, rel)
                    written.add(rel)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--alternatives", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=18)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    alternatives = json.loads(args.alternatives.read_text(encoding="utf-8"))
    manifest = capture_alternatives(
        catalog, alternatives, args.output, timeout=args.timeout,
        workers=args.workers,
    )
    print(json.dumps({
        "captured": manifest["captured_count"],
        "unavailable": manifest["unavailable_count"],
        "approval": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
