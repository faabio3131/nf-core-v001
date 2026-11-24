"""T13 boundary: session scope, current deterministic evidence and accountant MFA."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from kordena_fiscal.application.accounting_review import (
    ReviewConflict,
    ReviewDecision,
    ReviewTarget,
    project_review,
    record_decision,
)
from kordena_fiscal.application.annual_regime_comparison import PERIOD, verify_baseline_links
from kordena_fiscal.application.opportunity_radar import scan_benefits
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalRole
from kordena_fiscal.tax.annual_regime_comparison import SCHEMA, AnnualComparison, compare

from .annual_regime_comparison_api import annual_issuer_context
from .federal_benefits_api import (
    _authorized_federal_scope,
    build_federal_issuer_verifier,
    monthly_issuer_profile,
)
from .portal_evidence import SurfaceReader
from .state_benefits_api import build_state_issuer_verifier

AccountingReviewRunner = Callable[
    [
        AuthenticatedHuman,
        str,
        FiscalEnvironment,
        date,
        ReviewTarget,
        ReviewDecision | None,
        int | None,
    ],
    dict[str, Any],
]


def _current_subject(
    store: EconomyStore,
    uow_factory: Callable[[], AbstractContextManager[Any]],
    scope: ExecutionScope,
    period: date,
    target: ReviewTarget,
) -> tuple[Cnpj, dict[str, Any]]:
    profile, _, _ = monthly_issuer_profile(uow_factory, scope, period)
    issuer = profile.cnpj
    if target.kind == "annual_comparison":
        if period != PERIOD:
            raise FiscalValidationError("unsupported annual review year")
        row = store.unique_monthly_snapshot(issuer.value, period, SCHEMA)
        if row is None:
            raise FiscalValidationError("missing annual comparison evidence")
        facts = AnnualComparison.model_validate(row["content"])
        registered = annual_issuer_context(uow_factory, scope, issuer.value, facts.baseline.uf)
        verify_baseline_links(store, issuer, facts)
        report = compare(facts)
        subject = {
            "kind": target.kind,
            "snapshot": {k: row[k] for k in ("record_id", "version", "digest")},
            "result_digest": _digest(report)[1],
            "registered_regime_by_month": registered,
            "recommendation": report["recommendation"],
            "annual_tax_cents": report["scenarios"]["baseline"]["annual_tax_cents"],
            "source_mode": report["source_mode"],
        }
        return issuer, subject
    radar = scan_benefits(
        store,
        issuer.value,
        profile.address.jurisdiction.municipality_ibge_code,
        period,
        build_federal_issuer_verifier(uow_factory, scope, store),
        build_state_issuer_verifier(uow_factory, scope),
    )
    assert target.source is not None
    if radar["coverage"][target.source]["coverage_truncated"]:
        raise FiscalValidationError("incomplete benefit search cannot be approved")
    matches = [
        item
        for item in radar["opportunities"]
        if item["source"] == target.source and item["benefit_id"] == target.benefit_id
    ]
    if len(matches) != 1:
        raise FiscalValidationError("missing or ambiguous current benefit")
    candidate = matches[0]
    subject = {
        "kind": target.kind,
        "source": target.source,
        "benefit_id": target.benefit_id,
        "benefit_version": candidate["benefit_version"],
        "benefit_digest": candidate["benefit_digest"],
        "snapshot_id": candidate["snapshot_id"],
        "snapshot_version": candidate["snapshot_version"],
        "snapshot_digest": candidate["snapshot_digest"],
        "estimated_cents": candidate["estimated_cents"],
        "result_digest": _digest(candidate)[1],
        "candidate": candidate,
    }
    return issuer, subject


def build_accounting_review_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
    step_up: Callable[[str, datetime], bool] | None,
) -> AccountingReviewRunner:
    def run(
        authority: AuthenticatedHuman,
        unit: str,
        environment: FiscalEnvironment,
        period: date,
        target: ReviewTarget,
        command: ReviewDecision | None,
        before_version: int | None,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit, environment)
        designated = (
            authority.account.role is PortalRole.ACCOUNTANT
            and authority.account.unit_ids is not None
            and unit in authority.account.unit_ids
        )
        can_decide = designated and step_up is not None
        instant = datetime.now(UTC)
        if command is not None:
            if not designated:
                raise HTTPException(403, detail={"code": "ACCOUNTANT_REQUIRED"})
            if step_up is None:
                raise HTTPException(503, detail={"code": "ACCOUNTING_REVIEW_MFA_UNAVAILABLE"})
            if not step_up(authority.session_id, instant):
                raise HTTPException(403, detail={"code": "STEP_UP_REQUIRED"})
        try:
            with store_factory(scope) as store:
                try:
                    issuer, subject = _current_subject(store, uow_factory, scope, period, target)
                except (FiscalValidationError, ValidationError):
                    if command is not None:
                        raise
                    profile, _, _ = monthly_issuer_profile(uow_factory, scope, period)
                    report = project_review(
                        store,
                        profile.cnpj,
                        period,
                        target,
                        None,
                        before_version=before_version,
                    )
                    report["can_decide"] = False
                    return report
                if command is None:
                    report = project_review(
                        store,
                        issuer,
                        period,
                        target,
                        subject,
                        before_version=before_version,
                    )
                else:
                    instant = datetime.now(UTC)
                    if step_up is None or not step_up(authority.session_id, instant):
                        raise HTTPException(403, detail={"code": "STEP_UP_REQUIRED"})
                    report = record_decision(
                        store,
                        issuer,
                        period,
                        target,
                        subject,
                        command,
                        actor_id=authority.account.account_id,
                        now=instant,
                    )
                report["can_decide"] = can_decide
                return report
        except ReviewConflict:
            raise HTTPException(409, detail={"code": "ACCOUNTING_REVIEW_CONFLICT"}) from None
        except (FiscalValidationError, ValidationError, KeyError, TypeError, ValueError):
            raise HTTPException(
                422, detail={"code": "ACCOUNTING_REVIEW_EVIDENCE_INVALID"}
            ) from None

    return run
