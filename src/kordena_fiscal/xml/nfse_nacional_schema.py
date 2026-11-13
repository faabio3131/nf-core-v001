"""Hash-pinned National DPS schemas, loaded offline."""
from functools import lru_cache
from importlib.resources import files

from kordena_fiscal.domain import FiscalValidationError

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


@lru_cache(maxsize=2)
def national_dps_validator(version: str) -> XmlSchemaValidator:
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
