"""Offline audit for ORIGINAL GissOnline Jundiai WSDL and XSD artifacts.

Run on the machine where the official issuer-authorized WSDL and the official
Jundiai GissOnline developer RAR have been obtained. This command does NOT
contact providers, read credentials, or mark a city as homologated.

The output is an unsigned engineering evidence inventory, not a certificate
of municipal authenticity. Independent reviewer must check the provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
from datetime import UTC, datetime
from pathlib import Path

from lxml import etree

from kordena_fiscal.xml.schema import (
    SchemaResource,
    SchemaSet,
    XmlSchemaValidator,
)

WSDL_URL = "https://v2-ws-homologacao.giss.com.br/service-ws/nf/nfse-ws?wsdl"
XSD_URL = (
    "https://jundiai.giss.com.br/giss-ajuda/manuais/"
    "Schemas_XSD-Servicos_Prestados.rar"
)
_WSDL = "{http://schemas.xmlsoap.org/wsdl/}"
_SOAP = "{http://schemas.xmlsoap.org/wsdl/soap/}"
_XSD = "{http://www.w3.org/2001/XMLSchema}"
_GISS = "http://www.giss.com.br/"
_MAX = 2_097_152
_EXPECTED = {
    "RecepcionarLoteRps": (
        "EnviarLoteRpsEnvio", "enviar-lote-rps-envio-v2_04.xsd",
    ),
    "ConsultarLoteRps": (
        "ConsultarLoteRpsEnvio", "consultar-lote-rps-envio-v2_04.xsd",
    ),
    "ConsultarNfsePorRps": (
        "ConsultarNfseRpsEnvio", "consultar-nfse-rps-envio-v2_04.xsd",
    ),
    "CancelarNfse": (
        "CancelarNfseEnvio", "cancelar-nfse-envio-v2_04.xsd",
    ),
    "ConsultarNfseRpsResposta": (
        "ConsultarNfseRpsResposta", "consultar-nfse-rps-resposta-v2_04.xsd",
    ),
    "CancelarNfseResposta": (
        "CancelarNfseResposta", "cancelar-nfse-resposta-v2_04.xsd",
    ),
}


class ContractAuditError(ValueError):
    """Official proof is incomplete or incompatible with the Jundiai runtime."""


def _xml(payload: bytes) -> etree._Element:
    if not 0 < len(payload) <= _MAX or b"<!DOCTYPE" in payload.upper():
        raise ContractAuditError("Unsafe or oversized official XML")
    try:
        root = etree.fromstring(
            payload,
            parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ContractAuditError("Malformed WSDL/XSD XML") from exc
    if root.getroottree().docinfo.doctype:
        raise ContractAuditError("DTD in official WSDL/XSD")
    return root


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ContractAuditError("Official artifact missing or symbolic link")
    size = path.stat().st_size
    if not 0 < size <= _MAX:
        raise ContractAuditError("Official artifact is empty or oversized")
    return path.read_bytes()


def _wsdl_bindings(data: bytes) -> tuple[str, dict[str, str]]:
    root = _xml(data)
    if root.tag != _WSDL + "definitions":
        raise ContractAuditError("Not an official WSDL definitions document")
    namespace = root.get("targetNamespace")
    if not isinstance(namespace, str) or not namespace.startswith("http"):
        raise ContractAuditError("Unrecognized Giss WSDL targetNamespace")
    if root.findall(_WSDL + "import"):
        raise ContractAuditError("Unbundled WSDL imports need independent review")
    endpoints = {
        node.get("location")
        for node in root.findall(".//" + _SOAP + "address")
    }
    if WSDL_URL.removesuffix("?wsdl") not in endpoints:
        raise ContractAuditError("Official WSDL SOAP service endpoint differs")
    actions: dict[str, str] = {}
    for binding in root.findall(_WSDL + "binding"):
        soap11 = binding.find(_SOAP + "binding")
        if soap11 is None or soap11.get("style") not in (None, "document"):
            continue
        for operation in binding.findall(_WSDL + "operation"):
            method = operation.get("name")
            soap = operation.find(_SOAP + "operation")
            if not method or soap is None:
                continue
            action = soap.get("soapAction")
            if (
                not action or not action.startswith("http")
                or any(ch.isspace() for ch in action)
                or (method in actions and actions[method] != action)
            ):
                raise ContractAuditError("Ambiguous SOAPAction in WSDL")
            actions[method] = action
    documented = {
        "CancelarNfse", "RecepcionarLoteRps", "ConsultarLoteRps",
        "ConsultarNfsePorFaixa", "ConsultarNfsePorRps",
        "ConsultarNfseServicoPrestado",
    }
    if not documented.issubset(actions):
        missing = sorted(documented - actions.keys())
        raise ContractAuditError(
            "Documented Giss WSDL methods missing: " + ", ".join(missing)
        )
    required = set(_EXPECTED) - {
        "ConsultarNfseRpsResposta", "CancelarNfseResposta",
    }
    if not required.issubset(actions):
        missing = sorted(required - actions.keys())
        raise ContractAuditError("Required Giss WSDL methods missing: " + ", ".join(missing))
    return namespace, {name: actions[name] for name in sorted(required)}


def _schema_resources(folder: Path) -> tuple[tuple[SchemaResource, ...], dict[str, str]]:
    if not folder.is_dir() or folder.is_symlink():
        raise ContractAuditError("Missing extracted official XSD directory")
    files = sorted(folder.rglob("*"))
    if not files:
        raise ContractAuditError("Empty official Giss XSD distribution")
    found: dict[str, bytes] = {}
    for item in files:
        if item.is_dir():
            if item.is_symlink():
                raise ContractAuditError("Symlink in XSD distribution")
            continue
        if item.is_symlink() or item.suffix.lower() != ".xsd":
            raise ContractAuditError("Unexpected file in official XSD distribution")
        name = item.relative_to(folder).as_posix()
        # Runtime's SHA-256-pinned source reader intentionally accepts flat,
        # simple filenames only; nested archive imports must be reconciled
        # by a reviewed adapter change rather than silently flattened.
        if "/" in name or name.startswith(".") or name in found:
            raise ContractAuditError("Nested/unsafe XSD requires operator review: " + name)
        found[name] = _read(item)
    if "tipos-v2_04.xsd" not in found:
        raise ContractAuditError("Missing Giss official tipos-v2_04.xsd")
    roots: dict[str, str] = {}
    for filename, payload in found.items():
        root = _xml(payload)
        if root.tag != _XSD + "schema":
            raise ContractAuditError("Non-schema file in official XSD distribution: " + filename)
        ns = root.get("targetNamespace")
        if not isinstance(ns, str):
            raise ContractAuditError("Missing XSD namespace: " + filename)
        # The GissOnline RAR contains one or more W3C/third party schema
        # namespaces; operation roots are checked by both name and namespace.
        for reference in root.iter():
            if reference.tag not in (_XSD + "include", _XSD + "import", _XSD + "redefine"):
                continue
            linked = reference.get("schemaLocation")
            if not linked:
                if reference.tag == _XSD + "import":
                    continue  # An external import without location is checked by compilation.
                raise ContractAuditError("Missing local XSD dependency in " + filename)
            if (
                "://" in linked or linked.startswith(("/", "\\"))
                or posixpath.normpath(linked) != linked
                or linked not in found
            ):
                raise ContractAuditError(
                    "Unresolved/remote XSD dependency: " + filename + " -> " + linked
                )
        for method, (element, suffix) in _EXPECTED.items():
            if ns != _GISS + suffix:
                continue
            if root.findall(_XSD + "element[@name='" + element + "']"):
                if method in roots:
                    raise ContractAuditError("Duplicate Giss XML root " + method)
                roots[method] = filename
    if set(roots) != set(_EXPECTED):
        raise ContractAuditError(
            "Missing Giss XSD operation roots: " + ", ".join(
                sorted(set(_EXPECTED) - roots.keys())
            )
        )
    resources = tuple(
        SchemaResource.from_bytes(name, payload)
        for name, payload in sorted(found.items())
    )
    for _name, entry in sorted(roots.items()):
        # Compile *all* official operation entrypoints using the exact same
        # no-network schema implementation as the production runtime.
        XmlSchemaValidator(SchemaSet(
            version="giss-abrasf-2.04-official",
            root_schema=entry,
            resources=resources,
            source_uri=XSD_URL,
        ))
    return resources, roots


def audit(wsdl: Path, xsd_dir: Path, archive: Path | None = None) -> dict[str, object]:
    wsdl_xml = _read(wsdl)
    namespace, actions = _wsdl_bindings(wsdl_xml)
    resources, roots = _schema_resources(xsd_dir)
    schema = SchemaSet(
        version="giss-abrasf-2.04-official",
        root_schema=roots["RecepcionarLoteRps"],
        resources=resources,
        source_uri=XSD_URL,
    )
    result: dict[str, object] = {
        "municipality": "Jundiai/SP",
        "ibge": "3525904",
        "version": "GissOnline V2 / ABRASF 2.04",
        "audited_at_utc": datetime.now(UTC).isoformat(),
        "official_wsdl_url": WSDL_URL,
        "official_xsd_url": XSD_URL,
        "wsdl_filename": wsdl.name,
        "wsdl_sha256": hashlib.sha256(wsdl_xml).hexdigest(),
        "service_namespace": namespace,
        "method_actions": actions,
        "xsd_resources": {r.name: r.sha256 for r in resources},
        "xsd_roots": roots,
        "xsd_package_sha256": schema.package_sha256,
        "all_operation_xsd_compilation": "passed",
        "source_authenticity": "requires_independent_review",
        "municipal_homologation": "not_claimed",
    }
    if archive is not None:
        if archive.suffix.lower() != ".rar":
            raise ContractAuditError("Official Giss distribution must be RAR")
        if archive.is_symlink() or not archive.is_file():
            raise ContractAuditError("Official Giss source archive missing")
        result["source_rar_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsdl", required=True, type=Path)
    parser.add_argument("--xsd-dir", required=True, type=Path)
    parser.add_argument("--source-rar", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.wsdl, args.xsd_dir, args.source_rar)
        if args.report.exists() or args.report.is_symlink():
            raise ContractAuditError("Do not overwrite immutable audit evidence")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.chmod(args.report, 0o600)
    except (ContractAuditError, OSError, ValueError) as exc:
        parser.exit(status=2, message=f"Jundiai contract audit failed: {exc}\n")
    print("Jundiai contract audit passed: " + str(args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
