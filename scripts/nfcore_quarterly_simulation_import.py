"""Load one already-reviewed T11 quarter into a scoped homologation database."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from kordena_fiscal.application.quarterly_simulation import import_quarter
from kordena_fiscal.cognitive.federal_benefits_api import build_federal_issuer_verifier
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.tax.quarterly_simulation import Quarter, simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    if os.environ.get("NFCORE_ENVIRONMENT") not in {"development", "test", "staging"}:
        parser.error("homologation import requires a non-production environment")
    if args.bundle.stat().st_size > 1048576:
        parser.error("bundle exceeds T01 limit")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    if set(bundle) != {"tenant", "unit", "issuer_cnpj", "version", "facts"} or (
        bundle["tenant"], bundle["unit"]
    ) != (args.tenant, args.unit):
        parser.error("invalid bundle scope")
    issuer = Cnpj(bundle["issuer_cnpj"])
    facts = Quarter.model_validate(bundle["facts"])
    quarter = date.fromisoformat(facts.period_start)
    simulate(quarter, facts)
    scope = ExecutionScope(args.tenant, args.unit, FiscalEnvironment.HOMOLOGATION,
                           "quarterly-reviewed-import", "fm-nfcore")
    db = PostgresFiscalDatabase(os.environ["DATABASE_URL"])
    try:
        with db() as uow:
            unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if unit is None or scope.environment not in unit.enabled_environments:
            parser.error("unit not enabled in homologation")
        verify = build_federal_issuer_verifier(db, scope)
        if len({verify(issuer.value, date(quarter.year, quarter.month + n, 1)).regime
                for n in range(3)}) != 1:
            parser.error("regime changed within quarter")
        with db.economy(scope) as store:
            digest = import_quarter(store, issuer, bundle["version"], facts)
        print(json.dumps({"snapshot_digest": digest, "version": bundle["version"]}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
