"""HTTP surface of the second factor: login challenge, enrollment, step-up."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, Response, status

from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAccount,
    HumanIdentityService,
    HumanRateLimitError,
    IssuedWebSession,
    LoginAttemptLimiter,
    PortalPermission,
)
from kordena_fiscal.security.human_mfa import HumanMfaError, HumanMfaService, MfaEnrollment

TRUSTED_DEVICE_COOKIE = "nfcore_mfa_device"
_TRUSTED_DEVICE_PATH = "/v1/auth"


def second_factor_due(
    mfa: HumanMfaService, account: HumanAccount, device_token: str | None, now: datetime,
) -> dict[str, str] | None:
    """None when a session may be issued now; otherwise the challenge to answer."""
    enrolled = mfa.is_enrolled(account.account_id)
    if not enrolled and not mfa.required_for(account):
        return None
    if enrolled and mfa.is_trusted_device(account, device_token, now):
        return None
    token, purpose = mfa.open_challenge(account, now)
    return {"challenge": token, "purpose": purpose}


def _qr_data_uri(uri: str) -> str | None:
    try:
        import segno
    except ImportError:  # optional: the setup key is always returned
        return None
    return str(segno.make(uri, error="m").svg_data_uri(scale=4, border=2))


def _enrollment_body(enrollment: MfaEnrollment) -> dict[str, Any]:
    return {
        "secret_base32": enrollment.secret_base32,
        "otpauth_uri": enrollment.otpauth_uri,
        "qr_data_uri": _qr_data_uri(enrollment.otpauth_uri),
    }


def _invalid(code: str = "MFA_INVALID_CODE") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": "Código inválido ou expirado"},
    )


def _text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value or len(value) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_MFA_PAYLOAD", "message": f"{field} is required"},
        )
    return value


def add_human_mfa_routes(
    router: APIRouter,
    *,
    identity: HumanIdentityService,
    mfa: HumanMfaService,
    now: Callable[[], datetime],
    authenticated: Callable[[Request], AuthenticatedHuman],
    csrf_authenticated: Callable[[Request], AuthenticatedHuman],
    start_session: Callable[[Response, IssuedWebSession, datetime], dict[str, Any]],
) -> None:
    attempts = LoginAttemptLimiter(max_failures=5, window_seconds=300)

    def guarded(key: str, instant: datetime) -> None:
        try:
            attempts.assert_allowed(key, instant)
        except HumanRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "MFA_RATE_LIMITED", "message": "Try again later"},
            ) from exc

    def challenge_account(token: str, purpose: str, instant: datetime) -> HumanAccount:
        try:
            found = mfa.challenge_account(token, instant)
        except HumanMfaError as exc:
            raise _invalid("MFA_CHALLENGE_INVALID") from exc
        account = identity.account_by_id(found.account_id)
        if found.purpose != purpose or account is None or not account.enabled:
            raise _invalid("MFA_CHALLENGE_INVALID")
        return account

    def finish_login(
        response: Response, account: HumanAccount, instant: datetime, remember: object,
    ) -> dict[str, Any]:
        body = start_session(response, identity.issue_session(account, now=instant), instant)
        if remember is True:
            token, expires = mfa.issue_trusted_device(account, instant)
            response.set_cookie(
                TRUSTED_DEVICE_COOKIE, token,
                max_age=max(1, int((expires - instant).total_seconds())),
                path=_TRUSTED_DEVICE_PATH, secure=True, httponly=True, samesite="strict",
            )
        return body

    def require_step_up(auth: AuthenticatedHuman, instant: datetime) -> None:
        if not mfa.has_recent_step_up(auth.session_id, instant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "STEP_UP_REQUIRED", "message": "Confirme o código do app"},
            )

    @router.post("/mfa/verify")
    async def verify(
        response: Response, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        instant = now()
        token = _text(payload, "challenge")
        account = challenge_account(token, "verify", instant)
        try:
            mfa.verify(account, _text(payload, "code"), instant)
        except HumanMfaError as exc:
            mfa.fail_challenge(token)
            raise _invalid() from exc
        try:
            mfa.consume_challenge(token)
        except HumanMfaError as exc:
            raise _invalid("MFA_CHALLENGE_INVALID") from exc
        return finish_login(response, account, instant, payload.get("remember_device"))

    @router.post("/mfa/enroll/start")
    async def enroll_start(
        request: Request, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        instant = now()
        if "challenge" in payload:
            account = challenge_account(_text(payload, "challenge"), "enroll", instant)
        else:
            account = csrf_authenticated(request).account
        try:
            return _enrollment_body(mfa.start_enrollment(account, instant))
        except HumanMfaError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "MFA_ALREADY_ENROLLED", "message": "App autenticador já ativo"},
            ) from exc

    @router.post("/mfa/enroll/confirm")
    async def enroll_confirm(
        request: Request, response: Response, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        instant = now()
        token = payload.get("challenge")
        if token is not None:
            account = challenge_account(_text(payload, "challenge"), "enroll", instant)
        else:
            account = csrf_authenticated(request).account
        guarded(f"enroll:{account.account_id}", instant)
        try:
            codes = mfa.confirm_enrollment(account, _text(payload, "code"), instant)
        except HumanMfaError as exc:
            attempts.record_failure(f"enroll:{account.account_id}", instant)
            if isinstance(token, str):
                mfa.fail_challenge(token)
            raise _invalid() from exc
        body: dict[str, Any] = {"recovery_codes": list(codes)}
        if isinstance(token, str):
            mfa.consume_challenge(token)
            body.update(finish_login(response, account, instant, payload.get("remember_device")))
        return body

    @router.get("/mfa/status")
    async def mfa_status(request: Request) -> dict[str, Any]:
        auth = authenticated(request)
        current = mfa.status(auth.account)
        return {
            "required": current.required, "enrolled": current.enrolled,
            "recovery_codes_remaining": current.recovery_codes_remaining,
            "tenant_requires_all": current.tenant_requires_all,
            "step_up_active": mfa.has_recent_step_up(auth.session_id, now()),
        }

    @router.post("/mfa/step-up")
    async def step_up(
        request: Request, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = csrf_authenticated(request)
        instant = now()
        key = f"step-up:{auth.account.account_id}"
        guarded(key, instant)
        try:
            mfa.step_up(auth.account, auth.session_id, _text(payload, "code"), instant)
        except HumanMfaError as exc:
            attempts.record_failure(key, instant)
            raise _invalid() from exc
        attempts.reset(key, instant)
        return {"step_up": "active"}

    @router.post("/mfa/recovery-codes")
    async def recovery_codes(request: Request) -> dict[str, Any]:
        auth = csrf_authenticated(request)
        instant = now()
        require_step_up(auth, instant)
        return {"recovery_codes": list(mfa.regenerate_recovery_codes(auth.account, instant))}

    @router.post("/mfa/forget-devices", status_code=status.HTTP_204_NO_CONTENT)
    async def forget_devices(request: Request, response: Response) -> Response:
        auth = csrf_authenticated(request)
        mfa.forget_devices(auth.account)
        response.delete_cookie(TRUSTED_DEVICE_COOKIE, path=_TRUSTED_DEVICE_PATH,
                               secure=True, httponly=True, samesite="strict")
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @router.post("/mfa/policy")
    async def policy(
        request: Request, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = csrf_authenticated(request)
        instant = now()
        require_step_up(auth, instant)
        value = payload.get("require_all")
        if not isinstance(value, bool):
            raise HTTPException(400, detail={"code": "INVALID_MFA_PAYLOAD"})
        try:
            mfa.set_tenant_requires_all(auth.account, value, instant)
        except HumanMfaError as exc:
            raise HTTPException(403, detail={"code": "PORTAL_FORBIDDEN"}) from exc
        return {"tenant_requires_all": value}

    @router.post("/mfa/reset")
    async def reset(
        request: Request, payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """A user manager removes a member's factor (lost phone) and ends their sessions."""
        auth = csrf_authenticated(request)
        instant = now()
        if PortalPermission.USER_MANAGE not in auth.permissions:
            raise HTTPException(403, detail={"code": "PORTAL_FORBIDDEN"})
        require_step_up(auth, instant)
        target = identity.account_by_id(_text(payload, "account_id"))
        if (
            target is None or target.tenant_id != auth.tenant_id
            or target.account_id == auth.account.account_id
            or (target.platform_admin and not auth.account.platform_admin)
        ):
            raise HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND"})
        mfa.reset(target.account_id)
        identity.revoke_all_sessions(target.account_id)
        return {"account_id": target.account_id, "mfa": "reset"}
