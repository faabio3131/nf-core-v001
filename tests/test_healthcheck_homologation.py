"""No external network is needed to certify the homologation healthcheck gate."""

from __future__ import annotations

import ssl
import sys
from email.message import Message
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "healthcheck_homologation.py"
_SPEC = spec_from_file_location("nfcore_healthcheck_homologation", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
healthcheck = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = healthcheck  # dataclasses needs the module registered to resolve types
_SPEC.loader.exec_module(healthcheck)
HomologationTarget = healthcheck.HomologationTarget
check_tls_reachable = healthcheck.check_tls_reachable
run_healthcheck = healthcheck.run_healthcheck
resolve_homologation_targets = healthcheck.resolve_homologation_targets


def _targets(*, paulistana_url: str | None = None) -> tuple[Any, ...]:
    return (
        HomologationTarget(
            name="sefaz_nfe_sp_authorize", url="https://example.invalid/a", source="s1",
        ),
        HomologationTarget(
            name="nfse_nacional_sefin", url="https://example.invalid/b", source="s2",
        ),
        HomologationTarget(name="nota_paulistana", url=paulistana_url, source="s3"),
    )


def test_resolve_homologation_targets_only_pins_integrated_endpoints() -> None:
    targets = resolve_homologation_targets()
    by_name = {target.name: target for target in targets}
    assert by_name["sefaz_nfe_sp_authorize"].url == (
        "https://homologacao.nfe.fazenda.sp.gov.br/ws/nfeautorizacao4.asmx"
    )
    assert by_name["nfse_nacional_sefin"].url == (
        "https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional/nfse"
    )
    # Nota Paulistana has no integrated live transport client yet; never guessed.
    assert by_name["nota_paulistana"].url is None


def test_check_tls_reachable_rejects_non_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        check_tls_reachable("http://example.invalid/x")


def test_check_tls_reachable_treats_http_error_as_reachable() -> None:
    with patch.object(healthcheck, "urlopen", side_effect=HTTPError(
        "https://example.invalid", 500, "boom", Message(), None
    )):
        result = check_tls_reachable("https://example.invalid")
    assert result == {"status": "REACHABLE", "http_status": 500}


def test_check_tls_reachable_reports_tls_failure() -> None:
    with patch.object(healthcheck, "urlopen", side_effect=ssl.SSLError("bad cert")):
        result = check_tls_reachable("https://example.invalid")
    assert result["status"] == "TLS_FAILED"


def test_check_tls_reachable_reports_unreachable() -> None:
    with patch.object(healthcheck, "urlopen", side_effect=URLError("no route")):
        result = check_tls_reachable("https://example.invalid")
    assert result["status"] == "UNREACHABLE"


def test_run_healthcheck_all_pinned_reachable() -> None:
    def fake_check(url: str, *, timeout: float = 8.0) -> dict[str, object]:
        return {"status": "REACHABLE", "http_status": 200}

    with patch.object(healthcheck, "check_tls_reachable", side_effect=fake_check):
        result = run_healthcheck(_targets())
    assert result["all_pinned_reachable"] is True
    assert result["not_pinned"] == ["nota_paulistana"]
    assert result["targets"]["nota_paulistana"]["status"] == "NOT_PINNED"


def test_run_healthcheck_fails_closed_on_one_unreachable_pinned_target() -> None:
    def fake_check(url: str, *, timeout: float = 8.0) -> dict[str, object]:
        if "a" in url.rsplit("/", 1)[-1]:
            return {"status": "UNREACHABLE", "detail": "timeout"}
        return {"status": "REACHABLE", "http_status": 200}

    with patch.object(healthcheck, "check_tls_reachable", side_effect=fake_check):
        result = run_healthcheck(_targets())
    assert result["all_pinned_reachable"] is False


def test_run_healthcheck_never_probes_a_target_with_no_pinned_url() -> None:
    with patch.object(healthcheck, "check_tls_reachable") as probe:
        probe.return_value = {"status": "REACHABLE", "http_status": 200}
        run_healthcheck(_targets(paulistana_url=None))
    assert probe.call_count == 2  # the two pinned targets only, never Nota Paulistana
    probed_urls = {call.args[0] for call in probe.call_args_list}
    assert probed_urls == {"https://example.invalid/a", "https://example.invalid/b"}


def test_main_require_all_pinned_reachable_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    def fake_run(
        targets: tuple[Any, ...] | None = None, *, timeout: float = 8.0,
    ) -> dict[str, object]:
        return {
            "targets": {}, "not_pinned": [], "all_pinned_reachable": False, "limitations": [],
        }

    with patch.object(healthcheck, "run_healthcheck", side_effect=fake_run):
        with patch("sys.argv", ["healthcheck_homologation.py", "--require-all-pinned-reachable"]):
            exit_code = healthcheck.main()
    assert exit_code == 1
    assert "all_pinned_reachable" in capsys.readouterr().out
