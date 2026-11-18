"""Hash-pinned National DPS schemas, loaded offline."""
from functools import lru_cache
from importlib.resources import files

from kordena_fiscal.domain import FiscalValidationError

from .nfse_national_profiles import (
    NT009_RESTRICTED_PROFILE,
    PRODUCTION_PROFILE,
    national_restricted_validator,
)
from .schema import SchemaIntegrityError, SchemaResource, SchemaSet, XmlSchemaValidator

_SOURCE = (
    "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/"
    "nfse-esquemas_xsd-v1-01-20260209.zip"
)
_HASHES = {
    "1.00": {
        "DPS_v1.00.xsd": "a4d99ccff95b86378958692e68f8011333eee650956f7592f4b5b70799741dc6",
        "tiposComplexos_v1.00.xsd":
            "f26aa6110ca7e40fe9ee51c28ef4690e7d7a1c29436fac090f998523a0761d24",
        "tiposSimples_v1.00.xsd":
            "c709e5ee8e7bf6582e29f17fe49d4bbedb531361b5c3d4f7a725fc2f3bd463fd",
        "xmldsig-core-schema.xsd":
            "adbfc03b4d0b3ee8a18198383f81ec7b7857a5285f480717dfafd4696ce9f9be",
    },
    "1.01": {
        "DPS_v1.01.xsd": "8e1aab58d3850d654f119a0274e5d8f1826f39007d272d925fe5bf23fcd38ca3",
        "tiposComplexos_v1.01.xsd":
            "658f91cb16793cf814ae6c4d7a69ddda7820507ad2cbe70382bc979fedd2cecf",
        "tiposSimples_v1.01.xsd":
            "41df4fd084b80d86200e0edb1d7d8df4adbc7fb6d19b93f35014a9dcbb8a2fa9",
        "xmldsig-core-schema.xsd":
            "58dede7aaeb706b5c681302353567e6abd973f2110d3349187d62ca8f1b807d2",
    },
}


# Regulatory compatibility exception: the *unmodified* official 2026-02-09
# NFS-e 1.01 package includes PCRE-style anchors in the TSSerieDPS xs:pattern.
# XSD regex syntax implicitly anchors the whole value; '^' and '$' are literal.
# Do not edit official XML files or accept an arbitrary unverified replacement.
# Source and derived digests are independently pinned and documented.
_XSD101_SERIE_NAME = "tiposSimples_v1.01.xsd"
_XSD101_SERIE_OFFICIAL = b'<xs:pattern value="^0{0,4}\\d{1,5}$"/>'
_XSD101_SERIE_DERIVED = b'<xs:pattern value="0{0,4}\\d{1,5}"/>'
_XSD101_SERIE_DERIVED_SHA256 = (
    "42a3026812524f787c5157cb1d6411d4461151798a33569df069c3f35ef18773"
)


def _pinned_schema_resource(
    *, version: str, name: str, official_bytes: bytes, official_sha256: str,
) -> SchemaResource:
    """Verify official bytes first; derive only the single audited 1.01 erratum.

    A changed upstream package, an unexpected count of the offending pattern,
    or a drifted derived digest fails closed before XML validation.
    """
    official = SchemaResource(name, official_bytes, official_sha256)
    if version != "1.01" or name != _XSD101_SERIE_NAME:
        return official
    if official.content.count(_XSD101_SERIE_OFFICIAL) != 1:
        raise SchemaIntegrityError("NFS-e 1.01 TSSerieDPS official source no longer matches audit")
    derived_bytes = official.content.replace(
        _XSD101_SERIE_OFFICIAL, _XSD101_SERIE_DERIVED, 1,
    )
    return SchemaResource(name, derived_bytes, _XSD101_SERIE_DERIVED_SHA256)


@lru_cache(maxsize=4)
def national_dps_validator(
    version: str, *, profile: str = PRODUCTION_PROFILE,
) -> XmlSchemaValidator:
    if profile == NT009_RESTRICTED_PROFILE:
        if version != "1.01":
            raise FiscalValidationError("NT009 requires DPS version 1.01")
        return national_restricted_validator("DPS_v1.01.xsd")
    if profile != PRODUCTION_PROFILE:
        raise FiscalValidationError("Unsupported National DPS schema profile")
    if version not in _HASHES:
        raise FiscalValidationError("Unsupported National DPS schema version")
    directory = files("kordena_fiscal.xml").joinpath("official", f"NFSE_NACIONAL_{version}")
    return XmlSchemaValidator(SchemaSet(
        version=version,
        root_schema=f"DPS_v{version}.xsd",
        resources=tuple(
            _pinned_schema_resource(
                version=version,
                name=name,
                official_bytes=directory.joinpath(name).read_bytes(),
                official_sha256=digest,
            )
            for name, digest in _HASHES[version].items()
        ),
        source_uri=_SOURCE,
    ))


# National event schemas mirrored from the public reference repository listed
# below, with exact mirrored bytes pinned. The municipal Simpliss package must
# be reconciled separately: a mirror does not certify upstream source identity.
# https://github.com/nfse-nacional/nfse-php/tree/main/references/schemas
_EVENT_MIRROR_SOURCE = (
    "https://github.com/nfse-nacional/nfse-php/tree/main/references/schemas"
)
_EVENT_MIRROR_HASHES = {
    "pedRegEvento_v1.01.xsd": "e90b6816d29cca0bd5ed8f86ad98d3b7b0d8bbfc11a7583e6ff8f98170fd4009",
    "evento_v1.01.xsd": "986d0a1c4d27454f712169849aa7c2380aaa4560bd9c920e0ff03ba6599ae28b",
    "tiposEventos_v1.01.xsd": "1b32bea21089dc232d78b62d805e9c07382f440d4e0ea2cb3fb6b82ebde68c11",
}


@lru_cache(maxsize=4)
def national_event_validator(kind: str, *, profile: str = PRODUCTION_PROFILE) -> XmlSchemaValidator:
    """Offline validated cancellation request/response (national event 1.01)."""
    if kind not in ("request", "response"):
        raise FiscalValidationError("Unsupported national event schema")
    root_name = "pedRegEvento_v1.01.xsd" if kind == "request" else "evento_v1.01.xsd"
    if profile == NT009_RESTRICTED_PROFILE:
        return national_restricted_validator(root_name)
    if profile != PRODUCTION_PROFILE:
        raise FiscalValidationError("Unsupported national event schema profile")
    version = "1.01"
    directory = files("kordena_fiscal.xml").joinpath("official", "NFSE_NACIONAL_1.01")
    shared = {
        name: sha for name, sha in _HASHES["1.01"].items()
        if name != "DPS_v1.01.xsd"
    }
    resources = tuple(
        _pinned_schema_resource(
            version=version, name=name, official_bytes=directory.joinpath(name).read_bytes(),
            official_sha256=digest,
        )
        for name, digest in {**shared, **_EVENT_MIRROR_HASHES}.items()
    )
    return XmlSchemaValidator(SchemaSet(
        version=version, root_schema=root_name, resources=resources,
        source_uri=_EVENT_MIRROR_SOURCE,
    ))
