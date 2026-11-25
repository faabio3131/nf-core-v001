"""Post or reconcile reviewed T18 simulations, never production."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from kordena_fiscal.application.credit_ledger import ReviewedMovement, post_movement, reconcile
from kordena_fiscal.application.historical_audit import MAX_INPUT_BYTES
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
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--competence", required=True)
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("credit ledger requires a non-production environment")
    if os.environ.get("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("credit ledger unavailable")
    try:
        issuer = Cnpj(args.issuer)
        period = date.fromisoformat(args.competence)
        if period.day != 1 or period.isoformat() != args.competence:
            raise ValueError("invalid competence")
        reviewed = None
        if args.post:
            if args.post.stat().st_size > MAX_INPUT_BYTES:
                raise ValueError("ledger bundle exceeds 32 MiB")
            reviewed = ReviewedMovement.model_validate(
                json.loads(args.post.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
            )
            if reviewed.command.competence != period.isoformat():
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
        canonical, context = historical_issuer_context(db, scope, period)
        if canonical != issuer:
            parser.error("canonical issuer mismatch")
        verify_credit_unit(db, scope, issuer)
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        with db.economy(scope) as store:
            report = (
                reconcile(store, issuer, period)
                if reviewed is None
                else post_movement(store, issuer, reviewed, context=context, as_of=today)
            )
        print(json.dumps(report))
    except (FiscalValidationError, ValueError, TypeError, KeyError):
        parser.error("ledger evidence invalid or balance/version conflict")
    finally:
        db.close()


if __name__ == "__main__":
    main()
