"""Explicitly provisioned Extrema WebISS SOAP 1.1 homologation transport.

A configured URL is never selected from portal input or invoice XML.
No migration, retry, secret logging, provider auto-discovery or production route.
Only an operator-approved exact municipal homologation endpoint can enable it.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.mg_webiss_soap import EXTREMA_WEBISS_HOMOLOGATION_URL

_MAX_SOAP_BYTES = 2_097_152


class ExtremaWebissNetworkError(FiscalValidationError):
    """Sanitized uncertain SOAP delivery; mutations must be reconciled first."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self, request: Request, fp: object, code: int, msg: str,
        headers: Mapping[str, str], newurl: str,
    ) -> None:
        raise ExtremaWebissNetworkError("WebISS redirect forbidden")


def build_extrema_webiss_exchange(
    environ: Mapping[str, str],
) -> Callable[[bytes, str, ssl.SSLContext, float], bytes] | None:
    """Stay disabled unless the exact reviewed 2026 homologation address is set."""
    configured = environ.get("NFCORE_EXTREMA_WEBISS_HOMOLOGATION_URL", "")
    if not configured:
        return None
    if configured != EXTREMA_WEBISS_HOMOLOGATION_URL:
        raise FiscalValidationError("Unapproved Extrema WebISS homologation endpoint")

    def exchange(
        body: bytes, soap_action: str, context: ssl.SSLContext, timeout: float,
    ) -> bytes:
        if (
            not isinstance(body, bytes)
            or not 0 < len(body) <= _MAX_SOAP_BYTES
            or not isinstance(context, ssl.SSLContext)
            or not isinstance(soap_action, str)
            or not soap_action.startswith('"http://nfse.abrasf.org.br/')
            or not soap_action.endswith('"')
            or not isinstance(timeout, (float, int))
            or not 0 < timeout <= 30
        ):
            raise FiscalValidationError("Invalid scoped WebISS transmission contract")
        req = Request(
            EXTREMA_WEBISS_HOMOLOGATION_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "Accept": "text/xml",
                "SOAPAction": soap_action,
            },
        )
        opener = build_opener(HTTPSHandler(context=context), _NoRedirects())
        try:
            with opener.open(req, timeout=timeout) as response:
                if response.status != 200:
                    raise ExtremaWebissNetworkError("Non-success WebISS SOAP response")
                data = response.read(_MAX_SOAP_BYTES + 1)
                if len(data) > _MAX_SOAP_BYTES:
                    raise ExtremaWebissNetworkError("WebISS SOAP response size exceeded")
                return bytes(data)
        except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError):
            # Never log SOAP body, PKCS#12, headers, taxpayer or remote text.
            raise ExtremaWebissNetworkError(
                "WebISS delivery uncertain; query original fiscal intention before retry"
            ) from None

    return exchange
