"""Compile full public Osasco WCF XSD schemas without network or disk imports.

WCF singleWsdl embeds six namespaces and omits schemaLocation from imports.
Pin original downloaded bytes, then construct an in-memory schema package that
binds imports by their exact reviewed targetNamespace; never access URLs/files.
"""
from __future__ import annotations

from collections.abc import Mapping

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet, XmlSchemaValidator

_XSD = "{http://www.w3.org/2001/XMLSchema}"
_ROOT_NS = "http://tempuri.org/"
_SOURCE = (
    "https://homolog-nfe.osasco.sp.gov.br/"
    "EissnfeWebServices/NotaFiscalEletronica.svc?singleWsdl"
)
_MAX = 2_097_152


def compile_osasco_official_xsd(
    source: Mapping[str, bytes],
) -> XmlSchemaValidator:
    """Bind original municipal XSD namespaces to hashed in-memory resources.

    The caller has already validated every file against the operator manifesto
    SHA-256. This boundary refuses duplicate namespace, external import, DTD,
    schemaLocation, path aliasing and incomplete required WCF XML definitions.
    """
    if not isinstance(source, Mapping) or len(source) != 6:
        raise FiscalValidationError("Six reviewed official Osasco XSDs are required")
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
    )
    xml: dict[str, etree._Element] = {}
    namespaces: dict[str, str] = {}
    for name, raw in source.items():
        if (
            not isinstance(name, str) or not name.startswith("inline-xsd-")
            or not name.endswith(".xsd") or "/" in name or "\\" in name
            or not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX
        ):
            raise FiscalValidationError("Invalid official Osasco XSD resource")
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise FiscalValidationError("Official Osasco XSD rejects DTD")
        try:
            root = etree.fromstring(raw, parser=parser)
        except etree.XMLSyntaxError:
            raise FiscalValidationError("Malformed official Osasco XSD") from None
        if root.tag != _XSD + "schema":
            raise FiscalValidationError("Official Osasco XSD root mismatch")
        namespace = root.get("targetNamespace")
        if (
            not namespace or namespace in namespaces
            or any(item.get("schemaLocation") is not None
                   for item in root.findall(_XSD + "import"))
            or root.find(_XSD + "include") is not None
            or root.find(_XSD + "redefine") is not None
        ):
            raise FiscalValidationError("Unreviewed Osasco XSD namespace/import")
        namespaces[namespace] = name
        xml[name] = root
    if _ROOT_NS not in namespaces:
        raise FiscalValidationError("Official Osasco WCF method XSD absent")
    resources = []
    for name, root in xml.items():
        for imported in root.findall(_XSD + "import"):
            namespace = imported.get("namespace")
            if namespace not in namespaces:
                raise FiscalValidationError("Unresolved official Osasco XSD import")
            imported.set("schemaLocation", namespaces[namespace])
        resources.append(SchemaResource.from_bytes(
            name, etree.tostring(root, xml_declaration=True, encoding="utf-8"),
        ))
    return XmlSchemaValidator(SchemaSet(
        version="osasco-wcf-2026-11-public-v2.2",
        root_schema=namespaces[_ROOT_NS],
        resources=tuple(resources), source_uri=_SOURCE,
    ))
