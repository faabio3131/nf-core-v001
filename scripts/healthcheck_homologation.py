"""Pre-flight TLS reachability check for homologation (tpAmb=2) webservices.

Run this before promoting an environment to production fiscal mode
(tpAmb=1). It only confirms that the pinned, official homologation
endpoints that NFCore actually integrates are reachable over TLS from the
current host -- it never submits a fiscal document, never requires an A1
certificate, and never authenticates. A green result here is a network
pre-condition, not proof of fiscal authorization, provider homologation,
or operational readiness; it does not replace per-tenant certification.

Only endpoints already pinned elsewhere in the codebase are checked --
this script never invents or guesses a webservice URL. Where NFCore has
no integrated live transport client yet for an authority (currently: Nota
Paulistana -- `gateway/nfse_paulistana_envelope.py` only builds the XML
envelope; there is no HTTP client wired to a transactional endpoint), the
target is reported as ``NOT_PINNED`` rather than probed, so this script
can never be mistaken for having validated that authority's connectivity.
"""
from __future__ import annotations

import argparse
import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from kordena_fiscal.control_plane.sefaz_endpoint_catalog import (
    SefazService,
    resolve_sefaz_endpoint,
)
from kordena_fiscal.domain import BrazilianJurisdiction, FiscalDocumentKind, FiscalEnvironment
from kordena_fiscal.gateway.nfse_national_homologation import SEFIN_HOMOLOGATION_NFSE_URL

_SP_IBGE = "35"


@dataclass(frozen=True, slots=True)
class HomologationTarget:
    name: str
    url: str | None
    source: str


def resolve_homologation_targets() -> tuple[HomologationTarget, ...]:
    """Only pinned, already-integrated endpoints -- never a guessed URL."""
    nfe_sp = resolve_sefaz_endpoint(
        state_ibge_code=_SP_IBGE,
        document_kind=FiscalDocumentKind.NFE,
        environment=FiscalEnvironment.HOMOLOGATION,
        service=SefazService.AUTHORIZE,
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
    )
    return (
        HomologationTarget(
            name="sefaz_nfe_sp_authorize",
            url=nfe_sp.url,
            source=nfe_sp.source_url,
        ),
        HomologationTarget(
            name="nfse_nacional_sefin",
            url=SEFIN_HOMOLOGATION_NFSE_URL,
            source="gateway/nfse_national_homologation.py",
        ),
        HomologationTarget(
            name="nota_paulistana",
            url=None,
            source=(
                "no transactional webservice endpoint is pinned in code yet -- "
                "gateway/nfse_paulistana_envelope.py only builds the XML envelope"
            ),
        ),
    )


def _bare_https_origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
    ):
        raise ValueError("homologation target must be a plain HTTPS URL")
    return url


def check_tls_reachable(url: str, *, timeout: float = 8.0) -> dict[str, object]:
    """TLS/TCP reachability only: an HTTP error status still proves TLS worked."""
    target = _bare_https_origin(url)
    request = Request(target, headers={"Cache-Control": "no-cache"}, method="GET")
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return {"status": "REACHABLE", "http_status": response.status}
    except HTTPError as exc:
        # The server answered over TLS; a non-200 status is still reachability.
        return {"status": "REACHABLE", "http_status": exc.code}
    except ssl.SSLError as exc:
        return {"status": "TLS_FAILED", "detail": str(exc)}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "UNREACHABLE", "detail": str(exc)}


def run_healthcheck(
    targets: tuple[HomologationTarget, ...] | None = None, *, timeout: float = 8.0,
) -> dict[str, object]:
    resolved = targets if targets is not None else resolve_homologation_targets()
    results: dict[str, dict[str, object]] = {}
    for target in resolved:
        if target.url is None:
            results[target.name] = {"status": "NOT_PINNED", "detail": target.source}
            continue
        results[target.name] = {
            **check_tls_reachable(target.url, timeout=timeout),
            "url": target.url,
            "source": target.source,
        }
    pinned = {name: result for name, result in results.items() if result["status"] != "NOT_PINNED"}
    not_pinned = [name for name, result in results.items() if result["status"] == "NOT_PINNED"]
    all_pinned_reachable = bool(pinned) and all(
        result["status"] == "REACHABLE" for result in pinned.values()
    )
    return {
        "targets": results,
        "not_pinned": not_pinned,
        "all_pinned_reachable": all_pinned_reachable,
        "limitations": [
            "TLS reachability only; no fiscal document is submitted and no A1 "
            "certificate is used.",
            "A green result is a network pre-condition, not proof of fiscal "
            "authorization or provider homologation.",
            "Targets listed under 'not_pinned' have no integrated live transport "
            "yet and were not probed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Non-destructive TLS reachability check for homologation webservices"
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--require-all-pinned-reachable",
        action="store_true",
        help="Exit 1 unless every pinned endpoint is REACHABLE.",
    )
    args = parser.parse_args()
    result = run_healthcheck(timeout=args.timeout)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    if args.require_all_pinned_reachable and result["all_pinned_reachable"] is not True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
