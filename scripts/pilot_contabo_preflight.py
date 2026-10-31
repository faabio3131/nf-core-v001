"""Read-only NFCore Contabo pilot preflight; never authenticates or issues fiscal actions.

A healthy health endpoint is not evidence of fiscal provider readiness, nor of
the deployed Portal matching the integrated HEAD. The report never exposes
returned secrets, request bodies, tenant identifiers or personal information.
"""

from __future__ import annotations

import argparse
import json
import ssl
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _https_origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("pilot origin must be a bare HTTPS hostname")
    return url.rstrip("/")


def _probe(url: str, *, max_bytes: int = 131072) -> tuple[int, str]:
    """No credentials, no cache, no method other than GET, bounded response."""
    request = Request(
        url,
        headers={"Cache-Control": "no-cache", "Accept": "application/json, text/plain, */*"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=8, context=ssl.create_default_context()) as response:
            code = response.status
            body = response.read(max_bytes + 1)
    except HTTPError as exc:
        # Only the status is required from protected endpoints.
        return exc.code, ""
    except (URLError, TimeoutError, OSError):
        return 0, ""
    if len(body) > max_bytes:
        return 0, ""
    return code, body.decode("utf-8", errors="replace")


def _json_object(status: int, body: str) -> dict[str, Any]:
    if status != 200:
        return {}
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def assess_pilot(
    *,
    portal_status: int,
    portal_html: str,
    bootstrap_status: int,
    script_status: int,
    portal_script: str,
    live: Mapping[str, Any],
    ready: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, object]:
    """Separate safe internal Web pilot from official fiscal execution and sales."""
    checks: dict[str, bool] = {
        "portal_reachable": portal_status == 200 and "NFCore" in portal_html,
        "api_live": live.get("status") == "live",
        "api_ready": ready.get("status") == "ready",
        "login_protected": bootstrap_status == 401,
        "session_identity_wired": profile.get("human_identity_configured") is True,
        "portal_executor_wired": profile.get("portal_executor_configured") is True,
        "postgres_persistence": profile.get("persistence_backend") == "postgres",
        "password_recovery_wired": profile.get("password_recovery_configured") is True,
        "password_delivery_wired": profile.get("password_reset_delivery_configured") is True,
        "rtc09_portal_deployed": (
            script_status == 200
            and '"tax-reform"' in portal_script
            and "appendRtcIssuerSummary" in portal_script
        ),
    }
    fiscal_provider = (
        profile.get("fiscal_provider_transport_real_configured") is True
        and profile.get("fiscal_external_secret_client_configured") is True
        and profile.get("fiscal_signer_configured") is True
        and profile.get("fiscal_runtime_external_execution_ready") is True
    )
    handlers = profile.get("fiscal_operation_handlers_configured")
    fiscal_handlers = (
        isinstance(handlers, list)
        and all(isinstance(item, str) for item in handlers)
        and any(item in ("issueFiscalDocument", "cancelFiscalDocument", "inutilizeFiscalRange")
                for item in handlers)
    )
    billing = (
        profile.get("pricing_catalog_published") is True
        and profile.get("commercial_checkout_processing_configured") is True
    )
    return {
        "classification": "INTERNAL_WEB_PILOT_PREFLIGHT",
        "web_checks": checks,
        "web_pilot_ready": all(checks.values()),
        "fiscal_provider_ready": fiscal_provider and fiscal_handlers,
        "fiscal_provider_gate": "EXTERNAL_EVIDENCE_REQUIRED" if not (
            fiscal_provider and fiscal_handlers
        ) else "CONFIGURED_NOT_HOMOLOGATED",
        "public_sales_ready": billing,
        "public_sales_gate": "CONFIGURATION_REQUIRED" if not billing else "CHECK_EXTERNALLY",
        "limitations": [
            "No authenticated customer journey is proven by this unauthenticated check.",
            "No provider homologation, fiscal authorization, backup or production "
            "approval is inferred.",
        ],
    }


def run_preflight(portal_origin: str, api_origin: str) -> dict[str, object]:
    portal = _https_origin(portal_origin)
    api = _https_origin(api_origin)
    portal_status, portal_html = _probe(portal + "/")
    bootstrap_status, _ = _probe(portal + "/v1/portal/bootstrap")
    script_status, portal_script = _probe(portal + "/app.js")
    live_code, live_text = _probe(api + "/health/live")
    ready_code, ready_text = _probe(api + "/health/ready")
    profile_code, profile_text = _probe(api + "/runtime/profile")
    return assess_pilot(
        portal_status=portal_status,
        portal_html=portal_html,
        bootstrap_status=bootstrap_status,
        script_status=script_status,
        portal_script=portal_script,
        live=_json_object(live_code, live_text),
        ready=_json_object(ready_code, ready_text),
        profile=_json_object(profile_code, profile_text),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructive Web pilot preflight")
    parser.add_argument("--portal", default="https://app.nfcore.com.br")
    parser.add_argument("--api", default="https://api.nfcore.com.br")
    parser.add_argument("--require-web", action="store_true")
    parser.add_argument("--require-fiscal-provider", action="store_true")
    args = parser.parse_args()
    try:
        result = run_preflight(args.portal, args.api)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    if args.require_web and result["web_pilot_ready"] is not True:
        return 1
    if args.require_fiscal_provider and result["fiscal_provider_ready"] is not True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
