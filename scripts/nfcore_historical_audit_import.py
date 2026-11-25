"""Import one reviewed historical XML/assessment batch into T01 homologation only."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from kordena_fiscal.application.historical_audit import MAX_INPUT_BYTES, import_month
from kordena_fiscal.application.tax_recovery import import_recovery
from kordena_fiscal.application.unused_credits import import_credits, verify_credit_unit
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.tax.historical_audit import Month, closed_months
from kordena_fiscal.tax.tax_recovery import RecoveryBatch
from kordena_fiscal.tax.unused_credits import Batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--unused-credits", action="store_true", help="import a reviewed T16 purchase bundle"
    )
    mode.add_argument("--recovery", action="store_true", help="estimate reviewed T17 recovery")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("historical import requires a non-production environment")
    if os.environ.get("NFCORE_ECONOMY_ENABLED") != "true":
        parser.error("economy import unavailable")
    if args.bundle.stat().st_size > MAX_INPUT_BYTES:
        parser.error("historical bundle exceeds 32 MiB")
    try:

        def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate historical bundle key")
                result[key] = value
            return result

        bundle = json.loads(
            args.bundle.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )
        if set(bundle) != {"tenant", "unit", "issuer_cnpj", "version", "facts"} or (
            bundle["tenant"],
            bundle["unit"],
        ) != (args.tenant, args.unit):
            raise ValueError("invalid bundle scope")
        issuer = Cnpj(bundle["issuer_cnpj"])
        version = bundle["version"]
        if type(version) is not int or not 1 <= version <= 2147483647:
            raise ValueError("invalid bundle version")
        facts: Batch | Month | RecoveryBatch
        if args.recovery:
            facts = RecoveryBatch.model_validate(bundle["facts"])
        elif args.unused_credits:
            facts = Batch.model_validate(bundle["facts"])
        else:
            facts = Month.model_validate(bundle["facts"])
        period = date.fromisoformat(facts.competence)
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        closed_months(period, today)
    except (ValueError, TypeError, KeyError):
        parser.error("invalid reviewed historical bundle")
    scope = ExecutionScope(
        args.tenant,
        args.unit,
        FiscalEnvironment.HOMOLOGATION,
        "historical-audit-reviewed-import",
        "fm-nfcore",
    )
    db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with db() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("unit not enabled in homologation")
        canonical_issuer, context = historical_issuer_context(db, scope, period)
        if canonical_issuer != issuer:
            parser.error("canonical issuer mismatch")
        if isinstance(facts, (Batch, RecoveryBatch)):
            verify_credit_unit(db, scope, issuer)
        with db.economy(scope) as store:
            if isinstance(facts, RecoveryBatch):
                report = import_recovery(
                    store, issuer, period, version, facts, context=context, as_of=today
                )
            elif isinstance(facts, Batch):
                report = import_credits(
                    store, issuer, period, version, facts, context=context, as_of=today
                )
            else:
                report = import_month(
                    store,
                    issuer,
                    period,
                    version,
                    facts,
                    context=context,
                    as_of=today,
                )
        print(json.dumps(report))
    except (FiscalValidationError, ValueError, TypeError, KeyError):
        parser.error("historical evidence invalid or version conflict")
    finally:
        db.close()


if __name__ == "__main__":
    main()
