"""Approved metadata-only recovery over canonical configuration receipts.

A committed claim precedes dispatch. An interrupted claim is never dispatched again:
only exact canonical evidence can resolve it; otherwise reconciliation is required.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from kordena_fiscal.archive import FiscalArchiveKind
from kordena_fiscal.control_plane.models import ControlPlaneAuditAction, ControlPlaneAuditEvent
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.lifecycle import IdempotencyKey
from kordena_fiscal.operations.event_archive import EVENT_RESULT_MEDIA_TYPE, event_archive_reference
from kordena_fiscal.persistence.ports import FiscalUnitOfWork, FiscalUnitOfWorkFactory
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalPermission

PERMISSIONS = {
    "issueFiscalDocument": PortalPermission.DOCUMENT_ISSUE,
    "cancelFiscalDocument": PortalPermission.DOCUMENT_CANCEL,
    "inutilizeFiscalRange": PortalPermission.DOCUMENT_INUTILIZE,
    "reconcileFiscalOperation": PortalPermission.RECONCILIATION_EXECUTE,
}
OPERATIONS = {
    "issueFiscalDocument": frozenset({"issue", "issueFiscalDocument"}),
    "cancelFiscalDocument": frozenset({"cancel", "cancelFiscalDocument"}),
    "inutilizeFiscalRange": frozenset({"inutilize", "inutilizeFiscalRange"}),
    "reconcileFiscalOperation": frozenset({"reconcile", "reconcileFiscalOperation"}),
}
POLICY = "T07-v1-24h-same-account-epoch"
HOST = "fm-nfcore"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def denied(code: str, status: int = 409) -> HTTPException:
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": "Pedido bloqueado; preserve o original e consulte a reconciliação.",
        },
    )


class FiscalIntentRecovery:
    def __init__(self, factory: FiscalUnitOfWorkFactory) -> None:
        self.factory = factory

    def scope(self, auth: AuthenticatedHuman, payload: Mapping[str, Any]) -> ExecutionScope:
        if any(
            k in payload
            for k in (
                "tenant_id",
                "host_namespace",
                "account_id",
                "session_epoch",
                "platform_admin",
                "role",
                "permissions",
                "authority",
            )
        ):
            raise denied("INVALID_BROWSER_AUTHORITY", 400)
        unit = payload.get("unit_id")
        if not isinstance(unit, str) or not unit.strip():
            raise denied("FISCAL_UNIT_REQUIRED", 400)
        try:
            env = FiscalEnvironment(payload.get("environment", "homologation"))
        except (ValueError, TypeError) as exc:
            raise denied("INVALID_ENVIRONMENT", 400) from exc
        if not auth.account.enabled or (
            auth.account.unit_ids is not None and unit not in auth.account.unit_ids
        ):
            raise denied("PORTAL_FORBIDDEN", 403)
        scope = ExecutionScope(
            tenant_id=auth.tenant_id,
            unit_id=unit,
            environment=env,
            host_namespace=HOST,
            correlation_id="fiscal-recovery",
        )
        with self.factory() as uow:
            registration = uow.control_plane.get_unit(auth.tenant_id, unit)
            organization = uow.control_plane.get_organization(auth.tenant_id)
        if registration is None or organization is None:
            raise denied("FISCAL_UNIT_NOT_CONFIGURED")
        if env not in registration.enabled_environments:
            raise denied("FISCAL_ENVIRONMENT_NOT_ENABLED", 403)
        return scope

    @staticmethod
    def prefix(auth: AuthenticatedHuman) -> str:
        return "fiscal-intent:" + digest(HOST + ":" + auth.account.account_id) + ":"

    @staticmethod
    def permission(auth: AuthenticatedHuman, operation: str) -> None:
        if operation not in PERMISSIONS or PERMISSIONS[operation] not in auth.account.permissions:
            raise denied("PORTAL_FORBIDDEN", 403)

    @staticmethod
    def fingerprint(operation: str, scope: ExecutionScope, payload: Mapping[str, Any]) -> str:
        try:
            body = {**payload, "unit_id": scope.unit_id, "environment": scope.environment.value}
            return digest(
                json.dumps(
                    [
                        HOST,
                        scope.tenant_id,
                        scope.unit_id,
                        scope.environment.value,
                        operation,
                        body,
                    ],
                    sort_keys=True,
                    allow_nan=False,
                )
            )
        except (ValueError, TypeError) as exc:
            raise denied("INVALID_FISCAL_REQUEST", 400) from exc

    @staticmethod
    def audit(
        uow: FiscalUnitOfWork,
        auth: AuthenticatedHuman,
        scope: ExecutionScope,
        intent: str,
        action: ControlPlaneAuditAction,
    ) -> None:
        uow.control_plane.append_audit(
            ControlPlaneAuditEvent(
                event_id=uuid4().hex,
                occurred_at=datetime.now(UTC),
                actor_id=auth.account.account_id,
                action=action,
                target_type="fiscal_intent",
                target_id=digest(intent),
                correlation_id="fiscal-recovery",
                tenant_id=scope.tenant_id,
                unit_id=scope.unit_id,
            )
        )

    def blocked(
        self,
        auth: AuthenticatedHuman,
        scope: ExecutionScope,
        intent: str,
        code: str,
        status: int = 409,
    ) -> None:
        with self.factory() as uow:
            self.audit(uow, auth, scope, intent, ControlPlaneAuditAction.FISCAL_INTENT_BLOCKED)
            uow.commit()
        raise denied(code, status)

    @staticmethod
    def project(row: Mapping[str, object], *, replay: bool = True) -> Mapping[str, Any]:
        return {
            key: row.get(key)
            for key in (
                "intent_id",
                "operation",
                "unit_id",
                "environment",
                "created_at",
                "expires_at",
                "state",
                "reference_id",
            )
        } | {"replay": replay, "fiscal_confirmation": "not_inferred_from_receipt"}

    def validate(
        self,
        auth: AuthenticatedHuman,
        scope: ExecutionScope,
        row: Mapping[str, object],
        intent: str,
    ) -> None:
        if (
            row.get("policy") != POLICY
            or row.get("account_id") != auth.account.account_id
            or row.get("session_epoch") != auth.account.session_epoch
            or row.get("host_namespace") != HOST
            or row.get("tenant_id") != scope.tenant_id
            or row.get("unit_id") != scope.unit_id
            or row.get("environment") != scope.environment.value
        ):
            self.blocked(auth, scope, intent, "FISCAL_INTENT_AUTHORITY_CHANGED", 403)
        if PERMISSIONS.get(str(row.get("operation"))) not in auth.account.permissions:
            self.blocked(auth, scope, intent, "PORTAL_FORBIDDEN", 403)
        try:
            expired = datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC)
        except (ValueError, KeyError) as exc:
            raise denied("FISCAL_INTENT_POLICY_REQUIRED") from exc
        if expired:
            self.blocked(auth, scope, intent, "FISCAL_INTENT_EXPIRED")

    def prepare(
        self, auth: AuthenticatedHuman, operation: str, payload: Mapping[str, Any], key: str | None
    ) -> Mapping[str, Any]:
        self.permission(auth, operation)
        if not key or not key.strip():
            raise denied("MISSING_IDEMPOTENCY_KEY", 400)
        scope = self.scope(auth, payload)
        fingerprint = self.fingerprint(operation, scope, payload)
        intent = self.prefix(auth) + digest(self.prefix(auth) + fingerprint)
        alias = "fiscal-key:" + digest(HOST + ":" + auth.account.account_id + ":" + key)
        now = datetime.now(UTC)
        row: Mapping[str, object] = {
            "intent_id": intent,
            "policy": POLICY,
            "operation": operation,
            "account_id": auth.account.account_id,
            "session_epoch": auth.account.session_epoch,
            "host_namespace": HOST,
            "tenant_id": scope.tenant_id,
            "unit_id": scope.unit_id,
            "environment": scope.environment.value,
            "fingerprint": fingerprint,
            "original_key": key,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "state": "prepared",
            "reference_id": None,
        }
        with self.factory() as uow:
            old = uow.commercial.configuration_receipt(scope, intent)
        if old is not None:
            self.validate(auth, scope, old, intent)
        with self.factory() as uow:
            previous_alias = uow.commercial.reserve_configuration_command(scope, alias, fingerprint)
            if previous_alias is None:
                uow.commercial.complete_configuration_command(scope, alias, {"intent_id": intent})
            existing = uow.commercial.reserve_configuration_command(scope, intent, fingerprint)
            if existing is None:
                uow.commercial.complete_configuration_command(scope, intent, row)
            else:
                row = existing
            self.audit(uow, auth, scope, intent, ControlPlaneAuditAction.FISCAL_INTENT_PREPARED)
            uow.commit()
        self.validate(auth, scope, row, intent)
        return self.project(row, replay=existing is not None)

    def list(
        self, auth: AuthenticatedHuman, payload: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], ...]:
        scope = self.scope(auth, payload)
        with self.factory() as uow:
            rows = uow.commercial.list_configuration_receipts(scope, self.prefix(auth))
            self.audit(uow, auth, scope, "list", ControlPlaneAuditAction.FISCAL_INTENT_RECOVERED)
            uow.commit()
        return tuple(
            self.project(r)
            for r in rows
            if r.get("policy") == POLICY
            and r.get("session_epoch") == auth.account.session_epoch
            and PERMISSIONS.get(str(r.get("operation"))) in auth.account.permissions
        )

    def claim(
        self, auth: AuthenticatedHuman, intent: str, payload: Mapping[str, Any], key: str | None
    ) -> tuple[ExecutionScope, Mapping[str, object], bool]:
        if not key or not key.strip():
            raise denied("MISSING_IDEMPOTENCY_KEY", 400)
        scope = self.scope(auth, payload)
        if not intent.startswith(self.prefix(auth)):
            self.blocked(auth, scope, intent, "FISCAL_INTENT_NOT_FOUND", 404)
        with self.factory() as uow:
            row = uow.commercial.configuration_receipt(scope, intent)
        if row is None:
            self.blocked(auth, scope, intent, "FISCAL_INTENT_NOT_FOUND", 404)
        assert row is not None
        self.validate(auth, scope, row, intent)
        if row.get("fingerprint") != self.fingerprint(str(row["operation"]), scope, payload):
            self.blocked(auth, scope, intent, "FISCAL_INTENT_CONTENT_CONFLICT")
        if row.get("state") == "recorded":
            return scope, row, False
        if row.get("state") == "executing":
            return scope, self.resolve(auth, scope, row), False
        if row.get("state") != "prepared":
            self.blocked(auth, scope, intent, "FISCAL_INTENT_POLICY_REQUIRED")
        updated = dict(row) | {"state": "executing"}
        with self.factory() as uow:
            if not uow.commercial.replace_configuration_receipt(scope, intent, row, updated):
                raise denied("FISCAL_INTENT_CONCURRENT")
            self.audit(uow, auth, scope, intent, ControlPlaneAuditAction.FISCAL_INTENT_RESUMED)
            uow.commit()
        return scope, updated, True

    def resolve(
        self, auth: AuthenticatedHuman, scope: ExecutionScope, row: Mapping[str, object]
    ) -> Mapping[str, object]:
        with self.factory() as uow:
            entries = uow.outbox.list_for_scope(scope, operations=OPERATIONS[str(row["operation"])])
            matches = [
                e
                for e in entries
                if e.scope.host_namespace == HOST and e.scope.correlation_id == row["original_key"]
            ]
        if not matches and row["operation"] == "issueFiscalDocument":
            with self.factory() as uow:
                attempts = uow.idempotency.attempts(
                    IdempotencyKey(digest(str(row["original_key"])))
                )
                if len(attempts) == 1:
                    uow.lifecycle.assert_scope(attempts[0].document_id, scope)
                    document_id = attempts[0].document_id
                else:
                    document_id = None
            if document_id is not None:
                return self.finish(auth, scope, row, document_id)
        if not matches and row["operation"] in {"cancelFiscalDocument", "inutilizeFiscalRange"}:
            reference = event_archive_reference(str(row["operation"]), str(row["original_key"]))
            with self.factory() as uow:
                evidence = [
                    entry for entry in uow.archive.list_for_document(scope, reference)
                    if entry.kind is FiscalArchiveKind.FISCAL_EVENT
                    and entry.media_type == EVENT_RESULT_MEDIA_TYPE
                    and entry.scope.correlation_id == row["original_key"]
                    and entry.scope.identity_partition_key == scope.identity_partition_key
                ]
            if len(evidence) == 1:
                return self.finish(auth, scope, row, evidence[0].entry_id)
        if len(matches) != 1:
            self.blocked(auth, scope, str(row["intent_id"]), "FISCAL_RECONCILIATION_REQUIRED")
        return self.finish(auth, scope, row, matches[0].entry_id)

    def finish(
        self,
        auth: AuthenticatedHuman,
        scope: ExecutionScope,
        row: Mapping[str, object],
        reference: object = None,
    ) -> Mapping[str, object]:
        intent = str(row["intent_id"])
        updated = dict(row) | {
            "state": "recorded",
            "reference_id": reference if isinstance(reference, str) else None,
        }
        with self.factory() as uow:
            if not uow.commercial.replace_configuration_receipt(scope, intent, row, updated):
                current = uow.commercial.configuration_receipt(scope, intent)
                if (
                    current is None
                    or current.get("state") != "recorded"
                    or current.get("fingerprint") != row["fingerprint"]
                ):
                    raise denied("FISCAL_INTENT_CONCURRENT")
                updated = dict(current)
            self.audit(uow, auth, scope, intent, ControlPlaneAuditAction.FISCAL_INTENT_RECOVERED)
            uow.commit()
        return updated
