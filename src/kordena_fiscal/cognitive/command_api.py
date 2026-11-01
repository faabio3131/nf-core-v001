"""Read-only metrics endpoint for the FM Command (product -> Command, Integration Fabric).

Follows the pattern already used by FM products: a dedicated, per-product control-plane token
(``NFCORE_COMMAND_CONTROL_PLANE_TOKEN``, at least 32 characters, injected by the secret store),
a mandatory correlation id, no-store caching and a canonical facts envelope with provenance and
freshness. It exposes counters only, never prompts, answers, evidence or personal data, and
never turns an absence into zero.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.security.s2s import FixedWindowRateLimiter

from .usage_aggregates import CognitiveUsageAggregates

TOKEN_ENV = "NFCORE_COMMAND_CONTROL_PLANE_TOKEN"
MIN_TOKEN_LENGTH = 32
SCHEMA_VERSION = "nfcore.cognitive.metrics/v1"
MAPPING_VERSION = "1"
PRODUCT_ID = "nfcore"


def _fail(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def create_command_metrics_router(
    aggregates: CognitiveUsageAggregates,
    environ: Mapping[str, str],
    *,
    ai_enabled: bool,
    rate_limiter: FixedWindowRateLimiter | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    router = APIRouter(tags=["command-cognitive-metrics"])
    limiter = rate_limiter or FixedWindowRateLimiter(max_requests=60, window_seconds=60)

    @router.get("/v1/command/cognitive/metrics")
    async def metrics(request: Request) -> JSONResponse:
        token = environ.get(TOKEN_ENV, "")
        if len(token) < MIN_TOKEN_LENGTH:
            raise _fail(503, "COMMAND_CONTROL_PLANE_NOT_CONFIGURED")
        header = request.headers.get("Authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(presented.encode(), token.encode()):
            raise _fail(401, "COMMAND_AUTHENTICATION_FAILED")
        correlation_id = request.headers.get("X-Correlation-Id", "").strip()
        if not correlation_id or len(correlation_id) > 128:
            raise _fail(400, "CORRELATION_ID_REQUIRED")
        now = clock()
        if not limiter.allow("command-metrics", now):
            raise _fail(429, "COMMAND_RATE_LIMITED")
        body: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "mappingVersion": MAPPING_VERSION,
            "productId": PRODUCT_ID,
            "source": "nfcore.cognitive",
            "correlationId": correlation_id,
            "observedAt": now.isoformat(),
            "freshness": {"scope": "process", "semantics": "monotonic_counters_since"},
            "provenance": {"authority": "nfcore-cognitive-core", "deterministicCounters": True},
            "aiEnabled": ai_enabled,
            "facts": aggregates.snapshot(),
        }
        return JSONResponse(body, headers={"Cache-Control": "no-store, max-age=0"})

    return router
