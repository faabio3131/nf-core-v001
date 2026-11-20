"""IRON A1 delegated onboarding on the existing NFCore fiscal authority.

S2S scope is authorized by the canonical Bridge workload boundary. The browser
uploads directly into NFCore's existing encrypted A1 Vault with a short-lived,
single-use grant; PKCS#12 and password never transit the IRON backend.

This router is disabled until a trusted Web origin, scoped workload grant,
durable PostgreSQL schema, exact fiscal binding/profile, and Vault are present.
"""
from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.iron_a1_delegation import (
    IronA1DelegationStore,
    IronA1ScopeBusy,
    iron_a1_scope_key,
)
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.signing.contracts import InvalidCertificateMaterialError
from kordena_fiscal.vault.encrypted_a1 import A1VaultUnavailable, EncryptedA1Vault
from kordena_fiscal.web.app import (
    AuthorizedBridgeContext,
    BridgeHttpContext,
    BridgeSecurityBoundary,
    HttpContractError,
)

_MAX_BODY_BYTES = 3_200_000
_UPLOAD_PATH = "/v1/iron/a1/upload"

async def _read_bounded_body(request: Request, limit: int) -> bytes | None:
    """Stream with a strict in-process cap, including chunked/unknown-length bodies.

    Starlette Request.body() eagerly buffers an unbounded body, so checking
    len(body) afterwards does not protect this unauthenticated upload surface.
    """
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            return None
        if declared < 0 or declared > limit:
            return None
    data = bytearray()
    async for chunk in request.stream():
        if len(chunk) > limit - len(data):
            return None
        data.extend(chunk)
    return bytes(data)



def trusted_iron_origin(value: str | None) -> str | None:
    if not value or len(value) > 256:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
        parsed.password or parsed.path not in ("", "/") or parsed.query or
        parsed.fragment or parsed.port not in (None, 443)):
        return None
    return "https://" + parsed.hostname.lower()


def create_iron_a1_router(
    *, security: BridgeSecurityBoundary | None,
    database: PostgresFiscalDatabase | None, vault: EncryptedA1Vault | None,
    allowed_origin: str | None,
    context_from_request: Callable[[Request], BridgeHttpContext],
    scope_lock: Callable[
        [str, IronA1DelegationStore], AbstractContextManager[IronA1DelegationStore]
    ] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/iron/a1", tags=["iron-a1"])
    trusted_origin = trusted_iron_origin(allowed_origin)
    store = None if database is None else IronA1DelegationStore(database.connection)

    def locked(scope: ExecutionScope, cnpj: str) -> AbstractContextManager[IronA1DelegationStore]:
        assert store is not None
        key = iron_a1_scope_key(
            "fm.iron", scope.tenant_id, scope.unit_id, scope.environment.value, cnpj,
        )
        return scope_lock(key, store) if scope_lock is not None else store.locked(key)

    def is_json_content(request: Request) -> bool:
        content_type = request.headers.get("content-type", "").split(";")[0]
        return content_type.strip().lower() == "application/json"

    def ready() -> None:
        if security is None or store is None or vault is None or trusted_origin is None:
            raise HttpContractError(
                503, "IRON_A1_DELEGATION_UNAVAILABLE",
                "Delegated A1 onboarding is not configured", "unknown",
            )

    def authorize(request: Request, operation: str) -> ExecutionScope:
        ready()
        assert security is not None  # narrowed after ready(), not an authorization bypass
        context = context_from_request(request)
        authorized: AuthorizedBridgeContext = security.authorize(
            operation_id=operation, context=context
        )
        authority = authorized.authority
        scope = getattr(authority, "scope", None)
        if (context.host_namespace != "fm.iron" or
            not isinstance(scope, ExecutionScope) or
            scope.host_namespace != "fm.iron" or
            scope.environment is not FiscalEnvironment.HOMOLOGATION):
            raise HttpContractError(
                403, "IRON_A1_SCOPE_DENIED",
                "A1 onboarding requires an authorized IRON homologation scope",
                context.correlation_id,
            )
        return scope

    def verified_profile(scope: ExecutionScope, supplied_cnpj: object) -> str:
        if database is None:
            raise HttpContractError(
                503, "IRON_A1_BINDING_UNAVAILABLE",
                "Fiscal profile is unavailable", scope.correlation_id,
            )
        try:
            cnpj = Cnpj(supplied_cnpj).value if isinstance(supplied_cnpj, str) else ""
            with database() as uow:
                profile = uow.control_plane.resolve_profile(
                    host_namespace="fm.iron",
                    tenant_id=scope.tenant_id, unit_id=scope.unit_id,
                    environment=scope.environment, instant=datetime.now(UTC),
                )
            if profile is None or profile.cnpj.value != cnpj:
                raise ValueError("missing canonical issuer ownership")
            return cnpj
        except (FiscalValidationError, ValueError):
            raise HttpContractError(
                403, "IRON_A1_ISSUER_NOT_VERIFIED",
                "Canonical fiscal profile does not authorize this issuer",
                scope.correlation_id,
            ) from None

    @router.post("/delegations")
    async def prepare(request: Request) -> JSONResponse:
        scope = authorize(request, "prepareIronA1Delegation")
        if not is_json_content(request):
            raise HttpContractError(
                415, "INVALID_CONTENT_TYPE", "JSON required", scope.correlation_id,
            )
        raw = await _read_bounded_body(request, 1024)
        if raw is None:
            raise HttpContractError(
                413, "A1_PREPARE_TOO_LARGE", "Request too large", scope.correlation_id,
            )
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"issuer_cnpj", "actor_user_id"}:
                raise ValueError
            actor = body["actor_user_id"]
            if not isinstance(actor, str) or not 3 <= len(actor) <= 128 or not actor.isascii():
                raise ValueError
        except (ValueError, TypeError):
            raise HttpContractError(
                400, "INVALID_A1_PREPARE", "Request is invalid", scope.correlation_id,
            ) from None
        cnpj = verified_profile(scope, body["issuer_cnpj"])
        assert store is not None and trusted_origin is not None
        try:
            with locked(scope, cnpj) as held:
                token, expires = held.issue(
                    host_namespace="fm.iron", tenant_id=scope.tenant_id, unit_id=scope.unit_id,
                    environment=scope.environment.value, issuer_cnpj=cnpj,
                    allowed_origin=trusted_origin, issued_by=actor,
                )
        except IronA1ScopeBusy:
            raise HttpContractError(
                409, "IRON_A1_SCOPE_BUSY", "Try again", scope.correlation_id,
            ) from None
        return JSONResponse(
            content={"delegation_token": token, "expires_at": expires.isoformat(),
                     "upload_path": _UPLOAD_PATH, "status": "PENDING_UPLOAD"},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @router.post("/status")
    async def status(request: Request) -> JSONResponse:
        scope = authorize(request, "readIronA1Status")
        if not is_json_content(request):
            raise HttpContractError(
                415, "INVALID_CONTENT_TYPE", "JSON required", scope.correlation_id,
            )
        raw = await _read_bounded_body(request, 1024)
        if raw is None:
            raise HttpContractError(
                413, "A1_STATUS_TOO_LARGE", "Request too large", scope.correlation_id,
            )
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"issuer_cnpj"}:
                raise ValueError
        except (ValueError, TypeError):
            raise HttpContractError(
                400, "INVALID_A1_STATUS", "Request invalid", scope.correlation_id,
            ) from None
        cnpj = verified_profile(scope, body["issuer_cnpj"])
        assert vault is not None
        try:
            evidence = vault.inspect(scope=scope, issuer_cnpj=cnpj)
        except (A1VaultUnavailable, FiscalValidationError, InvalidCertificateMaterialError):
            raise HttpContractError(
                503, "IRON_A1_STATUS_UNVERIFIABLE", "A1 Vault readback failed",
                scope.correlation_id,
            ) from None
        return JSONResponse(
            content={"status": "STORED" if evidence is not None else "ABSENT",
                     "expires_at": None if evidence is None else evidence.expires_at.isoformat(),
                     "official_homologation": "NOT_VERIFIED"},
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/withdraw")
    async def withdraw(request: Request) -> JSONResponse:
        scope = authorize(request, "withdrawIronA1")
        if not is_json_content(request):
            raise HttpContractError(
                415, "INVALID_CONTENT_TYPE", "JSON required", scope.correlation_id,
            )
        raw = await _read_bounded_body(request, 1024)
        if raw is None:
            raise HttpContractError(
                413, "A1_WITHDRAW_TOO_LARGE", "Request too large", scope.correlation_id,
            )
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {
                "issuer_cnpj", "actor_user_id", "request_id",
            }:
                raise ValueError
            actor, request_id = body["actor_user_id"], body["request_id"]
            if (
                not isinstance(actor, str) or not 3 <= len(actor) <= 128 or not actor.isascii()
                or not isinstance(request_id, str) or str(UUID(request_id)) != request_id
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise HttpContractError(
                400, "INVALID_A1_WITHDRAW", "Request invalid", scope.correlation_id,
            ) from None
        cnpj = verified_profile(scope, body["issuer_cnpj"])
        assert vault is not None
        try:
            with locked(scope, cnpj) as held:
                if not held.reserve_withdrawal(
                    host_namespace="fm.iron", tenant_id=scope.tenant_id, unit_id=scope.unit_id,
                    environment=scope.environment.value, issuer_cnpj=cnpj,
                    actor_id=actor, request_id=request_id,
                ):
                    raise HttpContractError(
                        409, "IRON_A1_WITHDRAW_REPLAY", "Do not replay withdrawal",
                        scope.correlation_id,
                    )
                vault.withdraw(scope=scope, issuer_cnpj=cnpj)
        except IronA1ScopeBusy:
            raise HttpContractError(
                409, "IRON_A1_SCOPE_BUSY", "Try again", scope.correlation_id,
            ) from None
        except (A1VaultUnavailable, FiscalValidationError):
            raise HttpContractError(
                503, "IRON_A1_WITHDRAW_UNCONFIRMED", "Vault withdrawal failed",
                scope.correlation_id,
            ) from None
        return JSONResponse(
            content={"status": "WITHDRAWN", "official_revocation": "NOT_PERFORMED",
                     "official_homologation": "NOT_VERIFIED"},
            headers={"Cache-Control": "no-store"},
        )

    def cors_headers(origin: str) -> dict[str, str]:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                "Cache-Control": "no-store", "Pragma": "no-cache"}

    def authorized_origin(request: Request) -> str | None:
        origin = request.headers.get("origin", "")
        return origin if trusted_origin and origin == trusted_origin else None

    @router.options("/upload")
    async def upload_preflight(request: Request) -> JSONResponse:
        origin = authorized_origin(request)
        if origin is None or request.headers.get("access-control-request-method") != "POST":
            return JSONResponse(status_code=403, content={"code": "IRON_A1_ORIGIN_DENIED"},
                                headers={"Cache-Control": "no-store"})
        return JSONResponse(
            status_code=204, content=None,
            headers={**cors_headers(origin), "Access-Control-Allow-Methods": "POST, OPTIONS",
                     "Access-Control-Allow-Headers": "Content-Type",
                     "Access-Control-Max-Age": "60"},
        )

    @router.post("/upload")
    async def upload(request: Request) -> JSONResponse:
        origin = authorized_origin(request)
        if origin is None:
            return JSONResponse(status_code=403, content={"code": "IRON_A1_ORIGIN_DENIED"},
                                headers={"Cache-Control": "no-store"})
        headers = cors_headers(origin)

        def denied(code: str, status_code: int) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"code": code}, headers=headers)

        if vault is None or store is None:
            return denied("IRON_A1_DELEGATION_UNAVAILABLE", 503)
        if not is_json_content(request):
            return denied("INVALID_CONTENT_TYPE", 415)
        raw = await _read_bounded_body(request, _MAX_BODY_BYTES)
        if raw is None:
            return denied("A1_UPLOAD_TOO_LARGE", 413)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {
                "delegation_token", "pfx_base64", "password",
            }:
                raise ValueError
            if not all(isinstance(body.get(key), str) for key in body):
                raise ValueError
            pfx = base64.b64decode(body["pfx_base64"], validate=True)
            password = body["password"].encode("utf-8")
            if not 0 < len(pfx) <= 2_000_000 or not 0 < len(password) <= 512:
                raise ValueError
        except (ValueError, UnicodeError, binascii.Error, TypeError):
            return denied("INVALID_A1_UPLOAD", 400)

        # Lock the same scope for upload, issuance and withdrawal.
        record = store.lookup_scope(token=body["delegation_token"], origin=origin)
        if (
            record is None
            or record["host_namespace"] != "fm.iron"
            or record["environment"] != "homologation"
        ):
            return denied("IRON_A1_DELEGATION_INVALID", 409)
        scope = ExecutionScope(
            host_namespace="fm.iron", tenant_id=record["tenant_id"],
            unit_id=record["unit_id"], environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="iron-a1-direct-upload",
        )
        profile_verified = True
        try:
            verified_profile(scope, record["issuer_cnpj"])
        except HttpContractError:
            profile_verified = False
        try:
            with locked(scope, record["issuer_cnpj"]) as held:
                consumed = held.consume(token=body["delegation_token"], origin=origin)
                if consumed != record:
                    return denied("IRON_A1_DELEGATION_INVALID", 409)
                if not profile_verified:
                    return denied("IRON_A1_ISSUER_REVOKED", 403)
                try:
                    evidence = vault.provision(
                        scope=scope, issuer_cnpj=record["issuer_cnpj"],
                        pkcs12_bytes=pfx, password=password,
                    )
                except (A1VaultUnavailable, FiscalValidationError, InvalidCertificateMaterialError):
                    return denied("IRON_A1_VALIDATION_FAILED", 422)
        except IronA1ScopeBusy:
            return denied("IRON_A1_SCOPE_BUSY", 409)
        return JSONResponse(
            content={"status": "STORED", "expires_at": evidence.expires_at.isoformat(),
                     "official_homologation": "NOT_VERIFIED"},
            headers=headers,
        )

    return router
