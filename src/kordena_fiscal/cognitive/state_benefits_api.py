"""T09 state advisory API reuses T08 Portal session/unit and issuer authorities."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from kordena_fiscal.application.state_benefits_service import (
    evaluate_state_benefit,
    search_state_benefits,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
)
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman
from kordena_fiscal.tax.state_benefits import ReviewedStateIssuer

from .federal_benefits_api import (
    _authorized_federal_scope,
    build_federal_issuer_verifier,
)
from .portal_evidence import SurfaceReader

StateBenefitRunner = Callable[
    [AuthenticatedHuman, str, FiscalEnvironment, str, int, str, int], dict[str, Any]
]
StateSearchRunner = Callable[
    [AuthenticatedHuman, str, FiscalEnvironment, str, int], dict[str, Any]
]


def build_state_issuer_verifier(
    uow_factory: Callable[[], AbstractContextManager[Any]], scope: ExecutionScope,
) -> Callable[[str, date], ReviewedStateIssuer]:
    """No parallel issuer: T08 checks complete monthly profile/regime stability."""
    federal = build_federal_issuer_verifier(uow_factory, scope)

    def verify(cnpj: str, competence: date) -> ReviewedStateIssuer:
        authority = federal(cnpj, competence)
        instant = datetime.combine(
            competence, time.min, tzinfo=ZoneInfo("America/Sao_Paulo"),
        )
        with uow_factory() as uow:
            profile = uow.control_plane.resolve_profile(
                host_namespace=scope.host_namespace, tenant_id=scope.tenant_id,
                unit_id=scope.unit_id, environment=scope.environment, instant=instant,
            )
        if (
            not isinstance(profile, FiscalProfile)
            or profile.scope.identity_material != scope.identity_material
            or profile.cnpj.value != authority.cnpj
            or profile.primary_cnae.value != authority.cnae
        ):
            raise FiscalValidationError("canonical state issuer authority mismatch")
        return ReviewedStateIssuer(
            cnpj=cnpj, uf=profile.address.jurisdiction.state_code,
            primary_cnae=authority.cnae, regime=authority.regime,
            state_registration_present=(
                not profile.state_registration.exempt
                and bool(profile.state_registration.number)
            ),
            scope_identity=scope.identity_material,
        )
    return verify


def build_state_benefit_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> StateBenefitRunner:
    def run(
        authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment,
        snapshot_id: str, snapshot_version: int, benefit_id: str, benefit_version: int,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit_id, environment)
        try:
            verify = build_state_issuer_verifier(uow_factory, scope)
            with store_factory(scope) as store:
                return evaluate_state_benefit(
                    store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
                    benefit_id=benefit_id, benefit_version=benefit_version,
                    verify_issuer=verify,
                )
        except FiscalValidationError:
            raise HTTPException(
                422, detail={"code": "STATE_BENEFIT_EVIDENCE_INSUFFICIENT"},
            ) from None
    return run


def build_state_search_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> StateSearchRunner:
    def run(
        authority: AuthenticatedHuman, unit_id: str, environment: FiscalEnvironment,
        snapshot_id: str, snapshot_version: int,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit_id, environment)
        try:
            verify = build_state_issuer_verifier(uow_factory, scope)
            with store_factory(scope) as store:
                return search_state_benefits(
                    store, snapshot_id=snapshot_id, snapshot_version=snapshot_version,
                    verify_issuer=verify,
                )
        except FiscalValidationError:
            raise HTTPException(
                422, detail={"code": "STATE_BENEFIT_EVIDENCE_INSUFFICIENT"},
            ) from None
    return run
