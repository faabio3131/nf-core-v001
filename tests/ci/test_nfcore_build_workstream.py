"""Negative governance regressions for NFV1 BUILD-ONLY execution."""
from __future__ import annotations

import re
from pathlib import Path
from runpy import run_path

# CI installs only src/, not scripts/ as an importable package.
script = Path(__file__).resolve().parents[2] / "scripts/check_nfcore_build_workstream.py"
module = run_path(str(script))
ROOT = module["ROOT"]
assess = module["assess"]


def inputs() -> tuple[str, str]:
    return (
        (ROOT / "docs/NFCORE_V1_BUILD_INTEGRATION_EXECUTION_2026-10-18.md")
        .read_text(encoding="utf-8"),
        (ROOT / "docs/NFCORE_V1_BUILD_INTEGRATION_LEDGER.md")
        .read_text(encoding="utf-8"),
    )


def scenario() -> tuple[str, str]:
    """Synthetic ledger for negative cases, independent of live delivery progress."""
    plan, _ = inputs()
    entries = ["# Synthetic ledger — não substitui o cronograma mestre", "EM_EXECUCAO"]
    for index, heading in enumerate(re.findall(r"^### NFV1-BLD-.*$", plan, re.M)):
        state = "DONE" if index < 2 else "IN_PROGRESS" if index == 2 else "PENDING"
        proof = "PR #1; CI SUCCESS; " + "a" * 40 if index < 2 else "PENDENTE"
        entries.append(
            f"{heading}\n- **Estado:** {state}\n- **Depende de:** anterior\n"
            f"- **CURRENT:** cenário sintético\n- **Evidência final:** {proof}\n"
        )
    return plan, "\n\n".join(entries)


def test_current_build_ledger_is_structurally_valid() -> None:
    plan, ledger = inputs()
    assert not assess(plan, ledger)
    assert len(re.findall(r"^### NFV1-BLD-", ledger, re.M)) == 9
    assert "CONSTRUCTION_AND_WEB_INTEGRATION_COMPLETE" in plan


def test_no_missing_or_reordered_build_block() -> None:
    plan, ledger = inputs()
    assert assess(plan, ledger.replace("### NFV1-BLD-03", "### NFV1-BLD-13", 1))
    assert assess(plan.replace("### NFV1-BLD-06", "### NFV1-BLD-03", 1), ledger)


def test_cannot_skip_missing_work_with_ci_or_fake_evidence() -> None:
    plan, ledger = scenario()
    assert not assess(plan, ledger)
    changed = ledger.replace("- **Estado:** PENDING", "- **Estado:** DONE", 1)
    assert changed != ledger
    assert any("pular tarefa anterior" in x for x in assess(plan, changed))
    assert any("requer PR, CI e SHA" in x for x in assess(plan, changed))


def test_rejects_duplicate_concurrent_work_or_missing_proof() -> None:
    plan, ledger = scenario()
    assert not assess(plan, ledger)
    active = ledger.replace("- **Estado:** PENDING", "- **Estado:** IN_PROGRESS", 1)
    assert any("mais de um bloco" in x for x in assess(plan, active))
    missing = re.sub(
        r"(### NFV1-BLD-00[\s\S]*?)- \*\*Evidência final:\*\*.*",
        r"\1- **Sem evidência:** AUSENTE",
        ledger,
        count=1,
    )
    assert any("Evidência final ausente" in x for x in assess(plan, missing))
