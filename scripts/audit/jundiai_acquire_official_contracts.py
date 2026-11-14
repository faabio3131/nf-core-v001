#!/usr/bin/env python3
"""Acquire and inventory publicly published official Jundiai GissOnline contracts.

No taxpayer data or certificates are used. This is provenance collection, NOT
a substitute for an mTLS-authenticated WSDL audit or fiscal E2E certification.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = "https://jundiai.giss.com.br/giss-ajuda/manuais/"
PUBLIC = {
    "schemas-servicos-prestados.rar": BASE + "Schemas_XSD-Servicos_Prestados.rar",
    "manual-servicos-prestados-v1.8.pdf": BASE
        + "Manual%20T%C3%A9cnico%20-%20Servi%C3%A7os%20Prestados%20-%20V1.8.pdf",
    "manual-servicos-prestados-retorno-v1.0.pdf": BASE
        + "Manual%20T%C3%A9cnico%20-%20Servi%C3%A7os%20Prestados%20-%20Retorno%20-%20%20V1.0.pdf",
    "referencia-conceitual-abrasf-2.04.pdf": BASE
        + "NFS-e_Manual_de_Orienta%C3%A7%C3%A3o_do_Contribuinte_-_2.04.pdf",
}
# Baseline downloaded on 2026-11-14 from the official portal, not generated
# from simulator fixtures. Unexpected upstream changes require human review.
EXPECTED_SOURCE_SHA256 = {
    "schemas-servicos-prestados.rar": (
        "c14a542de5fa2ce1a6a2b43da6e4eb0bebab12e6ebc850fe24dbdc8f6bb04356"
    ),
    "manual-servicos-prestados-v1.8.pdf": (
        "cdf8095944bbe0308d7df11a9632da78cba85b1daa3973dfdd51a86f9b4b58fd"
    ),
    "manual-servicos-prestados-retorno-v1.0.pdf": (
        "8becda8d0a97a34fe938baef6709dd8bee7867c40cc4defc54b775d670fd0db1"
    ),
    "referencia-conceitual-abrasf-2.04.pdf": (
        "d6ac7c1237a9064042df63bb7af2b539676f8b3589bdfb3fea8378a1b2f10bb9"
    ),
}

WSDL = {
    "production": "https://ws-jundiai.giss.com.br/service-ws/nf/nfse-ws?wsdl",
    "homologation": "https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl",
}
MAX_FETCH = 30 * 1024 * 1024
ROOT = Path("contracts/official/jundiai/giss_v2_04")
XSD_NS = "{http://www.w3.org/2001/XMLSchema}"
WSDL_NS = "{http://schemas.xmlsoap.org/wsdl/}"
SOAP_NS = "{http://schemas.xmlsoap.org/wsdl/soap/}"


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch(url: str, *, expected_host: str) -> bytes:
    req = Request(url, headers={"User-Agent": "NFCore-Jundiai-Official-Audit/1.0"})
    with urlopen(req, timeout=35) as response:
        target = urlparse(response.geturl())
        if target.scheme != "https" or target.hostname != expected_host:
            raise ValueError(f"Unapproved redirect for {expected_host}")
        data = response.read(MAX_FETCH + 1)
    if not data or len(data) > MAX_FETCH:
        raise ValueError("Empty or oversized official file")
    return data


def schema_inventory(folder: Path) -> tuple[list[dict], list[dict]]:
    found = sorted(folder.rglob("*"))
    if len(found) > 500 or any(p.is_symlink() for p in found):
        raise ValueError("Unsafe schema extraction tree")
    files = [p for p in found if p.is_file()]
    if len(files) > 200 or sum(p.stat().st_size for p in files) > 50 * 1024 * 1024:
        raise ValueError("Unreasonable schema package size")
    schemas = [p for p in files if p.suffix.lower() == ".xsd"]
    if not schemas:
        raise ValueError("Official archive did not contain XSD schemas")
    inventory = []
    unresolved = []
    for path in schemas:
        raw = path.read_bytes()
        root = ET.fromstring(raw)
        if root.tag != XSD_NS + "schema":
            raise ValueError(f"Not an XML Schema: {path.name}")
        includes = []
        for node in root.iter():
            if node.tag not in {
                XSD_NS + "include", XSD_NS + "import", XSD_NS + "redefine",
            }:
                continue
            location = node.get("schemaLocation")
            if not location:
                continue
            includes.append(location)
            parsed = urlparse(location)
            if parsed.scheme or location.startswith("/") or ".." in Path(location).parts:
                unresolved.append({"file": str(path.relative_to(folder)),
                                   "schemaLocation": location})
                continue
            resolved = (path.parent / location).resolve()
            if not resolved.is_relative_to(folder.resolve()) or not resolved.is_file():
                unresolved.append({"file": str(path.relative_to(folder)),
                                   "schemaLocation": location})
        inventory.append({
            "path": str(path.relative_to(ROOT)).replace(os.sep, "/"),
            "sha256": sha(raw),
            "size_bytes": len(raw),
            "target_namespace": root.get("targetNamespace"),
            "schema_dependencies": includes,
        })
    return inventory, unresolved


def probe_wsdl(folder: Path) -> dict:
    results = {}
    folder.mkdir(parents=True, exist_ok=True)
    for env, url in WSDL.items():
        host = urlparse(url).hostname
        assert host is not None
        row = {"source_url": url, "captured": False}
        try:
            raw = fetch(url, expected_host=host)
            root = ET.fromstring(raw)
            if root.tag != WSDL_NS + "definitions":
                raise ValueError("Response is not WSDL definitions")
            operations = []
            for binding in root.findall(WSDL_NS + "binding"):
                for op in binding.findall(WSDL_NS + "operation"):
                    soap = op.find(SOAP_NS + "operation")
                    operations.append({"name": op.get("name"),
                                       "soap_action": None if soap is None
                                       else soap.get("soapAction")})
            out = folder / f"{env}.wsdl"
            out.write_bytes(raw)
            row.update({"captured": True, "sha256": sha(raw),
                        "target_namespace": root.get("targetNamespace"),
                        "operations": operations,
                        "size_bytes": len(raw)})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError,
                ET.ParseError) as exc:
            row["capture_error_type"] = type(exc).__name__
            if isinstance(exc, HTTPError):
                row["http_status"] = exc.code
            row["needs_authenticated_contract_verification"] = True
        results[env] = row
    return results


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nfcore-jundiai-") as temp:
        tmp = Path(temp)
        sources = {}
        for name, url in PUBLIC.items():
            raw = fetch(url, expected_host="jundiai.giss.com.br")
            if name.endswith(".pdf") and not raw.startswith(b"%PDF"):
                raise ValueError(f"{name}: official PDF signature missing")
            if name.endswith(".rar") and not raw.startswith(b"Rar!\x1a\x07"):
                raise ValueError("Official schema download is not a RAR archive")
            digest = sha(raw)
            if digest != EXPECTED_SOURCE_SHA256[name]:
                raise ValueError("Official source drift requires independent review: " + name)
            (tmp / name).write_bytes(raw)
            sources[name] = {"url": url, "sha256": digest,
                             "size_bytes": len(raw),
                             "redistributed_in_git": False}
        extracted = ROOT / "xsd"
        extracted.mkdir(exist_ok=True)
        archive = tmp / "schemas-servicos-prestados.rar"
        extractor = shutil.which("unar")
        if not extractor:
            raise RuntimeError("unar extractor required on GitHub runner")
        proc = subprocess.run(
            [extractor, "-quiet", "-force-overwrite", "-output-directory",
             str(extracted), str(archive)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if proc.returncode:
            raise RuntimeError("Official RAR extraction failed: "
                               + proc.stderr[:300])
        inventory, unresolved = schema_inventory(extracted)
        wsdl = probe_wsdl(ROOT / "wsdl")
        manifest = {
            "municipality": "Jundiai/SP",
            "municipality_ibge": "3525904",
            "official_publisher": "GissOnline portal for Jundiai",
            "official_developers_index":
                "https://jundiai.giss.com.br/giss-ajuda/desenvolvedores.html",
            "acquisition_method": "HTTPS exact URLs; SHA256 of downloaded bytes",
            "sources": sources,
            "schemas": inventory,
            "schema_dependency_unresolved": unresolved,
            "wsdl": wsdl,
            "wsdl_status": ("BOTH_CAPTURED" if all(v["captured"]
                            for v in wsdl.values()) else "MTLS_VERIFICATION_REQUIRED"),
            "contract_validation_status": "NOT_CERTIFIED",
            "limitations": [
                "No A1/ICP-Brasil client certificate supplied to WSDL acquisition",
                "Official XSD presence does not certify municipal XML or SOAP actions",
                "Authenticated HTTP/DB E2E and substitution still require independent tests",
            ],
        }
        (ROOT / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"OFFICIAL_SOURCE_DOWNLOADS={len(sources)}")
        print(f"OFFICIAL_XSD_FILES={len(inventory)}")
        print(f"UNRESOLVED_SCHEMA_IMPORTS={len(unresolved)}")
        print(f"OFFICIAL_WSDL_STATUS={manifest['wsdl_status']}")
        for name, record in sources.items():
            print(f"OFFICIAL_SHA256 {name} {record['sha256']}")
        for name, row in wsdl.items():
            print(f"OFFICIAL_WSDL {name} captured={row['captured']} "
                  f"sha256={row.get('sha256', 'NOT_ACQUIRED')}")


if __name__ == "__main__":
    main()
