"""Exact Santana Simpliss 2026 municipal XSD contract, pinned offline.

The 18 unchanged original files and source SHA-256 digests are preserved in
contracts/official/santana/simpliss_2026/manifest.json.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from kordena_fiscal.domain import FiscalValidationError

from .schema import SchemaIntegrityError, SchemaResource, SchemaSet, XmlSchemaValidator

_SOURCE = (
    "https://santanadeparnaiba.simplissweb.com.br/contrib/app/nfse/"
    "DocumentoIntegracaoNotaNacional/DownloadArquivo?nomeDocumento="
    "nfse-esquemas_xsd-anexos_i_ii_iv-sefin_adn-prod-v1-00-20251210"
)
_HASHES = {
    "DPS_v1.01.xsd": "fe45e5250a48e519aba89fc6a472863b8e602ed957778fb64692804933a00d0c",
    "NFSe_v1.01.xsd": "af0bd2d8c50acba3d9c3f3f515426eca083b3f66e3211ce8dd48a7cf101818b8",
    "evento_v1.01.xsd": "986d0a1c4d27454f712169849aa7c2380aaa4560bd9c920e0ff03ba6599ae28b",
    "pedRegEvento_v1.01.xsd": "e90b6816d29cca0bd5ed8f86ad98d3b7b0d8bbfc11a7583e6ff8f98170fd4009",
    "tiposComplexos_v1.01.xsd": "89ab79cb36ec48db9aec452d4f679577774d2a5986132eba221159fd9a099a58",
    "tiposEventos_v1.01.xsd": "ac2ce6a34254445fb36a768b7b6c14dbb0906101ec3900a5dbb8909adfa159a0",
    "tiposSimples_v1.01.xsd": "def6ce6f89598a4fa1f39049957105aec92d7639eb1c1bcb189c8a9b1edbf26d",
    "xmldsig-core-schema.xsd": "49848f732663aecb618d72ad6130c5c3240f0a10f3a1a8544b7d48a6c726046f",
}
_ROOTS = {
    "dps": "DPS_v1.01.xsd",
    "invoice": "NFSe_v1.01.xsd",
    "request": "pedRegEvento_v1.01.xsd",
    "response": "evento_v1.01.xsd",
}

# Official Simpliss TSSerieDPS contains a non-XSD PCRE negative lookahead.
# Keep original files immutable, verify the upstream SHA, and derive only
# this equivalent W3C XSD regex: one to five digits, at least one nonzero.
_OFFICIAL_PCRE = b'<xs:pattern value="^(?!0{1,5}$)\\d{1,5}$"/>'
_DERIVED_XSD = b'<xs:pattern value="[0-9]*[1-9][0-9]*"/>'
_DERIVED_HASH = "e8f478f40dbc8118c038e3917baf50f729678b582cd1f68637219bb6f0fbc2af"


def _resource(name: str, content: bytes, digest: str) -> SchemaResource:
    official = SchemaResource(name, content, digest)
    if name != "tiposSimples_v1.01.xsd":
        return official
    if official.content.count(_OFFICIAL_PCRE) != 1:
        raise SchemaIntegrityError("Santana official TSSerieDPS exception drifted")
    derived = official.content.replace(_OFFICIAL_PCRE, _DERIVED_XSD, 1)
    return SchemaResource(name, derived, _DERIVED_HASH)


@lru_cache(maxsize=4)
def santana_official_validator(kind: str) -> XmlSchemaValidator:
    """Validate signed DPS, NFS-e, cancellation request and official event."""
    if kind not in _ROOTS:
        raise FiscalValidationError("Unsupported Santana Simpliss schema operation")
    folder = files("kordena_fiscal.xml").joinpath(
        "official", "SANTANA_SIMPLISS_2026",
    )
    resources = tuple(
        _resource(name, folder.joinpath(name).read_bytes(), checksum)
        for name, checksum in _HASHES.items()
    )
    return XmlSchemaValidator(SchemaSet(
        version="1.01", root_schema=_ROOTS[kind], resources=resources,
        source_uri=_SOURCE,
    ))
