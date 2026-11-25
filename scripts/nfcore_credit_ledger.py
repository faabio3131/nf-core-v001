"""Post or reconcile reviewed T18 simulations, never production."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from kordena_fiscal.application.credit_ledger import (
    ReviewedMovement,
    history,
    post_movement,
    reconcile,
)
from kordena_fiscal.application.unused_credits import verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.tax.unused_credits import _unique_fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--post", type=Path)
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--history", metavar="FINDING_ID")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--competence", help="required for --post and --history")
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("credit ledger requires a non-production environment")
    if os.environ.get("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("credit ledger unavailable")
    try:
        issuer = Cnpj(args.issuer)
        period = date.fromisoformat(args.competence) if args.competence else None
        if period is None and not args.report:
            raise ValueError("competence required for movement or history")
        if period is not None and (period.day != 1 or period.isoformat() != args.competence):
            raise ValueError("invalid competence")
        reviewed = None
        if args.post:
            with args.post.open("rb") as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                raise ValueError("ledger bundle exceeds 64 KiB")
            reviewed = ReviewedMovement.model_validate(
                json.loads(raw, object_pairs_hook=_unique_fields)
            )
            if period is None or reviewed.command.competence != period.isoformat():
                raise ValueError("ledger competence mismatch")
    except (OSError, FiscalValidationError, ValueError, TypeError, KeyError):
        parser.error("invalid ledger bundle or scope")
    scope = ExecutionScope(
        args.tenant, args.unit, FiscalEnvironment.HOMOLOGATION,
        "credit-ledger-reviewed-simulation", "fm-nfcore",
    )
    db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with db() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("unit not enabled in homologation")
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        anchor = period or (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        canonical, context = historical_issuer_context(db, scope, anchor)
        if canonical != issuer:
            parser.error("canonical issuer mismatch")
        unit_proof = verify_credit_unit(db, scope, issuer)
        with db.economy(scope) as store:
            if reviewed is not None:
                report = post_movement(
                    store, issuer, reviewed, context=context, as_of=today, unit=unit_proof
                )
            elif args.history:
                if period is None:
                    raise FiscalValidationError("history requires competence")
                report = history(store, issuer, period, args.history)
            else:
                report = reconcile(store, issuer, period)
        print(json.dumps(report))
    except (FiscalValidationError, ValueError, TypeError, KeyError):
        parser.error("ledger evidence invalid or balance/version conflict")
    finally:
        db.close()


if __name__ == "__main__":
    main()
