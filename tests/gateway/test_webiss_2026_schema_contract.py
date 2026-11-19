"""Offline schema-contract tests. Synthetic XSD != official WebISS certification.

The controlled fixture models the XML Schema order regression reported for
Extrema E160 (IBSCBS/dest identification first). Real fiscal readiness still
requires the municipal original XSD package with reviewed SHA-256.
"""
from __future__ import annotations

import pytest

from kordena_fiscal.gateway import webiss_2026_schema
from kordena_fiscal.gateway.webiss_2026_schema import (
    WebissMunicipalSchemaUnverified,
    build_pinned_webiss_municipal_schema,
    validate_webiss_official_xml,
)
from kordena_fiscal.xml.schema import SchemaResource, SchemaSet

_A = "http://www.abrasf.org.br/nfse.xsd"
_SAMPLE_XSD = b"""<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
 targetNamespace="http://www.abrasf.org.br/nfse.xsd"
 xmlns="http://www.abrasf.org.br/nfse.xsd" elementFormDefault="qualified">
 <xs:element name="IBSCBS"><xs:complexType><xs:sequence>
  <xs:element name="dest"><xs:complexType><xs:sequence>
   <xs:element name="CNPJ" type="xs:string"/>
   <xs:element name="xNome" type="xs:string"/>
  </xs:sequence></xs:complexType></xs:element>
 </xs:sequence></xs:complexType></xs:element>
</xs:schema>"""
_VALID = (
    f'<IBSCBS xmlns="{_A}"><dest>'
    "<CNPJ>12345678000195</CNPJ><xNome>Tomador Sintetico</xNome>"
    "</dest></IBSCBS>"
).encode()
_INVALID_E160 = (
    f'<IBSCBS xmlns="{_A}"><dest>'
    "<xNome>Tomador Sintetico</xNome><CNPJ>12345678000195</CNPJ>"
    "</dest></IBSCBS>"
).encode()


def _resources() -> tuple[SchemaResource, ...]:
    return (SchemaResource.from_bytes("sample.xsd", _SAMPLE_XSD),)


def _digest() -> str:
    return SchemaSet(
        version="2.02", root_schema="sample.xsd",
        resources=_resources(), source_uri="https://extremamg.webiss.com.br/",
    ).package_sha256


def test_unpinned_schema_cannot_be_loaded_into_fiscal_transport() -> None:
    with pytest.raises(WebissMunicipalSchemaUnverified, match="differs from reviewed SHA"):
        build_pinned_webiss_municipal_schema(
            municipality_ibge="3125101",
            root_schema="sample.xsd", resources=_resources(),
            source_uri="https://extremamg.webiss.com.br/",
        )


def test_schema_loader_rejects_cross_city_or_tampered_digest(monkeypatch) -> None:
    monkeypatch.setattr(
        webiss_2026_schema,
        "PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS", {"3125101": _digest()},
    )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="provenance"):
        build_pinned_webiss_municipal_schema(
            municipality_ibge="3125101", root_schema="sample.xsd",
            resources=_resources(), source_uri="https://uberabamg.webiss.com.br/",
        )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="Unknown"):
        build_pinned_webiss_municipal_schema(
            municipality_ibge="3125109", root_schema="sample.xsd",
            resources=_resources(), source_uri="https://extremamg.webiss.com.br/",
        )
    monkeypatch.setattr(
        webiss_2026_schema,
        "PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS", {"3125101": "0" * 64},
    )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="reviewed SHA"):
        build_pinned_webiss_municipal_schema(
            municipality_ibge="3125101", root_schema="sample.xsd",
            resources=_resources(), source_uri="https://extremamg.webiss.com.br/",
        )


def test_schema_order_guard_reproduces_extrema_e160_without_provider_call(
    monkeypatch,
) -> None:
    # Explicit test-only pin: never installed in production.
    monkeypatch.setattr(
        webiss_2026_schema,
        "PINNED_WEBISS_MG_2026_SCHEMA_DIGESTS", {"3125101": _digest()},
    )
    evidence, validator = build_pinned_webiss_municipal_schema(
        municipality_ibge="3125101",
        root_schema="sample.xsd", resources=_resources(),
        source_uri="https://extremamg.webiss.com.br/",
    )
    validate_webiss_official_xml(
        evidence=evidence, validator=validator, xml=_VALID,
    )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="incompatible"):
        validate_webiss_official_xml(
            evidence=evidence, validator=validator, xml=_INVALID_E160,
        )
    with pytest.raises(WebissMunicipalSchemaUnverified, match="incompatible"):
        validate_webiss_official_xml(
            evidence=evidence, validator=validator,
            xml=b'<!DOCTYPE IBSCBS><IBSCBS/>',
        )
