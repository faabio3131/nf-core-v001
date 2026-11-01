"""Versioned classification catalogs (CST/CSOSN/PIS-COFINS, NCM, cClassTrib).

Only the small, stable code tables ship as a seed, and they are labelled
``PENDING_NORMATIVE_REVIEW``. NCM and cClassTrib catalogs are empty until an official
artifact is loaded by a human-reviewed process (with SHA-256); their absence is reported as
"not verified", never filled in by guess.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from kordena_fiscal.domain import FiscalValidationError

from ..contracts import stable_hash
from .rejections import ReviewStatus


class CatalogKind(StrEnum):
    CST_ICMS = "cst_icms"
    CSOSN = "csosn"
    CST_PIS_COFINS = "cst_pis_cofins"
    NCM = "ncm"
    CCLASSTRIB = "cclasstrib"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    kind: CatalogKind
    code: str
    description: str
    valid_from: date | None = None
    valid_to: date | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_NORMATIVE_REVIEW

    def __post_init__(self) -> None:
        if not self.code.isdigit():
            raise FiscalValidationError("catalog code must be numeric")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise FiscalValidationError("catalog entry validity is inverted")

    def effective_on(self, day: date) -> bool:
        return (self.valid_from is None or day >= self.valid_from) and (
            self.valid_to is None or day <= self.valid_to
        )


class ClassificationCatalog:
    def __init__(self, entries: Iterable[CatalogEntry], *, version: str) -> None:
        self._by_kind: dict[CatalogKind, dict[str, CatalogEntry]] = {}
        for entry in entries:
            bucket = self._by_kind.setdefault(entry.kind, {})
            if entry.code in bucket:
                raise FiscalValidationError(f"duplicate {entry.kind} code {entry.code}")
            bucket[entry.code] = entry
        self.version = version
        self.fingerprint = stable_hash(
            [
                [e.kind.value, e.code, e.description, str(e.valid_from), str(e.valid_to)]
                for kind in sorted(self._by_kind, key=lambda k: k.value)
                for e in sorted(self._by_kind[kind].values(), key=lambda e: e.code)
            ]
        )

    def is_loaded(self, kind: CatalogKind) -> bool:
        return bool(self._by_kind.get(kind))

    def lookup(self, kind: CatalogKind, code: str) -> CatalogEntry | None:
        return self._by_kind.get(kind, {}).get(code.strip())

    def entries(self, kind: CatalogKind) -> tuple[CatalogEntry, ...]:
        return tuple(sorted(self._by_kind.get(kind, {}).values(), key=lambda e: e.code))

    def review_status(self, kind: CatalogKind) -> ReviewStatus:
        items = self.entries(kind)
        if items and all(e.review_status is ReviewStatus.REVIEWED for e in items):
            return ReviewStatus.REVIEWED
        return ReviewStatus.PENDING_NORMATIVE_REVIEW


_CST_ICMS = {
    "00": "Tributada integralmente",
    "10": "Tributada e com cobrança do ICMS por substituição tributária",
    "20": "Com redução de base de cálculo",
    "30": "Isenta ou não tributada e com cobrança do ICMS por substituição tributária",
    "40": "Isenta",
    "41": "Não tributada",
    "50": "Suspensão",
    "51": "Diferimento",
    "60": "ICMS cobrado anteriormente por substituição tributária",
    "70": "Com redução de base de cálculo e cobrança do ICMS por substituição tributária",
    "90": "Outras",
}
_CSOSN = {
    "101": "Tributada pelo Simples Nacional com permissão de crédito",
    "102": "Tributada pelo Simples Nacional sem permissão de crédito",
    "103": "Isenção do ICMS no Simples Nacional para faixa de receita bruta",
    "201": "Tributada com permissão de crédito e com cobrança do ICMS por substituição tributária",
    "202": "Tributada sem permissão de crédito e com cobrança do ICMS por substituição tributária",
    "203": "Isenção do ICMS para faixa de receita bruta e com cobrança do ICMS por ST",
    "300": "Imune",
    "400": "Não tributada pelo Simples Nacional",
    "500": "ICMS cobrado anteriormente por substituição tributária ou por antecipação",
    "900": "Outros",
}
_PIS_COFINS = {
    "01": "Operação tributável com alíquota básica",
    "02": "Operação tributável com alíquota diferenciada",
    "03": "Operação tributável com alíquota por unidade de medida de produto",
    "04": "Operação tributável monofásica — revenda a alíquota zero",
    "05": "Operação tributável por substituição tributária",
    "06": "Operação tributável a alíquota zero",
    "07": "Operação isenta da contribuição",
    "08": "Operação sem incidência da contribuição",
    "09": "Operação com suspensão da contribuição",
    "49": "Outras operações de saída",
    "99": "Outras operações",
}


def default_classification_catalog() -> ClassificationCatalog:
    entries: list[CatalogEntry] = []
    for kind, table in (
        (CatalogKind.CST_ICMS, _CST_ICMS),
        (CatalogKind.CSOSN, _CSOSN),
        (CatalogKind.CST_PIS_COFINS, _PIS_COFINS),
    ):
        entries.extend(CatalogEntry(kind, code, text) for code, text in table.items())
    return ClassificationCatalog(entries, version="classification.seed/2026-10-31")
