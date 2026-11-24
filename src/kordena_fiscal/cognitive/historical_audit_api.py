"""T15 read-only 60-month audit under the canonical Portal scope."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from kordena_fiscal.application.federal_regime_store import load_federal_regime_declarations
from kordena_fiscal.application.historical_audit import finding_page, window_report
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.security.human_identity import AuthenticatedHuman
from kordena_fiscal.tax.historical_audit import IssuerContext, closed_months
from kordena_fiscal.tax.regimes import resolve_federal_regime_timeline

from .federal_benefits_api import _authorized_federal_scope, monthly_issuer_profile
from .portal_evidence import SurfaceReader

LOCAL = ZoneInfo("America/Sao_Paulo")
HistoricalAuditRunner = Callable[
    [AuthenticatedHuman, str, FiscalEnvironment, date, dict[str, Any] | None], dict[str, Any]
]


def historical_issuer_context(
    uow_factory: Callable[[], AbstractContextManager[Any]],
    scope: ExecutionScope,
    period: date,
) -> tuple[Cnpj, IssuerContext]:
    profile, start, end = monthly_issuer_profile(uow_factory, scope, period)
    declarations = load_federal_regime_declarations(uow_factory, scope)
    regime = resolve_federal_regime_timeline(profile, declarations, start)
    if (
        resolve_federal_regime_timeline(
            profile,
            declarations,
            end - timedelta(microseconds=1),
        )
        is not regime
    ):
        raise FiscalValidationError("historical federal regime changed during competence")
    city = profile.address.jurisdiction.municipality_ibge_code
    if city is None or profile.tax_regime.value not in {1, 3}:
        raise FiscalValidationError("unsupported historical issuer context")
    return profile.cnpj, IssuerContext.model_validate(
        {
            "uf": profile.address.jurisdiction.state_code,
            "state_ibge_code": city[:2],
            "crt": profile.tax_regime.value,
            "regime": regime.value,
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "cnae": profile.primary_cnae.value,
        }
    )


def build_historical_audit_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
) -> HistoricalAuditRunner:
    def run(
        authority: AuthenticatedHuman,
        unit: str,
        environment: FiscalEnvironment,
        end: date,
        detail: dict[str, Any] | None,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit, environment)
        today = datetime.now(LOCAL).date()
        try:
            periods = closed_months(end, today)
            with uow_factory() as uow:

                def shared() -> AbstractContextManager[Any]:
                    return nullcontext(uow)

                anchor, _ = historical_issuer_context(shared, scope, end)
                profiles: dict[date, IssuerContext | None] = {}
                for period in periods:
                    try:
                        issuer, context = historical_issuer_context(shared, scope, period)
                        profiles[period] = context if issuer == anchor else None
                    except (FiscalValidationError, ValueError):
                        profiles[period] = None
            with store_factory(scope) as store:
                report, indexed = window_report(store, anchor, end, today, profiles)
                report["window_digest"] = _digest(report)[1]
                if detail is None:
                    return report
                period = date.fromisoformat(detail["month"])
                if detail["window_digest"] != report["window_digest"]:
                    raise HTTPException(409, detail={"code": "HISTORICAL_AUDIT_CHANGED"})
                row = indexed.get(period)
                if row is None or row["digest"] != detail["snapshot_digest"]:
                    raise HTTPException(409, detail={"code": "HISTORICAL_AUDIT_CHANGED"})
                month = next(x for x in report["months"] if x["competence"] == period.isoformat())
                return finding_page(
                    store,
                    anchor,
                    period,
                    row,
                    month,
                    detail["page"],
                    detail["snapshot_digest"],
                )
        except (FiscalValidationError, ValueError, KeyError, TypeError):
            raise HTTPException(422, detail={"code": "HISTORICAL_AUDIT_EVIDENCE_INVALID"}) from None

    return run
