"""The container build and the Python adapter pin the same official commit."""
from __future__ import annotations

from pathlib import Path

from kordena_fiscal.tax.rfb_simples_calculator import SIMPLES_CALCULATOR_PIN

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_builds_the_pinned_commit_and_compose_publishes_no_port() -> None:
    dockerfile = (ROOT / "deploy/rfb/simples/Dockerfile").read_text(encoding="utf-8")
    assert f"ARG RFB_COMMIT={SIMPLES_CALCULATOR_PIN.commit}" in dockerfile
    assert 'test "$(git rev-parse HEAD)" = "$RFB_COMMIT"' in dockerfile
    assert "USER rtc" in dockerfile
    compose = (ROOT / "deploy/contabo/compose.rtc-simples.opt-in.yml").read_text(encoding="utf-8")
    assert "ports:" not in compose
    assert "read_only: true" in compose
    assert SIMPLES_CALCULATOR_PIN.commit[:8] in compose
