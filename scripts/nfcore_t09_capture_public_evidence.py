"""Capture T09 public primary-source bytes WITHOUT granting tax eligibility.

A capture is *technical provenance only*. It is never a legal consolidation,
taxpayer concession, independent accountant review, or fiscal approval.
Captured bytes stay in a separate evidence bundle; drafts remain draft.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_BYTES = 32 * 1024 * 1024
ERROR_MARKERS = (
    "captcha", "access denied", "bad gateway", "403 forbidden",
    "404 not found", "502 bad gateway", "service unavailable",
    "site em manutencao", "manutencao em andamento",
    "pagina nao encontrada", "pagina temporariamente indisponivel",
    "acesso negado", "mensagem de bloqueio",
    "bloqueia acessos provenientes", "the requested url was rejected",
    "website is under maintenance",
    "doesn't work properly without javascript enabled",
    "please enable it to continue",
)


# Two exact first-party endpoints verified through the state's legal system
# and STF. Never trust arbitrary *.com.br or arbitrary *.jus.br subdomains.
_EXPLICIT_GOVERNMENT_PUBLISHERS = frozenset({
    "www.ioepa.com.br",  # Pará State Official Gazette, linked by Sisleis/PA
    "portal.stf.jus.br",  # Federal Supreme Court official ADI records
})


def official_url(url: str) -> bool:
    """Permit official HTTPS jurisdictions and exact verified publisher hosts."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    host = u.hostname
    try:
        port = u.port
    except ValueError:
        return False
    return bool(
        u.scheme == "https" and host
        and (
            host == "gov.br"
            or host.endswith((".gov.br", ".leg.br"))
            or host in _EXPLICIT_GOVERNMENT_PUBLISHERS
        )
        and not u.username and not u.password and port in (None, 443)
        and not u.fragment
    )


class PublicSectorRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent redirection to unauthorized hosts before requesting them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise ValueError("redirect outside official HTTPS government domain")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def inspect_bytes(content: bytes) -> str:
    """Conservatively reject error pages even when they hash correctly."""
    if not content or len(content) > MAX_BYTES:
        raise ValueError("empty or oversized official document")
    prefix = content[:65536].lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if prefix.startswith(b"%PDF-"):
        # A prefix is not proof of a complete PDF or a legally effective norm.
        if b"%%EOF" not in content[-8192:]:
            raise ValueError("incomplete PDF trailer")
        return "pdf"
    first = prefix[:4096].lower()
    if b"<html" not in first and b"<!doctype html" not in first:
        raise ValueError("unsupported official document format")
    normalized = html.unescape(prefix.decode("utf-8", errors="ignore")).casefold()
    normalized = "".join(
        ch for ch in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(ch)
    )
    normalized = " ".join(normalized.split())
    if any(marker in normalized for marker in ERROR_MARKERS):
        raise ValueError("HTML maintenance/access/error page")
    if len(content) < 256:
        raise ValueError("HTML response too short to treat as a legal source")
    return "html"


def capture_one(row: dict[str, Any], out: Path, timeout: int) -> dict[str, Any]:
    uf = row["uf"]
    url = row["state_official_source_url"]
    evidence: dict[str, Any] = {
        "uf": uf,
        "candidate_id": row["candidate_id"],
        "source_url": url,
        "status": "unavailable",
        "approved_for_import": False,
        "legal_consolidation_verified": False,
        "taxpayer_concession_verified": False,
        "independent_fiscal_review": False,
    }
    if not official_url(url):
        evidence["error"] = "non-official or invalid source URL"
        return evidence
    try:
        opener = urllib.request.build_opener(PublicSectorRedirects())
        req = urllib.request.Request(
            url, headers={"User-Agent": "NFCore/1.0 legal-provenance-audit"},
        )
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200 or not official_url(resp.url):
                raise ValueError("non-200 or non-official final source")
            data = resp.read(MAX_BYTES + 1)
            kind = inspect_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            filename = f"{uf}-{digest[:16]}.{kind}"
            # One immutable name per digest. Never trust remote filenames.
            destination = out / "sources" / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ValueError("immutable evidence filename conflict")
            else:
                destination.write_bytes(data)
            evidence.update({
                "status": "captured_unreviewed",
                "final_url": resp.url,
                "content_type_reported": resp.headers.get("Content-Type", ""),
                "format_detected": kind,
                "source_sha256": digest,
                "size_bytes": len(data),
                "relative_path": f"sources/{filename}",
                "captured_at_utc": datetime.now(UTC).isoformat(),
            })
    except (ValueError, OSError, urllib.error.URLError, TimeoutError) as exc:
        evidence["error"] = str(exc)[:250]
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=16)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    if args.timeout < 1 or args.timeout > 120 or not 1 <= args.workers <= 8:
        parser.error("unsafe source download bounds")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    rows = catalog.get("candidates", [])
    if (
        len(rows) != 27 or len({row["uf"] for row in rows}) != 27
        or any(
            row.get("review_status") != "draft"
            or row.get("import_authorized") is not False
            for row in rows
        )
    ):
        parser.error("expected 27 non-authorized state research candidates")
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        entries = list(pool.map(
            lambda row: capture_one(row, out, args.timeout), rows,
        ))
    entries.sort(key=lambda row: row["uf"])
    manifest = {
        "schema_version": "nfcore.t09.public-source-capture/v1",
        "purpose": "Technical byte preservation only: no fiscal or legal approval",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "catalog_schema": catalog.get("schema_version"),
        "complete_state_benefit_coverage": False,
        "import_authorized": False,
        "review_required": True,
        "captured_count": sum(row["status"] == "captured_unreviewed" for row in entries),
        "unavailable_count": sum(row["status"] != "captured_unreviewed" for row in entries),
        "sources": entries,
    }
    manifest_path = out / "capture_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    archive = out / "nfcore_t09_official_source_evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(manifest_path, "capture_manifest.json")
        for row in entries:
            if row["status"] == "captured_unreviewed":
                z.write(out / row["relative_path"], row["relative_path"])
    print(json.dumps({
        "captured": manifest["captured_count"],
        "unavailable": manifest["unavailable_count"],
        "evidence_bundle": str(archive),
        "legal_approval": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
