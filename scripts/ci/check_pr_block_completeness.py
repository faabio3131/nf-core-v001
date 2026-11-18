"""T2: verifica se uma PR marcada como pronta tem o bloco completo.

Le o evento do GitHub Actions (``GITHUB_EVENT_PATH``). Em Draft nao
reprova. Fora de Draft reprova quando a descricao:

* esta vazia ou curta demais;
* tem item de checklist interno sem marcar;
* tem item externo sem motivo (``EXTERNAL_BLOCKED: <motivo>``);
* nao declara prova de ponta a ponta nem ``NAO COMPROVADO``;
* se classifica como certificada sem link de execucao de CI.

Pendencia externa (certificado A1 real, homologacao de prefeitura ou
SEFAZ, decisao de terceiro) nao bloqueia o fechamento do bloco. Ela e
registrada como item sem marcar na forma
``- [ ] EXTERNAL_BLOCKED: <o que falta e quem resolve>`` e fica fora da
contagem de pendencias internas. Pendencia de codigo, teste ou
documentacao e sempre interna.

A descricao e dado nao confiavel: so e lida, nunca executada.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

UNCHECKED_LINE = re.compile(r"^\s*[-*]\s+\[ \](.*)$", re.MULTILINE)
EXTERNAL_WITH_REASON = re.compile(
    r"^\s*EXTERNAL_BLOCKED\s*:\s*\S.{14,}$"
)
EXTERNAL_PREFIX = "EXTERNAL_BLOCKED"
CERTIFIED = re.compile(r"DONE_CERTIFIED_(INTERNAL|OPERATIONAL)")
RUN_URL = re.compile(r"https://github\.com/[^\s)]+/actions/runs/\d+")
EVIDENCE_TOKENS = (
    "e2e",
    "ponta a ponta",
    "não comprovado",
    "nao comprovado",
)
MIN_BODY_CHARS = 200
FILES_WARNING_THRESHOLD = 40


def classify_unchecked(text: str) -> tuple[int, int]:
    """Conta itens sem marcar: (internos, externos sem motivo)."""
    internal = 0
    external_without_reason = 0
    for match in UNCHECKED_LINE.finditer(text):
        item = match.group(1)
        if item.strip().startswith(EXTERNAL_PREFIX):
            if not EXTERNAL_WITH_REASON.match(item):
                external_without_reason += 1
        else:
            internal += 1
    return internal, external_without_reason


def check_body(body: str | None) -> list[str]:
    """Devolve a lista de problemas da descricao; vazia significa OK."""
    text = body or ""
    problems: list[str] = []
    if len(text.strip()) < MIN_BODY_CHARS:
        problems.append(
            "Descrição vazia ou curta demais: preencha o modelo de PR."
        )
    internal, external_bad = classify_unchecked(text)
    if internal:
        problems.append(
            f"{internal} item(ns) interno(s) do checklist sem marcar. "
            "PR pronta exige o checklist interno 100% marcado. "
            "Só pendência realmente externa pode ficar de fora, "
            "como: - [ ] EXTERNAL_BLOCKED: <o que falta e quem resolve>."
        )
    if external_bad:
        problems.append(
            f"{external_bad} item(ns) EXTERNAL_BLOCKED sem motivo. "
            "Escreva o que falta e quem resolve "
            "(mínimo de 15 caracteres após os dois pontos)."
        )
    lowered = text.lower()
    if not any(token in lowered for token in EVIDENCE_TOKENS):
        problems.append(
            "Declare a prova de ponta a ponta (E2E) ou escreva "
            "NÃO COMPROVADO onde faltar evidência."
        )
    if CERTIFIED.search(text) and not RUN_URL.search(text):
        problems.append(
            "Classificação certificada sem link de execução de CI "
            "(.../actions/runs/<id>). Sem evidência: "
            "IMPLEMENTED_NOT_CERTIFIED."
        )
    return problems


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("::error::GITHUB_EVENT_PATH ausente.")
        return 1
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not pr:
        print("::notice::Evento sem pull_request; nada a verificar.")
        return 0
    changed = pr.get("changed_files") or 0
    if changed > FILES_WARNING_THRESHOLD:
        print(
            f"::warning::PR com {changed} arquivos alterados. "
            "Considere dividir o bloco em sub-blocos."
        )
    if pr.get("draft"):
        print("::notice::PR em Draft: verificação T2 não aplicada.")
        return 0
    problems = check_body(pr.get("body"))
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(
            "Volte a PR para Draft até o bloco estar completo "
            "(regra: um bloco, uma PR)."
        )
        return 1
    print("Bloco completo: descrição e checklist conferem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
