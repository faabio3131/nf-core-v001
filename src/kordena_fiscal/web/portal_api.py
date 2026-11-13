"""Session-authorized portal API for the FM NFCORE web control center.

The browser never supplies tenant authority. Human authority is reconstructed from
the opaque session cookie and every operation is delegated to a server-side product
executor. No synthetic fallback exists: if the executor is unavailable the portal
fails closed with 503.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, runtime_checkable
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import Response

from kordena_fiscal.archive import FiscalArchiveKind
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    CsrfValidationError,
    HumanAuthenticationError,
    HumanAuthorizationError,
    HumanIdentityService,
    PortalPermission,
)
from kordena_fiscal.signing.contracts import InvalidCertificateMaterialError
from kordena_fiscal.vault.encrypted_a1 import A1VaultUnavailable, EncryptedA1Vault
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE


@runtime_checkable
class HumanPortalExecutor(Protocol):
    """Server-side product projection and operation boundary used by the web portal."""

    def snapshot(self, *, authority: AuthenticatedHuman) -> Mapping[str, Any]: ...

    def surface(
        self,
        *,
        surface_id: str,
        authority: AuthenticatedHuman,
        unit_id: str | None = None,
        environment: FiscalEnvironment | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Mapping[str, Any]]: ...

    def execute(
        self,
        *,
        operation_id: str,
        authority: AuthenticatedHuman,
        payload: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Mapping[str, Any]: ...


_SURFACE_PERMISSIONS: dict[str, PortalPermission] = {
    "overview": PortalPermission.PORTAL_READ,
    "documents": PortalPermission.DOCUMENT_QUERY,
    "issuances": PortalPermission.DOCUMENT_QUERY,
    "inutilizations": PortalPermission.DOCUMENT_INUTILIZE,
    "errors": PortalPermission.PORTAL_READ,
    "reconciliation": PortalPermission.DOCUMENT_QUERY,
    "onboarding": PortalPermission.CONFIGURATION_WRITE,
    "companies": PortalPermission.CONFIGURATION_WRITE,
    "units": PortalPermission.CONFIGURATION_WRITE,
    "environments": PortalPermission.CONFIGURATION_WRITE,
    "capabilities": PortalPermission.PORTAL_READ,
    "tax-reform": PortalPermission.PORTAL_READ,
    "certificates": PortalPermission.CERTIFICATE_MANAGE,
    "providers": PortalPermission.INTEGRATION_MANAGE,
    "webhooks": PortalPermission.INTEGRATION_MANAGE,
    "integrations": PortalPermission.INTEGRATION_MANAGE,
    "usage": PortalPermission.BILLING_READ,
    "billing": PortalPermission.BILLING_READ,
    "plans": PortalPermission.BILLING_READ,
    "audit": PortalPermission.AUDIT_READ,
    "support": PortalPermission.PORTAL_READ,
    "settings": PortalPermission.CONFIGURATION_WRITE,
    "users": PortalPermission.USER_MANAGE,
}

_OPERATION_PERMISSIONS: dict[str, PortalPermission] = {
    "onboardUnit": PortalPermission.CONFIGURATION_WRITE,
    "configureCertificates": PortalPermission.CERTIFICATE_MANAGE,
    "configureProviders": PortalPermission.INTEGRATION_MANAGE,
    "configureWebhooks": PortalPermission.INTEGRATION_MANAGE,
    "configureIntegrations": PortalPermission.INTEGRATION_MANAGE,
    "configureSettings": PortalPermission.CONFIGURATION_WRITE,
    "registerFiscalProfile": PortalPermission.CONFIGURATION_WRITE,
    "prepareExtremaNfse": PortalPermission.CONFIGURATION_WRITE,
    "prepareNativeNfse": PortalPermission.DOCUMENT_ISSUE,
    "createUser": PortalPermission.USER_MANAGE,
    "updateUser": PortalPermission.USER_MANAGE,
    "issueFiscalDocument": PortalPermission.DOCUMENT_ISSUE,
    "queryFiscalDocument": PortalPermission.DOCUMENT_QUERY,
    "queryArchiveReference": PortalPermission.DOCUMENT_QUERY,
    "cancelFiscalDocument": PortalPermission.DOCUMENT_CANCEL,
    "cancelExtremaNfse": PortalPermission.DOCUMENT_CANCEL,
    "substituteExtremaNfse": PortalPermission.DOCUMENT_CANCEL,
    "inutilizeFiscalRange": PortalPermission.DOCUMENT_INUTILIZE,
    "reconcileFiscalOperation": PortalPermission.RECONCILIATION_EXECUTE,
}

_IDEMPOTENT_MUTATIONS = {
    "onboardUnit",
    "configureCertificates",
    "configureProviders",
    "configureWebhooks",
    "configureIntegrations",
    "configureSettings",
    "registerFiscalProfile",
    "prepareExtremaNfse",
    "prepareNativeNfse",
    "createUser",
    "updateUser",
    "issueFiscalDocument",
    "cancelFiscalDocument",
    "cancelExtremaNfse",
    "substituteExtremaNfse",
    "inutilizeFiscalRange",
    "reconcileFiscalOperation",
}

_SECRET_KEYS = {
    "password",
    "password_hash",
    "secret",
    "token",
    "session_token",
    "csrf_token",
    "private_key",
    "private_key_pem",
    "certificate_pem",
    "csc",
}

_BROWSER_AUTHORITY_FIELDS = {
    "tenant_id",
    "account_id",
    "role",
    "permissions",
    "authority",
    "session_epoch",
    "platform_admin",
    "host_namespace",
}


def _safe_payload(value: object, *, path: str = "payload") -> None:
    """Fail closed if a portal projection attempts to expose secret material."""

    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().casefold()
            if key in _SECRET_KEYS or key.endswith("_secret") or key.endswith("_token"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "PORTAL_SECRET_BOUNDARY_VIOLATION",
                        "message": "Portal projection attempted to expose protected material",
                    },
                )
            _safe_payload(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _safe_payload(nested, path=f"{path}[{index}]")


def _reject_browser_authority(value: object) -> None:
    """Reject mass-assignment attempts for server-owned authority fields."""

    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().casefold()
            if key in _BROWSER_AUTHORITY_FIELDS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "BROWSER_AUTHORITY_REJECTED",
                        "message": "Authority fields are derived from the authenticated session",
                    },
                )
            _reject_browser_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_browser_authority(nested)


def _authenticated(
    request: Request,
    identity: HumanIdentityService,
    *,
    now: datetime,
) -> AuthenticatedHuman:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REQUIRED", "message": "Web session is required"},
        )
    try:
        return identity.authenticate_session(session_token=token, now=now)
    except HumanAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_SESSION", "message": "Web session is not usable"},
        ) from exc


def _csrf(
    request: Request,
    identity: HumanIdentityService,
    authority: AuthenticatedHuman,
) -> None:
    header_token = request.headers.get(CSRF_HEADER, "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not header_token or not cookie_token or header_token != cookie_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_REQUIRED", "message": "Valid CSRF proof is required"},
        )
    try:
        identity.assert_csrf(authority, header_token)
    except CsrfValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_INVALID", "message": "Valid CSRF proof is required"},
        ) from exc


def _authorized(
    authority: AuthenticatedHuman,
    permission: PortalPermission,
    *,
    unit_id: str | None = None,
) -> None:
    try:
        authority.assert_permission(permission, unit_id=unit_id)
    except HumanAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PORTAL_FORBIDDEN", "message": "Operation is not permitted"},
        ) from exc


def create_portal_router(
    identity: HumanIdentityService,
    executor: HumanPortalExecutor | None,
    *,
    platform_surfaces: tuple[str, ...] = (),
    certificate_vault: EncryptedA1Vault | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/portal", tags=["human-portal"])

    def authority(request: Request) -> AuthenticatedHuman:
        return _authenticated(request, identity, now=datetime.now(UTC))

    def require_executor() -> HumanPortalExecutor:
        if executor is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "PORTAL_RUNTIME_NOT_READY",
                    "message": "Portal product executor is not configured",
                },
            )
        return executor

    @router.get("/certificates/a1/status")
    def inspect_a1(
        request: Request,
        response: Response,
        unit_id: str,
        issuer_cnpj: str,
        environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    ) -> dict[str, str]:
        """Confirm current vault readback for the authenticated fiscal scope.

        The endpoint never sends PKCS#12 bytes, password, storage path or
        decryption key to the browser. No mutation or fiscal operation occurs.
        """
        auth = authority(request)
        _authorized(auth, PortalPermission.CERTIFICATE_MANAGE, unit_id=unit_id)
        response.headers["Cache-Control"] = "no-store"
        if environment is not FiscalEnvironment.HOMOLOGATION:
            raise HTTPException(
                status_code=400, detail={"code": "A1_STATUS_HOMOLOGATION_ONLY"}
            )
        if certificate_vault is None:
            raise HTTPException(
                status_code=503, detail={"code": "A1_VAULT_UNAVAILABLE"}
            )
        scope = ExecutionScope(
            tenant_id=auth.tenant_id, unit_id=unit_id,
            environment=environment, correlation_id=uuid4().hex,
            host_namespace="fm-nfcore",
        )
        try:
            evidence = certificate_vault.inspect(
                scope=scope, issuer_cnpj=issuer_cnpj,
            )
        except (A1VaultUnavailable, FiscalValidationError, InvalidCertificateMaterialError):
            raise HTTPException(
                status_code=503,
                detail={"code": "A1_STATUS_UNVERIFIABLE",
                        "message": "Não foi possível confirmar a leitura do certificado"},
            ) from None
        if evidence is None:
            return {"status": "absent"}
        return {
            "status": "stored",
            "issuer_cnpj": evidence.issuer_cnpj,
            "expires_at": evidence.expires_at.isoformat(),
            "fingerprint_sha256": evidence.certificate_fingerprint_sha256,
        }

    @router.post("/certificates/a1")
    async def upload_a1(request: Request) -> dict[str, str]:
        auth = authority(request)
        _csrf(request, identity, auth)
        if certificate_vault is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "A1_VAULT_UNAVAILABLE",
                        "message": "Cofre A1 não configurado neste ambiente"},
            )
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise HTTPException(415, detail={"code": "INVALID_CERTIFICATE_CONTENT_TYPE"})
        raw = await request.body()
        if len(raw) > 3_200_000:
            raise HTTPException(413, detail={"code": "CERTIFICATE_TOO_LARGE"})
        try:
            fields = json.loads(raw)
            if not isinstance(fields, dict) or set(fields) != {
                "unit_id", "environment", "issuer_cnpj", "pfx_base64", "password"
            }:
                raise ValueError
            unit_id = fields["unit_id"]
            issuer_cnpj = fields["issuer_cnpj"]
            environment = FiscalEnvironment(fields["environment"])
            if (
                not isinstance(unit_id, str) or not unit_id or
                not isinstance(issuer_cnpj, str) or
                not isinstance(fields["pfx_base64"], str) or
                not isinstance(fields["password"], str)
            ):
                raise ValueError
            certificate = base64.b64decode(fields["pfx_base64"], validate=True)
            password = fields["password"].encode("utf-8")
            if environment is not FiscalEnvironment.HOMOLOGATION:
                raise ValueError
        except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
            raise HTTPException(
                400, detail={"code": "INVALID_A1_UPLOAD",
                             "message": "Dados do certificado A1 inválidos"},
            ) from None
        _authorized(auth, PortalPermission.CERTIFICATE_MANAGE, unit_id=unit_id)
        scope = ExecutionScope(
            tenant_id=auth.tenant_id, unit_id=unit_id,
            environment=environment, correlation_id=uuid4().hex,
            host_namespace="fm-nfcore",
        )
        try:
            evidence = certificate_vault.provision(
                scope=scope, issuer_cnpj=issuer_cnpj,
                pkcs12_bytes=certificate, password=password,
            )
        except (A1VaultUnavailable, FiscalValidationError, InvalidCertificateMaterialError):
            raise HTTPException(
                422, detail={"code": "A1_VALIDATION_FAILED",
                             "message": "Certificado A1 inválido, vencido ou não pertence ao CNPJ"},
            ) from None
        return {
            "status": "stored",
            "issuer_cnpj": evidence.issuer_cnpj,
            "expires_at": evidence.expires_at.isoformat(),
            "fingerprint_sha256": evidence.certificate_fingerprint_sha256,
        }

    @router.get("/documents/{document_reference}/artifacts/{kind}")
    async def download_fiscal_artifact(
        document_reference: str,
        kind: str,
        request: Request,
        unit_id: str,
        environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    ) -> Response:
        """Serve immutable fiscal files to the same authorized human session."""
        auth = authority(request)
        _authorized(auth, PortalPermission.DOCUMENT_QUERY, unit_id=unit_id)
        if kind not in {"authorized_xml", "danfe", "auxiliary_pdf"}:
            raise HTTPException(400, detail={"code": "FISCAL_ARTIFACT_KIND_INVALID"})
        if not 1 <= len(document_reference) <= 256:
            raise HTTPException(400, detail={"code": "FISCAL_ARTIFACT_REFERENCE_INVALID"})
        reader = getattr(require_executor(), "fiscal_artifact", None)
        if not callable(reader):
            raise HTTPException(503, detail={"code": "FISCAL_ARTIFACT_READER_NOT_CONFIGURED"})
        content, media_type = reader(
            authority=auth, unit_id=unit_id, environment=environment,
            document_reference=document_reference, kind=FiscalArchiveKind(kind),
        )
        extension = "xml" if kind == "authorized_xml" else "pdf"
        disposition = "attachment" if extension == "xml" else "inline"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'{disposition}; filename="nfcore-documento.{extension}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/bootstrap")
    async def bootstrap(request: Request) -> dict[str, Any]:
        auth = authority(request)
        _authorized(auth, PortalPermission.PORTAL_READ)
        projection = dict(require_executor().snapshot(authority=auth))
        available = projection.get("available_surfaces")
        if isinstance(available, (list, tuple)):
            normalized = [
                str(item)
                for item in available
                if (
                    _SURFACE_PERMISSIONS.get(str(item)) is None
                    or _SURFACE_PERMISSIONS[str(item)] in auth.permissions
                )
            ]
            if auth.account.platform_admin:
                for platform_surface in platform_surfaces:
                    if platform_surface not in normalized:
                        normalized.append(platform_surface)
            projection["available_surfaces"] = normalized
        _safe_payload(projection)
        unit_ids = sorted(auth.account.unit_ids) if auth.account.unit_ids is not None else None
        return {
            "product": "FM NFCORE",
            "version": "1.0",
            "tenant_id": auth.account.tenant_id,
            "unit_ids": unit_ids,
            "role": auth.account.role.value,
            "platform_admin": auth.account.platform_admin,
            "permissions": sorted(permission.value for permission in auth.permissions),
            "supported_documents": ["nfe", "nfce", "nfse"],
            "projection": projection,
        }

    @router.get("/surfaces/{surface_id}")
    async def surface(surface_id: str, request: Request) -> dict[str, Any]:
        permission = _SURFACE_PERMISSIONS.get(surface_id)
        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "UNKNOWN_PORTAL_SURFACE", "message": "Unknown portal surface"},
            )
        auth = authority(request)
        unit_id = request.query_params.get("unit_id")
        _authorized(auth, permission, unit_id=unit_id)
        try:
            raw_environment = request.query_params.get("environment")
            environment = FiscalEnvironment(raw_environment) if raw_environment else None
            limit = int(request.query_params.get("limit", "100"))
            offset = int(request.query_params.get("offset", "0"))
            if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
                raise ValueError("invalid page")
            if unit_id is not None and not unit_id.strip():
                raise ValueError("blank unit")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_SURFACE_FILTER",
                    "message": "Invalid unit, environment or page",
                },
            ) from exc
        projected_rows = require_executor().surface(
            surface_id=surface_id,
            authority=auth,
            unit_id=unit_id,
            environment=environment,
            limit=limit,
            offset=offset,
        )
        rows = [dict(row) for row in projected_rows]
        _safe_payload(rows)
        return {"surface": surface_id, "rows": rows}

    def recovery_method(name: str) -> Any:
        method = getattr(require_executor(), name, None)
        if not callable(method):
            raise HTTPException(503, detail={"code": "FISCAL_RECOVERY_NOT_READY"})
        return method

    @router.get("/fiscal-intents")
    async def fiscal_intents(
        request: Request,
        unit_id: str,
        environment: FiscalEnvironment = FiscalEnvironment.HOMOLOGATION,
    ) -> dict[str, Any]:
        auth = authority(request)
        _authorized(auth, PortalPermission.PORTAL_READ, unit_id=unit_id)
        return {
            "rows": list(
                recovery_method("fiscal_intents")(
                    authority=auth, unit_id=unit_id, environment=environment
                )
            )
        }

    @router.post("/fiscal-intents/prepare/{operation_id}")
    async def prepare_intent(
        operation_id: str, request: Request, payload: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        auth = authority(request)
        _reject_browser_authority(payload)
        _csrf(request, identity, auth)
        return dict(
            recovery_method("prepare_fiscal_intent")(
                authority=auth,
                operation_id=operation_id,
                payload=payload,
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )

    @router.post("/fiscal-intents/{intent_id}/resume")
    async def resume_intent(
        intent_id: str, request: Request, payload: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        auth = authority(request)
        _reject_browser_authority(payload)
        _csrf(request, identity, auth)
        result = dict(
            recovery_method("resume_fiscal_intent")(
                authority=auth,
                intent_id=intent_id,
                payload=payload,
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )
        _safe_payload(result)
        return result

    @router.post("/operations/{operation_id}")
    async def execute_operation(
        operation_id: str,
        request: Request,
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        permission = _OPERATION_PERMISSIONS.get(operation_id)
        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "UNKNOWN_PORTAL_OPERATION", "message": "Unknown portal operation"},
            )
        auth = authority(request)
        _reject_browser_authority(payload)
        unit_id = payload.get("unit_id")
        if unit_id is not None and not isinstance(unit_id, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_UNIT", "message": "unit_id must be text"},
            )
        _authorized(auth, permission, unit_id=unit_id)
        _csrf(request, identity, auth)
        idempotency_key = request.headers.get("Idempotency-Key")
        if operation_id in _IDEMPOTENT_MUTATIONS and not (idempotency_key or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_IDEMPOTENCY_KEY",
                    "message": "Idempotency-Key is required",
                },
            )
        result = dict(
            require_executor().execute(
                operation_id=operation_id,
                authority=auth,
                payload=payload,
                idempotency_key=idempotency_key.strip() if idempotency_key else None,
            )
        )
        _safe_payload(result)
        return result

    @router.get("/egress/{tenant_id}/{unit_id}/{environment}/{destination_id}")
    async def review_egress(
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        destination_id: str,
        request: Request,
    ) -> dict[str, Any]:
        auth = authority(request)
        if not auth.account.platform_admin:
            raise HTTPException(403, detail={"code": "EGRESS_FORBIDDEN"})
        method = getattr(require_executor(), "egress_request", None)
        if not callable(method):
            raise HTTPException(503, detail={"code": "EGRESS_RUNTIME_NOT_READY"})
        result = dict(
            method(
                authority=auth,
                tenant_id=tenant_id,
                unit_id=unit_id,
                environment=environment,
                destination_id=destination_id,
            )
        )
        _safe_payload(result)
        return result

    @router.post("/egress/{tenant_id}/{unit_id}/{environment}/{destination_id}/{decision}")
    async def decide_egress(
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        destination_id: str,
        decision: str,
        request: Request,
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        auth = authority(request)
        if not auth.account.platform_admin:
            raise HTTPException(403, detail={"code": "EGRESS_FORBIDDEN"})
        _csrf(request, identity, auth)
        _reject_browser_authority(payload)
        if set(payload) - {"url", "expires_at", "expected_version"}:
            raise HTTPException(400, detail={"code": "INVALID_EGRESS_DECISION"})
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise HTTPException(400, detail={"code": "MISSING_IDEMPOTENCY_KEY"})
        method = getattr(require_executor(), "configure", None)
        if not callable(method):
            raise HTTPException(503, detail={"code": "EGRESS_RUNTIME_NOT_READY"})
        result = dict(
            method(
                authority=auth,
                tenant_id=tenant_id,
                surface_id="webhooks",
                decision=decision,
                idempotency_key=key,
                payload={
                    "unit_id": unit_id,
                    "environment": environment.value,
                    "expected_version": payload.get("expected_version"),
                    "values": {
                        "destination_id": destination_id,
                        "url": payload.get("url", ""),
                        "expires_at": payload.get("expires_at", ""),
                    },
                },
            )
        )
        _safe_payload(result)
        return result

    return router
