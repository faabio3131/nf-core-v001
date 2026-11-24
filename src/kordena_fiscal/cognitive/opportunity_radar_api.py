"""Company scan using the Portal's authorized unit and the canonical issuer."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from fastapi import HTTPException

from kordena_fiscal.application.opportunity_radar import scan_benefits
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.security.human_identity import AuthenticatedHuman

from .federal_benefits_api import (
    _authorized_federal_scope,
    build_federal_issuer_verifier,
    monthly_issuer_profile,
)
from .normative_radar_api import NormativeReader
from .portal_evidence import SurfaceReader
from .state_benefits_api import build_state_issuer_verifier

OpportunityRunner = Callable[[AuthenticatedHuman, str, FiscalEnvironment, date], dict[str, Any]]


def build_opportunity_runner(
    reader: SurfaceReader,
    store_factory: Callable[[ExecutionScope], AbstractContextManager[EconomyStore]],
    uow_factory: Callable[[], AbstractContextManager[Any]],
    normative: NormativeReader | None,
) -> OpportunityRunner:
    def run(
        authority: AuthenticatedHuman, unit: str, environment: FiscalEnvironment, month: date,
    ) -> dict[str, Any]:
        scope = _authorized_federal_scope(reader, authority, unit, environment)
        try:
            profile, _, _ = monthly_issuer_profile(uow_factory, scope, month)
            with store_factory(scope) as store:
                report = scan_benefits(
                    store, profile.cnpj.value, profile.address.jurisdiction.municipality_ibge_code,
                    month, build_federal_issuer_verifier(uow_factory, scope, store),
                    build_state_issuer_verifier(uow_factory, scope),
                )
        except FiscalValidationError:
            raise HTTPException(422, detail={"code": "RADAR_SCOPE_OR_EVIDENCE_INVALID"}) from None
        signals = []
        status = "unavailable"
        if normative is not None:
            try:
                projection = normative(authority, unit, environment)
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
            else:
                status = projection["status"]
                categories = {"anistia", "refis", "transacao", "parcelamento"}
                signals = [event for event in projection["alerts"] if event["source_current"]
                           and event["category"] in categories]
        report["public_signals"] = signals
        report["coverage"]["public_signals"] = {"status": status}
        return report
    return run
