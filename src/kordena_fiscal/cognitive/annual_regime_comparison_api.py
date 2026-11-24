"""Read-only annual comparison under existing Portal authorization and T01 RLS."""
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from kordena_fiscal.application.annual_regime_comparison import PERIOD, verify_baseline_links
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman
from kordena_fiscal.tax.annual_regime_comparison import SCHEMA, AnnualComparison, compare

from .federal_benefits_api import (
    _authorized_federal_scope,
    build_federal_issuer_verifier,
    monthly_issuer_profile,
)
from .opportunity_radar_api import OpportunityRunner
from .portal_evidence import SurfaceReader


def annual_issuer_context(
    uow_factory: Callable[[], AbstractContextManager[Any]], scope: ExecutionScope,
    issuer: str, uf: str,
) -> dict[str, str]:
    registered: dict[str, str] = {}
    # Keep the canonical profile/regime resolution, without opening 36 separate UoWs.
    with uow_factory() as uow:
        def shared() -> AbstractContextManager[Any]:
            return nullcontext(uow)

        verify = build_federal_issuer_verifier(shared, scope)
        for month in range(1, 13):
            competence = date(PERIOD.year, month, 1)
            profile, _, _ = monthly_issuer_profile(shared, scope, competence)
            if profile.cnpj.value != issuer or profile.address.jurisdiction.state_code != uf:
                raise FiscalValidationError("annual issuer scope or UF mismatch")
            registered[competence.isoformat()] = verify(issuer, competence).regime.value
    return registered


def build_annual_comparison_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> OpportunityRunner:
    def run(
        authority: AuthenticatedHuman, unit: str, environment: FiscalEnvironment, period: date,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit, environment)
        if period != PERIOD:
            raise HTTPException(422, detail={"code": "UNSUPPORTED_COMPARISON_YEAR"})
        try:
            profile, _, _ = monthly_issuer_profile(uow_factory, scope, period)
            issuer = profile.cnpj.value
            with store_factory(scope) as store:
                row = store.unique_monthly_snapshot(issuer, period, SCHEMA)
                if row is None:
                    return {"status": "insufficient_basis", "year": period.year,
                            "advisory_only": True}
                facts = AnnualComparison.model_validate(row["content"])
                registered = annual_issuer_context(uow_factory, scope, issuer, facts.baseline.uf)
                verify_baseline_links(store, profile.cnpj, facts)
                report = compare(facts)
                report["snapshot"] = {k: row[k] for k in ("record_id", "version", "digest")}
                report["registered_regime_by_month"] = registered
                return report
        except (FiscalValidationError, ValidationError):
            raise HTTPException(
                422, detail={"code": "ANNUAL_COMPARISON_EVIDENCE_INVALID"},
            ) from None

    return run
