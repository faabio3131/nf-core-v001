"""Local PDF/XLSX/ZIP rendering of verified T20 evidence. No fiscal calculation."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import re
import textwrap
from collections.abc import Iterator
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from kordena_fiscal.domain import FiscalValidationError

MAX_PACKAGE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 4096
MAX_ROWS = 30000
SCHEMA = "nfcore.accounting-dossier/v1"
DISCLAIMER = (
    "SIMULAÇÃO INTERNA - SEM RECONHECIMENTO DE CRÉDITO OU EFEITO FISCAL REAL. "
    "Parecer preparatório: exige revisão e assinatura do contador. "
    "Valores e estados históricos não constituem direito atual, pagamento ou homologação externa."
)
PATH = re.compile(r"^(?:[a-z0-9_-]+/)*[a-z0-9_.-]+$")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: Any, *, unicode: bool = True) -> bytes:
    return json.dumps(
        value, ensure_ascii=not unicode, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _safe_path(name: str) -> bool:
    return bool(PATH.fullmatch(name)) and all(
        part not in {".", ".."} for part in name.split("/")
    )


def _pairs(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in sorted(value.items()):
            yield from _pairs(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        if not value:
            yield path or "Estado", "Nenhum registro"
        for index, item in enumerate(value, 1):
            yield from _pairs(item, f"{path}[{index}]")
    else:
        yield path, value


def _text(value: Any) -> str:
    if value is None:
        return "Não disponível"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    text = str(value)
    # Preserve otherwise unrepresentable XML control characters as explicit escapes.
    return "".join(
        ch if ord(ch) >= 32 and ord(ch) not in {0xFFFE, 0xFFFF}
        else f"\\u{ord(ch):04x}" for ch in text
    )


_LABELS = {
    "scope": "Escopo", "issuer": "CNPJ emitente", "competence": "Competência",
    "finding_id": "Identificador do achado", "actor_id": "Responsável",
    "record_id": "Registro", "version": "Versão", "digest": "SHA-256",
    "basis_digest": "Hash da base", "dossier_id": "Identificador do dossiê",
    "dossier_version": "Versão do dossiê", "generated_at": "Gerado em",
    "source_cutoff": "Data de corte", "issuer_context": "Contexto do emitente",
    "ledger_events": "Eventos do ledger", "case_count": "Quantidade de casos",
    "identity": "Identificador", "tax": "Tributo", "access_key": "Chave de acesso",
    "item": "Item", "status": "Situação", "reason": "Motivo",
    "principal_cents": "Principal (centavos)", "adjustment_cents": "Ajuste (centavos)",
    "estimated_cents": "Estimativa (centavos)", "candidate_cents": "Potencial (centavos)",
    "t16_candidate_cents": "Potencial T16 (centavos)", "credit_recognized": "Crédito reconhecido",
    "rate_memory": "Memória de taxas", "basis_points": "Pontos-base",
    "citation": "Referência legal", "reference": "Referência",
    "source": "Fonte", "source_sha256": "SHA-256 da fonte", "review_reference": "Revisão",
    "published_on": "Publicação", "valid_from": "Vigência inicial",
    "valid_until": "Vigência final", "modality": "Modalidade", "anchor": "Marco inicial",
    "deadline": "Prazo", "receipt_id": "Recibo", "review_sha256": "SHA-256 da revisão",
    "legal_source_sha256": "SHA-256 da base legal", "xml_sha256": "SHA-256 do XML",
    "policy": "Política legal", "payment": "Pagamento", "paid_on": "Data de pagamento",
    "federal_correction": "Correção federal", "available": "Disponível",
    "reserved": "Reservado", "selic_cents": "SELIC (centavos)", "basis": "Fundamentação",
    "limits": "Limites", "action": "Orientação", "residual_gate": "Gate pendente",
    "evidence_scope": "Abrangência das provas", "regime": "Regime",
    "state": "UF", "municipality": "Município", "cnae": "CNAE",
    "deadline_source": "Fonte do prazo", "deadline_provision": "Dispositivo do prazo",
    "interest_source": "Fonte dos juros", "interest_provision": "Dispositivo dos juros",
    "originally_due_cents": "Devido original (centavos)",
    "corrected_due_cents": "Devido corrigido (centavos)",
    "historical_digest": "Hash histórico", "payment_sha256": "SHA-256 do pagamento",
    "assessment_reference": "Apuração original",
    "corrected_assessment_reference": "Apuração corrigida",
    "provision": "Dispositivo", "month": "Mês",
}

_VALUES = {
    "potential": "Potencial, não reconhecido",
    "reviewed_candidate_only": "Candidato revisado, sem reconhecimento",
    "unused_candidate": "Crédito potencial não utilizado",
    "icms_bookkeeping": "Escrituração de ICMS",
    "federal_undue_payment": "Pagamento federal indevido",
    "pis": "PIS", "cofins": "COFINS", "icms": "ICMS",
    "requested": "Solicitado", "transmitted": "Transmitido (simulação)",
    "homologated": "Homologado (simulação)", "granted": "Deferido (simulação)",
    "paid": "Pago (simulação)", "cancelled": "Cancelado",
    "rejected": "Rejeitado", "denied": "Indeferido",
}

def _label(path: str) -> str:
    return " / ".join(
        re.sub(r"[a-zA-Z_]+", lambda m: _LABELS.get(m[0], m[0].replace("_", " ")), part)
        for part in path.split(".")
    )


def _display(value: Any) -> str:
    return _VALUES.get(value, _text(value)) if isinstance(value, str) else _text(value)


def _pdf_text(value: Any) -> str:
    return _text(value).encode("cp1252", errors="backslashreplace").decode("cp1252")


def _money(cents: int) -> str:
    whole, rest = divmod(cents, 100)
    return f"R$ {whole:,}".replace(",", ".") + f",{rest:02d}"


def _pdf(payload: dict[str, Any], entries: list[dict[str, Any]]) -> bytes:
    fpdf = importlib.import_module("fpdf")
    pdf = fpdf.FPDF(format="A4")
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(16, 16, 16)
    pdf.set_title("NFCore - Dossie contabil para revisao")
    pdf.set_author("FM NFCore")
    pdf.add_page()

    def line(value: Any) -> None:
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(24, 36, 52)
        pdf.multi_cell(
            w=0, h=5.4, text=_pdf_text(value), new_x="LMARGIN", new_y="NEXT", wrapmode="WORD",
        )

    def section(title: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.set_text_color(15, 69, 127)
        pdf.multi_cell(w=0, h=7, text=_pdf_text(title), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", style="B", size=18)
    pdf.set_text_color(14, 35, 63)
    pdf.multi_cell(
        w=0, h=9, text="FM NFCORE | Dossiê contábil",
        new_x="LMARGIN", new_y="NEXT",
    )
    line(DISCLAIMER)
    section("1. Identificação e proveniência")
    for key, value in _pairs(payload["identification"]):
        line(f"{_label(key)}: {_display(value)}")
    section("2. Memória de cálculo e conclusão preparatória")
    finding = payload["t17"]
    for field, label in (
        ("principal_cents", "Principal"),
        ("adjustment_cents", "SELIC"),
        ("estimated_cents", "Estimativa"),
    ):
        line(f"{label}: {_money(finding[field])} ({finding[field]} centavos)")
    for key, value in _pairs(payload["t16"]):
        line(f"T16 — {_label(key)}: {_display(value)}")
    for key, value in _pairs(finding):
        line(f"T17 — {_label(key)}: {_display(value)}")
    section("3. Base legal revisada")
    for key, value in _pairs(payload["legal"]):
        line(f"{_label(key)}: {_display(value)}")
    section("4. Histórico de simulação")
    ledger = payload["ledger_summary"]
    if ledger is None:
        line("Sem lote T18 registrado para este achado.")
    else:
        for key, value in _pairs(ledger):
            line(f"T18 — {_label(key)}: {_display(value)}")
    cases = payload["cases"]
    if not cases:
        line("Sem caso T19 registrado para este achado.")
    for case in cases:
        line(
            f"Caso {case['case_id']} | {_display(case['status'])} | "
            f"versão {case['version']} | SHA-256 {case['digest']}"
        )
    section("5. Provas e limites")
    line(f"{len(entries)} arquivos de prova/memória. Consulte manifesto.json para SHA-256.")
    line("XMLs originais preservados byte a byte; nunca assinados ou emitidos por este gerador.")
    for key, value in _pairs(payload["opinion"]):
        line(f"{_label(key)}: {_display(value)}")
    pdf.add_page()
    section("6. Revisão e assinatura humana - não preenchida")
    line("Resultado da revisão:  (  ) Aprovar análise  (  ) Rejeitar  (  ) Solicitar ajustes")
    line("Observações do contador:")
    for _ in range(4):
        line("________________________________________________________________________")
    pdf.ln(8)
    line("Nome / CRC: ____________________________________________________________")
    pdf.ln(8)
    line("Assinatura: ____________________________________________________________")
    line("Data: ____ / ____ / ________")
    line("Assinar não efetiva automaticamente restituição, compensação ou emissão.")
    return bytes(pdf.output())


def _xlsx(payload: dict[str, Any], entries: list[dict[str, Any]]) -> bytes:
    ox = importlib.import_module("openpyxl")
    styles = importlib.import_module("openpyxl.styles")
    wb = ox.Workbook()
    wb.remove(wb.active)
    total_rows = 0

    def sheet(
        name: str, rows: Iterator[tuple[Any, ...]],
        headers: tuple[str, ...] = ("Campo", "Valor (centavos exatos quando indicado)"),
        widths: tuple[int, ...] = (52, 90),
    ) -> None:
        nonlocal total_rows
        ws = wb.create_sheet(name)
        ws.append(list(headers))
        for cell in ws[1]:
            cell.font = styles.Font(bold=True, color="FFFFFFFF")
            cell.fill = styles.PatternFill("solid", fgColor="FF163B64")
            cell.alignment = styles.Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        for row in rows:
            total_rows += 1
            if total_rows > MAX_ROWS:
                raise FiscalValidationError("dossier workbook row bound exceeded")
            # Excel supports 15 significant digits; larger integers remain exact text.
            stored = [
                value if type(value) is int and abs(value) <= 999_999_999_999_999
                else _text(value)
                for value in row
            ]
            if any(isinstance(value, str) and len(value) > 32767 for value in stored):
                raise FiscalValidationError("dossier workbook cell bound exceeded")
            ws.append(stored)
            lines = 1
            for cell, width in zip(ws[ws.max_row], widths, strict=True):
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # Never create a formula from source text.
                    cell.number_format = "@"
                    cell.quotePrefix = True
                else:
                    cell.number_format = "0"
                cell.alignment = styles.Alignment(vertical="top", wrap_text=True)
                lines = max(lines, len(textwrap.wrap(str(cell.value), width=max(1, width - 8))))
            ws.row_dimensions[ws.max_row].height = min(409, max(22, lines * 16 + 6))
        ws.freeze_panes = "B2"
        for index, width in enumerate(widths):
            ws.column_dimensions[chr(65 + index)].width = width
        ws.auto_filter.ref = ws.dimensions

    sheet("Resumo", _pairs({
        "aviso": DISCLAIMER, "identificação": payload["identification"],
        "parecer": payload["opinion"],
    }))
    sheet("Memória T16", _pairs(payload["t16"]))
    sheet("Memória T17", _pairs(payload["t17"]))
    sheet("Base legal", _pairs(payload["legal"]))
    sheet("Ledger T18", _pairs(
        payload["ledger_summary"] if payload["ledger_summary"] is not None
        else {"Estado": "Sem lote T18 registrado para este achado."}
    ))
    sheet("Casos T19", _pairs(
        payload["cases"] or {"Estado": "Sem caso T19 registrado para este achado."}
    ))
    sheet(
        "Evidências", ((entry["path"], entry["sha256"], entry["bytes"]) for entry in entries),
        ("Caminho", "SHA-256", "Bytes"), (82, 76, 18),
    )
    stream = io.BytesIO()
    wb.save(stream)
    return stream.getvalue()


def render_package(payload: dict[str, Any], evidence: dict[str, bytes]) -> bytes:
    """One archive; exact XML/input bytes and a non-self-referential hash manifest."""
    if (
        not evidence
        or not any(name.startswith("xml/") and name.endswith(".xml") for name in evidence)
        or any(not _safe_path(name) or not raw for name, raw in evidence.items())
        or any("/" not in name for name in evidence)
        or len(evidence) + 4 > MAX_FILES
        or sum(map(len, evidence.values())) > MAX_TOTAL
    ):
        raise FiscalValidationError("dossier evidence unavailable or exceeds bounds")
    files = dict(evidence)
    files["memoria.json"] = json_bytes(payload)
    entries = [
        {"path": name, "sha256": digest(raw), "bytes": len(raw)}
        for name, raw in sorted(files.items())
    ]
    files["dossie.pdf"] = _pdf(payload, entries)
    files["memoria.xlsx"] = _xlsx(payload, entries)
    manifest = {
        "schema_version": SCHEMA,
        "basis_digest": payload["identification"]["basis_digest"],
        "simulation_only": True,
        "credit_recognized": False,
        "files": [
            {"path": name, "sha256": digest(raw), "bytes": len(raw)}
            for name, raw in sorted(files.items())
        ],
    }
    files["manifesto.json"] = json_bytes(manifest)
    if sum(map(len, files.values())) > MAX_TOTAL:
        raise FiscalValidationError("dossier uncompressed bound exceeded")
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
    result = stream.getvalue()
    if len(result) > MAX_PACKAGE:
        raise FiscalValidationError("dossier archive bound exceeded")
    verify_package(result, payload["identification"]["basis_digest"])
    return result


def verify_package(raw: bytes, basis_digest: str) -> None:
    """Fail closed on corrupt, duplicate, unsafe or missing package members."""
    if not raw or len(raw) > MAX_PACKAGE:
        raise FiscalValidationError("dossier archive bound exceeded")
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                len(names) != len(set(names)) or len(names) > MAX_FILES
                or any(not _safe_path(name) for name in names)
                or sum(info.file_size for info in infos) > MAX_TOTAL
                or not {"manifesto.json", "dossie.pdf", "memoria.xlsx", "memoria.json"}
                <= set(names)
                or not any(name.startswith("xml/") and name.endswith(".xml") for name in names)
            ):
                raise ValueError("invalid dossier package members")
            manifest_raw = archive.read("manifesto.json")
            actual_total = len(manifest_raw)
            manifest = json.loads(manifest_raw)
            if (
                manifest["schema_version"] != SCHEMA
                or manifest["basis_digest"] != basis_digest
                or manifest["simulation_only"] is not True
                or manifest["credit_recognized"] is not False
            ):
                raise ValueError("dossier manifest binding")
            expected = manifest["files"]
            if (
                len(expected) != len(names) - 1
                or {entry["path"] for entry in expected} != set(names) - {"manifesto.json"}
            ):
                raise ValueError("dossier manifest membership")
            for entry in expected:
                content = archive.read(entry["path"])
                actual_total += len(content)
                if actual_total > MAX_TOTAL:
                    raise ValueError("dossier actual uncompressed bound exceeded")
                if len(content) != entry["bytes"] or digest(content) != entry["sha256"]:
                    raise ValueError("dossier member integrity")
            memory = json.loads(archive.read("memoria.json"))
            if (
                digest(json_bytes(memory["basis"])) != basis_digest
                or memory["identification"]["basis_digest"] != basis_digest
                or memory["simulation_only"] is not True
                or memory["credit_recognized"] is not False
            ):
                raise ValueError("dossier memory binding")
            if not archive.read("dossie.pdf").startswith(b"%PDF-"):
                raise ValueError("invalid dossier PDF")
            if not archive.read("memoria.xlsx").startswith(b"PK"):
                raise ValueError("invalid dossier workbook")
    except Exception as exc:
        raise FiscalValidationError("dossier package integrity mismatch") from exc
