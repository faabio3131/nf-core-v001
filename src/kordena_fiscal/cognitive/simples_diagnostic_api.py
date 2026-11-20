"""T05 session-scoped diagnostic using the existing canonical database."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from kordena_fiscal.application.federal_regime_store import load_federal_regime_declarations
from kordena_fiscal.application.rtc_shadow_recorder import shadow_clients_from_env
from kordena_fiscal.application.simples_diagnostic_service import evaluate_and_record
from kordena_fiscal.application.simples_segregation_service import evaluate_segregation
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
)
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalPermission
from kordena_fiscal.tax.regimes import (
    FederalIncomeTaxRegime,
    resolve_federal_regime_timeline,
)
from kordena_fiscal.tax.simples_nacional import SimplesFacts

from .portal_evidence import SurfaceReader

DiagnosticRunner = Callable[
    [AuthenticatedHuman, str, FiscalEnvironment, str, int, str, int], dict[str, Any]
]


def build_diagnostic_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
    *, segregation: bool = False, assessment: bool = False,
) -> DiagnosticRunner:
    def run(
        authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment,
        snapshot_id: str, snapshot_version: int, rule_id: str, rule_version: int,
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
            raise HTTPException(403, detail={"code": "SIMPLES_SCOPE_FORBIDDEN"})
        scope = ExecutionScope(
            tenant_id=authority.tenant_id, unit_id=unit_id, environment=environment,
            correlation_id="simples-diagnostic", host_namespace="fm-nfcore",
        )

        verify = build_issuer_verifier(uow_factory, scope)

        try:
            with store_factory(scope) as store:
                if segregation or assessment:
                    rtc_simples, rtc_regular = shadow_clients_from_env() if assessment else (
                        None, None,
                    )
                    return evaluate_segregation(
                        store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
                        rule_id=rule_id, rule_version=rule_version, verify_issuer=verify,
                        assessment=assessment, rtc_simples=rtc_simples, rtc_regular=rtc_regular,
                    )
                return evaluate_and_record(
                    store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
                    rule_id=rule_id, rule_version=rule_version, verify_issuer=verify,
                )
        except FiscalValidationError:
            raise HTTPException(422, detail={"code": "SIMPLES_EVIDENCE_INSUFFICIENT"}) from None

    return run


def build_issuer_verifier(
    uow_factory: Callable[[], AbstractContextManager[Any]], scope: ExecutionScope,
) -> Callable[[str, SimplesFacts], FiscalProfile]:
    """Reuse existing effective-dated issuer and declared-regime authority."""
    def verify(issuer: str, facts: SimplesFacts) -> FiscalProfile:
        start = datetime.combine(
            facts.competence, time.min, tzinfo=ZoneInfo("America/Sao_Paulo"),
        )
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if facts.registered_on is not None and facts.opened_month == facts.competence:
            start = datetime.combine(facts.registered_on, time.min, tzinfo=start.tzinfo)
        with uow_factory() as uow:
            profile = uow.control_plane.resolve_profile(
                host_namespace="fm-nfcore", tenant_id=scope.tenant_id,
                unit_id=scope.unit_id, environment=scope.environment, instant=start,
            )
        if (
            not isinstance(profile, FiscalProfile) or profile.cnpj.value != issuer
            or profile.address.jurisdiction.state_code != facts.uf
            or int(profile.tax_regime) not in (1, 2)
            or profile.effective_to is not None and profile.effective_to < end
        ):
            raise FiscalValidationError("canonical issuer does not match reviewed snapshot")
        declarations = load_federal_regime_declarations(uow_factory, scope)
        for instant in (start, end - timedelta(microseconds=1)):
            if resolve_federal_regime_timeline(
                profile, declarations, instant,
            ) is not FederalIncomeTaxRegime.SIMPLES_NACIONAL:
                raise FiscalValidationError("Simples regime not declared for competence")
        return profile

    return verify
