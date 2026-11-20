"""Container builds, the database build and the Python adapters pin the same commits."""
from __future__ import annotations

from pathlib import Path

from kordena_fiscal.tax.rfb_regime_regular_calculator import (
    CALCULATOR_DATABASE_VERSION,
    REGIME_REGULAR_CALCULATOR_PIN,
)
from kordena_fiscal.tax.rfb_simples_calculator import SIMPLES_CALCULATOR_PIN

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfiles_build_the_pinned_commits_as_non_root() -> None:
    for path, pin in (("deploy/rfb/simples/Dockerfile", SIMPLES_CALCULATOR_PIN),
                      ("deploy/rfb/regime-regular/Dockerfile", REGIME_REGULAR_CALCULATOR_PIN)):
        dockerfile = _read(path)
        assert f"ARG RFB_COMMIT={pin.commit}" in dockerfile
        assert 'test "$(git rev-parse HEAD)" = "$RFB_COMMIT"' in dockerfile
        assert "USER rtc" in dockerfile and "UseBASE64Intrinsics" in dockerfile


def test_database_is_generated_from_the_regime_regular_pin_and_checked() -> None:
    dockerfile = _read("deploy/rfb/database/Dockerfile")
    assert f"ARG RFB_COMMIT={REGIME_REGULAR_CALCULATOR_PIN.commit}" in dockerfile
    assert f"ARG RFB_DB_VERSION={CALCULATOR_DATABASE_VERSION}" in dockerfile
    assert "flyway_schema_history where success = 0" in dockerfile


def test_compose_publishes_no_port_and_mounts_the_database_read_only() -> None:
    compose = _read("deploy/contabo/compose.rtc-calculators.opt-in.yml")
    assert "ports:" not in compose and "read_only: true" in compose
    assert SIMPLES_CALCULATOR_PIN.commit[:8] in compose
    assert REGIME_REGULAR_CALCULATOR_PIN.commit[:8] in compose
