"""Classification advisory (CST/CSOSN/PIS-COFINS/NCM/cClassTrib). Suggestion only, never a write.

The deterministic baseline validates the *current* canonical decision against versioned
catalogs. Where an official catalog is not loaded, the result says "não verificado" instead
of guessing. Applying any change is a separate, human-approved command in the fiscal services.
"""

from __future__ import annotations

from dataclasses import dataclass

from .baseline import Baseline, insufficient
from .contracts import (
    AdviceRequest,
    AdviceSection,
    AdviceStatus,
    Evidence,
    EvidenceKind,
    SectionKind,
)
from .knowledge import CatalogKind, ClassificationCatalog

_CSOSN_REGIMES = frozenset({"1", "4"})  # Simples Nacional, MEI
_CST_REGIMES = frozenset({"3"})  # regime normal
_NO_APPROVAL = "Nenhuma alteração foi salva; a aplicação depende de aprovação humana."


@dataclass(frozen=True, slots=True)
class _Finding:
    text: str
    inconsistent: bool


class ClassificationBaseline:
    def __init__(self, catalog: ClassificationCatalog) -> None:
        self._catalog = catalog

    def __call__(self, request: AdviceRequest) -> Baseline:
        decision = next(
            (e for e in request.evidence if e.kind is EvidenceKind.TAX_DECISION), None
        )
        if decision is None or "icms_code" not in decision.data:
            return insufficient(
                "Não há decisão tributária informada para analisar: não há base suficiente."
            )
        product = next(
            (e for e in request.evidence if e.kind is EvidenceKind.PRODUCT_PROFILE), None
        )
        findings = self._validate(decision, product)
        kb_evidence = self._catalog_evidence(decision)
        kb_ids = tuple(e.evidence_id for e in kb_evidence)
        cited = (decision.evidence_id, *kb_ids)

        d = decision.data
        current = (
            f"Classificação atual — CRT {d.get('crt', '?')}, ICMS {d['icms_code']}, "
            f"PIS {d.get('pis_cst', '?')}, COFINS {d.get('cofins_cst', '?')}"
            + (f", CFOP {d['cfop']}" if "cfop" in d else "")
            + (f", cClassTrib {d['cclasstrib']}" if "cclasstrib" in d else "")
            + (
                f" (regra {d['rule_id']} v{d.get('rule_version', '?')})"
                if "rule_id" in d
                else ""
            )
            + "."
        )
        sections: list[AdviceSection] = [
            AdviceSection(SectionKind.FACT, current, (decision.evidence_id,))
        ]
        for finding in findings:
            sections.append(AdviceSection(SectionKind.FACT, finding.text, cited))
        if not any(f.inconsistent for f in findings):
            sections.append(
                AdviceSection(
                    SectionKind.FACT,
                    "Nenhuma inconsistência encontrada nos códigos verificáveis pelos "
                    "catálogos internos; itens não verificados estão indicados acima.",
                    cited,
                )
            )
        sections.append(
            AdviceSection(
                SectionKind.ACTION,
                "Submeter qualquer ajuste ao contador responsável antes de alterar regra "
                f"ou cadastro. {_NO_APPROVAL}",
                cited,
            )
        )
        sections.append(
            AdviceSection(
                SectionKind.SOURCE,
                f"Catálogos internos {self._catalog.version}; " + self._source_note(),
                kb_ids or (decision.evidence_id,),
            )
        )
        needs_model = any(f.inconsistent for f in findings) or bool(request.question)
        return Baseline(
            status=AdviceStatus.BASELINE_ONLY,
            sections=tuple(sections),
            model_eligible=needs_model,
            no_model_reason="no_ai_needed",
            extra_evidence=kb_evidence,
        )

    # ------------------------------------------------------------------ rules

    def _validate(self, decision: Evidence, product: Evidence | None) -> list[_Finding]:
        d = decision.data
        out: list[_Finding] = []
        crt = d.get("crt", "").strip()
        icms = d["icms_code"].strip()

        if crt in _CSOSN_REGIMES and len(icms) != 3:
            out.append(
                _Finding(
                    f"Regime CRT {crt} (Simples/MEI) normalmente usa CSOSN de 3 dígitos, "
                    f"mas o ICMS informado é {icms}.",
                    True,
                )
            )
        elif crt in _CST_REGIMES and len(icms) != 2:
            out.append(
                _Finding(
                    f"Regime normal (CRT 3) usa CST de 2 dígitos, mas o ICMS informado é {icms}.",
                    True,
                )
            )
        elif crt == "2":
            out.append(
                _Finding(
                    "CRT 2 (excesso de sublimite): a família de código de ICMS depende de "
                    "norma específica; não verificado — confirmar com o contador.",
                    False,
                )
            )
        elif not crt:
            out.append(_Finding("Regime (CRT) não informado: coerência não verificada.", False))

        kind = CatalogKind.CSOSN if len(icms) == 3 else CatalogKind.CST_ICMS
        if self._catalog.lookup(kind, icms) is None:
            out.append(
                _Finding(
                    f"ICMS {icms} não consta do catálogo interno ({kind.value}); "
                    "verificar na tabela oficial vigente.",
                    True,
                )
            )
        for field, label in (("pis_cst", "PIS"), ("cofins_cst", "COFINS")):
            value = d.get(field, "").strip()
            if value and self._catalog.lookup(CatalogKind.CST_PIS_COFINS, value) is None:
                out.append(
                    _Finding(
                        f"CST {label} {value} não consta do catálogo interno de saídas; "
                        "verificar na tabela oficial vigente (pode ser código de entrada).",
                        False,
                    )
                )
        pis, cofins = d.get("pis_cst", "").strip(), d.get("cofins_cst", "").strip()
        if pis and cofins and pis != cofins:
            out.append(
                _Finding(
                    f"CST de PIS ({pis}) e COFINS ({cofins}) diferem; confirmar se é intencional.",
                    True,
                )
            )

        ncm = (product.data.get("ncm", "").strip() if product is not None else "")
        if ncm:
            if not (len(ncm) == 8 and ncm.isdigit()):
                out.append(_Finding(f"NCM {ncm[:12]} não tem o formato de 8 dígitos.", True))
            elif not self._catalog.is_loaded(CatalogKind.NCM):
                out.append(
                    _Finding(
                        f"NCM {ncm}: tabela oficial não carregada; existência e vigência "
                        "não verificadas.",
                        False,
                    )
                )
            elif self._catalog.lookup(CatalogKind.NCM, ncm) is None:
                out.append(_Finding(f"NCM {ncm} não consta da tabela carregada.", True))
        cclass = d.get("cclasstrib", "").strip()
        if cclass:
            if not self._catalog.is_loaded(CatalogKind.CCLASSTRIB):
                out.append(
                    _Finding(
                        f"cClassTrib {cclass}: catálogo oficial não carregado; "
                        "não verificado.",
                        False,
                    )
                )
            elif self._catalog.lookup(CatalogKind.CCLASSTRIB, cclass) is None:
                out.append(_Finding(f"cClassTrib {cclass} não consta do catálogo carregado.", True))
        return out

    def _source_note(self) -> str:
        if self._catalog.is_loaded(CatalogKind.NCM) and self._catalog.is_loaded(
            CatalogKind.CCLASSTRIB
        ):
            return (
                "NCM e cClassTrib vêm de tabelas oficiais com integridade verificada "
                "(SHA-256), sem revisão normativa humana; os demais catálogos são sementes "
                "com revisão normativa pendente."
            )
        return (
            "revisão normativa pendente para os catálogos de semente. Tabelas oficiais de "
            "NCM e cClassTrib só valem quando carregadas por processo revisado."
        )

    def _catalog_evidence(self, decision: Evidence) -> tuple[Evidence, ...]:
        crt = decision.data.get("crt", "").strip()
        informed = CatalogKind.CSOSN if len(decision.data["icms_code"].strip()) == 3 else (
            CatalogKind.CST_ICMS
        )
        if crt in _CSOSN_REGIMES:
            icms_kinds = {CatalogKind.CSOSN}
        elif crt in _CST_REGIMES:
            icms_kinds = {CatalogKind.CST_ICMS}
        else:
            icms_kinds = {CatalogKind.CSOSN, CatalogKind.CST_ICMS}
        icms_wanted = sorted(icms_kinds | {informed}, key=lambda k: k.value)
        wanted = [*icms_wanted, CatalogKind.CST_PIS_COFINS]
        evidence: list[Evidence] = []
        for catalog_kind in wanted:
            entries = self._catalog.entries(catalog_kind)
            if not entries:
                continue
            evidence.append(
                Evidence(
                    evidence_id=f"kb:cls:{catalog_kind.value}",
                    kind=EvidenceKind.CLASSIFICATION_CATALOG,
                    origin=f"classification-catalog@{self._catalog.version}",
                    data={
                        **_chunked([f"{e.code}={e.description}" for e in entries]),
                        "review_status": self._catalog.review_status(catalog_kind).value,
                    },
                    tenant_id=decision.tenant_id,
                    unit_id=decision.unit_id,
                )
            )
        return tuple(evidence)


def _chunked(items: list[str], limit: int = 400) -> dict[str, str]:
    """Split a long code list into evidence-sized values (``codes_1``, ``codes_2``...)."""

    chunks: list[str] = []
    current = ""
    for item in items:
        candidate = f"{current} | {item}" if current else item
        if len(candidate) > limit and current:
            chunks.append(current)
            current = item
        else:
            current = candidate
    if current:
        chunks.append(current)
    return {f"codes_{index}": chunk for index, chunk in enumerate(chunks, start=1)}
