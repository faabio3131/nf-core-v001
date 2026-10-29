"""Hash-pinned, no-network XSD validation for NF-e/NFC-e XML payloads."""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from lxml import etree  # type: ignore[import-untyped]

from kordena_fiscal.domain import FiscalDomainError, FiscalValidationError

from .access_key import NfeAccessKey

_NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"


class SchemaIntegrityError(FiscalDomainError):
    """Raised when a schema resource does not match its pinned digest."""


class XmlSchemaValidationError(FiscalDomainError):
    """Raised when schema compilation or XML validation fails."""


@dataclass(frozen=True, slots=True)
class SchemaResource:
    """One immutable schema file pinned by SHA-256."""

    name: str
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        name = self.name.strip().replace("\\", "/")
        if not name or name.startswith("/") or ".." in name.split("/"):
            raise FiscalValidationError("schema resource name must be a safe relative path")
        if not isinstance(self.content, bytes) or not self.content:
            raise FiscalValidationError("schema resource content must be non-empty bytes")
        digest = self.sha256.strip().lower()
        if len(digest) != 64:
            raise FiscalValidationError("schema sha256 must contain 64 hexadecimal characters")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise FiscalValidationError("schema sha256 must be hexadecimal") from exc
        actual = hashlib.sha256(self.content).hexdigest()
        if actual != digest:
            raise SchemaIntegrityError(f"schema resource digest mismatch: {name}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "sha256", digest)

    @classmethod
    def from_bytes(cls, name: str, content: bytes) -> SchemaResource:
        return cls(name=name, content=content, sha256=hashlib.sha256(content).hexdigest())


@dataclass(frozen=True, slots=True)
class SchemaSet:
    """Versioned in-memory XSD package; issuance never downloads schemas dynamically."""

    version: str
    root_schema: str
    resources: tuple[SchemaResource, ...]
    source_uri: str

    def __post_init__(self) -> None:
        version = self.version.strip()
        root_schema = self.root_schema.strip().replace("\\", "/")
        source_uri = self.source_uri.strip()
        if not version:
            raise FiscalValidationError("schema version must not be blank")
        if not root_schema:
            raise FiscalValidationError("root_schema must not be blank")
        if not source_uri:
            raise FiscalValidationError("source_uri must not be blank")
        if not self.resources:
            raise FiscalValidationError("schema set must contain at least one resource")
        names = [resource.name for resource in self.resources]
        if len(set(names)) != len(names):
            raise FiscalValidationError("schema resource names must be unique")
        if root_schema not in names:
            raise FiscalValidationError("root_schema must exist in schema resources")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "root_schema", root_schema)
        object.__setattr__(self, "source_uri", source_uri)

    @property
    def package_sha256(self) -> str:
        digest = hashlib.sha256()
        for resource in sorted(self.resources, key=lambda item: item.name):
            digest.update(resource.name.encode())
            digest.update(b"\0")
            digest.update(resource.sha256.encode())
            digest.update(b"\n")
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class XmlValidationResult:
    schema_version: str
    schema_package_sha256: str
    xml_sha256: str


@dataclass(frozen=True, slots=True)
class NfceXmlPayload:
    """Shared model-55/65 XML identity check; legacy public name remains compatible."""

    access_key: NfeAccessKey
    xml: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")
        if not isinstance(self.xml, bytes) or not self.xml:
            raise FiscalValidationError("xml must be non-empty bytes")
        root = _parse_xml(self.xml)
        if root.tag != f"{{{_NFE_NAMESPACE}}}NFe":
            raise XmlSchemaValidationError("NFC-e XML root must be NFe in the fiscal namespace")
        inf_nfe = root.findall(f"{{{_NFE_NAMESPACE}}}infNFe")
        if len(inf_nfe) != 1:
            raise XmlSchemaValidationError("NFC-e XML must contain exactly one direct infNFe")
        expected_id = f"NFe{self.access_key.value}"
        if inf_nfe[0].get("Id") != expected_id:
            raise XmlSchemaValidationError("infNFe Id does not match the access key")


class _MemorySchemaResolver(etree.Resolver):  # type: ignore[misc]
    def __init__(self, resources: dict[str, bytes]) -> None:
        super().__init__()
        self._resources = resources

    def resolve(self, url: str, pubid: str, context: object) -> object | None:
        del pubid
        raw = url.replace("\\", "/")
        if "://" in raw or raw.startswith("/"):
            return None
        normalized = posixpath.normpath(raw).lstrip("./")
        if ".." in normalized.split("/"):
            return None
        content = self._resources.get(normalized)
        if content is None:
            return None
        resolved = self.resolve_string(content.decode("utf-8"), context)
        return cast(object, resolved)


class XmlSchemaValidator:
    """Compile a pinned schema set in memory and validate XML with network disabled."""

    def __init__(self, schema_set: SchemaSet) -> None:
        if not isinstance(schema_set, SchemaSet):
            raise FiscalValidationError("schema_set must be SchemaSet")
        self._schema_set = schema_set
        resources = {resource.name: resource.content for resource in schema_set.resources}
        parser = _secure_parser()
        parser.resolvers.add(_MemorySchemaResolver(resources))
        try:
            root_resource = next(
                resource
                for resource in schema_set.resources
                if resource.name == schema_set.root_schema
            )
            root = etree.parse(
                BytesIO(root_resource.content),
                parser,
                base_url=schema_set.root_schema,
            )
            self._schema = etree.XMLSchema(root)
        except (etree.XMLSyntaxError, etree.XMLSchemaParseError, UnicodeDecodeError) as exc:
            raise XmlSchemaValidationError("schema set could not be compiled") from exc

    def validate(self, payload: NfceXmlPayload) -> XmlValidationResult:
        if not isinstance(payload, NfceXmlPayload):
            raise FiscalValidationError("payload must be NfceXmlPayload")
        document = _parse_xml_document(payload.xml)
        if not self._schema.validate(document):
            message = self._schema.error_log.last_error
            detail = message.message if message is not None else "unknown XSD validation error"
            raise XmlSchemaValidationError(f"XML does not satisfy pinned XSD: {detail}")
        return XmlValidationResult(
            schema_version=self._schema_set.version,
            schema_package_sha256=self._schema_set.package_sha256,
            xml_sha256=hashlib.sha256(payload.xml).hexdigest(),
        )


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        remove_comments=False,
    )


def _parse_xml(xml: bytes) -> etree._Element:
    return _parse_xml_document(xml).getroot()


def _parse_xml_document(xml: bytes) -> etree._ElementTree:
    if b"<!DOCTYPE" in xml.upper():
        raise XmlSchemaValidationError("DOCTYPE is forbidden in fiscal XML")
    try:
        return etree.parse(BytesIO(xml), _secure_parser())
    except etree.XMLSyntaxError as exc:
        raise XmlSchemaValidationError("fiscal XML is not well-formed") from exc
