"""Explicit, offline national schema profiles; municipal layouts stay independent."""
from datetime import date
from functools import lru_cache
from importlib.resources import files

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError

from .schema import SchemaResource, SchemaSet, XmlSchemaValidator

PRODUCTION_PROFILE = "production-20260209"
NT009_RESTRICTED_PROFILE = "nt009-prodrest-20261020"
NT009_RESTRICTED_FROM = date(2026, 10, 20)
# Planned production cutover requires the actual production package to be
# revalidated. Never silently keep an obsolete production layout afterwards.
PRODUCTION_REVIEW_FROM = date(2026, 12, 1)
NT009_OFFICIAL_SOURCE = (
    "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/"
    "producao-restrita/esquemas_prod_restrita_20261020.zip"
)
NT009_OFFICIAL_HASHES = {
    "CNC_v1.00.xsd": "7032188bb6f137d52b16512583b739a361e6b1434c42cb539a29b8efa32f8321",
    "DPS_v1.01.xsd": "fe45e5250a48e519aba89fc6a472863b8e602ed957778fb64692804933a00d0c",
    "NFSe_v1.01.xsd": "af0bd2d8c50acba3d9c3f3f515426eca083b3f66e3211ce8dd48a7cf101818b8",
    "evento_v1.01.xsd": "986d0a1c4d27454f712169849aa7c2380aaa4560bd9c920e0ff03ba6599ae28b",
    "pedRegEvento_v1.01.xsd": "e90b6816d29cca0bd5ed8f86ad98d3b7b0d8bbfc11a7583e6ff8f98170fd4009",
    "tiposCnc_v1.00.xsd": "af606b7317824fa8fa7ad8e44bac2ad8530cd5d162ebcdec647205473c41d525",
    "tiposComplexos_v1.01.xsd": "4f66f7c15bd3b05b3a16cbe5fa671b90c10e4c9c74276038730be1c8c794b721",
    "tiposEventos_v1.01.xsd": "1b32bea21089dc232d78b62d805e9c07382f440d4e0ea2cb3fb6b82ebde68c11",
    "tiposSimples_v1.01.xsd": "562e326724f85cd7c41176d35e67c542376784d4c950ec1719704d480a8af226",
    "xmldsig-core-schema.xsd": "8c9792a056aedcadfc95bf16f2d7448a35da40df71533e20aea37d0329980c48",
}


def select_national_dps_profile(
    *, environment: FiscalEnvironment, schema_version: str, effective_on: date,
) -> str:
    if (
        not isinstance(environment, FiscalEnvironment)
        or schema_version != "1.01"
        or type(effective_on) is not date
    ):
        raise FiscalValidationError("Invalid national schema selection context")
    if environment is FiscalEnvironment.HOMOLOGATION:
        return (
            NT009_RESTRICTED_PROFILE if effective_on >= NT009_RESTRICTED_FROM
            else PRODUCTION_PROFILE
        )
    if environment is FiscalEnvironment.PRODUCTION:
        if effective_on >= PRODUCTION_REVIEW_FROM:
            raise FiscalValidationError("National production schema cutover requires review")
        return PRODUCTION_PROFILE
    raise FiscalValidationError("Unsupported national fiscal environment")


@lru_cache(maxsize=4)
def national_restricted_validator(root_schema: str) -> XmlSchemaValidator:
    if root_schema not in (
        "DPS_v1.01.xsd", "NFSe_v1.01.xsd",
        "pedRegEvento_v1.01.xsd", "evento_v1.01.xsd",
    ):
        raise FiscalValidationError("Unsupported National NT009 schema root")
    directory = files("kordena_fiscal.xml").joinpath(
        "official", "NFSE_NACIONAL_1.01_NT009_20261020",
    )
    return XmlSchemaValidator(SchemaSet(
        version=NT009_RESTRICTED_PROFILE,
        root_schema=root_schema,
        resources=tuple(
            SchemaResource(name, directory.joinpath(name).read_bytes(), digest)
            for name, digest in NT009_OFFICIAL_HASHES.items()
        ),
        source_uri=NT009_OFFICIAL_SOURCE,
    ))
