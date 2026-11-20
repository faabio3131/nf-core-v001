"""T08 HTTP runner: same Portal session/unit authority and T01 scoped database."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from kordena_fiscal.application.federal_benefits_service import evaluate_federal_benefit
from kordena_fiscal.application.federal_regime_store import load_federal_regime_declarations
from kordena_fiscal.domain import (
    ExecutionScope, FiscalEnvironment, FiscalProfile, FiscalValidationError,
)
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalPermission
from kordena_fiscal.tax.federal_benefits import ReviewedFederalIssuer
from kordena_fiscal.tax.regimes import resolve_federal_regime_timeline

from .portal_evidence import SurfaceReader

FederalBenefitRunner = Callable[
    [AuthenticatedHuman, str, FiscalEnvironment, str, int, str, int], dict[str, Any]
]


def build_federal_issuer_verifier(
    uow_factory: Callable[[], AbstractContextManager[Any]], scope: ExecutionScope,
) -> Callable[[str, date], ReviewedFederalIssuer]:
    """Resolve the canonical issuer and effective federal regime for a whole month."""
    def verify(issuer: str, competence: date) -> ReviewedFederalIssuer:
        start = datetime.combine(competence, time.min, tzinfo=ZoneInfo("America/Sao_Paulo"))
        end = datetime.combine(
            date(competence.year + (competence.month == 12), competence.month % 12 + 1, 1),
            time.min, tzinfo=start.tzinfo,
        )
        with uow_factory() as uow:
            first = uow.control_plane.resolve_profile(
                host_namespace=scope.host_namespace, tenant_id=scope.tenant_id,
                unit_id=scope.unit_id, environment=scope.environment, instant=start,
            )
            last = uow.control_plane.resolve_profile(
                host_namespace=scope.host_namespace, tenant_id=scope.tenant_id,
                unit_id=scope.unit_id, environment=scope.environment,
                instant=end - timedelta(microseconds=1),
            )
        if (
            not isinstance(first, FiscalProfile)
            or not isinstance(last, FiscalProfile)
            or first != last
            or first.cnpj.value != issuer
            or first.scope.identity_material != scope.identity_material
        ):
            raise FiscalValidationError("canonical issuer not stable across competence")
        declarations = load_federal_regime_declarations(uow_factory, scope)
        regime = resolve_federal_regime_timeline(first, declarations, start)
        if resolve_federal_regime_timeline(
            first, declarations, end - timedelta(microseconds=1),
        ) is not regime:
            raise FiscalValidationError("federal regime changed during competence")
        return ReviewedFederalIssuer(
            cnpj=issuer, cnae=first.primary_cnae.value, regime=regime,
            scope_identity=scope.identity_material,
        )
    return verify


def build_federal_benefit_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> FederalBenefitRunner:
    def run(
        authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment,
        snapshot_id: str, snapshot_version: int, benefit_id: str, benefit_version: int,
    ) -> dict[str, Any]:
        authority.assert_permission(PortalPermission.AUDIT_READ, unit_id=unit_id)
        rows = reader.surface(
            surface_id="units", authority=authority, unit_id=unit_id, environment=environment,
        )
        if not any(
            row.get("unit_id") == unit_id
            and row.get("tenant_id", authority.tenant_id) == authority.tenant_id
            and environment.value in (row.get("enabled_environments") or ())
            for row in rows
        ):
            raise HTTPException(403, detail={"code": "FEDERAL_BENEFIT_SCOPE_FORBIDDEN"})
        scope = ExecutionScope(
            tenant_id=authority.tenant_id, unit_id=unit_id, environment=environment,
            correlation_id="federal-benefit-advisory", host_namespace="fm-nfcore",
        )
        try:
            verify = build_federal_issuer_verifier(uow_factory, scope)
            with store_factory(scope) as store:
                return evaluate_federal_benefit(
                    store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
                    benefit_id=benefit_id, benefit_version=benefit_version,
                    verify_issuer=verify,
                )
        except FiscalValidationError:
            raise HTTPException(
                422, detail={"code": "FEDERAL_BENEFIT_EVIDENCE_INSUFFICIENT"},
            ) from None
    return run
