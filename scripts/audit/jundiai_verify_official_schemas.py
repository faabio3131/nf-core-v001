#!/usr/bin/env python3
"""Offline, reproducible cryptographic and XMLSchema compilation audit.

Uses the bytes captured from Jundiai's official published RAR, never samples or
schemas from another municipality. Does not infer unavailable WSDL SOAPActions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

ROOT = Path("contracts/official/jundiai/giss_v2_04")
MANIFEST = ROOT / "manifest.json"
PARSER = etree.XMLParser(no_network=True, load_dtd=False,
                         resolve_entities=False, huge_tree=False)
XSD = "{http://www.w3.org/2001/XMLSchema}"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("municipality_ibge") != "3525904":
        raise SystemExit("FAIL: unexpected municipality")
    schemas = manifest.get("schemas")
    if not isinstance(schemas, list) or len(schemas) < 20:
        raise SystemExit("FAIL: incomplete public schema package")
    results = []
    for item in schemas:
        path = ROOT / item["path"]
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise SystemExit("FAIL: invalid schema path")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise SystemExit(f"FAIL: official XSD SHA mismatch: {path.name}")
        report = {"file": path.name, "sha256": digest, "compiled": False}
        try:
            tree = etree.parse(str(path), parser=PARSER)
            if tree.getroot().tag != XSD + "schema":
                raise ValueError("not a schema")
            schema = etree.XMLSchema(tree)
            for elem in tree.getroot().findall(XSD + "element"):
                name = elem.get("name")
                if name:
                    ns = tree.getroot().get("targetNamespace", "")
                    xml = etree.Element(f"{{{ns}}}DefinitelyNotAnOfficialElement")
                    if schema.validate(xml):
                        raise ValueError("invalid XML was incorrectly accepted")
            report["compiled"] = True
        except (OSError, ValueError, etree.XMLSchemaError,
                etree.XMLSyntaxError) as exc:
            report["failure_type"] = type(exc).__name__
            report["failure_detail"] = str(exc)[:500]
        results.append(report)
        print(f"SCHEMA_VERIFY {path.name} "
              f"{'PASS' if report['compiled'] else 'FAIL'} "
              f"{report.get('failure_detail', '')}")
    successful = sum(row["compiled"] for row in results)
    summary = {
        "municipality_ibge": "3525904",
        "kind": "official-public-XSD-compilation",
        "files_verified": len(results),
        "compiled": successful,
        "failed": len(results) - successful,
        "results": results,
        "does_not_certify": ["WSDL SOAPAction", "authenticated mTLS",
                              "municipal operation semantics", "HTTP/DB E2E"],
    }
    (ROOT / "schema-validation.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"SCHEMA_VERIFICATION_SUMMARY={successful}/{len(results)}")
    if successful != len(results):
        raise SystemExit("FAIL: official XSD compilation requires engineering review")


if __name__ == "__main__":
    main()
