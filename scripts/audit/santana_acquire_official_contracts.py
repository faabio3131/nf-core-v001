#!/usr/bin/env python3
"""Capture Santana's public Simpliss schema archive with SHA-256 provenance.

This is official-source acquisition only, not a fiscal authorization or mTLS test.
The original archive remains in the CI artifact; Git stores only public XSDs
and a deterministic manifest. Never use taxpayer credentials here.
"""
from __future__ import annotations

import hashlib
import io
import json
import stat
import xml.etree.ElementTree as ET
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

LANDING = (
    "https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/"
    "DocumentoIntegracaoNotaNacional/Index"
)
SOURCE = (
    "https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/"
    "DocumentoIntegracaoNotaNacional/DownloadArquivo?nomeDocumento="
)
DOCUMENTS = {
    "schemas": ("nfse-esquemas_xsd-anexos_i_ii_iv-sefin_adn-prod-v1-00-20251210", "PK"),
    "manual": ("manual_integracao_nota_nacional_-_simpliss_v1.00", "%PDF"),
    "layout_rtc": ("AnexoVI-LeiautesRN_RTC_IBSCBS-V1.01.01_Simpliss", "PK"),
    "layout_dps": ("ANEXO_I-SEFIN_ADN-DPS_NFSe-SNNFSe_Simpliss", "PK"),
    "layout_event": ("ANEXO_II-SEFIN_ADN-PEDREGEVT_EVT-SNNFSe_Simpliss", "PK"),
}
ROOT = Path("contracts/official/santana/simpliss_2026")
MAX_DOWNLOAD = 30 * 1024 * 1024
XSD_TAG = "{http://www.w3.org/2001/XMLSchema}schema"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_OPENER = build_opener(HTTPCookieProcessor(CookieJar()))
_SESSION_READY = False


def download(name: str) -> bytes:
    global _SESSION_READY
    if not _SESSION_READY:
        landing = Request(LANDING, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NFCore-OfficialContractAudit/1.0)",
            "Accept": "text/html",
        })
        with _OPENER.open(landing, timeout=35) as response:
            html = response.read(2_097_153)
            print(
                "SIMPLISS_LANDING_STATUS=" + str(response.status),
                "BYTES=" + str(len(html)),
            )
            if (
                b"Manuais de Nota Fiscal" not in html
                or len(html) > 2_097_152
            ):
                raise ValueError("Municipal official source page is unverified")
        _SESSION_READY = True
    url = SOURCE + quote(name)
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; NFCore-OfficialContractAudit/1.0)",
        "Referer": LANDING,
        "Accept": "application/zip, application/pdf, application/vnd.openxmlformats-"
                  "officedocument.spreadsheetml.sheet, */*",
    })
    with _OPENER.open(request, timeout=35) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "santanadeparnaiba.simplissweb.com.br":
            raise ValueError("Unexpected official redirect")
        data = response.read(MAX_DOWNLOAD + 1)
        print(
            "SIMPLISS_DOWNLOAD_STATUS=" + str(response.status),
            "CONTENT_TYPE=" + str(response.headers.get("Content-Type")),
            "BYTES=" + str(len(data)),
        )
        if not data or len(data) > MAX_DOWNLOAD:
            raise ValueError("Official file size invalid")
        return data


def extract_schemas(blob: bytes) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        if len(entries) > 250:
            raise ValueError("Excessive official archive entries")
        total = 0
        for member in entries:
            if member.is_dir():
                continue
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if (
                path.is_absolute() or not path.parts
                or ".." in path.parts
                or any(part in ("", ".") for part in path.parts)
                or (member.external_attr >> 16) & stat.S_IFMT(0o170000) == stat.S_IFLNK
            ):
                raise ValueError("Unsafe archive filename")
            if path.suffix.lower() != ".xsd":
                continue
            target = ROOT / "xsd" / path
            key = str(path).lower()
            if key in seen or member.file_size > 4 * 1024 * 1024:
                raise ValueError("Duplicate or oversized official XSD")
            seen.add(key)
            total += member.file_size
            if total > 25 * 1024 * 1024:
                raise ValueError("Oversized official XSD package")
            data = archive.read(member)
            parsed = ET.fromstring(data)
            if parsed.tag != XSD_TAG:
                raise ValueError("Non-schema document in official XSD archive")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            result.append({
                "path": str(target).replace("\\", "/"),
                "size_bytes": len(data),
                "sha256": digest(data),
                "target_namespace": parsed.get("targetNamespace"),
            })
    if not result:
        raise ValueError("Official archive contained no XSD files")
    return sorted(result, key=lambda x: str(x["path"]))


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict[str, object]] = {}
    schema_blob = b""
    for alias, (name, header) in DOCUMENTS.items():
        content = download(name)
        if not content.startswith(header.encode()):
            raise ValueError("Unexpected official document type: " + alias)
        sources[alias] = {
            "source_url": SOURCE + quote(name),
            "sha256": digest(content),
            "size_bytes": len(content),
            "redistributed_in_git": False,
        }
        if alias == "schemas":
            schema_blob = content
    # GitHub artifact contains original public source material and exact checksum;
    # the repo stores only XML/XSD files and the manifest (no private evidence).
    (ROOT / "source-schemas.zip").write_bytes(schema_blob)
    schemas = extract_schemas(schema_blob)
    manifest = {
        "municipality_ibge": "3547304",
        "municipality": "Santana de Parnaiba/SP",
        "provider": "Simpliss",
        "source_kind": "municipal_contributor_portal",
        "retrieved_via": "HTTPS public DownloadArquivo",
        "sources": sources,
        "schemas": schemas,
        "status": "SOURCE_ACQUIRED_NOT_EXTERNAL_HOMOLOGATION",
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("SANTANA_OFFICIAL_SCHEMA_COUNT=" + str(len(schemas)))
    for alias, row in sources.items():
        print("SANTANA_SOURCE_SHA256 " + alias + " " + str(row["sha256"]))


if __name__ == "__main__":
    main()
