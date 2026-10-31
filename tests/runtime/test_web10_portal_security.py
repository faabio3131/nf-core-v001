from __future__ import annotations

import json
import runpy
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


def _portal_namespace() -> dict[str, object]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "serve_portal.py"
    return runpy.run_path(str(script))


def _secure_portal_handler():
    return _portal_namespace()["SecurePortalHandler"]


def _start_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_portal_server_emits_browser_security_headers(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>NFCORE</title>", encoding="utf-8"
    )
    handler = partial(_secure_portal_handler(), directory=str(tmp_path))
    server, thread = _start_server(handler)

    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/", timeout=2) as response:  # noqa: S310
            assert response.status == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
            assert response.headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_portal_api_proxy_fails_closed_without_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NFCORE_PORTAL_API_UPSTREAM", raising=False)
    handler = partial(_secure_portal_handler(), directory=str(tmp_path))
    server, thread = _start_server(handler)

    try:
        host, port = server.server_address
        request = Request(
            f"http://{host}:{port}/v1/auth/password-reset/complete",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=2)  # noqa: S310
        assert exc_info.value.code == 503
        assert json.loads(exc_info.value.read().decode("utf-8")) == {
            "detail": "portal API upstream is not configured"
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_portal_api_proxy_preserves_auth_boundary_and_cookies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    class UpstreamHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            del args

        def do_POST(self) -> None:  # noqa: N802
            observed["path"] = self.path
            observed["origin"] = self.headers.get("Origin", "")
            observed["csrf"] = self.headers.get("X-CSRF-Token", "")
            observed["cookie"] = self.headers.get("Cookie", "")
            length = int(self.headers.get("Content-Length", "0"))
            observed["body"] = self.rfile.read(length).decode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header(
                "Set-Cookie",
                "nfcore_session=opaque; Path=/; Secure; HttpOnly; SameSite=lax",
            )
            self.send_header(
                "Set-Cookie",
                "nfcore_csrf=proof; Path=/; Secure; SameSite=lax",
            )
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

    upstream, upstream_thread = _start_server(UpstreamHandler)
    upstream_host, upstream_port = upstream.server_address
    monkeypatch.setenv(
        "NFCORE_PORTAL_API_UPSTREAM",
        f"http://{upstream_host}:{upstream_port}",
    )

    handler = partial(_secure_portal_handler(), directory=str(tmp_path))
    portal, portal_thread = _start_server(handler)

    try:
        portal_host, portal_port = portal.server_address
        request = Request(
            f"http://{portal_host}:{portal_port}/v1/auth/login?source=portal",
            data=b'{"email":"owner@example.test","password":"secret"}',
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Cookie": "existing=value",
                "Origin": "https://portal.example.test",
                "X-CSRF-Token": "csrf-proof",
            },
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310
            assert response.status == 200
            assert response.read() == b'{"status":"ok"}'
            cookies = response.headers.get_all("Set-Cookie", [])
            assert any("nfcore_session=opaque" in cookie for cookie in cookies)
            assert any("nfcore_csrf=proof" in cookie for cookie in cookies)
            assert response.headers["X-Frame-Options"] == "DENY"

        assert observed == {
            "path": "/v1/auth/login?source=portal",
            "csrf": "csrf-proof",
            "origin": "https://portal.example.test",
            "cookie": "existing=value",
            "body": '{"email":"owner@example.test","password":"secret"}',
        }
    finally:
        portal.shutdown()
        portal.server_close()
        portal_thread.join(timeout=2)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=2)



def test_portal_proxy_allows_only_exact_staging_admin_path_and_public_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NFCORE_PORTAL_API_UPSTREAM", raising=False)
    portal, thread = _start_server(
        partial(_secure_portal_handler(), directory=str(tmp_path))
    )
    try:
        host, port = portal.server_address
        for path, method, status in (
            ("/internal/staging/commercial-trial-binding", "POST", 503),
            ("/internal/staging/commercial-trial-binding", "GET", 404),
            ("/internal/staging/other-binding", "POST", 404),
            ("/runtime/profile", "GET", 503),
            ("/runtime/profile", "POST", 404),
        ):
            request = Request(
                f"http://{host}:{port}{path}", method=method,
                data=b"" if method == "POST" else None,
            )
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=2)  # noqa: S310
            assert error.value.code == status
    finally:
        portal.shutdown()
        portal.server_close()
        thread.join(timeout=2)


def test_portal_api_proxy_rejects_credentialed_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _portal_namespace()
    api_upstream = namespace["_api_upstream"]
    monkeypatch.setenv(
        "NFCORE_PORTAL_API_UPSTREAM",
        "https://user:password@example.test",
    )

    with pytest.raises(RuntimeError, match="absolute HTTP"):
        api_upstream()


def test_portal_static_assets_require_revalidation(tmp_path: Path) -> None:
    (tmp_path / "styles.css").write_text("body { color: white; }", encoding="utf-8")
    handler = partial(_secure_portal_handler(), directory=str(tmp_path))
    server, thread = _start_server(handler)

    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/styles.css?v=test", timeout=2) as response:  # noqa: S310
            assert response.status == 200
            assert response.headers["Cache-Control"] == (
                "no-cache, max-age=0, must-revalidate"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("path", (
    "/v1/public/trials", "/v1/public/%74rials", "/v1/%70ublic/trials/",
))
def test_public_trial_proxy_does_not_downgrade_authorization(tmp_path, monkeypatch, path):
    # Upstream address is valid but must never be contacted for this request.
    monkeypatch.setenv("NFCORE_PORTAL_API_UPSTREAM", "http://127.0.0.1:1")
    portal, thread = _start_server(
        partial(_secure_portal_handler(), directory=str(tmp_path))
    )
    try:
        host, port = portal.server_address
        request = Request(
            f"http://{host}:{port}{path}", method="POST", data=b"{}",
            headers={"Authorization": "Bearer synthetic-rejected", "Origin": "https://portal.test"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)  # noqa: S310
        assert error.value.code == 403
        assert json.loads(error.value.read()) == {"detail": "anonymous request required"}
    finally:
        portal.shutdown()
        portal.server_close()
        thread.join(timeout=2)
