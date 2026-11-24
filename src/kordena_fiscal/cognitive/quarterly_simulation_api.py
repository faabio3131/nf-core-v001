"""Resolve the company's reviewed quarter from T01 under the existing Portal session."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman
from kordena_fiscal.tax.quarterly_simulation import SCHEMA, Quarter, simulate

from .federal_benefits_api import (
    _authorized_federal_scope,
    build_federal_issuer_verifier,
    monthly_issuer_profile,
)
from .opportunity_radar_api import OpportunityRunner
from .portal_evidence import SurfaceReader


def build_simulation_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> OpportunityRunner:
    def run(
        authority: AuthenticatedHuman, unit: str, environment: FiscalEnvironment, quarter: date,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit, environment)
        if quarter.year != 2026 or quarter.day != 1 or quarter.month not in (1, 4, 7, 10):
            raise HTTPException(422, detail={"code": "UNSUPPORTED_SIMULATION_QUARTER"})
        try:
            profile, _, _ = monthly_issuer_profile(uow_factory, scope, quarter)
            issuer = profile.cnpj.value
            verify = build_federal_issuer_verifier(uow_factory, scope)
            regimes = {verify(issuer, date(quarter.year, quarter.month + offset, 1)).regime
                       for offset in range(3)}
            if len(regimes) != 1:
                raise FiscalValidationError("regime changed within quarter")
            with store_factory(scope) as store:
                row = store.unique_monthly_snapshot(issuer, quarter, SCHEMA)
                if row is None:
                    return {"status": "insufficient_basis", "period_start": quarter.isoformat(),
                            "advisory_only": True}
                report = simulate(quarter, Quarter.model_validate(row["content"]))
                report["snapshot"] = {k: row[k] for k in ("record_id", "version", "digest")}
                report["registered_regime"] = regimes.pop().value
                return report
        except (FiscalValidationError, ValidationError):
            raise HTTPException(422, detail={"code": "SIMULATION_EVIDENCE_INVALID"}) from None
    return run
