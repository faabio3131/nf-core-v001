"""Browser authentication routes for FM NFCORE human users."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, Response, status

from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    CsrfValidationError,
    HumanAccount,
    HumanAuthenticationError,
    HumanIdentityService,
    HumanRateLimitError,
    IssuedWebSession,
)

if TYPE_CHECKING:
    from kordena_fiscal.security.human_mfa import HumanMfaService

SESSION_COOKIE = "nfcore_session"
CSRF_COOKIE = "nfcore_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _account_payload(account: HumanAccount) -> dict[str, Any]:
    return {
        "account_id": account.account_id,
        "email": account.email,
        "tenant_id": account.tenant_id,
        "role": account.role.value,
        "unit_ids": sorted(account.unit_ids) if account.unit_ids is not None else None,
        "platform_admin": account.platform_admin,
        "permissions": sorted(permission.value for permission in account.permissions),
    }


def create_human_auth_router(
    identity: HumanIdentityService,
    *,
    on_login: Callable[[str, datetime], None] | None = None,
    now: Callable[[], datetime] | None = None,
    mfa: HumanMfaService | None = None,
) -> APIRouter:
    """Create cookie-session routes without accepting tenant authority from headers."""

    now_provider = now or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/v1/auth", tags=["human-auth"])

    def authenticated(request: Request) -> AuthenticatedHuman:
        token = request.cookies.get(SESSION_COOKIE, "")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "SESSION_REQUIRED", "message": "Web session is required"},
            )
        try:
            return identity.authenticate_session(session_token=token, now=now_provider())
        except HumanAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_SESSION", "message": "Web session is not usable"},
            ) from exc

    def csrf_authenticated(request: Request) -> AuthenticatedHuman:
        auth = authenticated(request)
        header_token = request.headers.get(CSRF_HEADER, "")
        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        if not header_token or not cookie_token or header_token != cookie_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "CSRF_REQUIRED", "message": "Valid CSRF proof is required"},
            )
        try:
            identity.assert_csrf(auth, header_token)
        except CsrfValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "CSRF_INVALID", "message": "Valid CSRF proof is required"},
            ) from exc
        return auth

    def start_session(
        response: Response, issued: IssuedWebSession, instant: datetime,
    ) -> dict[str, Any]:
        if on_login is not None:
            try:
                on_login(issued.account.account_id, instant)
            except Exception:
                # Authentication remains authoritative and successful. Commercial
                # activation reconciliation is retryable and must not lock the user out.
                pass
        ttl = max(1, int((issued.expires_at - instant).total_seconds()))
        response.set_cookie(
            SESSION_COOKIE,
            issued.session_token,
            max_age=ttl,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            CSRF_COOKIE,
            issued.csrf_token,
            max_age=ttl,
            path="/",
            secure=True,
            httponly=False,
            samesite="lax",
        )
        return {
            "account": _account_payload(issued.account),
            "expires_at": issued.expires_at.isoformat(),
        }

    if mfa is not None:
        from kordena_fiscal.web.human_mfa_routes import add_human_mfa_routes

        add_human_mfa_routes(
            router, identity=identity, mfa=mfa, now=now_provider,
            authenticated=authenticated, csrf_authenticated=csrf_authenticated,
            start_session=start_session,
        )

    @router.post("/login")
    async def login(
        request: Request,
        response: Response,
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        email = payload.get("email")
        password = payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_LOGIN_PAYLOAD",
                    "message": "Email and password are required",
                },
            )
        instant = now_provider()
        try:
            account = identity.authenticate_password(email=email, password=password, now=instant)
        except HumanRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "LOGIN_RATE_LIMITED", "message": "Try again later"},
            ) from exc
        except (HumanAuthenticationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
            ) from exc
        if mfa is not None:
            from kordena_fiscal.web.human_mfa_routes import (
                TRUSTED_DEVICE_COOKIE,
                second_factor_due,
            )

            challenge = second_factor_due(
                mfa, account, request.cookies.get(TRUSTED_DEVICE_COOKIE), instant,
            )
            if challenge is not None:
                return {"mfa": challenge}
        return start_session(response, identity.issue_session(account, now=instant), instant)

    @router.get("/me")
    async def me(request: Request) -> dict[str, Any]:
        auth = authenticated(request)
        body: dict[str, Any] = {
            "account": _account_payload(auth.account),
            "expires_at": auth.expires_at.isoformat(),
        }
        if mfa is not None:
            current = mfa.status(auth.account)
            body["mfa"] = {
                "required": current.required, "enrolled": current.enrolled,
                "recovery_codes_remaining": current.recovery_codes_remaining,
                "tenant_requires_all": current.tenant_requires_all,
            }
        return body

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request, response: Response) -> Response:
        auth = csrf_authenticated(request)
        identity.logout(auth)
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            CSRF_COOKIE,
            path="/",
            secure=True,
            httponly=False,
            samesite="lax",
        )
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    return router
