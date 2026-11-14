"""Testes da verificacao T2 de bloco completo."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ci"
    / "check_pr_block_completeness.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_pr_block_completeness", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD_BODY = (
    "## Evidência\n"
    + "- [x] Escopo de um único bloco.\n"
    + "- [x] CI verde no HEAD exato.\n"
    + "E2E: percorrido de ponta a ponta no teste de integração.\n"
    + "Classificação: IMPLEMENTED_NOT_CERTIFIED\n"
    + "Detalhes adicionais para ultrapassar o tamanho mínimo. " * 3
)


def test_good_body_passes() -> None:
    assert _load().check_body(GOOD_BODY) == []


def test_empty_body_fails() -> None:
    assert _load().check_body(None) != []
    assert _load().check_body("") != []


def test_unchecked_item_fails() -> None:
    body = GOOD_BODY + "\n- [ ] Falta fazer isto.\n"
    problems = _load().check_body(body)
    assert any("sem marcar" in p for p in problems)


def test_external_blocked_with_reason_does_not_block() -> None:
    body = GOOD_BODY + (
        "\n- [ ] EXTERNAL_BLOCKED: falta o A1 real; "
        "o proprietário fornece pelo cofre.\n"
    )
    assert _load().check_body(body) == []


def test_external_blocked_without_reason_fails() -> None:
    body = GOOD_BODY + "\n- [ ] EXTERNAL_BLOCKED\n"
    problems = _load().check_body(body)
    assert any("sem motivo" in p for p in problems)


def test_external_blocked_short_reason_fails() -> None:
    body = GOOD_BODY + "\n- [ ] EXTERNAL_BLOCKED: depois\n"
    problems = _load().check_body(body)
    assert any("sem motivo" in p for p in problems)


def test_internal_item_still_fails_next_to_external() -> None:
    body = GOOD_BODY + (
        "\n- [ ] EXTERNAL_BLOCKED: falta o A1 real do proprietário.\n"
        "- [ ] Escrever o teste que ainda não existe.\n"
    )
    problems = _load().check_body(body)
    assert any("interno(s)" in p for p in problems)


def test_missing_evidence_statement_fails() -> None:
    body = (
        "Descrição longa sem declarar a prova real do fluxo. " * 8
        + "\n- [x] Item.\n"
    )
    problems = _load().check_body(body)
    assert any("NÃO COMPROVADO" in p for p in problems)


def test_certified_without_ci_link_fails() -> None:
    body = GOOD_BODY.replace(
        "IMPLEMENTED_NOT_CERTIFIED", "DONE_CERTIFIED_INTERNAL"
    )
    problems = _load().check_body(body)
    assert any("link de execução" in p for p in problems)


def test_certified_with_ci_link_passes() -> None:
    body = GOOD_BODY.replace(
        "IMPLEMENTED_NOT_CERTIFIED", "DONE_CERTIFIED_INTERNAL"
    ) + "\nCI: https://github.com/o/r/actions/runs/123456\n"
    assert _load().check_body(body) == []
