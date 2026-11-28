"""Provider-neutral edge security controls for the FM NFCORE runtime."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import RuntimeSettings

_FORWARDED_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
)

_API_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
    )
)


class ForwardedHeaderGuardMiddleware:
    """Reject proxy-derived authority when the direct peer is not trusted."""

    def __init__(self, app: ASGIApp, *, trusted_proxy_cidrs: tuple[str, ...]) -> None:
        self.app = app
        self._trusted_networks = tuple(
            ipaddress.ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs
        )

    def _client_is_trusted(self, client_host: str | None) -> bool:
        if client_host is None:
            return False
        try:
            address = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        return any(
            address.version == network.version and address in network
            for network in self._trusted_networks
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        has_forwarded_authority = any(name in headers for name in _FORWARDED_HEADERS)
        client = scope.get("client")
        client_host = client[0] if client else None
        if has_forwarded_authority and not self._client_is_trusted(client_host):
            response = JSONResponse(
                status_code=400,
                content={"detail": "untrusted proxy forwarding headers"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Apply browser-facing hardening headers without pretending to terminate TLS."""

    def __init__(self, app: ASGIApp, *, production_like: bool, require_https: bool) -> None:
        self.app = app
        self._hsts_enabled = production_like and require_https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = _API_CONTENT_SECURITY_POLICY
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
                headers["Cross-Origin-Resource-Policy"] = "same-site"
                if self._hsts_enabled:
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


# The delegated IRON A1 upload enforces its own single-origin, credential-less
# CORS contract (NFCORE_IRON_A1_ALLOWED_ORIGIN) inside the router. The global
# credentialed portal CORS policy must neither answer nor widen it.
IRON_A1_UPLOAD_PATH = "/v1/iron/a1/upload"


class PathScopedCORSMiddleware:
    """Apply the global CORS policy everywhere except the router-owned A1 upload."""

    def __init__(self, app: ASGIApp, /, **cors_options: Any) -> None:
        self.app = app
        self.cors = CORSMiddleware(app, **cors_options)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == IRON_A1_UPLOAD_PATH:
            await self.app(scope, receive, send)
            return
        await self.cors(scope, receive, send)


def configure_edge_security(app: FastAPI, settings: RuntimeSettings) -> None:
    """Attach fail-closed host, CORS, proxy and response-header boundaries."""

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.trusted_hosts),
        www_redirect=False,
    )
    if settings.allowed_origins:
        wildcard = "*" in settings.allowed_origins
        app.add_middleware(
            PathScopedCORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=not wildcard,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Accept",
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-CSRF-Token",
                "X-Causation-Id",
                "X-Correlation-Id",
            ],
        )
    app.add_middleware(
        ForwardedHeaderGuardMiddleware,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        production_like=settings.is_production_like,
        require_https=settings.require_https,
    )
