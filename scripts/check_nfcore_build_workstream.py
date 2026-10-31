#!/usr/bin/env python3
"""Guard structure/order/evidence of subordinate NFCore BUILD-ONLY workstream.

This checks repository text, NOT GitHub CI or Railway runtime. No external I/O,
no client data, no secrets; external evidence must still be checked by executor.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md"
LEDGER = ROOT / "docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md"
PATTERN = re.compile(r"^### NFV1-BLD-(\d{2}) — (.+)$", re.M)
STATUS = re.compile(r"^- \*\*Estado:\*\* (.+)$", re.M)
PROOF = re.compile(r"^- \*\*Evidência final:\*\* (.+)$", re.M)
ALLOWED = {
    "PENDING", "IN_PROGRESS", "BLOCKED_HUMAN_ACTION", "BLOCKED_EXTERNAL",
    "DONE", "ALREADY_INTEGRATED",
}
PR = re.compile(r"(?:PR\s*#\d+|/pull/\d+)", re.I)
CI = re.compile(r"(?:CI\s*#\d+|CI\s*\S*SUCCESS|/actions/runs/\d+)", re.I)
SHA = re.compile(r"\b[a-f0-9]{40}\b", re.I)


def assess(plan: str, ledger: str) -> list[str]:
    errors: list[str] = []
    plan_ids = [m.group(1) for m in PATTERN.finditer(plan)]
    entries = list(PATTERN.finditer(ledger))
    ledger_ids = [m.group(1) for m in entries]
    if plan_ids != [f"{i:02d}" for i in range(10)]:
        errors.append("anexo BUILD exige IDs BLD-00..09 completos e em ordem")
    if ledger_ids != plan_ids:
        errors.append("ledger BUILD e anexo possuem IDs divergentes, repetidos ou fora de ordem")
    if not plan.startswith("# FM NFCORE V1 — Anexo"):
        errors.append("anexo BUILD não identificado")
    if "não substitui" not in ledger.lower():
        errors.append("ledger BUILD deve preservar cronograma mestre")
    if "EM_EXECUCAO" not in ledger:
        errors.append("ledger BUILD deve identificar trilha EM_EXECUCAO")

    active = 0
    seen_open = False
    for i, match in enumerate(entries):
        body = ledger[match.end():entries[i + 1].start() if i + 1 < len(entries)
                      else ledger.find("\n## Checkpoint permanente", match.end())
                      if "\n## Checkpoint permanente" in ledger[match.end():]
                      else len(ledger)]
        state_match = STATUS.search(body)
        proof_match = PROOF.search(body)
        key = f"BLD-{match.group(1)}"
        if not state_match:
            errors.append(f"{key}: Estado ausente")
            continue
        state = state_match.group(1).strip()
        if state not in ALLOWED:
            errors.append(f"{key}: estado inválido {state}")
        if not proof_match:
            errors.append(f"{key}: Evidência final ausente")
        if "- **Depende de:**" not in body or "- **CURRENT:**" not in body:
            errors.append(f"{key}: predecessores e CURRENT obrigatórios")
        if state == "IN_PROGRESS":
            active += 1
        if state in {"DONE", "ALREADY_INTEGRATED"}:
            if seen_open:
                errors.append(f"{key}: tentativa de pular tarefa anterior pendente")
            proof = proof_match.group(1).strip() if proof_match else ""
            if not (PR.search(proof) and CI.search(proof) and SHA.search(proof)):
                errors.append(f"{key}: conclusão requer PR, CI e SHA reais na evidência")
            if "PENDENTE" in proof:
                errors.append(f"{key}: evidência ainda está PENDENTE")
        else:
            # An operator-blocked task is not done. Independent internal work
            # can still continue in a branch; no later DONE until reconciled.
            seen_open = True
    if active > 1:
        errors.append("mais de um bloco BUILD em execução")
    return errors


def main() -> int:
    if not PLAN.exists() or not LEDGER.exists():
        print("ERRO: anexo ou ledger BUILD ausente")
        return 1
    errors = assess(PLAN.read_text(encoding="utf-8"), LEDGER.read_text(encoding="utf-8"))
    for error in errors:
        print("ERRO:", error)
    if not errors:
        ledger = LEDGER.read_text(encoding="utf-8")
        next_id = next(
            (m.group(1) for m in PATTERN.finditer(ledger)
             if not (lambda x: x and x.group(1) in {"DONE", "ALREADY_INTEGRATED"})
             (STATUS.search(ledger[m.end():ledger.find("\n### NFV1-BLD-", m.end())
                if ledger.find("\n### NFV1-BLD-", m.end()) >= 0
                else len(ledger)]))),
            None,
        )
        print(f"OK: 10 blocos BUILD, primeiro aberto BLD-{next_id or 'NONE'}; "
              "validação estrutural, não prova de runtime")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
