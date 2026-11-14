#!/usr/bin/env python3
"""Cross-validate current Jundiai XML serializers against official published XSD.

No municipality, user credentials, signed certificates or network transaction.
This is NOT equivalent to HTTP/DB E2E or live municipal homologation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import runpy

from lxml import etree

from kordena_fiscal.gateway.jundiai_giss_cancellation_builder import build_jundiai_cancel_xml
from kordena_fiscal.gateway.jundiai_giss_issue_builder import build_jundiai_giss_issue_xml
from kordena_fiscal.gateway.jundiai_giss_rps_query_builder import build_jundiai_rps_query
from kordena_fiscal.gateway.jundiai_giss_request_builder import build_jundiai_original_rps_query_xml
from kordena_fiscal.domain import TaxRegimeCode

ROOT = Path("contracts/official/jundiai/giss_v2_04")
MANIFEST = ROOT / "manifest.json"
PARSER = etree.XMLParser(no_network=True, load_dtd=False,
                         resolve_entities=False, huge_tree=False)


def fixture(path: str) -> dict:
    return runpy.run_path(str(Path("tests/gateway") / path))


def real_schema(manifest: dict, basename: str) -> etree.XMLSchema:
    matches = [s for s in manifest["schemas"]
               if Path(s["path"]).name == basename]
    if len(matches) != 1:
        raise ValueError(f"Official XSD missing/ambiguous: {basename}")
    chosen = matches[0]
    path = ROOT / chosen["path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != chosen["sha256"]:
        raise ValueError(f"XSD SHA mismatch: {basename}")
    return etree.XMLSchema(etree.parse(str(path), parser=PARSER))


def audit_case(name: str, xml: bytes, schema: etree.XMLSchema) -> dict:
    root = etree.fromstring(xml, parser=PARSER)
    is_valid = schema.validate(root)
    item = {
        "operation": name,
        "root_qname": root.tag,
        "xml_sha256": hashlib.sha256(xml).hexdigest(),
        "official_xsd_valid": is_valid,
    }
    if not is_valid:
        item["errors"] = [str(e) for e in schema.error_log][:12]
    print(f"ACTUAL_SERIALIZER_{name} {'PASS' if is_valid else 'FAIL'}")
    if item.get("errors"):
        for message in item["errors"][:5]:
            print("  XSD_ERROR " + message[:500])
    # Negative verification: an alien root cannot pass the official schema.
    alien = etree.Element("{urn:nfcore-negative}NotAnOfficialGissElement")
    if schema.validate(alien):
        raise ValueError("Official XMLSchema accepted an invalid foreign root")
    return item


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    issue = fixture("test_jundiai_giss_issue_builder.py")
    cancel = fixture("test_jundiai_giss_cancellation_builder.py")
    query = fixture("test_jundiai_giss_rps_query_builder.py")
    original = issue["_original"]()
    request = issue["_request"](original)
    fields = issue["_fields"]()
    result = []

    issuance = build_jundiai_giss_issue_xml(
        request=request, original=original, fields=fields,
    )
    result.append(audit_case(
        "RECEPCIONAR_LOTE_RPS", issuance,
        real_schema(manifest, "enviar-lote-rps-envio-v2_04.xsd"),
    ))

    rtc_fields = replace(
        fields, operation_indicator="050101", rtc_cst="000",
        rtc_classification="000001", rtc_fin_nfse="0",
        rtc_ind_dest="0", rtc_incidence_ibge="3525904",
        rtc_taxable_base=Decimal("145.00"), rtc_ind_final="0",
        rtc_government_reduction_percent=Decimal("0.00"),
    )
    rtc_xml = build_jundiai_giss_issue_xml(
        request=request, original=original, fields=rtc_fields,
    )
    result.append(audit_case(
        "RECEPCIONAR_LOTE_RPS_RTC_2026", rtc_xml,
        real_schema(manifest, "enviar-lote-rps-envio-v2_04.xsd"),
    ))

    cancellation = build_jundiai_cancel_xml(**cancel["_fields"]())
    result.append(audit_case(
        "CANCELAR_NFSE", cancellation,
        real_schema(manifest, "cancelar-nfse-envio-v2_04.xsd"),
    ))

    qsource = query["_original"]()
    rps_query = build_jundiai_rps_query(
        qsource, TaxRegimeCode.NORMAL, municipal_registration="1234567",
    )
    result.append(audit_case(
        "CONSULTAR_NFSE_POR_RPS", rps_query.signed_xml,
        real_schema(manifest, "consultar-nfse-rps-envio-v2_04.xsd"),
    ))
    alternate_query_xml = build_jundiai_original_rps_query_xml(
        original=qsource, municipal_registration="1234567",
    )
    result.append(audit_case(
        "CONSULTAR_NFSE_RPS_ALTERNATE_BUILDER", alternate_query_xml,
        real_schema(manifest, "consultar-nfse-rps-envio-v2_04.xsd"),
    ))
    good = sum(1 for item in result if item["official_xsd_valid"])
    report = {
        "type": "actual-current-code-vs-official-jundiai-public-XSD",
        "source_rar_sha256": manifest["sources"]["schemas-servicos-prestados.rar"]["sha256"],
        "checked": len(result),
        "compatible": good,
        "incompatible": len(result) - good,
        "operations": result,
        "not_checked": [
            "Actual WSDL/SOAPAction (mTLS authentication required)",
            "Signed SOAP request response against live municipality",
            "Persistence, retry, timeout and HTTP/DB E2E",
            "SubstituirNfse (not implemented in reviewed method map)",
        ],
    }
    (ROOT / "xml-compatibility.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"ACTUAL_XML_COMPATIBILITY_SUMMARY={good}/{len(result)}")
    if good != len(result):
        raise SystemExit("FAIL: Jundiai existing XML is incompatible with official XSD")


if __name__ == "__main__":
    main()
