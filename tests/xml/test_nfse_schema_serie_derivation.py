"""Reproducible audit of the National DPS 1.01 series XSD erratum.

The upstream XSD remains byte-for-byte unchanged. The derived, hash-pinned
in-memory copy is used *only* to interpret the misanchored TSSerieDPS pattern.
"""
from __future__ import annotations

import hashlib
from importlib.resources import files

import pytest
from lxml import etree

from kordena_fiscal.xml.nfse_nacional_schema import (
    _XSD101_SERIE_DERIVED,
    _XSD101_SERIE_DERIVED_SHA256,
    _XSD101_SERIE_OFFICIAL,
    _pinned_schema_resource,
    national_dps_validator,
)
from kordena_fiscal.xml.schema import SchemaIntegrityError

_OFFICIAL_SHA256 = "41df4fd084b80d86200e0edb1d7d8df4adbc7fb6d19b93f35014a9dcbb8a2fa9"
_NAME = "tiposSimples_v1.01.xsd"


def _source() -> bytes:
    return (
        files("kordena_fiscal.xml")
        .joinpath("official", "NFSE_NACIONAL_1.01", _NAME)
        .read_bytes()
    )


def test_xsd101_official_source_is_immutable_and_derived_digest_is_pinned() -> None:
    original = _source()
    assert hashlib.sha256(original).hexdigest() == _OFFICIAL_SHA256
    assert original.count(_XSD101_SERIE_OFFICIAL) == 1
    resource = _pinned_schema_resource(
        version="1.01", name=_NAME,
        official_bytes=original, official_sha256=_OFFICIAL_SHA256,
    )
    assert original != resource.content
    assert resource.content == original.replace(
        _XSD101_SERIE_OFFICIAL, _XSD101_SERIE_DERIVED, 1,
    )
    assert resource.sha256 == _XSD101_SERIE_DERIVED_SHA256
    assert hashlib.sha256(resource.content).hexdigest() == (
        "42a3026812524f787c5157cb1d6411d4461151798a33569df069c3f35ef18773"
    )


def test_xsd101_derivation_fails_closed_if_official_bytes_drift() -> None:
    original = _source()
    with pytest.raises(SchemaIntegrityError, match="digest mismatch"):
        _pinned_schema_resource(
            version="1.01", name=_NAME, official_bytes=original + b" ",
            official_sha256=_OFFICIAL_SHA256,
        )


def test_xsd101_derivation_does_not_modify_other_versions() -> None:
    original = _source()
    resource = _pinned_schema_resource(
        version="1.00", name=_NAME,
        official_bytes=original, official_sha256=_OFFICIAL_SHA256,
    )
    assert resource.content == original
    assert resource.sha256 == _OFFICIAL_SHA256


def test_xsd101_serie_regex_accepts_real_series_and_rejects_literals() -> None:
    """XSD semantics, not Python's regex semantics; no all-values bypass."""
    ns = "http://www.w3.org/2001/XMLSchema"
    schema_xml = (
        f'<xs:schema xmlns:xs="{ns}"><xs:element name="serie">'
        '<xs:simpleType><xs:restriction base="xs:string">'
        '<xs:maxLength value="5"/>'
        + _XSD101_SERIE_DERIVED.decode("ascii")
        + '</xs:restriction></xs:simpleType></xs:element></xs:schema>'
    )
    schema = etree.XMLSchema(etree.fromstring(schema_xml.encode("utf-8")))
    for value in ("1", "17", "00001"):
        assert schema.validate(etree.fromstring(f"<serie>{value}</serie>".encode()))
    for value in ("^1$", "12A", "", "123456"):
        assert not schema.validate(etree.fromstring(f"<serie>{value}</serie>".encode()))


def test_xsd101_full_schema_remains_compileable() -> None:
    assert national_dps_validator("1.01") is national_dps_validator("1.01")
