"""No external network is needed to certify the Contabo pilot preflight gate."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pilot_contabo_preflight.py"
_SPEC = spec_from_file_location("nfcore_pilot_preflight", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
pilot_preflight = module_from_spec(_SPEC)
_SPEC.loader.exec_module(pilot_preflight)
_https_origin = pilot_preflight._https_origin
assess_pilot = pilot_preflight.assess_pilot
run_preflight = pilot_preflight.run_preflight


def _profile() -> dict[str, object]:
    return {
        "human_identity_configured": True,
        "portal_executor_configured": True,
        "persistence_backend": "postgres",
        "password_recovery_configured": True,
        "password_reset_delivery_configured": True,
        "fiscal_operation_handlers_configured": ["queryArchiveReference"],
        "fiscal_provider_transport_real_configured": False,
        "fiscal_external_secret_client_configured": False,
        "fiscal_signer_configured": False,
        "fiscal_runtime_external_execution_ready": False,
        "pricing_catalog_published": False,
        "commercial_checkout_processing_configured": False,
    }


def _assess(profile: dict[str, object] | None = None, *, deployed: bool = True):
    return assess_pilot(
        portal_status=200,
        portal_html="<title>NFCore</title>",
        bootstrap_status=401,
        script_status=200,
        portal_script=(
            'const navigation = [["tax-reform"]]; appendRtcIssuerSummary()'
            if deployed else "const navigation = []"
        ),
        live={"status": "live"},
        ready={"status": "ready"},
        profile=_profile() if profile is None else profile,
    )


def test_web_pilot_does_not_require_payment_or_official_fiscal_issuance() -> None:
    report = _assess()
    assert report["web_pilot_ready"] is True
    assert report["fiscal_provider_ready"] is False
    assert report["public_sales_ready"] is False
    assert report["fiscal_provider_gate"] == "EXTERNAL_EVIDENCE_REQUIRED"


def test_legacy_deployment_is_not_classified_as_current_web_pilot() -> None:
    report = _assess(deployed=False)
    assert report["web_pilot_ready"] is False
    assert report["web_checks"]["rtc09_portal_deployed"] is False


def test_auth_bypass_or_missing_identity_fails_closed() -> None:
    profile = _profile()
    profile["human_identity_configured"] = False
    report = _assess(profile)
    assert report["web_pilot_ready"] is False
    assert report["web_checks"]["session_identity_wired"] is False
    report_unprotected = assess_pilot(
        portal_status=200,
        portal_html="NFCore",
        bootstrap_status=200,
        script_status=200,
        portal_script='"tax-reform" appendRtcIssuerSummary',
        live={"status": "live"},
        ready={"status": "ready"},
        profile=_profile(),
    )
    assert report_unprotected["web_pilot_ready"] is False
    assert report_unprotected["web_checks"]["login_protected"] is False


def test_official_fiscal_gate_requires_transport_secrets_signing_and_handler() -> None:
    profile = _profile()
    for key in (
        "fiscal_provider_transport_real_configured",
        "fiscal_external_secret_client_configured",
        "fiscal_signer_configured",
        "fiscal_runtime_external_execution_ready",
    ):
        profile[key] = True
    assert _assess(profile)["fiscal_provider_ready"] is False
    profile["fiscal_operation_handlers_configured"] = ["issueFiscalDocument"]
    report = _assess(profile)
    assert report["fiscal_provider_ready"] is True
    assert report["fiscal_provider_gate"] == "CONFIGURED_NOT_HOMOLOGATED"


@pytest.mark.parametrize(
    "url",
    [
        "http://app.nfcore.com.br",
        "https://user:pass@app.nfcore.com.br",
        "https://app.nfcore.com.br/evil",
        "https://app.nfcore.com.br/?token=secret",
        "https://app.nfcore.com.br/#fragment",
    ],
)
def test_reject_non_https_or_credential_bearing_pilot_origins(url: str) -> None:
    with pytest.raises(ValueError):
        _https_origin(url)


def test_endpoint_probe_uses_expected_read_only_routes_and_never_posts() -> None:
    calls: list[str] = []
    results = {
        "/": (200, "NFCore"),
        "/v1/portal/bootstrap": (401, ""),
        "/app.js": (200, '"tax-reform" appendRtcIssuerSummary'),
        "/health/live": (200, '{"status":"live"}'),
        "/health/ready": (200, '{"status":"ready"}'),
        "/runtime/profile": (200, '{"human_identity_configured":true,'
                             '"portal_executor_configured":true,'
                             '"persistence_backend":"postgres",'
                             '"password_recovery_configured":true,'
                             '"password_reset_delivery_configured":true}'),
    }

    def fake_probe(url: str, *, max_bytes: int = 131072) -> tuple[int, str]:
        calls.append(url)
        for path in sorted(results, key=len, reverse=True):
            if url.endswith(path):
                return results[path]
        raise AssertionError(url)

    with patch.object(pilot_preflight, "_probe", side_effect=fake_probe):
        result = run_preflight("https://app.nfcore.com.br", "https://api.nfcore.com.br")
    assert result["web_pilot_ready"] is True
    assert len(calls) == 6
    assert all(url.startswith("https://") for url in calls)
    assert all("tenant" not in url and "token" not in url for url in calls)


def test_production_promotion_pr_gets_same_quality_gate_as_main() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    trigger = workflow.split("  pull_request:", 1)[1].split("  push:", 1)[0]
    assert "      - main" in trigger
    assert "      - production" in trigger
